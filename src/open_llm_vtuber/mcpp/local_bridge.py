"""Proxy MCP tool calls to a server running in the user's browser.

The browser cannot accept server-initiated connections, so the request travels
down the existing ``/client-ws`` socket and the result comes back as a
``local-tool-result`` message. Only the owning client's socket is used; the
backend never dials the user's localhost itself.
"""

import asyncio
import json
from typing import Any, Callable
from uuid import uuid4

from loguru import logger

from ..message_handler import message_handler
from .user_servers import (
    LOCAL_MCP_TIMEOUT_SECONDS,
    error_tool_result,
    result_size_exceeded,
)

_MAX_CONTENT_ITEMS = 64


class LocalMCPBridge:
    """Send tool calls to the browser that registered a local MCP server."""

    def __init__(
        self,
        client_uid: str,
        send_text: Callable | None,
        timeout: float = LOCAL_MCP_TIMEOUT_SECONDS,
    ) -> None:
        self._client_uid = client_uid
        self._send_text = send_text
        self._timeout = timeout

    async def call_tool(
        self,
        *,
        server_key: str,
        tool_name: str,
        tool_args: dict[str, Any] | None,
    ) -> dict[str, Any]:
        server_id = server_key.partition(":")[2]
        if not server_id or self._send_text is None:
            return error_tool_result("Local MCP is not connected")

        request_id = uuid4().hex
        payload = {
            "type": "local-tool-call",
            "request_id": request_id,
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": tool_args or {},
        }
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return error_tool_result("Tool arguments are not valid JSON")

        async with message_handler.response_waiter(
            self._client_uid, "local-tool-result", request_id
        ) as wait:
            try:
                sent = self._send_text(encoded)
                if asyncio.iscoroutine(sent):
                    await sent
            except Exception:
                logger.exception(
                    "MCPC: Failed to send a local tool call to the browser"
                )
                return error_tool_result("Could not reach the browser-side MCP server")

            response = await wait(self._timeout)
        if response is None:
            return error_tool_result("Local MCP did not respond in time")

        if response.get("server_id") not in (None, server_id):
            logger.warning("MCPC: Local tool result came from an unexpected server")
            return error_tool_result("Invalid local MCP response")

        raw_items = response.get("content_items")
        if not isinstance(raw_items, list):
            return error_tool_result("Invalid local MCP response")

        content_items: list[dict[str, Any]] = []
        for item in raw_items[:_MAX_CONTENT_ITEMS]:
            if not isinstance(item, dict):
                continue
            normalized: dict[str, Any] = {
                "type": str(item.get("type") or "text"),
            }
            for key in ("text", "data", "mimeType", "url", "altText"):
                value = item.get(key)
                if isinstance(value, str):
                    normalized[key] = value
            content_items.append(normalized)

        if not content_items:
            content_items = [{"type": "text", "text": ""}]

        if response.get("is_error"):
            text = next(
                (
                    item.get("text")
                    for item in content_items
                    if item.get("type") in {"error", "text"} and item.get("text")
                ),
                "Local MCP tool failed",
            )
            return error_tool_result(text)

        if result_size_exceeded(content_items):
            return error_tool_result("Local MCP result exceeded the size limit")

        metadata = response.get("metadata")
        return {
            "metadata": metadata if isinstance(metadata, dict) else {},
            "content_items": content_items,
        }
