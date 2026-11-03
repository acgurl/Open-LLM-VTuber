"""Authenticated HTTP API for binding platform accounts to the web account.

The logged-in user asks for a one-time code here and sends it to a global bot
(``/bind CODE``) from the platform account. Only accounts whose login email is
in ``connectors.binding.allowed_email_domains`` may get a code.
"""

from collections.abc import Callable

from fastapi import APIRouter, Request
from loguru import logger
from starlette.responses import JSONResponse, Response

from .auth import AuthManager
from .connectors import ConnectorManager, user_eligible
from .service_context import ServiceContext
from .storage import DEFAULT_USER_ID, validate_identity, validate_key
from .utils.timestamps import to_wire_timestamp


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def init_connector_routes(
    default_context_cache: ServiceContext,
    get_manager: Callable[[], ConnectorManager | None],
    auth: AuthManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/connectors")

    def _user_id(request: Request) -> str | None:
        identity = getattr(request.state, "identity", None)
        if identity is not None:
            return identity.user_id
        if auth is not None and auth.enabled:
            return None
        return getattr(default_context_cache, "user_id", None) or DEFAULT_USER_ID

    def _context(request: Request):
        """Return (user_id, repository, manager) or an error response."""
        user_id = _user_id(request)
        if user_id is None:
            return None, _error(401, "Authentication required")
        repository = default_context_cache.history_repository
        if repository is None:
            return None, _error(503, "Storage is not ready")
        manager = get_manager()
        if manager is None or not manager.enabled:
            return None, _error(404, "Connectors are not enabled")
        return (user_id, repository, manager), None

    @router.get("")
    async def get_connectors(request: Request):
        resolved, failure = _context(request)
        if failure is not None:
            return failure
        user_id, repository, manager = resolved
        profile = await repository.get_user_profile(user_id=user_id)
        names = {status["id"]: status for status in manager.statuses()}
        bindings = [
            {
                "connector_id": row["connector_id"],
                "connector_name": (names.get(row["connector_id"]) or {}).get("name"),
                "external_id": row["external_id"],
                "display_name": row.get("display_name"),
                "created_at": to_wire_timestamp(row.get("created_at")),
            }
            for row in await repository.list_connector_identities(user_id=user_id)
        ]
        return {
            "eligible": user_eligible(
                profile, manager.config.binding.allowed_email_domains
            ),
            "allowed_email_domains": manager.config.binding.allowed_email_domains,
            "connectors": [
                {
                    "id": status["id"],
                    "name": status["name"],
                    "platform": status["platform"],
                    "state": status["state"],
                }
                for status in manager.statuses()
            ],
            "bindings": bindings,
        }

    @router.post("/bind-code")
    async def create_bind_code(request: Request):
        resolved, failure = _context(request)
        if failure is not None:
            return failure
        user_id, repository, manager = resolved
        profile = await repository.get_user_profile(user_id=user_id)
        if not user_eligible(profile, manager.config.binding.allowed_email_domains):
            return _error(
                403, "Binding requires an account that logs in with a campus email"
            )
        code, expires_in = manager.bind_codes.issue(user_id)
        logger.info(f"Connector API: user {user_id} requested a binding code")
        return {"code": code, "expires_in": expires_in}

    @router.delete("/bindings/{connector_id}/{external_id}")
    async def delete_binding(request: Request, connector_id: str, external_id: str):
        resolved, failure = _context(request)
        if failure is not None:
            return failure
        user_id, repository, manager = resolved
        try:
            validate_key(connector_id, "connector_id")
            validate_identity(external_id, "external_id")
        except ValueError as exc:
            return _error(400, str(exc))
        deleted = await repository.delete_connector_identity(
            user_id=user_id,
            connector_id=connector_id,
            external_id=external_id,
        )
        if not deleted:
            return _error(404, "Binding not found")
        await manager.dispatcher.close_sender_sessions(connector_id, external_id)
        return Response(status_code=204)

    return router
