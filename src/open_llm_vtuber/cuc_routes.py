"""Authenticated HTTP proxy for CUC campus account binding and status.

Credentials (campus net password, SMS verification codes, WeChat QR sessions)
flow directly between the user's browser, this backend, and the internal
``cuc-server`` without ever traversing the LLM context.
"""

from collections.abc import Callable
import re
from typing import Any

import httpx
from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from .auth import AuthManager, request_user_id
from .config_manager.cuc import CucAuthConfig
from .mcpp.user_servers import format_user_header_value
from .service_context import ServiceContext

_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MIN_POLL_TIMEOUT_MS = 1000
_MAX_POLL_TIMEOUT_MS = 25000


class MailSmsInput(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)


class NetSubmitInput(BaseModel):
    username: str | None = Field(default=None, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)
    verifyCode: str = Field(..., min_length=1, max_length=32)


class NetSmsInput(BaseModel):
    smsCode: str = Field(..., min_length=1, max_length=32)


def _error(status_code: int, message: str, **extra: Any) -> JSONResponse:
    payload: dict[str, Any] = {"error": message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


def _validate_task_id(task_id: str) -> str | None:
    if not _TASK_ID_PATTERN.fullmatch(task_id or ""):
        return None
    return task_id


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", ""}


def _rewrite_asset_paths(payload: Any, task_id: str | None = None) -> Any:
    if not isinstance(payload, dict):
        return payload
    copied = dict(payload)
    resolved_id = copied.get("taskId") or task_id
    if isinstance(resolved_id, str) and _TASK_ID_PATTERN.fullmatch(resolved_id):
        if isinstance(copied.get("qrPath"), str):
            copied["qrPath"] = f"/api/cuc/auth/wechat/{resolved_id}/qr"
        if isinstance(copied.get("captchaPath"), str):
            copied["captchaPath"] = f"/api/cuc/auth/net/{resolved_id}/captcha"
    return copied


def _extract_upstream_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        data = None
    if isinstance(data, dict) and isinstance(data.get("error"), str) and data["error"]:
        return data["error"]
    text = response.text.strip()
    if text:
        return text[:500]
    return f"Upstream error ({response.status_code})"


def _default_client_factory(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_seconds)


class _CucAuthRoutes:
    """Request handlers for ``/api/cuc/auth``."""

    def __init__(
        self,
        default_context_cache: ServiceContext,
        cuc_config: CucAuthConfig,
        auth: AuthManager | None,
        client_factory: Callable[[float], httpx.AsyncClient] | None = None,
    ) -> None:
        self.default_context_cache = default_context_cache
        self.cuc_config = cuc_config
        self.auth = auth
        self._client_factory = client_factory or _default_client_factory

    def _resolve_context(
        self, request: Request
    ) -> tuple[str | None, JSONResponse | None]:
        user_id = request_user_id(request, self.auth, self.default_context_cache)
        if user_id is None:
            return None, _error(401, "Authentication required")
        if not self.cuc_config.enabled:
            return None, _error(404, "CUC account binding is not enabled")
        return user_id, None

    def _headers_for(self, user_id: str) -> dict[str, str]:
        profile = format_user_header_value(user_id, self.cuc_config.user_prefix)
        return {
            "X-API-Key": self.cuc_config.api_key,
            self.cuc_config.user_header: profile,
        }

    async def _upstream_request(
        self,
        user_id: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[httpx.Response | None, JSONResponse | None]:
        url = f"{self.cuc_config.server_url}{path}"
        headers = self._headers_for(user_id)
        try:
            async with self._client_factory(self.cuc_config.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
        except httpx.TimeoutException:
            return None, _error(504, "CUC auth service timed out")
        except httpx.HTTPError as exc:
            logger.warning(
                f"CUC proxy request failed for {method} {path}: {type(exc).__name__}"
            )
            return None, _error(502, "Could not reach CUC auth service")

        if response.status_code >= 400:
            # Map upstream 401 to 422 so the browser never mistakes a CUC auth
            # failure for an expired Open-LLM-VTuber Casdoor session.
            mapped_status = 422 if response.status_code == 401 else response.status_code
            return None, _error(
                mapped_status,
                _extract_upstream_error(response),
                upstream_status=response.status_code,
            )
        return response, None

    async def _proxy_json(
        self,
        request: Request,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        task_id: str | None = None,
    ):
        user_id, failure = self._resolve_context(request)
        if failure is not None:
            return failure
        response, failure = await self._upstream_request(
            user_id, method, path, params=params, json_body=json_body
        )
        if failure is not None:
            return failure
        try:
            data = response.json()
        except ValueError:
            return _error(502, "Invalid JSON from CUC auth service")
        return _rewrite_asset_paths(data, task_id=task_id)

    async def _proxy_binary(self, request: Request, path: str, default_mime: str):
        user_id, failure = self._resolve_context(request)
        if failure is not None:
            return failure
        response, failure = await self._upstream_request(user_id, "GET", path)
        if failure is not None:
            return failure
        media_type = response.headers.get("content-type") or default_mime
        return Response(
            content=response.content,
            status_code=200,
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    async def get_status(self, request: Request):
        verify = "verify" in request.query_params and _truthy(
            request.query_params.get("verify")
        )
        upstream_path = "/status" if verify else "/auth/status"
        return await self._proxy_json(request, "GET", upstream_path)

    async def start_wechat(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/login/wechat")

    async def poll_wechat(self, request: Request, task_id: str):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        params: dict[str, Any] = {}
        if "wait" in request.query_params:
            wait_val = request.query_params.get("wait")
            if wait_val is not None:
                params["wait"] = "1" if _truthy(wait_val) else "0"
        if "timeout" in request.query_params:
            raw_timeout = request.query_params.get("timeout", "")
            try:
                parsed_timeout = int(raw_timeout)
            except ValueError:
                return _error(400, "Invalid timeout")
            if parsed_timeout <= 0:
                return _error(400, "timeout must be positive")
            params["timeout"] = max(
                _MIN_POLL_TIMEOUT_MS, min(_MAX_POLL_TIMEOUT_MS, parsed_timeout)
            )
        return await self._proxy_json(
            request,
            "GET",
            f"/auth/login/wechat/{task_id}",
            params=params or None,
            task_id=task_id,
        )

    async def get_wechat_qr(self, request: Request, task_id: str):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        return await self._proxy_binary(
            request, f"/auth/login/wechat/{task_id}/qr", "image/jpeg"
        )

    async def cancel_wechat(self, request: Request, task_id: str):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        return await self._proxy_json(
            request, "DELETE", f"/auth/login/wechat/{task_id}", task_id=task_id
        )

    async def logout_sso(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/logout")

    async def start_mail(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/mail")

    async def submit_mail_sms(self, request: Request, task_id: str, body: MailSmsInput):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        return await self._proxy_json(
            request,
            "POST",
            f"/auth/mail/{task_id}/sms",
            json_body={"code": body.code},
            task_id=task_id,
        )

    async def logout_mail(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/mail/logout")

    async def start_net(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/net")

    async def get_net_captcha(self, request: Request, task_id: str):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        return await self._proxy_binary(
            request, f"/auth/net/{task_id}/captcha", "image/png"
        )

    async def submit_net(self, request: Request, task_id: str, body: NetSubmitInput):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        payload: dict[str, Any] = {
            "password": body.password,
            "verifyCode": body.verifyCode,
        }
        if body.username is not None and body.username.strip():
            payload["username"] = body.username.strip()
        return await self._proxy_json(
            request,
            "POST",
            f"/auth/net/{task_id}/submit",
            json_body=payload,
            task_id=task_id,
        )

    async def submit_net_sms(self, request: Request, task_id: str, body: NetSmsInput):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        return await self._proxy_json(
            request,
            "POST",
            f"/auth/net/{task_id}/sms",
            json_body={"smsCode": body.smsCode},
            task_id=task_id,
        )

    async def cancel_net(self, request: Request, task_id: str):
        if _validate_task_id(task_id) is None:
            return _error(400, "Invalid task_id")
        return await self._proxy_json(
            request, "DELETE", f"/auth/net/{task_id}", task_id=task_id
        )

    async def logout_net(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/net/logout")

    async def auth_opac(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/lib/book")

    async def logout_opac(self, request: Request):
        return await self._proxy_json(request, "POST", "/auth/lib/book/logout")


def init_cuc_auth_routes(
    default_context_cache: ServiceContext,
    cuc_config: CucAuthConfig,
    auth: AuthManager | None = None,
    *,
    client_factory: Callable[[float], httpx.AsyncClient] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/cuc/auth")
    handlers = _CucAuthRoutes(
        default_context_cache, cuc_config, auth, client_factory=client_factory
    )
    router.add_api_route("/status", handlers.get_status, methods=["GET"])
    router.add_api_route("/wechat/start", handlers.start_wechat, methods=["POST"])
    router.add_api_route("/wechat/{task_id}", handlers.poll_wechat, methods=["GET"])
    router.add_api_route(
        "/wechat/{task_id}/qr", handlers.get_wechat_qr, methods=["GET"]
    )
    router.add_api_route(
        "/wechat/{task_id}", handlers.cancel_wechat, methods=["DELETE"]
    )
    router.add_api_route("/logout", handlers.logout_sso, methods=["POST"])
    router.add_api_route("/mail/start", handlers.start_mail, methods=["POST"])
    router.add_api_route(
        "/mail/{task_id}/sms", handlers.submit_mail_sms, methods=["POST"]
    )
    router.add_api_route("/mail/logout", handlers.logout_mail, methods=["POST"])
    router.add_api_route("/net/start", handlers.start_net, methods=["POST"])
    router.add_api_route(
        "/net/{task_id}/captcha", handlers.get_net_captcha, methods=["GET"]
    )
    router.add_api_route("/net/{task_id}/submit", handlers.submit_net, methods=["POST"])
    router.add_api_route(
        "/net/{task_id}/sms", handlers.submit_net_sms, methods=["POST"]
    )
    router.add_api_route("/net/{task_id}", handlers.cancel_net, methods=["DELETE"])
    router.add_api_route("/net/logout", handlers.logout_net, methods=["POST"])
    router.add_api_route("/opac/auth", handlers.auth_opac, methods=["POST"])
    router.add_api_route("/opac/logout", handlers.logout_opac, methods=["POST"])
    return router
