import json
from typing import Any, Literal
from loguru import logger
from pydantic import ValidationError
from fastapi import WebSocket

from prompts import prompt_loader
from .live2d_model import Live2dModel
from .asr.asr_interface import ASRInterface
from .tts.tts_interface import TTSInterface
from .vad.vad_interface import VADInterface
from .agent.agents.agent_interface import AgentInterface
from .agent.agents.basic_memory_agent import BasicMemoryAgent
from .translate.translate_interface import TranslateInterface

from .conversations.types import OutboundChannels
from .mcpp.server_registry import ServerRegistry
from .mcpp.tool_manager import ToolManager
from .mcpp.mcp_client import MCPClient
from .mcpp.tool_executor import ToolExecutor
from .mcpp.tool_adapter import ToolAdapter
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
from .storage import (
    DEFAULT_USER_ID,
    HistoryMessage,
    HistoryRepository,
    UserHistoryStore,
)
from .utils.security import redact_secrets, resolve_existing_file_within

from .asr.asr_factory import ASRFactory
from .tts.tts_factory import TTSFactory
from .vad.vad_factory import VADFactory
from .agent.agent_factory import AgentFactory
from .translate.translate_factory import TranslateFactory

from .config_manager import (
    Config,
    AgentConfig,
    CharacterConfig,
    SystemConfig,
    ASRConfig,
    TTSConfig,
    VADConfig,
    TranslatorConfig,
    read_yaml,
    validate_config,
)
from .config_manager.access import is_user_allowed


