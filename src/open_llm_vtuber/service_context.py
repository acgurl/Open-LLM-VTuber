import json
import sys
from typing import Any, Literal
from loguru import logger
from pydantic import ValidationError
from fastapi import WebSocket

from prompts import prompt_loader
from .live2d_model import Live2dModel
from .asr.asr_interface import ASRInterface
from .tts.tts_interface import TTSInterface
from .agent.agents.agent_interface import AgentInterface
from .agent.agents.basic_memory_agent import BasicMemoryAgent
from .translate.translate_interface import TranslateInterface

from .conversations.types import OutboundChannels

# SessionTooling resolves these MCP classes through this module at call time;
# keep every one importable here even when this file does not use it.
from .mcpp.server_registry import ServerRegistry
from .mcpp.tool_manager import ToolManager  # noqa: F401
from .mcpp.mcp_client import MCPClient  # noqa: F401
from .mcpp.tool_executor import ToolExecutor  # noqa: F401
from .mcpp.tool_adapter import ToolAdapter
from .storage import (
    DEFAULT_USER_ID,
    HistoryMessage,
    HistoryRepository,
    UserHistoryStore,
)
from .session_tooling import SessionTooling, ToolingField
from .utils.dicts import deep_merge
from .utils.security import redact_secrets, resolve_existing_file_within

from .asr.asr_factory import ASRFactory
from .tts.tts_factory import TTSFactory
from .agent.agent_factory import AgentFactory
from .translate.translate_factory import TranslateFactory

from .config_manager import (
    Config,
    AgentConfig,
    CharacterConfig,
    SystemConfig,
    ASRConfig,
    TTSConfig,
    TranslatorConfig,
    read_yaml,
    validate_config,
)
from .config_manager.access import is_user_allowed

# Tool prompts that are injected per turn (or, for MCP, by the agent from the
# live tool list) rather than baked into the persona system prompt.
_PROMPTS_NOT_IN_SYSTEM_PROMPT = frozenset(
    {"group_conversation_prompt", "proactive_speak_prompt", "mcp_prompt"}
)

# Default for the history writers' ``history_uid``: write to the history that
# is open now. An explicit ``None`` means the turn is not persisted (proactive
# or skip_history turns bind ``turn_history_uid=None``), so it must never fall
# back to the open history.
CURRENT_HISTORY: Any = object()


def _engine_kwargs(config, field_name: str) -> dict:
    """Return the engine's sub-config as kwargs; engines without one get {}."""
    sub_config = getattr(config, field_name, None)
    return sub_config.model_dump() if sub_config is not None else {}


