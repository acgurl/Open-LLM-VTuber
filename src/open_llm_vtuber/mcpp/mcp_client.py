"""MCP Client for Open-LLM-Vtuber."""

from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Callable
from loguru import logger
from datetime import timedelta

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.types import Tool
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import (
    create_mcp_http_client,
    streamable_http_client,
)

from .server_registry import ServerRegistry
from .types import MCPServer
from .user_servers import (
    MAX_MCP_RESULT_BYTES,
    content_items_size,
    validate_public_https_url_async,
)

DEFAULT_TIMEOUT = timedelta(seconds=30)


class MCPClient:
    """MCP Client for Open-LLM-Vtuber.
    Manages persistent connections to multiple MCP servers.
    """

    def __init__(
        self,
        server_registry: ServerRegistry,
        send_text: Callable = None,
        client_uid: str = None,
    ) -> None:
        """Initialize the MCP Client."""
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        self.active_sessions: Dict[str, ClientSession] = {}
        self._list_tools_cache: Dict[str, List[Tool]] = {}  # Cache for list_tools
        self._send_text: Callable = send_text
        self._client_uid: str = client_uid

        if isinstance(server_registry, ServerRegistry):
            self.server_registry = server_registry
        else:
            raise TypeError(
                "MCPC: Invalid server manager. Must be an instance of ServerRegistry."
            )
        logger.info("MCPC: Initialized MCPClient instance.")

    def _get_server(self, server_name: str) -> MCPServer:
        server = self.server_registry.get_server(server_name)
        if not server:
            raise ValueError(
                f"MCPC: Server '{server_name}' not found in available servers."
            )
        return server

    @staticmethod
    def _get_timeout(server: MCPServer) -> timedelta:
        timeout = server.timeout if server.timeout else DEFAULT_TIMEOUT
        if isinstance(timeout, (int, float)):
            timeout = timedelta(seconds=timeout)
        return timeout

    async def _ensure_stdio_session(self, server_name: str) -> ClientSession:
        """Gets the existing stdio session or creates a new one."""
        if server_name in self.active_sessions:
            return self.active_sessions[server_name]

        server = self._get_server(server_name)
        timeout = self._get_timeout(server)

        logger.info(f"MCPC: Starting and connecting to server '{server_name}'...")
        server_params = StdioServerParameters(
            command=server.command,
            args=server.args,
            env=server.env,
            cwd=server.cwd,
        )

        try:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport

            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=timeout)
            )
            await session.initialize()

            self.active_sessions[server_name] = session
            logger.info(f"MCPC: Successfully connected to server '{server_name}'.")
            return session
        except Exception as e:
            logger.exception(f"MCPC: Failed to connect to server '{server_name}': {e}")
            raise RuntimeError(
                f"MCPC: Failed to connect to server '{server_name}'."
            ) from e

    @asynccontextmanager
    async def _http_session(
        self, server_name: str, server: MCPServer, timeout: timedelta
    ) -> AsyncIterator[ClientSession]:
        """Open a short-lived HTTP session in the caller's task.

        The transport owns AnyIO task groups, so it must be entered and exited
        from the same task. Tool calls run in a conversation task while
        disconnect cleanup runs in the WebSocket task; a cached session would
        therefore be closed from the wrong task.
        """
        if server.is_user:
            # Re-resolve immediately before connecting: the configuration may
            # have pointed at a public address when it was saved.
            await validate_public_https_url_async(server.url)

        logger.info(
            f"MCPC: Connecting to remote server '{server_name}' at {server.url}..."
        )
        async with AsyncExitStack() as stack:
            try:
                http_client = await stack.enter_async_context(
                    create_mcp_http_client(
                        headers=server.headers or None,
                        timeout=httpx.Timeout(timeout.total_seconds()),
                    )
                )
                transport = await stack.enter_async_context(
                    streamable_http_client(server.url, http_client=http_client)
                )
                read, write = transport[0], transport[1]

                session = await stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=timeout)
                )
                await session.initialize()
            except Exception as e:
                logger.exception(
                    f"MCPC: Failed to connect to server '{server_name}': {e}"
                )
                raise RuntimeError(
                    f"MCPC: Failed to connect to server '{server_name}'."
                ) from e

            logger.info(f"MCPC: Successfully connected to server '{server_name}'.")
            yield session

    @asynccontextmanager
    async def _sse_session(
        self, server_name: str, server: MCPServer, timeout: timedelta
    ) -> AsyncIterator[ClientSession]:
        """Open a short-lived legacy HTTP+SSE session in the caller's task."""
        if server.is_user:
            await validate_public_https_url_async(server.url)

        logger.info(
            f"MCPC: Connecting to SSE server '{server_name}' at {server.url}..."
        )
        async with AsyncExitStack() as stack:
            try:
                transport = await stack.enter_async_context(
                    sse_client(
                        server.url,
                        headers=server.headers or None,
                        timeout=timeout.total_seconds(),
                        sse_read_timeout=300,
                    )
                )
                read, write = transport
                session = await stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=timeout)
                )
                await session.initialize()
            except Exception as e:
                logger.exception(
                    f"MCPC: Failed to connect to SSE server '{server_name}': {e}"
                )
                raise RuntimeError(
                    f"MCPC: Failed to connect to server '{server_name}'."
                ) from e

            logger.info(f"MCPC: Successfully connected to SSE server '{server_name}'.")
            yield session

    @asynccontextmanager
    async def _session(self, server_name: str) -> AsyncIterator[ClientSession]:
        """Yield a session using the transport configured for the server."""
        server = self._get_server(server_name)
        if server.url:
            if server.transport == "sse":
                async with self._sse_session(
                    server_name, server, self._get_timeout(server)
                ) as session:
                    yield session
            else:
                async with self._http_session(
                    server_name, server, self._get_timeout(server)
                ) as session:
                    yield session
        else:
            yield await self._ensure_stdio_session(server_name)

    async def list_tools(self, server_name: str) -> List[Tool]:
        """List all available tools on the specified server."""
        # Check cache first
        if server_name in self._list_tools_cache:
            logger.debug(f"MCPC: Cache hit for list_tools on server '{server_name}'.")
            return self._list_tools_cache[server_name]

        logger.debug(
            f"MCPC: Cache miss for list_tools on server '{server_name}'. Fetching..."
        )
        async with self._session(server_name) as session:
            response = await session.list_tools()

        # Store in cache before returning
        self._list_tools_cache[server_name] = response.tools
        logger.debug(f"MCPC: Cached list_tools result for server '{server_name}'.")
        return response.tools

    async def call_tool(
        self, server_name: str, tool_name: str, tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call a tool on the specified server.

        Returns:
            Dict containing the metadata and content_items from the tool response.
        """
        server = self._get_server(server_name)
        logger.info(f"MCPC: Calling tool '{tool_name}' on server '{server_name}'...")
        async with self._session(server_name) as session:
            response = await session.call_tool(tool_name, tool_args)

        if response.isError:
            error_text = (
                response.content[0].text
                if response.content and hasattr(response.content[0], "text")
                else "Unknown server error"
            )
            logger.error(f"MCPC: Error calling tool '{tool_name}': {error_text}")
            # Return error information within the standard structure
            return {
                "metadata": getattr(response, "metadata", {}),
                "content_items": [{"type": "error", "text": error_text}],
            }

        content_items = []
        if response.content:
            for item in response.content:
                item_dict = {"type": getattr(item, "type", "text")}
                # Extract available attributes from content item
                for attr in [
                    "text",
                    "data",
                    "mimeType",
                    "url",
                    "altText",
                ]:  # Added url and altText
                    if (
                        hasattr(item, attr) and getattr(item, attr) is not None
                    ):  # Check for None
                        item_dict[attr] = getattr(item, attr)
                content_items.append(item_dict)
        else:
            logger.warning(
                f"MCPC: Tool '{tool_name}' returned no content. Returning empty content_items."
            )
            content_items.append(
                {"type": "text", "text": ""}
            )  # Ensure content_items is not empty

        if server.is_user and content_items_size(content_items) > MAX_MCP_RESULT_BYTES:
            return {
                "metadata": {},
                "content_items": [
                    {
                        "type": "error",
                        "text": "User MCP tool result exceeded the size limit",
                    }
                ],
            }

        result = {
            "metadata": getattr(response, "metadata", {}),
            "content_items": content_items,
        }
        return result

    async def aclose(self) -> None:
        """Closes all active server connections."""
        logger.info(
            f"MCPC: Closing client instance and {len(self.active_sessions)} active connections..."
        )
        await self.exit_stack.aclose()
        self.active_sessions.clear()
        self._list_tools_cache.clear()  # Clear cache on close
        self.exit_stack = AsyncExitStack()
        logger.info("MCPC: Client instance closed.")

    async def __aenter__(self) -> "MCPClient":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """Exit the async context manager."""
        await self.aclose()
        if exc_type:
            logger.error(f"MCPC: Exception in async context: {exc_value}")


# if __name__ == "__main__":
#     # Test the MCPClient.
#     async def main():
#         server_registry = ServerRegistry()
#         async with MCPClient(server_registry) as client:
#             # Assuming 'example' server and 'example_tool' exist
#             # The old call used: await client.call_tool("example_tool", {"arg1": "value1"})
#             # The new call needs server name:
#             try:
#                 result = await client.call_tool("example", "example_tool", {"arg1": "value1"})
#                 print(f"Tool result: {result}")
#                 # Test error handling by calling a non-existent tool
#                 await client.call_tool("example", "non_existent_tool", {})
#             except ValueError as e:
#                 print(f"Caught expected error: {e}")
#             except Exception as e:
#                 print(f"Caught unexpected error: {e}")

#     asyncio.run(main())
