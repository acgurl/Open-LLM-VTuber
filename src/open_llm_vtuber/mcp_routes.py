"""Authenticated HTTP API for per-user MCP configuration.

Users edit the same ``mcp_servers`` document shape as the deployment
``mcp_servers.json``. The backend validates each entry and classifies it as
``remote`` (the backend connects) or ``local`` (the browser connects); the
deployment-managed servers themselves are never exposed or modified here.
"""

import asyncio
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from .auth import AuthManager
from .mcpp.mcp_client import MCPClient
from .mcpp.server_registry import ServerRegistry
from .mcpp.types import MCPServer
from .mcpp.user_servers import (
    MAX_USER_MCP_TOOLS,
    USER_MCP_TIMEOUT_SECONDS,
    classify_mcp_url,
    parse_user_mcp_config,
    user_server_key,
    validate_server_id,
)
from .service_context import ServiceContext
from .storage import DEFAULT_USER_ID, HistoryRepository

_MASKED_VALUE = "***"


class MCPConfigInput(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class MCPTestInput(BaseModel):
    server_id: str


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _request_user_id(
    request: Request,
    auth: AuthManager | None,
    default_context_cache: ServiceContext,
) -> str | None:
    identity = getattr(request.state, "identity", None)
    if identity is not None:
        return identity.user_id
    if auth is not None and auth.enabled:
        return None
    return getattr(default_context_cache, "user_id", None) or DEFAULT_USER_ID


def _repository(context: ServiceContext) -> HistoryRepository | None:
    return context.history_repository


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: _MASKED_VALUE for key in headers}


def _resolve_masked_headers(
    existing: dict[str, str],
    incoming: dict[str, str],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in incoming.items():
        if value == _MASKED_VALUE:
            if key not in existing:
                raise ValueError(
                    f"header '{key}' uses the masked placeholder; enter its value"
                )
            resolved[key] = existing[key]
        else:
            resolved[key] = value
    return resolved


def _config_response(records: list[dict]) -> dict:
    config: dict[str, dict] = {"mcp_servers": {}}
    servers: list[dict] = []
    for record in records:
        headers = _mask_headers(record.get("headers") or {})
        entry: dict[str, Any] = {"url": record["url"]}
        if headers:
            entry["headers"] = headers
        entry["enabled"] = bool(record.get("enabled", True))
        config["mcp_servers"][record["name"]] = entry
        servers.append(
            {
                "id": record["id"],
                "name": record["name"],
                "url": record["url"],
                "headers": headers,
                "enabled": bool(record.get("enabled", True)),
                "mode": record.get("mode") or "remote",
            }
        )
    return {"config": config, "servers": servers}


async def _find_server(
    repository: HistoryRepository, user_id: str, server_id: str
) -> dict | None:
    for server in await repository.list_user_mcp_servers(user_id=user_id):
        if server.get("id") == server_id:
            return server
    return None


def init_user_mcp_routes(
    default_context_cache: ServiceContext,
    auth: AuthManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/mcp")

    def _user_or_error(request: Request) -> tuple[str | None, JSONResponse | None]:
        user_id = _request_user_id(request, auth, default_context_cache)
        if user_id is None:
            return None, _error(401, "Authentication required")
        repository = _repository(default_context_cache)
        if repository is None:
            return None, _error(503, "Storage is not ready")
        return user_id, None

    async def _load_response(user_id: str) -> dict:
        repository = _repository(default_context_cache)
        records = await repository.list_user_mcp_servers(user_id=user_id)
        return _config_response(records)

    @router.get("/config")
    async def get_config(request: Request):
        user_id, failure = _user_or_error(request)
        if failure is not None:
            return failure
        return await _load_response(user_id)

    @router.put("/config")
    async def put_config(request: Request, body: MCPConfigInput):
        user_id, failure = _user_or_error(request)
        if failure is not None:
            return failure
        repository = _repository(default_context_cache)

        try:
            entries = parse_user_mcp_config(body.config)
        except ValueError as exc:
            return _error(400, str(exc))

        existing = {
            record["name"]: record
            for record in await repository.list_user_mcp_servers(user_id=user_id)
        }
        try:
            for entry in entries:
                existing_headers = (existing.get(entry["name"]) or {}).get(
                    "headers"
                ) or {}
                entry["headers"] = _resolve_masked_headers(
                    existing_headers, entry["headers"]
                )
        except ValueError as exc:
            return _error(400, str(exc))

        try:
            records = await repository.replace_user_mcp_servers(
                user_id=user_id,
                servers=entries,
            )
        except ValueError as exc:
            return _error(400, str(exc))

        logger.info(f"MCP API: user {user_id} saved {len(records)} MCP server(s)")
        return _config_response(records)

    @router.post("/config/test")
    async def test_server(request: Request, body: MCPTestInput):
        user_id, failure = _user_or_error(request)
        if failure is not None:
            return failure
        try:
            validate_server_id(body.server_id)
        except ValueError as exc:
            return _error(400, str(exc))
        repository = _repository(default_context_cache)

        record = await _find_server(repository, user_id, body.server_id)
        if record is None:
            return _error(404, "MCP server not found")

        mode = record.get("mode")
        if mode not in {"local", "remote"}:
            try:
                mode = classify_mcp_url(record.get("url"))
            except ValueError as exc:
                return _error(400, str(exc))
        if mode == "local":
            # The browser owns the connection; its status is reported by
            # local-mcp-registered / local-mcp-error over WebSocket.
            return {"mode": "local", "tools": []}

        key = user_server_key(body.server_id)
        registry = ServerRegistry.from_servers(
            {
                key: MCPServer(
                    name=key,
                    url=record["url"],
                    headers=record.get("headers") or None,
                    timeout=timedelta(seconds=USER_MCP_TIMEOUT_SECONDS),
                    is_user=True,
                    display_name=record.get("name"),
                )
            }
        )

        try:
            async with MCPClient(registry) as client:
                tools = await asyncio.wait_for(
                    client.list_tools(key),
                    timeout=USER_MCP_TIMEOUT_SECONDS + 5,
                )
        except Exception as exc:
            logger.warning(
                f"MCP API: test failed for user {user_id} server "
                f"{body.server_id}: {type(exc).__name__}"
            )
            return _error(502, "Could not reach this MCP server")

        return {
            "mode": "remote",
            "tools": [
                {"name": tool.name, "description": tool.description}
                for tool in tools[:MAX_USER_MCP_TOOLS]
            ],
        }

    return router