class ServiceContext:
    """Initializes, stores, and updates the asr, tts, and llm instances and other
    configurations for a connected client."""

    # MCP state lives in ``self._tooling``; these keep the context's
    # attribute names (read and assigned by callers and tests).
    mcp_server_registry = ToolingField()
    tool_adapter = ToolingField()
    tool_manager = ToolingField()
    mcp_client = ToolingField()
    tool_executor = ToolingField()
    mcp_prompt = ToolingField()
    mcp_active = ToolingField()
    local_mcp_bridge = ToolingField()
    local_mcp_servers = ToolingField()
    local_mcp_tools = ToolingField()
    _user_mcp_records = ToolingField()
    _local_mcp_config = ToolingField()
    _base_mcp_tools = ToolingField()
    _base_mcp_prompt = ToolingField()
    _local_mcp_servers_info = ToolingField()

    def __init__(self):
        self.config: Config | None = None
        self.system_config: SystemConfig | None = None
        self.character_config: CharacterConfig | None = None

        self.live2d_model: Live2dModel | None = None
        self.asr_engine: ASRInterface | None = None
        self.tts_engine: TTSInterface | None = None
        self.agent_engine: AgentInterface | None = None
        # translate_engine can be none if translation is disabled
        self.translate_engine: TranslateInterface | None = None

        # Per-session MCP state. The MCP classes are looked up on this module
        # at call time, so patching them here still applies.
        self._tooling = SessionTooling(self, sys.modules[__name__])

        # the system prompt is a combination of the persona prompt and live2d expression prompt
        self.system_prompt: str | None = None

        # Empty/None means no history is open and turns are not persisted.
        self.history_uid: str | None = ""
        self.history_repository: HistoryRepository | None = None
        self.history: UserHistoryStore | None = None
        self.user_id: str | None = DEFAULT_USER_ID
        # Used to match character allowlists by name; the session cookie only
        # carries the display name, not the email or OIDC subject.
        self.user_display_name: str | None = None
        # Verified login emails; matched by character allowlists.
        self.user_emails: tuple[str, ...] = ()
        # The active turn keeps writing to the history it started in, even if
        # another history is opened while its audio is still playing.
        self.turn_history_uid: str | None = None
        self.turn_response_persisted: bool = False

        # TTS is normally shared from the default context. A session that
        # switches to a different TTS config creates its own engine and must be
        # the only one allowed to close it.
        self._owns_tts_engine = False

        self.channels: OutboundChannels | None = None
        self.client_uid: str | None = None

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
            f"  MCP Enabled: {'Yes' if self.mcp_client else 'No'}"
        )

    # ==== Initializers

    async def _init_mcp_components(self, use_mcpp, enabled_servers):
        """Initializes MCP components based on configuration, dynamically fetching tool info."""
        await self._tooling.rebuild(use_mcpp, enabled_servers)

    def get_local_mcp_config(self) -> list[dict]:
        """Return the browser-facing local server config for this session."""
        return self._tooling.get_local_config()

    def register_local_mcp_server(
        self,
        *,
        server_id: str,
        tools: list[dict],
    ) -> list[str]:
        """Register tools from an MCP server running in this user's browser."""
        return self._tooling.register_local_server(server_id, tools)

    def unregister_local_mcp_server(self, server_id: str) -> bool:
        return self._tooling.unregister_local_server(server_id)

    @staticmethod
    async def _close_agent(agent: AgentInterface | None) -> None:
        if agent and hasattr(agent, "close"):
            try:
                await agent.close()
            except Exception:
                logger.exception("Failed to close agent engine")

    async def close(self):
        """Clean up resources, especially the MCPClient."""
        logger.info("Closing ServiceContext resources...")
        await self._tooling.close()
        await self._close_agent(self.agent_engine)
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

    def _target_history_uid(self, history_uid: str | None) -> str | None:
        """Resolve ``history_uid`` to a writable history, or ``None``.

        An explicit ``None`` writes nothing; so does a context without a
        history store or without an open history.
        """
        target = self.history_uid if history_uid is CURRENT_HISTORY else history_uid
        return target if self.history is not None and target else None

    async def store_history_message(
        self,
        role: Literal["human", "ai", "system"],
        content: str,
        name: str | None = None,
        avatar: str | None = None,
        history_uid: str | None = CURRENT_HISTORY,
    ) -> None:
        target_uid = self._target_history_uid(history_uid)
        if not target_uid:
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
        history_uid: str | None = CURRENT_HISTORY,
    ) -> bool:
        """Persist a tool execution; failures must never break the live stream."""
        target_uid = self._target_history_uid(history_uid)
        if not target_uid or not tool_id:
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
        target_uid = self._target_history_uid(
            CURRENT_HISTORY if history_uid is None else history_uid
        )
        if not target_uid:
            return []
        return await self.history.list_tool_calls(
            self.character_config.conf_uid, target_uid
        )

    async def update_history_metadata(self, metadata: dict) -> bool:
        target_uid = self._target_history_uid(CURRENT_HISTORY)
        if not target_uid:
            return False
        return await self.history.update_metadata(
            self.character_config.conf_uid,
            target_uid,
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
        user_emails: tuple[str, ...] = (),
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
        self.agent_engine = agent_engine
        self.translate_engine = translate_engine
        self.channels = channels
        self.client_uid = client_uid
        # Load potentially shared components by reference
        self._tooling.load_records(
            mcp_server_registry, tool_adapter, user_mcp_servers, local_mcp_servers
        )
        # Engines passed in by load_cache are shared with the default context.
        self._owns_tts_engine = False
        self.set_history_storage(history_repository, user_id)
        self.user_display_name = user_display_name
        self.user_emails = tuple(user_emails)

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

    async def load_headless(self, config: Config) -> None:
        """Load a text-only context for message connectors.

        Only MCP and the agent are created. There is no Live2D model, ASR,
        TTS or translation, so the system prompt carries no expression
        keywords and turns must run with ``tts_manager=None``.
        """
        self.config = config
        self.system_config = config.system_config
        self.character_config = config.character_config
        self.live2d_model = None
        settings = config.character_config.agent_config.agent_settings
        basic = settings.basic_memory_agent
        await self._init_mcp_components(basic.use_mcpp, basic.mcp_enabled_servers)
        await self.init_agent(
            config.character_config.agent_config,
            config.character_config.persona_prompt,
        )

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
                **_engine_kwargs(asr_config, asr_config.asr_model),
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
                **_engine_kwargs(tts_config, tts_config.tts_model.lower()),
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

    async def init_agent(self, agent_config: AgentConfig, persona_prompt: str) -> None:
        """Initialize or update the LLM engine based on agent configuration."""
        logger.info(f"Initializing Agent: {agent_config.conversation_agent_choice}")

        if (
            self.agent_engine is not None
            and agent_config == self.character_config.agent_config
            and persona_prompt == self.character_config.persona_prompt
        ):
            logger.debug("Agent already initialized with the same config.")
            # MCP was rebuilt (and the old client closed) before this call;
            # the kept agent must use the new tooling, not the closed one.
            self._rewire_agent_tooling(agent_config)
            return

        system_prompt = await self.construct_system_prompt(persona_prompt)

        # Pass avatar to agent factory
        avatar = self.character_config.avatar or ""  # Get avatar from config
        agent_settings = agent_config.agent_settings.model_dump()
        # User/local MCP tools are an explicit opt-in and may need to enable
        # tool calling even when the character's deployment config disables it.
        if self.mcp_active and agent_settings.get("basic_memory_agent") is not None:
            agent_settings["basic_memory_agent"]["use_mcpp"] = True

        previous_agent = self.agent_engine
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

        # A replaced agent is owned by this context (sessions get their own
        # agent from init_session_agent); release e.g. a Hume socket.
        if previous_agent is not self.agent_engine:
            await self._close_agent(previous_agent)

    def _rewire_agent_tooling(self, agent_config: AgentConfig) -> None:
        if not isinstance(self.agent_engine, BasicMemoryAgent):
            return
        basic_settings = getattr(
            agent_config.agent_settings, "basic_memory_agent", None
        )
        self.agent_engine.set_tooling(
            self.tool_manager,
            self.tool_executor,
            self.mcp_prompt,
            enabled=self.mcp_active or bool(getattr(basic_settings, "use_mcpp", False)),
        )

    def init_translate(self, translator_config: TranslatorConfig) -> None:
        """Initialize or update the translation engine based on the configuration."""

        if not translator_config.translate_audio:
            logger.debug("Translation is disabled.")
            # Drop an engine left over from a previous character config.
            self.translate_engine = None
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
            self.user_emails,
        )

    def model_conf_payload(self, client_uid: str | None = None) -> dict:
        """Build the set-model-and-conf payload for the current character."""
        payload = {
            "type": "set-model-and-conf",
            "model_info": self.live2d_model.model_info if self.live2d_model else {},
            "conf_name": self.character_config.conf_name,
            "conf_uid": self.character_config.conf_uid,
            "welcome_message": self.character_config.welcome_message,
            "starter_prompts": list(self.character_config.starter_prompts),
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
            if prompt_name in _PROMPTS_NOT_IN_SYSTEM_PROMPT:
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
