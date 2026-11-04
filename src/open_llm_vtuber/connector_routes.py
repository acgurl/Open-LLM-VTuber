"""Authenticated HTTP API for binding platform accounts to the web account.

The logged-in user asks for a one-time code here and sends it to a global bot
(``/bind CODE``) from the platform account. Only accounts whose login email is
in ``connectors.binding.allowed_email_domains`` may get a code.
"""

from collections.abc import Callable

from fastapi import APIRouter, Request
from loguru import logger
from starlette.responses import JSONResponse, Response

from .auth import AuthManager, request_user_id
from .connectors import ConnectorManager, user_eligible
from .service_context import ServiceContext
from .storage import validate_identity, validate_key
from .utils.timestamps import to_wire_timestamp


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _binding_rows(rows: list[dict], statuses: list[dict]) -> list[dict]:
    names = {status["id"]: status for status in statuses}
    return [
        {
            "connector_id": row["connector_id"],
            "connector_name": (names.get(row["connector_id"]) or {}).get("name"),
            "external_id": row["external_id"],
            "display_name": row.get("display_name"),
            "created_at": to_wire_timestamp(row.get("created_at")),
        }
        for row in rows
    ]


class _ConnectorRoutes:
    """Request handlers for ``/api/connectors``; mounted by the init factory."""

    def __init__(
        self,
        default_context_cache: ServiceContext,
        get_manager: Callable[[], ConnectorManager | None],
        auth: AuthManager | None,
    ) -> None:
        self.default_context_cache = default_context_cache
        self.get_manager = get_manager
        self.auth = auth

    def _context(self, request: Request):
        """Return (user_id, repository, manager) or an error response."""
        user_id = request_user_id(request, self.auth, self.default_context_cache)
        if user_id is None:
            return None, _error(401, "Authentication required")
        repository = self.default_context_cache.history_repository
        if repository is None:
            return None, _error(503, "Storage is not ready")
        manager = self.get_manager()
        if manager is None or not manager.enabled:
            return None, _error(404, "Connectors are not enabled")
        return (user_id, repository, manager), None

    async def get_connectors(self, request: Request):
        resolved, failure = self._context(request)
        if failure is not None:
            return failure
        user_id, repository, manager = resolved
        profile = await repository.get_user_profile(user_id=user_id)
        statuses = manager.statuses()
        bindings = _binding_rows(
            await repository.list_connector_identities(user_id=user_id), statuses
        )
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

    async def create_bind_code(self, request: Request):
        resolved, failure = self._context(request)
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

    async def delete_binding(
        self, request: Request, connector_id: str, external_id: str
    ):
        resolved, failure = self._context(request)
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


def init_connector_routes(
    default_context_cache: ServiceContext,
    get_manager: Callable[[], ConnectorManager | None],
    auth: AuthManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/connectors")
    handlers = _ConnectorRoutes(default_context_cache, get_manager, auth)
    router.add_api_route("", handlers.get_connectors, methods=["GET"])
    router.add_api_route("/bind-code", handlers.create_bind_code, methods=["POST"])
    router.add_api_route(
        "/bindings/{connector_id}/{external_id}",
        handlers.delete_binding,
        methods=["DELETE"],
    )
    return router
