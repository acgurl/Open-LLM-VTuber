"""Authenticated HTTP API for per-user MCP configuration.

Users edit the same ``mcp_servers`` document shape as the deployment
``mcp_servers.json``. The backend validates each entry and classifies it as
``remote`` (the backend connects) or ``local`` (the browser connects); the
deployment-managed servers themselves are never exposed or modified here.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from .auth import AuthManager, request_user_id
from .mcpp.mcp_client import MCPClient
from .mcpp.server_registry import ServerRegistry
from .mcpp.user_servers import (
    MAX_USER_MCP_TOOLS,
    USER_MCP_TIMEOUT_SECONDS,
    build_user_mcp_server,
    classify_mcp_url,
    parse_user_mcp_config,
    validate_server_id,
)
from .service_context import ServiceContext
from .storage import HistoryRepository

_MASKED_VALUE = "***"


class MCPConfigInput(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class MCPTestInput(BaseModel):
    server_id: str


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _repository(context: ServiceContext) -> HistoryRepository | None:
    return context.history_repository


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    return dict.fromkeys(headers, _MASKED_VALUE)


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
        transport = record.get("transport") or "http"
        entry: dict[str, Any] = {"url": record["url"]}
        if transport == "sse":
            entry["type"] = "sse"
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
                "transport": transport,
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


def _resolve_test_mode(record: dict) -> str:
    """Return the stored mode, classifying legacy rows without one."""
    mode = record.get("mode")
    if mode in {"local", "remote"}:
        return mode
    return classify_mcp_url(record.get("url"))


def _restore_masked_headers(entries: list[dict], records: list[dict]) -> None:
    """Swap masked header placeholders for the values already stored."""
    existing = {record["name"]: record for record in records}
    for entry in entries:
        existing_headers = (existing.get(entry["name"]) or {}).get("headers") or {}
        entry["headers"] = _resolve_masked_headers(existing_headers, entry["headers"])


async def _list_remote_tools(client: MCPClient, server_name: str) -> list[dict]:
    tools = await asyncio.wait_for(
        client.list_tools(server_name),
        timeout=USER_MCP_TIMEOUT_SECONDS + 5,
    )
    return [
        {"name": tool.name, "description": tool.description}
        for tool in tools[:MAX_USER_MCP_TOOLS]
    ]


class _UserMCPRoutes:
    """Request handlers for ``/api/mcp``; ``init_user_mcp_routes`` mounts them."""

    def __init__(
        self, default_context_cache: ServiceContext, auth: AuthManager | None
    ) -> None:
        self.default_context_cache = default_context_cache
        self.auth = auth

    def _user_or_error(
        self, request: Request
    ) -> tuple[str | None, JSONResponse | None]:
        user_id = request_user_id(request, self.auth, self.default_context_cache)
        if user_id is None:
            return None, _error(401, "Authentication required")
        repository = _repository(self.default_context_cache)
        if repository is None:
            return None, _error(503, "Storage is not ready")
        return user_id, None

    async def _load_response(self, user_id: str) -> dict:
        repository = _repository(self.default_context_cache)
        records = await repository.list_user_mcp_servers(user_id=user_id)
        return _config_response(records)

    async def get_config(self, request: Request):
        user_id, failure = self._user_or_error(request)
        if failure is not None:
            return failure
        return await self._load_response(user_id)

    async def put_config(self, request: Request, body: MCPConfigInput):
        user_id, failure = self._user_or_error(request)
        if failure is not None:
            return failure
        repository = _repository(self.default_context_cache)

        try:
            entries = parse_user_mcp_config(body.config)
        except ValueError as exc:
            return _error(400, str(exc))

        records = await repository.list_user_mcp_servers(user_id=user_id)
        try:
            _restore_masked_headers(entries, records)
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

    async def test_server(self, request: Request, body: MCPTestInput):
        user_id, failure = self._user_or_error(request)
        if failure is not None:
            return failure
        try:
            validate_server_id(body.server_id)
        except ValueError as exc:
            return _error(400, str(exc))
        repository = _repository(self.default_context_cache)

        record = await _find_server(repository, user_id, body.server_id)
        if record is None:
            return _error(404, "MCP server not found")

        try:
            mode = _resolve_test_mode(record)
        except ValueError as exc:
            return _error(400, str(exc))
        if mode == "local":
            # The browser owns the connection; its status is reported by
            # local-mcp-registered / local-mcp-error over WebSocket.
            return {"mode": "local", "tools": []}

        server = build_user_mcp_server(record)
        registry = ServerRegistry.from_servers({server.name: server})
        try:
            async with MCPClient(registry) as client:
                tools = await _list_remote_tools(client, server.name)
        except Exception as exc:
            logger.warning(
                f"MCP API: test failed for user {user_id} server "
                f"{body.server_id}: {type(exc).__name__}"
            )
            return _error(502, "Could not reach this MCP server")
        return {"mode": "remote", "tools": tools}


def init_user_mcp_routes(
    default_context_cache: ServiceContext,
    auth: AuthManager | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/mcp")
    handlers = _UserMCPRoutes(default_context_cache, auth)
    router.add_api_route("/config", handlers.get_config, methods=["GET"])
    router.add_api_route("/config", handlers.put_config, methods=["PUT"])
    router.add_api_route("/config/test", handlers.test_server, methods=["POST"])
    return router
