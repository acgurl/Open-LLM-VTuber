"""Per-session MCP tooling owned by a ServiceContext.

``SessionTooling`` assembles the deployment/user HTTP tools (registry, adapter,
tool manager, client, executor) and merges in tools registered from the
user's browser. ``ServiceContext`` stays the public facade and exposes every
attribute here under the same name through ``ToolingField``.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any

from loguru import logger

from .agent.agents.basic_memory_agent import BasicMemoryAgent
from .mcpp.local_bridge import LocalMCPBridge
from .mcpp.types import FormattedTool, MCPServer
from .mcpp.user_servers import (
    MAX_LOCAL_MCP_SERVERS,
    MAX_LOCAL_MCP_TOOLS,
    build_user_mcp_servers,
    local_mcp_config_payload,
    local_server_key,
    make_exposed_tool_name,
    unique_tool_name,
    validate_local_tool,
)

if TYPE_CHECKING:  # annotations only; runtime classes come from ``factories``
    from .mcpp.mcp_client import MCPClient
    from .mcpp.server_registry import ServerRegistry
    from .mcpp.tool_adapter import ToolAdapter
    from .mcpp.tool_executor import ToolExecutor
    from .mcpp.tool_manager import ToolManager
    from .service_context import ServiceContext


class ToolingField:
    """Expose a ``SessionTooling`` attribute on ``ServiceContext`` by name."""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return getattr(obj._tooling, self.name)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj._tooling, self.name, value)


class SessionTooling:
    """MCP state and assembly for one ServiceContext.

    ``owner`` supplies ``channels``, ``client_uid`` and ``agent_engine`` at
    call time. ``factories`` is the namespace that holds ``ServerRegistry``,
    ``ToolAdapter``, ``ToolManager``, ``MCPClient`` and ``ToolExecutor``
    (the service_context module); they are looked up on it per call so
    patches applied to that module keep taking effect.
    """

    def __init__(self, owner: ServiceContext, factories: ModuleType) -> None:
        self._owner = owner
        self._factories = factories

        self.mcp_server_registry: ServerRegistry | None = None
        self.tool_adapter: ToolAdapter | None = None
        self.tool_manager: ToolManager | None = None
        self.mcp_client: MCPClient | None = None
        self.tool_executor: ToolExecutor | None = None

        # ``_user_mcp_records`` is loaded from the database at connection
        # time; browser-local tools are registered over the WebSocket after
        # the session is established.
        self._user_mcp_records: list[dict] = []
        self._local_mcp_config: dict[str, dict] = {}
        self._base_mcp_tools: dict[str, FormattedTool] = {}
        self._base_mcp_prompt: str = ""
        self.local_mcp_bridge: LocalMCPBridge | None = None
        self.local_mcp_servers: dict[str, dict] = {}
        self.local_mcp_tools: dict[str, FormattedTool] = {}
        self._local_mcp_servers_info: dict[str, dict[str, dict]] = {}
        self.mcp_active: bool = False
        # Store the generated MCP prompt string (if MCP enabled)
        self.mcp_prompt: str = ""

    def load_records(
        self,
        mcp_server_registry: ServerRegistry | None,
        tool_adapter: ToolAdapter | None,
        user_mcp_servers: list[dict] | None,
        local_mcp_servers: list[dict] | None,
    ) -> None:
        """Adopt shared components and this user's stored MCP records."""
        self.mcp_server_registry = mcp_server_registry
        self.tool_adapter = tool_adapter
        self._user_mcp_records = list(user_mcp_servers or [])
        self._local_mcp_config = {
            record["id"]: record
            for record in (local_mcp_servers or [])
            if isinstance(record.get("id"), str)
        }

    # ==== Deployment/user HTTP tools

    def reset(self) -> None:
        # Local (browser-side) registrations survive a character switch; only
        # the deployment/user HTTP base is rebuilt. The caller owns closing
        # the dropped MCP client.
        self.mcp_server_registry = None
        self.tool_manager = None
        self.mcp_client = None
        self.tool_executor = None
        self.mcp_prompt = ""
        self._base_mcp_tools = {}
        self._base_mcp_prompt = ""
        self.mcp_active = False

    async def rebuild(self, use_mcpp, enabled_servers) -> None:
        """Initializes MCP components based on configuration, dynamically fetching tool info."""
        logger.debug(
            f"Initializing MCP components: use_mcpp={use_mcpp}, enabled_servers={enabled_servers}"
        )
        previous_client = self.mcp_client
        self.reset()
        # Each rebuild creates a new client; close the old one so its server
        # connections (and stdio subprocesses) do not leak on every switch.
        await self.close_client(previous_client)

        user_servers = build_user_mcp_servers(self._user_mcp_records)
        # Global tools remain gated by the character config. Enabled user
        # servers are always included for this user, even when the character
        # disables its deployment-level MCP list.
        global_enabled = list(enabled_servers or []) if use_mcpp else []
        effective_servers = global_enabled + list(user_servers.keys())

        if effective_servers:
            self._prepare_tool_adapter(user_servers)
            await self._fetch_tools(effective_servers)
            self.mcp_client = self._build_mcp_client()
            self.tool_executor = self._build_tool_executor()
            if self.tool_executor is None:
                logger.warning(
                    "MCPClient or ToolManager not available. ToolExecutor not created."
                )
            else:
                logger.info("ToolExecutor initialized for this session.")
            self.mcp_active = self.tool_manager is not None
        elif use_mcpp:
            logger.warning(
                "use_mcpp is True, but mcp_enabled_servers list is empty. "
                "MCP components not initialized."
            )
        else:
            logger.debug(
                "MCP components not initialized (use_mcpp is False or no enabled servers)."
            )

        if self.local_mcp_tools:
            self.merge_into_agent()

    async def _fetch_tools(self, enabled_servers) -> None:
        try:
            (
                mcp_prompt_string,
                openai_tools,
                claude_tools,
                raw_tools_dict,
            ) = await self.tool_adapter.build_tools(enabled_servers)
            self.mcp_prompt = mcp_prompt_string
            self._base_mcp_prompt = mcp_prompt_string
            self._base_mcp_tools = (
                dict(raw_tools_dict) if isinstance(raw_tools_dict, dict) else {}
            )
            logger.info(
                f"Dynamically generated MCP prompt string (length: {len(self.mcp_prompt)})."
            )
            logger.info(
                f"Dynamically formatted tools - OpenAI: {len(openai_tools)}, "
                f"Claude: {len(claude_tools)}."
            )
            self.tool_manager = self._factories.ToolManager(
                formatted_tools_openai=openai_tools,
                formatted_tools_claude=claude_tools,
                initial_tools_dict=raw_tools_dict,
            )
            logger.info("ToolManager initialized with dynamically fetched tools.")
        except Exception as e:
            logger.error(
                f"Failed during dynamic MCP tool construction: {e}", exc_info=True
            )
            self.tool_manager = None
            self._base_mcp_tools = {}
            self._base_mcp_prompt = ""
            self.mcp_prompt = "[Error constructing MCP tools/prompt]"

    def _prepare_tool_adapter(self, user_servers: dict[str, MCPServer]) -> None:
        """Build this session's registry and an adapter over the same registry.

        The adapter is session-local by design: one borrowed from an earlier
        configuration may point at a different registry.
        """
        base_registry = self._factories.ServerRegistry()
        self.mcp_server_registry = (
            base_registry.merged_with(user_servers) if user_servers else base_registry
        )
        self.tool_adapter = self._factories.ToolAdapter(
            server_registry=self.mcp_server_registry
        )

    def _ensure_server_registry(self) -> ServerRegistry:
        if self.mcp_server_registry is None:
            self.mcp_server_registry = self._factories.ServerRegistry.from_servers({})
        return self.mcp_server_registry

    def _ensure_tool_adapter(self) -> ToolAdapter:
        if self.tool_adapter is None:
            self.tool_adapter = self._factories.ToolAdapter(
                server_registry=self._ensure_server_registry()
            )
        return self.tool_adapter

    def _build_mcp_client(self) -> MCPClient:
        channels = self._owner.channels
        client = self._factories.MCPClient(
            self._ensure_server_registry(),
            channels.text if channels else None,
            self._owner.client_uid,
        )
        logger.info("MCPClient initialized for this session.")
        return client

    def _build_tool_executor(self) -> ToolExecutor | None:
        if not (self.mcp_client and self.tool_manager):
            return None
        if self.local_mcp_bridge is None:
            return self._factories.ToolExecutor(self.mcp_client, self.tool_manager)
        return self._factories.ToolExecutor(
            self.mcp_client, self.tool_manager, self.local_mcp_bridge
        )

    async def close_client(self, client: MCPClient | None) -> None:
        if not client:
            return
        logger.info(f"Closing MCPClient for context instance {id(self._owner)}...")
        try:
            await client.aclose()
        except Exception:
            logger.exception("Failed to close MCPClient")

    async def close(self) -> None:
        client, self.mcp_client = self.mcp_client, None
        await self.close_client(client)

    # ==== Browser-local tools

    def get_local_config(self) -> list[dict]:
        """Return the browser-facing local server config for this session."""
        return local_mcp_config_payload(list(self._local_mcp_config.values()))

    def register_local_server(self, server_id: str, tools: list[dict]) -> list[str]:
        """Register tools from an MCP server running in this user's browser."""
        channels = self._owner.channels
        if channels is None or getattr(channels, "text", None) is None:
            raise ValueError("This session has no browser connection")
        config = self._local_mcp_config.get(server_id)
        if config is None:
            raise ValueError("Unknown local MCP server")
        name = config.get("name") or server_id
        if not isinstance(tools, list):
            raise ValueError("tools must be a list")
        if len(tools) > MAX_LOCAL_MCP_TOOLS:
            raise ValueError(f"At most {MAX_LOCAL_MCP_TOOLS} tools are allowed")

        key = local_server_key(server_id)
        if (
            key not in self.local_mcp_servers
            and len(self.local_mcp_servers) >= MAX_LOCAL_MCP_SERVERS
        ):
            raise ValueError(
                f"At most {MAX_LOCAL_MCP_SERVERS} local MCP servers are allowed"
            )

        formatted, server_info = self._format_local_tools(key, tools)

        # Only touch the live registration after every tool validated.
        self._remove_local_server(server_id)
        self.local_mcp_tools.update(formatted)
        self._local_mcp_servers_info[key] = server_info
        self.local_mcp_servers[key] = {
            "id": server_id,
            "name": name,
            "tool_names": list(formatted),
        }
        self._ensure_local_bridge()
        self.merge_into_agent()
        return list(formatted)

    def unregister_local_server(self, server_id: str) -> bool:
        if local_server_key(server_id) not in self.local_mcp_servers:
            return False
        self._remove_local_server(server_id)
        self.merge_into_agent()
        return True

    def _remove_local_server(self, server_id: str) -> None:
        key = local_server_key(server_id)
        metadata = self.local_mcp_servers.pop(key, None)
        if metadata:
            for tool_name in metadata.get("tool_names", []):
                self.local_mcp_tools.pop(tool_name, None)
        self._local_mcp_servers_info.pop(key, None)

    def _format_local_tools(
        self, key: str, tools: list[dict]
    ) -> tuple[dict[str, FormattedTool], dict[str, dict]]:
        """Validate browser tools and give each a collision-free exposed name."""
        previous_names = set(self.local_mcp_servers.get(key, {}).get("tool_names", []))
        taken = (set(self._base_mcp_tools) | set(self.local_mcp_tools)) - previous_names
        formatted: dict[str, FormattedTool] = {}
        server_info: dict[str, dict] = {}
        for tool in tools:
            remote_name, description, schema = validate_local_tool(tool)
            candidate = make_exposed_tool_name("l", key, remote_name)
            exposed_name = unique_tool_name(candidate, taken)
            taken.add(exposed_name)
            formatted[exposed_name] = FormattedTool(
                input_schema=schema,
                related_server=key,
                description=description,
                remote_name=remote_name,
            )
            server_info[exposed_name] = {
                "description": description,
                "parameters": schema.get("properties", {}),
                "required": schema.get("required", []),
            }
        return formatted, server_info

    def _ensure_local_bridge(self) -> None:
        channels = self._owner.channels
        if self.local_mcp_bridge is None and channels is not None:
            self.local_mcp_bridge = LocalMCPBridge(
                self._owner.client_uid, channels.text
            )

    def merge_into_agent(self) -> None:
        """Merge base (global/user HTTP) and browser-local tools into the agent."""
        merged: dict[str, FormattedTool] = dict(self._base_mcp_tools)
        merged.update(self.local_mcp_tools)

        adapter = self._ensure_tool_adapter()

        local_prompt = ""
        if self._local_mcp_servers_info:
            local_prompt = adapter.construct_mcp_prompt_string(
                self._local_mcp_servers_info,
                display_names={
                    key: metadata.get("name", key)
                    for key, metadata in self.local_mcp_servers.items()
                },
            )
        self.mcp_prompt = "\n\n".join(
            part for part in (self._base_mcp_prompt, local_prompt) if part
        )

        if merged:
            openai_tools, claude_tools = adapter.format_tools_for_api(merged)
            self.tool_manager = self._factories.ToolManager(
                formatted_tools_openai=openai_tools,
                formatted_tools_claude=claude_tools,
                initial_tools_dict=merged,
            )
            if self.mcp_client is None:
                self.mcp_client = self._build_mcp_client()
            self._ensure_local_bridge()
            self.tool_executor = self._build_tool_executor()
            self.mcp_active = True
        else:
            self.tool_manager = None
            self.tool_executor = None
            self.mcp_active = False

        agent = self._owner.agent_engine
        if isinstance(agent, BasicMemoryAgent):
            agent.set_tooling(
                self.tool_manager,
                self.tool_executor,
                self.mcp_prompt,
                enabled=bool(merged),
            )