class ServiceContext:
    """Initializes, stores, and updates the asr, tts, and llm instances and other
    configurations for a connected client."""

    def __init__(self):
        self.config: Config = None
        self.system_config: SystemConfig = None
        self.character_config: CharacterConfig = None

        self.live2d_model: Live2dModel = None
        self.asr_engine: ASRInterface = None
        self.tts_engine: TTSInterface = None
        self.agent_engine: AgentInterface = None
        # translate_engine can be none if translation is disabled
        self.vad_engine: VADInterface | None = None
        self.translate_engine: TranslateInterface | None = None

        self.mcp_server_registry: ServerRegistry | None = None
        self.tool_adapter: ToolAdapter | None = None
        self.tool_manager: ToolManager | None = None
        self.mcp_client: MCPClient | None = None
        self.tool_executor: ToolExecutor | None = None

        # Per-session MCP state. ``user_mcp_records`` is loaded from the
        # database at connection time; browser-local tools are registered over
        # the WebSocket after the session is established.
        self._user_mcp_records: list[dict] = []
        self._local_mcp_config: dict[str, dict] = {}
        self._base_mcp_tools: dict[str, FormattedTool] = {}
        self._base_mcp_prompt: str = ""
        self.local_mcp_bridge: LocalMCPBridge | None = None
        self.local_mcp_servers: dict[str, dict] = {}
        self.local_mcp_tools: dict[str, FormattedTool] = {}
        self._local_mcp_servers_info: dict[str, dict[str, dict]] = {}
        self.mcp_active: bool = False

        # the system prompt is a combination of the persona prompt and live2d expression prompt
        self.system_prompt: str = None

        # Store the generated MCP prompt string (if MCP enabled)
        self.mcp_prompt: str = ""

        self.history_uid: str = ""  # Add history_uid field
        self.history_repository: HistoryRepository | None = None
        self.history: UserHistoryStore | None = None
        self.user_id: str | None = DEFAULT_USER_ID
        # Used to match character allowlists by name; the session cookie only
        # carries the display name, not the email or OIDC subject.
        self.user_display_name: str | None = None
        # The active turn keeps writing to the history it started in, even if
        # another history is opened while its audio is still playing.
        self.turn_history_uid: str | None = None
        self.turn_response_persisted: bool = False

        # TTS is normally shared from the default context. A session that
        # switches to a different TTS config creates its own engine and must be
        # the only one allowed to close it.
        self._owns_tts_engine = False

        self.channels: OutboundChannels | None = None
        self.client_uid: str = None

    def __str__(self):
        if not self.character_config:
            return "ServiceContext: not loaded"

        model_name = (
            self.live2d_model.model_info.get("name", "unknown")
            if self.live2d_model
            else "Not Loaded"
        )
        return (
            f"ServiceContext:\n"
            f"  Character: {self.character_config.character_name} "
            f"({self.character_config.conf_name})\n"
            f"  Live2D Model: {model_name}\n"
            f"  ASR Engine: {type(self.asr_engine).__name__ if self.asr_engine else 'Not Loaded'}\n"
            f"  TTS Engine: {type(self.tts_engine).__name__ if self.tts_engine else 'Not Loaded'}\n"
            f"  LLM Engine: {type(self.agent_engine).__name__ if self.agent_engine else 'Not Loaded'}\n"
            f"  VAD Engine: {type(self.vad_engine).__name__ if self.vad_engine else 'Not Loaded'}\n"
            f"  MCP Enabled: {'Yes' if self.mcp_client else 'No'}"
        )

    # ==== Initializers

    def _reset_mcp_components(self) -> None:
        # Local (browser-side) registrations survive a character switch; only
        # the deployment/user HTTP base is rebuilt.
        self.mcp_server_registry = None
        self.tool_manager = None
        self.mcp_client = None
        self.tool_executor = None
        self.mcp_prompt = ""
        self._base_mcp_tools = {}
        self._base_mcp_prompt = ""
        self.mcp_active = False

    async def _init_mcp_tools(self, enabled_servers) -> None:
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
            self.tool_manager = ToolManager(
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

    def _init_mcp_client(self) -> None:
        if not self.mcp_server_registry:
            logger.error(
                "MCP enabled but ServerRegistry not available. MCPClient not created."
            )
            self.mcp_client = None
            return

        self.mcp_client = self._build_mcp_client()
        logger.info("MCPClient initialized for this session.")

    def _ensure_mcp_client(self) -> None:
        if self.mcp_client is None:
            if self.mcp_server_registry is None:
                self.mcp_server_registry = ServerRegistry.from_servers({})
            self._init_mcp_client()

    def _build_mcp_client(self) -> MCPClient:
        return MCPClient(
            self.mcp_server_registry,
            self.channels.text if self.channels else None,
            self.client_uid,
        )

    def _build_tool_executor(self) -> ToolExecutor | None:
        if not (self.mcp_client and self.tool_manager):
            return None
        if self.local_mcp_bridge is None:
            return ToolExecutor(self.mcp_client, self.tool_manager)
        return ToolExecutor(self.mcp_client, self.tool_manager, self.local_mcp_bridge)

    def _init_tool_executor(self) -> None:
        self.tool_executor = self._build_tool_executor()
        if self.tool_executor is None:
            logger.warning(
                "MCPClient or ToolManager not available. ToolExecutor not created."
            )
        else:
            logger.info("ToolExecutor initialized for this session.")

    def _prepare_tool_adapter(self, user_servers: dict[str, MCPServer]) -> None:
        """Build this session's registry and an adapter over the same registry.

        The adapter is session-local by design: one borrowed from an earlier
        configuration may point at a different registry.
        """
        base_registry = ServerRegistry()
        self.mcp_server_registry = (
            base_registry.merged_with(user_servers) if user_servers else base_registry
        )
        self.tool_adapter = ToolAdapter(server_registry=self.mcp_server_registry)

    def _ensure_tool_adapter(self) -> ToolAdapter:
        if self.tool_adapter is None:
            if self.mcp_server_registry is None:
                self.mcp_server_registry = ServerRegistry.from_servers({})
            self.tool_adapter = ToolAdapter(server_registry=self.mcp_server_registry)
        return self.tool_adapter

    async def _init_mcp_components(self, use_mcpp, enabled_servers):
        """Initializes MCP components based on configuration, dynamically fetching tool info."""
        logger.debug(
            f"Initializing MCP components: use_mcpp={use_mcpp}, enabled_servers={enabled_servers}"
        )
        self._reset_mcp_components()

        user_servers = build_user_mcp_servers(self._user_mcp_records)
        # Global tools remain gated by the character config. Enabled user
        # servers are always included for this user, even when the character
        # disables its deployment-level MCP list.
        global_enabled = list(enabled_servers or []) if use_mcpp else []
        effective_servers = global_enabled + list(user_servers.keys())

        if effective_servers:
            self._prepare_tool_adapter(user_servers)
            await self._init_mcp_tools(effective_servers)
            self._init_mcp_client()
            self._init_tool_executor()
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
            self._rebuild_tooling()

    def _remove_local_mcp_server(self, server_id: str) -> None:
        key = local_server_key(server_id)
        metadata = self.local_mcp_servers.pop(key, None)
        if metadata:
            for tool_name in metadata.get("tool_names", []):
                self.local_mcp_tools.pop(tool_name, None)
        self._local_mcp_servers_info.pop(key, None)

    def get_local_mcp_config(self) -> list[dict]:
        """Return the browser-facing local server config for this session."""
        return local_mcp_config_payload(list(self._local_mcp_config.values()))

    def register_local_mcp_server(
        self,
        *,
        server_id: str,
        tools: list[dict],
    ) -> list[str]:
        """Register tools from an MCP server running in this user's browser."""
        if self.channels is None or getattr(self.channels, "text", None) is None:
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
        self._remove_local_mcp_server(server_id)
        self.local_mcp_tools.update(formatted)
        self._local_mcp_servers_info[key] = server_info
        self.local_mcp_servers[key] = {
            "id": server_id,
            "name": name,
            "tool_names": list(formatted),
        }
        if self.local_mcp_bridge is None:
            self.local_mcp_bridge = LocalMCPBridge(self.client_uid, self.channels.text)
        self._rebuild_tooling()
        return list(formatted)

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

    def unregister_local_mcp_server(self, server_id: str) -> bool:
        if local_server_key(server_id) not in self.local_mcp_servers:
            return False
        self._remove_local_mcp_server(server_id)
        self._rebuild_tooling()
        return True

    def _rebuild_tooling(self) -> None:
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
            self.tool_manager = ToolManager(
                formatted_tools_openai=openai_tools,
                formatted_tools_claude=claude_tools,
                initial_tools_dict=merged,
            )
            self._ensure_mcp_client()
            if self.local_mcp_bridge is None and self.channels is not None:
                self.local_mcp_bridge = LocalMCPBridge(
                    self.client_uid, self.channels.text
                )
            self.tool_executor = self._build_tool_executor()
            self.mcp_active = True
        else:
            self.tool_manager = None
            self.tool_executor = None
            self.mcp_active = False

        if isinstance(self.agent_engine, BasicMemoryAgent):
            self.agent_engine.set_tooling(
                self.tool_manager,
                self.tool_executor,
                self.mcp_prompt,
                enabled=bool(merged),
            )

    async def close(self):
        """Clean up resources, especially the MCPClient."""
        logger.info("Closing ServiceContext resources...")
        if self.mcp_client:
            logger.info(f"Closing MCPClient for context instance {id(self)}...")
            try:
                await self.mcp_client.aclose()
            except Exception:
                logger.exception("Failed to close MCPClient")
            self.mcp_client = None
        if self.agent_engine and hasattr(self.agent_engine, "close"):
            try:
                await self.agent_engine.close()
            except Exception:
                logger.exception("Failed to close agent engine")
        if self._owns_tts_engine and self.tts_engine is not None:
            try:
                self.tts_engine.close()
            except Exception:
                logger.exception("Failed to close session TTS engine")
            self._owns_tts_engine = False
        logger.info("ServiceContext closed.")

    def set_history_storage(
        self,
        repository: HistoryRepository | None,
        user_id: str | None = DEFAULT_USER_ID,
    ) -> None:
        self.history_repository = repository
        self.user_id = user_id
        self.history = (
            UserHistoryStore(repository, user_id)
            if repository is not None and user_id is not None
            else None
        )

    async def load_history(self, history_uid: str) -> list[HistoryMessage]:
        """Load a user-owned history into the agent's working memory."""
        if self.history is None:
            raise RuntimeError("History storage is not configured")
        if not history_uid or not await self.history.history_exists(
            self.character_config.conf_uid, history_uid
        ):
            raise ValueError(f"History not found: {history_uid}")

        messages = await self.history.get_history(
            self.character_config.conf_uid, history_uid
        )
        metadata = await self.history.get_metadata(
            self.character_config.conf_uid, history_uid
        )
        await self.agent_engine.set_memory(messages, metadata)
        self.history_uid = history_uid
        return messages

    async def store_history_message(
        self,
        role: Literal["human", "ai", "system"],
        content: str,
        name: str | None = None,
        avatar: str | None = None,
        history_uid: str | None = None,
    ) -> None:
        target_uid = history_uid if history_uid is not None else self.history_uid
        if self.history is None or not target_uid:
            return
        await self.history.store_message(
            self.character_config.conf_uid,
            target_uid,
            role=role,
            content=content,
            name=name,
            avatar=avatar,
        )

    async def store_history_tool_call(
        self,
        *,
        tool_id: str,
        tool_name: str,
        status: str,
        content: str = "",
        timestamp: str | None = None,
        history_uid: str | None = None,
    ) -> bool:
        """Persist a tool execution; failures must never break the live stream."""
        target_uid = history_uid if history_uid is not None else self.history_uid
        if self.history is None or not target_uid or not tool_id:
            return False
        try:
            await self.history.store_tool_call(
                self.character_config.conf_uid,
                target_uid,
                tool_id=tool_id,
                tool_name=tool_name,
                status=status,
                content=content,
                timestamp=timestamp,
            )
            return True
        except Exception:
            logger.exception("Failed to store tool call in history")
            return False

    async def get_history_tool_calls(self, history_uid: str | None = None):
        target_uid = history_uid if history_uid is not None else self.history_uid
        if self.history is None or not target_uid:
            return []
        return await self.history.list_tool_calls(
            self.character_config.conf_uid, target_uid
        )

    async def update_history_metadata(self, metadata: dict) -> bool:
        if self.history is None or not self.history_uid:
            return False
        return await self.history.update_metadata(
            self.character_config.conf_uid,
            self.history_uid,
            metadata,
        )

    async def load_cache(
        self,
        config: Config,
        system_config: SystemConfig,
        character_config: CharacterConfig,
        live2d_model: Live2dModel,
        asr_engine: ASRInterface,
        tts_engine: TTSInterface,
        vad_engine: VADInterface,
        agent_engine: AgentInterface,
        translate_engine: TranslateInterface | None,
        mcp_server_registry: ServerRegistry | None = None,
        tool_adapter: ToolAdapter | None = None,
        channels: OutboundChannels | None = None,
        client_uid: str | None = None,
        history_repository: HistoryRepository | None = None,
        user_id: str | None = DEFAULT_USER_ID,
        user_display_name: str | None = None,
        user_mcp_servers: list[dict] | None = None,
        local_mcp_servers: list[dict] | None = None,
    ) -> None:
        """
        Load the ServiceContext with the reference of the provided instances.
        Pass by reference so no reinitialization will be done.
        """
        if not character_config:
            raise ValueError("character_config cannot be None")
        if not system_config:
            raise ValueError("system_config cannot be None")

        self.config = config
        self.system_config = system_config
        self.character_config = character_config
        self.live2d_model = live2d_model
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.vad_engine = vad_engine
        self.agent_engine = agent_engine
        self.translate_engine = translate_engine
        # Load potentially shared components by reference
        self.mcp_server_registry = mcp_server_registry
        self.tool_adapter = tool_adapter
        self.channels = channels
        self.client_uid = client_uid
        self._user_mcp_records = list(user_mcp_servers or [])
        self._local_mcp_config = {
            record["id"]: record
            for record in (local_mcp_servers or [])
            if isinstance(record.get("id"), str)
        }
        # Engines passed in by load_cache are shared with the default context.
        self._owns_tts_engine = False
        self.set_history_storage(history_repository, user_id)
        self.user_display_name = user_display_name

        # Initialize session-specific MCP components
        await self._init_mcp_components(
            self.character_config.agent_config.agent_settings.basic_memory_agent.use_mcpp,
            self.character_config.agent_config.agent_settings.basic_memory_agent.mcp_enabled_servers,
        )

        logger.debug(
            f"Loaded service context for character {character_config.conf_uid}"
        )

    async def init_session_agent(self, shared_agent: AgentInterface) -> None:
        """Give this session its own agent so concurrent clients keep separate memory."""
        if isinstance(shared_agent, BasicMemoryAgent):
            system_prompt = await self.construct_system_prompt(
                self.character_config.persona_prompt
            )
            basic_settings = getattr(
                self.character_config.agent_config.agent_settings,
                "basic_memory_agent",
                None,
            )
            effective_use_mcpp = self.mcp_active or bool(
                getattr(basic_settings, "use_mcpp", False)
            )
            self.agent_engine = shared_agent.clone_for_session(
                system=system_prompt,
                live2d_model=self.live2d_model,
                tts_preprocessor_config=self.character_config.tts_preprocessor_config,
                tool_manager=self.tool_manager,
                tool_executor=self.tool_executor,
                mcp_prompt_string=self.mcp_prompt,
                use_mcpp=effective_use_mcpp,
            )
            self.system_prompt = system_prompt
        else:
            self.agent_engine = None
            await self.init_agent(
                self.character_config.agent_config,
                self.character_config.persona_prompt,
            )

    async def load_from_config(self, config: Config) -> None:
        """
        Load the ServiceContext with the config.
        Reinitialize the instances if the config is different.

        Parameters:
        - config (Dict): The configuration dictionary.
        """
        if not self.config:
            self.config = config

        if not self.system_config:
            self.system_config = config.system_config

        if not self.character_config:
            self.character_config = config.character_config

        # update all sub-configs

        # init live2d from character config
        self.init_live2d(config.character_config.live2d_model_name)

        # init asr from character config
        self.init_asr(config.character_config.asr_config)

        # init tts from character config
        self.init_tts(config.character_config.tts_config)

        # init vad from character config
        self.init_vad(config.character_config.vad_config)

        # Initialize MCP Components before initializing Agent
        await self._init_mcp_components(
            config.character_config.agent_config.agent_settings.basic_memory_agent.use_mcpp,
            config.character_config.agent_config.agent_settings.basic_memory_agent.mcp_enabled_servers,
        )

        # init agent from character config
        await self.init_agent(
            config.character_config.agent_config,
            config.character_config.persona_prompt,
        )

        self.init_translate(
            config.character_config.tts_preprocessor_config.translator_config
        )

        # store typed config references
        self.config = config
        self.system_config = config.system_config or self.system_config
        self.character_config = config.character_config

    def init_live2d(self, live2d_model_name: str) -> None:
        logger.info(f"Initializing Live2D: {live2d_model_name}")
        try:
            self.live2d_model = Live2dModel(live2d_model_name)
            self.character_config.live2d_model_name = live2d_model_name
        except Exception as e:
            logger.critical(f"Error initializing Live2D: {e}")
            logger.critical("Try to proceed without Live2D...")

    def init_asr(self, asr_config: ASRConfig) -> None:
        if not self.asr_engine or (self.character_config.asr_config != asr_config):
            logger.info(f"Initializing ASR: {asr_config.asr_model}")
            self.asr_engine = ASRFactory.get_asr_system(
                asr_config.asr_model,
                **getattr(asr_config, asr_config.asr_model).model_dump(),
            )
            # saving config should be done after successful initialization
            self.character_config.asr_config = asr_config
        else:
            logger.info("ASR already initialized with the same config.")

    def init_tts(self, tts_config: TTSConfig) -> None:
        if not self.tts_engine or (self.character_config.tts_config != tts_config):
            logger.info(f"Initializing TTS: {tts_config.tts_model}")
            previous_engine = self.tts_engine
            self.tts_engine = TTSFactory.get_tts_engine(
                tts_config.tts_model,
                **getattr(tts_config, tts_config.tts_model.lower()).model_dump(),
            )
            # Never close an engine borrowed from the default context; other
            # sessions may still be using it.
            if previous_engine is not None and self._owns_tts_engine:
                previous_engine.close()
            self._owns_tts_engine = True
            # saving config should be done after successful initialization
            self.character_config.tts_config = tts_config
        else:
            logger.info("TTS already initialized with the same config.")

    def init_vad(self, vad_config: VADConfig) -> None:
        if vad_config.vad_model is None:
            logger.info("VAD is disabled.")
            self.vad_engine = None
            return

        if not self.vad_engine or (self.character_config.vad_config != vad_config):
            logger.info(f"Initializing VAD: {vad_config.vad_model}")
            self.vad_engine = VADFactory.get_vad_engine(
                vad_config.vad_model,
                **getattr(vad_config, vad_config.vad_model.lower()).model_dump(),
            )
            # saving config should be done after successful initialization
            self.character_config.vad_config = vad_config
        else:
            logger.info("VAD already initialized with the same config.")

    async def init_agent(self, agent_config: AgentConfig, persona_prompt: str) -> None:
        """Initialize or update the LLM engine based on agent configuration."""
        logger.info(f"Initializing Agent: {agent_config.conversation_agent_choice}")

        if (
            self.agent_engine is not None
            and agent_config == self.character_config.agent_config
            and persona_prompt == self.character_config.persona_prompt
        ):
            logger.debug("Agent already initialized with the same config.")
            return

        system_prompt = await self.construct_system_prompt(persona_prompt)

        # Pass avatar to agent factory
        avatar = self.character_config.avatar or ""  # Get avatar from config
        agent_settings = agent_config.agent_settings.model_dump()
        # User/local MCP tools are an explicit opt-in and may need to enable
        # tool calling even when the character's deployment config disables it.
        if self.mcp_active and agent_settings.get("basic_memory_agent") is not None:
            agent_settings["basic_memory_agent"]["use_mcpp"] = True

        try:
            self.agent_engine = AgentFactory.create_agent(
                conversation_agent_choice=agent_config.conversation_agent_choice,
                agent_settings=agent_settings,
                llm_configs=agent_config.llm_configs.model_dump(),
                system_prompt=system_prompt,
                live2d_model=self.live2d_model,
                tts_preprocessor_config=self.character_config.tts_preprocessor_config,
                character_avatar=avatar,
                # Agents only need prompt paths; keep auth/storage secrets out
                # of the agent configuration dict.
                system_config={"tool_prompts": self.system_config.tool_prompts},
                tool_manager=self.tool_manager,
                tool_executor=self.tool_executor,
                mcp_prompt_string=self.mcp_prompt,
                history_metadata_writer=self.update_history_metadata,
            )

            logger.debug(f"Agent choice: {agent_config.conversation_agent_choice}")
            logger.debug(f"System prompt: {system_prompt}")

            # Save the current configuration
            self.character_config.agent_config = agent_config
            self.system_prompt = system_prompt

        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise

    def init_translate(self, translator_config: TranslatorConfig) -> None:
        """Initialize or update the translation engine based on the configuration."""

        if not translator_config.translate_audio:
            logger.debug("Translation is disabled.")
            return

        if (
            not self.translate_engine
            or self.character_config.tts_preprocessor_config.translator_config
            != translator_config
        ):
            logger.info(
                f"Initializing Translator: {translator_config.translate_provider}"
            )
            self.translate_engine = TranslateFactory.get_translator(
                translator_config.translate_provider,
                getattr(
                    translator_config, translator_config.translate_provider
                ).model_dump(),
            )
            self.character_config.tts_preprocessor_config.translator_config = (
                translator_config
            )
        else:
            logger.info("Translation already initialized with the same config.")

    # ==== utils

    def character_allowed(self, character_config: dict) -> bool:
        """Whether this session may use a preset's raw ``character_config``.

        Called with the preset YAML as written, never the merged config, so a
        preset that omits ``allowed_users`` stays public instead of inheriting
        the base character's list.
        """
        if not isinstance(character_config, dict):
            return True
        return is_user_allowed(
            character_config.get("allowed_users"),
            self.user_id,
            self.user_display_name,
        )

    def model_conf_payload(self, client_uid: str | None = None) -> dict:
        """Build the set-model-and-conf payload for the current character."""
        payload = {
            "type": "set-model-and-conf",
            "model_info": self.live2d_model.model_info if self.live2d_model else {},
            "conf_name": self.character_config.conf_name,
            "conf_uid": self.character_config.conf_uid,
            "welcome_message": self.character_config.welcome_message,
        }
        if client_uid is not None:
            payload["client_uid"] = client_uid
        return payload

    async def construct_system_prompt(self, persona_prompt: str) -> str:
        """
        Append tool prompts to persona prompt.

        Parameters:
        - persona_prompt (str): The persona prompt.

        Returns:
        - str: The system prompt with all tool prompts appended.
        """
        logger.debug(f"constructing persona_prompt: '''{persona_prompt}'''")

        for prompt_name, prompt_file in self.system_config.tool_prompts.items():
            if (
                prompt_name == "group_conversation_prompt"
                or prompt_name == "proactive_speak_prompt"
            ):
                continue

            if prompt_name == "live2d_expression_prompt" and self.live2d_model is None:
                logger.warning(
                    "Live2D model is unavailable; skipping the expression prompt"
                )
                continue

            prompt_content = prompt_loader.load_util(prompt_file)

            if prompt_name == "live2d_expression_prompt":
                prompt_content = prompt_content.replace(
                    "[<insert_emomap_keys>]", self.live2d_model.emo_str
                )
                prompt_content = prompt_content.replace(
                    "[<insert_motionmap_keys>]", self.live2d_model.motion_str
                )

            if prompt_name == "mcp_prompt":
                continue

            persona_prompt += prompt_content

        logger.debug("\n === System Prompt ===")
        logger.debug(persona_prompt)

        return persona_prompt

    async def handle_config_switch(
        self,
        websocket: WebSocket,
        config_file_name: str,
    ) -> None:
        """
        Handle the configuration switch request.
        Change the configuration to a new config and notify the client.

        Parameters:
        - websocket (WebSocket): The WebSocket connection.
        - config_file_name (str): The name of the configuration file.
        """
        try:
            character_config_data, raw_character_config = (
                self._load_character_config_data(config_file_name)
            )
            if not self.character_allowed(raw_character_config):
                logger.warning(
                    f"User {self.user_id} is not allowed to use character "
                    f"{config_file_name}"
                )
                await self._send_config_switch_error(
                    websocket, "Character not available"
                )
                return
            await self._apply_character_config(character_config_data)
            await self._notify_config_switched(websocket, config_file_name)
        except Exception as e:
            self._log_config_switch_error(e)
            await self._send_config_switch_error(websocket)

    def _load_character_config_data(self, config_file_name: str) -> tuple[Any, dict]:
        """Return the merged character config plus the preset's own raw mapping."""
        if config_file_name == "conf.yaml":
            character_config_data = read_yaml("conf.yaml").get("character_config")
            raw_character_config: dict = {}
        else:
            # Resolve inside the character presets directory; the raw client
            # string must not be able to reach anywhere else (including
            # sibling directories whose name shares the same prefix).
            characters_dir = self.system_config.config_alts_dir
            try:
                file_path = resolve_existing_file_within(
                    characters_dir, config_file_name, allowed_suffixes={".yaml"}
                )
            except ValueError as e:
                raise ValueError(f"Invalid configuration file: {e}") from e

            alt_config_data = read_yaml(str(file_path)).get("character_config")
            if not isinstance(alt_config_data, dict):
                raise ValueError("Character config must be a mapping")
            raw_character_config = alt_config_data

            # Merge against the base config every time. Using the current
            # (already merged) config makes overrides leak across switches.
            base_config_data = read_yaml("conf.yaml").get("character_config")
            if not isinstance(base_config_data, dict):
                raise ValueError("Base character config must be a mapping")

            character_config_data = deep_merge(base_config_data, alt_config_data)

        if not character_config_data:
            raise ValueError(f"Failed to load configuration from {config_file_name}")

        return character_config_data, raw_character_config

    async def _apply_character_config(self, character_config_data: Any) -> None:
        new_config = validate_config(
            {
                "system_config": self.system_config.model_dump(),
                "character_config": character_config_data,
            }
        )
        await self.load_from_config(new_config)
        self.history_uid = None
        logger.debug(f"New config: {self}")

    async def _notify_config_switched(
        self, websocket: WebSocket, config_file_name: str
    ) -> None:
        await websocket.send_text(json.dumps(self.model_conf_payload()))

        await websocket.send_text(
            json.dumps(
                {
                    "type": "config-switched",
                    "message": f"Switched to config: {config_file_name}",
                }
            )
        )

        logger.info(f"Configuration switched to {config_file_name}")

    @staticmethod
    def _log_config_switch_error(error: Exception) -> None:
        # ValidationError messages can embed raw config values, so keep the
        # client-visible text generic; safe details are logged by
        # validate_config.
        if isinstance(error, ValidationError):
            logger.error("Error switching configuration: invalid configuration")
        else:
            logger.error(
                "Error switching configuration: "
                f"{type(error).__name__}: {redact_secrets(str(error))}"
            )

    @staticmethod
    async def _send_config_switch_error(
        websocket: WebSocket,
        message: str = "Failed to switch configuration",
    ) -> None:
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": message,
                    }
                )
            )
        except Exception:
            logger.debug("Client disconnected before config-switch error was sent")


def deep_merge(dict1, dict2):
    """
    Recursively merges dict2 into dict1, prioritizing values from dict2.
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
