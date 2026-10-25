"""MCP Server Manager for Open-LLM-Vtuber."""

import shutil
import json

from pathlib import Path
from typing import Dict, Optional, Union, Any
from loguru import logger

from .types import MCPServer
from .user_servers import (
    headers_are_string_pairs,
    normalize_mcp_transport,
    parse_mcp_url,
)
from .utils.path import validate_file

DEFAULT_CONFIG_PATH = "mcp_servers.json"


class ServerRegistry:
    """MCP Server Manager for managing server files."""

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        *,
        servers: Dict[str, MCPServer] | None = None,
    ) -> None:
        """Initialize the MCP Server Manager.

        ``servers`` builds an in-memory registry (used for per-session
        overlays); otherwise the deployment-managed JSON file is loaded.
        """
        self.servers: Dict[str, MCPServer] = {}

        self.npx_available = self._detect_runtime("npx")
        self.uvx_available = self._detect_runtime("uvx")
        self.node_available = self._detect_runtime("node")

        if servers is not None:
            self.config: Dict[str, Union[str, dict]] = {"mcp_servers": {}}
            self.servers = dict(servers)
            return

        try:
            config_path = validate_file(config_path, ".json")
        except ValueError:
            logger.error(
                f"MCPSR: File '{config_path}' does not exist, or is not a json file."
            )
            raise ValueError(
                f"MCPSR: File '{config_path}' does not exist, or is not a json file."
            )

        self.config = json.loads(config_path.read_text(encoding="utf-8"))

        self.load_servers()

    @classmethod
    def from_servers(cls, servers: Dict[str, MCPServer]) -> "ServerRegistry":
        return cls(servers=servers)

    def merged_with(self, additions: Dict[str, MCPServer]) -> "ServerRegistry":
        """Return a session-only registry with global and user servers.

        Global entries always win: user server keys are namespaced and an
        accidental collision is ignored rather than overriding the deployment
        configuration.
        """
        merged = dict(self.servers)
        for name, server in additions.items():
            if name in merged:
                logger.warning(
                    f"MCPSR: Ignoring user server '{name}' because it collides "
                    "with a global server."
                )
                continue
            merged[name] = server
        return ServerRegistry(servers=merged)

    def _detect_runtime(self, target: str) -> bool:
        """Check if a runtime is available in the system PATH."""
        return bool(shutil.which(target))

    def load_servers(self) -> None:
        """Load servers from the config file."""
        servers_config: Dict[str, Dict[str, Any]] = self.config.get("mcp_servers", {})
        if servers_config == {}:
            logger.warning("MCPSR: No servers found in the config file.")
            return

        for server_name, server_details in servers_config.items():
            server = self._parse_server(server_name, server_details)
            if server is not None:
                self.servers[server_name] = server

    def _parse_server(
        self, server_name: str, server_details: Any
    ) -> Optional[MCPServer]:
        if not isinstance(server_details, dict):
            logger.warning(
                f"MCPSR: Invalid server details for '{server_name}'. Ignoring."
            )
            return None

        if server_details.get("url") is not None:
            return self._parse_http_server(server_name, server_details)
        return self._parse_stdio_server(server_name, server_details)

    def _parse_http_server(
        self, server_name: str, server_details: Dict[str, Any]
    ) -> Optional[MCPServer]:
        url = server_details.get("url")
        if not self._is_valid_http_url(url):
            logger.warning(f"MCPSR: Invalid HTTP url for '{server_name}'. Ignoring.")
            return None

        headers = server_details.get("headers")
        if headers is not None and not self._is_valid_headers(headers):
            logger.warning(
                f"MCPSR: Invalid HTTP headers for '{server_name}'. Ignoring."
            )
            return None

        try:
            transport = normalize_mcp_transport(
                server_details.get("transport", server_details.get("type"))
            )
        except ValueError as exc:
            logger.warning(
                f"MCPSR: Invalid transport for '{server_name}': {exc}. Ignoring."
            )
            return None

        logger.debug(
            f"MCPSR: Loaded HTTP server: '{server_name}' ({url}, {transport})."
        )
        return MCPServer(
            name=server_name,
            url=url,
            headers=headers,
            timeout=server_details.get("timeout", None),
            transport=transport,
        )

    def _parse_stdio_server(
        self, server_name: str, server_details: Dict[str, Any]
    ) -> Optional[MCPServer]:
        if "command" not in server_details or "args" not in server_details:
            logger.warning(
                f"MCPSR: Invalid server details for '{server_name}'. Ignoring."
            )
            return None

        command = server_details["command"]
        missing_runtime = (
            (command == "npx" and not self.npx_available)
            or (command == "uvx" and not self.uvx_available)
            or (command == "node" and not self.node_available)
        )
        if missing_runtime:
            logger.warning(
                f"MCPSR: {command} is not available. Cannot load server '{server_name}'."
            )
            return None

        logger.debug(f"MCPSR: Loaded server: '{server_name}'.")
        return MCPServer(
            name=server_name,
            command=command,
            args=server_details["args"],
            env=server_details.get("env", None),
            cwd=server_details.get("cwd", None),
            timeout=server_details.get("timeout", None),
        )

    @staticmethod
    def _is_valid_http_url(url: Any) -> bool:
        try:
            parse_mcp_url(url)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_valid_headers(headers: Any) -> bool:
        return headers_are_string_pairs(headers)

    def remove_server(self, server_name: str) -> None:
        """Remove a server from the available servers."""
        try:
            self.servers.pop(server_name)
            logger.info(f"MCPSR: Removed server: {server_name}")
        except KeyError:
            logger.warning(f"MCPSR: Server '{server_name}' not found. Cannot remove.")

    def get_server(self, server_name: str) -> Optional[MCPServer]:
        """Get the server by name."""
        return self.servers.get(server_name, None)
