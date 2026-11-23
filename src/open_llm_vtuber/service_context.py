import json
import sys
from collections.abc import Callable
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
from .llm_catalog import (
    MODEL_SETTING_KEY,
    THINKING_SETTING_PREFIX,
    LLMModelCatalog,
    LLMModelEntry,
)
from .speech_models import SPEECH_KINDS, SpeechKind, SpeechModelEntry
from .config_manager.character import CharacterModelRefs
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
        self._character_asr_engine: ASRInterface | None = None
        self._character_tts_engine: TTSInterface | None = None
        self._selected_asr_engine: ASRInterface | None = None
        self._selected_tts_engine: TTSInterface | None = None
        self._character_speech: dict[SpeechKind, SpeechModelEntry] = {}
        self._character_llm_entry: LLMModelEntry | None = None
        self._applied_llm_override: LLMModelEntry | None = None
        self._speech_choices: dict[SpeechKind, str | None] = {}
        self._active_speech: dict[SpeechKind, SpeechModelEntry] = {}
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

        # User-selectable models (see llm_catalog.py). The catalog is shared;
        # the rest is this session's view of the user's choice.
        self.llm_catalog: LLMModelCatalog | None = None
        # The user's stored choice; None follows the character's own LLM.
        self.selected_model_id: str | None = None
        # The catalog model the agent answers with now; None is the
        # character's LLM (also when the stored choice is unavailable).
        self.active_model: LLMModelEntry | None = None
        # The LLM the character preset configured, to go back to.
        self._character_llm: tuple[Any, str] | None = None
        # The user's thinking level per catalog model id; a missing or
        # unknown level means the model's default.
        self.thinking_choices: dict[str, str] = {}

    @property
    def asr_engine(self) -> ASRInterface | None:
        return self._selected_asr_engine or self._character_asr_engine

    @asr_engine.setter
    def asr_engine(self, engine: ASRInterface | None) -> None:
        self._character_asr_engine = engine

    @property
    def tts_engine(self) -> TTSInterface | None:
        return self._selected_tts_engine or self._character_tts_engine

    @tts_engine.setter
    def tts_engine(self, engine: TTSInterface | None) -> None:
        self._character_tts_engine = engine

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
        self._close_tts(self._selected_tts_engine)
        self._selected_tts_engine = None
        self._selected_asr_engine = None
        if self._owns_tts_engine:
            self._close_tts(self._character_tts_engine)
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

    def inherit_character_models(self, base: "ServiceContext") -> None:
        """Copy the bindings for engines borrowed from the shared context."""
        self.llm_catalog = getattr(base, "llm_catalog", None)
        self._character_llm_entry = base._character_llm_entry
        self._character_speech = base._character_speech.copy()

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
            self._agent_replaced()
        else:
            self.agent_engine = None
            await self.init_agent(
                self.character_config.agent_config,
                self.character_config.persona_prompt,
            )

    # ==== user-selectable model

    def _agent_replaced(self) -> None:
        """A new agent starts on the character's LLM; reapply the user's choice."""
        agent = self.agent_engine
        self._character_llm = (
            (agent.llm, agent.interrupt_method)
            if isinstance(agent, BasicMemoryAgent)
            else None
        )
        self.active_model = self._character_llm_entry
        self._applied_llm_override = None
        self._apply_model_selection()

    def _apply_model_selection(self) -> None:
        """Point the agent at the selected model, or back at the character's.

        Sync on purpose: the swap must not interleave with a running turn.
        """
        agent = self.agent_engine
        if not isinstance(agent, BasicMemoryAgent) or self._character_llm is None:
            self.active_model = None
            return

        entry = None
        if self.llm_catalog is not None and self.selected_model_id:
            entry = self.llm_catalog.resolve(
                self.selected_model_id, self.user_id, self.user_emails
            )
        if entry == self._applied_llm_override:
            self._apply_thinking()
            return

        if entry is not None:
            try:
                agent.use_llm(self.llm_catalog.client(entry), entry.interrupt_method)
            except Exception as error:
                logger.error(
                    f"Model '{entry.id}' could not be initialized "
                    f"({type(error).__name__}); using the character's LLM"
                )
                entry = None
        if entry is None:
            agent.use_llm(*self._character_llm)
        self._applied_llm_override = entry
        self.active_model = entry or self._character_llm_entry
        self._apply_thinking()
        logger.info(
            f"Session {self.client_uid} now answers with "
            f"{'model ' + entry.id if entry else 'the character LLM'}"
        )

    def thinking_level(self) -> str | None:
        """The thinking level of the active model; None when it has none."""
        if self.active_model is None:
            return None
        level = self.active_model.thinking_level(
            self.thinking_choices.get(self.active_model.id)
        )
        return level.id if level else None

    def _apply_thinking(self) -> None:
        """Send the active model's chosen level with each request."""
        agent = self.agent_engine
        if not isinstance(agent, BasicMemoryAgent):
            return
        level = (
            self.active_model.thinking_level(
                self.thinking_choices.get(self.active_model.id)
            )
            if self.active_model is not None
            else None
        )
        agent.request_options = dict(level.params) if level and level.params else None

    async def sync_model_selection(self, *, sync_speech: bool = True) -> None:
        """Re-read the user's stored choice and apply it.

        Run before each turn, so a choice made in another tab, an edit to
        ``llm_models.yaml`` and a revoked ``allowed_users`` entry all take
        effect on the next message without reconnecting.
        """
        if not isinstance(self.llm_catalog, LLMModelCatalog):
            return
        repository = self.history_repository
        if repository is not None and self.user_id is not None:
            try:
                self.selected_model_id = await repository.get_user_setting(
                    user_id=self.user_id, key=MODEL_SETTING_KEY
                )
            except Exception:
                logger.exception("Failed to read the user's model choice")
        self._apply_model_selection()
        await self.load_thinking_choice()
        if sync_speech:
            await self._sync_speech_choices()

    async def load_thinking_choice(self) -> None:
        """Re-read and apply the stored thinking level of the active model."""
        entry = self.active_model
        repository = self.history_repository
        if entry is None or repository is None or self.user_id is None:
            self._apply_thinking()
            return
        try:
            stored = await repository.get_user_setting(
                user_id=self.user_id, key=THINKING_SETTING_PREFIX + entry.id
            )
        except Exception:
            logger.exception("Failed to read the user's thinking level")
            stored = self.thinking_choices.get(entry.id)
        if stored is None:
            self.thinking_choices.pop(entry.id, None)
        else:
            self.thinking_choices[entry.id] = stored
        self._apply_thinking()

    async def select_thinking(self, level_id: str, apply: bool = True) -> bool:
        """Store the thinking level of the active model; False when invalid."""
        entry = self.active_model
        if entry is None or not any(
            level.id == level_id for level in entry.thinking_levels
        ):
            return False
        if self.history_repository is not None and self.user_id is not None:
            await self.history_repository.set_user_setting(
                user_id=self.user_id,
                key=THINKING_SETTING_PREFIX + entry.id,
                value=level_id,
            )
        self.thinking_choices[entry.id] = level_id
        if apply:
            self._apply_thinking()
        return True

    async def select_model(self, model_id: str | None, apply: bool = True) -> bool:
        """Store and apply the user's choice; False when it is not available.

        ``None`` goes back to the character's own LLM. ``apply=False`` only
        stores the choice; the next turn picks it up.
        """
        if not isinstance(self.llm_catalog, LLMModelCatalog):
            return False
        if model_id is not None and (
            self.llm_catalog.resolve(model_id, self.user_id, self.user_emails) is None
        ):
            return False
        if self.history_repository is not None and self.user_id is not None:
            await self.history_repository.set_user_setting(
                user_id=self.user_id, key=MODEL_SETTING_KEY, value=model_id
            )
        self.selected_model_id = model_id
        if apply:
            self._apply_model_selection()
        return True

    def _available_speech(self, kind: SpeechKind) -> list[SpeechModelEntry]:
        if self.llm_catalog is None or self._character_asr_engine is None:
            return []
        return self.llm_catalog.available_speech(kind, self.user_id, self.user_emails)

    def _resolve_speech(
        self, kind: SpeechKind, model_id: str | None
    ) -> SpeechModelEntry | None:
        if model_id is None:
            return None
        return next(
            (entry for entry in self._available_speech(kind) if entry.id == model_id),
            None,
        )

    def _set_speech_engine(
        self, kind: SpeechKind, entry: SpeechModelEntry | None, engine
    ) -> None:
        if kind == "tts":
            previous = self._selected_tts_engine
            self._selected_tts_engine = engine
            if previous is not engine:
                self._close_tts(previous)
        else:
            self._selected_asr_engine = engine
        if entry is None:
            self._active_speech.pop(kind, None)
        else:
            self._active_speech[kind] = entry

    def _make_speech_engine(self, entry: SpeechModelEntry):
        kwargs = _engine_kwargs(entry.config, entry.provider)
        factory = (
            TTSFactory.get_tts_engine
            if entry.kind == "tts"
            else ASRFactory.get_asr_system
        )
        try:
            return factory(entry.provider, **kwargs)
        except Exception as error:
            logger.warning(
                f"Speech preset '{entry.id}' could not initialize ({type(error).__name__})"
            )
            return None

    async def _sync_speech_choices(self) -> None:
        for kind in SPEECH_KINDS:
            await self._sync_speech_choice(kind)

    async def sync_asr_choice(self, *, can_apply: Callable[[], bool]) -> None:
        await self._sync_speech_choice("asr", can_apply=can_apply)

    async def _sync_speech_choice(
        self, kind: SpeechKind, *, can_apply: Callable[[], bool] | None = None
    ) -> None:
        if self._character_asr_engine is None:
            return
        choice = self._speech_choices.get(kind)
        repository = self.history_repository
        if repository is not None and self.user_id is not None:
            try:
                choice = await repository.get_user_setting(
                    user_id=self.user_id, key=f"{kind}_model"
                )
            except Exception:
                logger.exception("Failed to read user speech preset")
        if can_apply is not None and not can_apply():
            return
        self._speech_choices[kind] = choice
        entry = self._resolve_speech(kind, choice)
        if entry != self._active_speech.get(kind):
            engine = self._make_speech_engine(entry) if entry is not None else None
            self._set_speech_engine(kind, entry if engine is not None else None, engine)

    async def select_speech_model(
        self, kind: SpeechKind, model_id: str | None, *, apply: bool
    ) -> bool:
        entry = None
        engine = None
        changed = False
        if model_id is not None:
            entry = self._resolve_speech(kind, model_id)
            if entry is None:
                return False
        if apply and entry != self._active_speech.get(kind):
            changed = True
            if entry is not None:
                engine = self._make_speech_engine(entry)
                if engine is None:
                    return False
        try:
            if self.history_repository is not None and self.user_id is not None:
                await self.history_repository.set_user_setting(
                    user_id=self.user_id, key=f"{kind}_model", value=model_id
                )
        except BaseException:
            if kind == "tts":
                self._close_tts(engine)
            raise
        self._speech_choices[kind] = model_id
        if changed:
            self._set_speech_engine(kind, entry, engine)
        return True

    def model_list_payload(self) -> dict:
        """Build the model-list payload: what this user may pick, and the pick."""
        models = (
            self.llm_catalog.available(self.user_id, self.user_emails)
            if isinstance(self.llm_catalog, LLMModelCatalog)
            else []
        )
        payload = {
            "type": "model-list",
            "models": [entry.public_info() for entry in models],
            "current": self._applied_llm_override.id
            if self._applied_llm_override
            else None,
            "thinking": self.thinking_level(),
        }
        if self._character_llm_entry is not None:
            payload["default_model"] = self._character_llm_entry.public_info()
        for kind in SPEECH_KINDS:
            options = self._available_speech(kind)
            active = self._active_speech.get(kind)
            default = self._character_speech.get(kind)
            if default is not None or options or active is not None:
                payload[f"{kind}_models"] = [entry.public_info() for entry in options]
                payload[f"{kind}_current"] = active.id if active else None
                if default is not None:
                    payload[f"{kind}_default_model"] = default.public_info()
        return payload

    def resolve_character_models(
        self, character: CharacterConfig, *, public: bool = False
    ) -> tuple[LLMModelEntry, dict[SpeechKind, SpeechModelEntry]]:
        if not isinstance(self.llm_catalog, LLMModelCatalog):
            raise ValueError("A model catalog is required to load character model_refs")
        return self.llm_catalog.character_models(
            character.model_refs, () if public else character.allowed_users
        )

    async def load_from_config(self, config: Config, *, public: bool = True) -> None:
        """Load a browser character and its referenced engines."""
        character = config.character_config
        llm, speech = self.resolve_character_models(character, public=public)
        bound_llm = (self.llm_catalog.client(llm), llm.interrupt_method)
        asr_entry, tts_entry = speech["asr"], speech["tts"]
        old_asr = self._character_speech.get("asr")
        old_tts = self._character_speech.get("tts")
        asr_engine = self._character_asr_engine
        tts_engine = self._character_tts_engine
        # Validate and build both speech engines before swapping either one.
        if asr_engine is None or old_asr is None or old_asr.config != asr_entry.config:
            asr_engine = ASRFactory.get_asr_system(
                asr_entry.provider,
                **_engine_kwargs(asr_entry.config, asr_entry.provider),
            )
        if tts_engine is None or old_tts is None or old_tts.config != tts_entry.config:
            tts_engine = TTSFactory.get_tts_engine(
                tts_entry.provider,
                **_engine_kwargs(tts_entry.config, tts_entry.provider),
            )
        previous_character = self.character_config
        previous_model = self.live2d_model
        previous_system = self.system_config
        previous_translate = self.translate_engine
        self.character_config = character
        self.system_config = config.system_config or previous_system
        try:
            self.init_live2d(character.live2d_model_name)
            self.init_translate(
                character.tts_preprocessor_config.translator_config,
                previous=previous_character,
            )
            basic = character.agent_config.agent_settings.basic_memory_agent
            await self._init_mcp_components(basic.use_mcpp, basic.mcp_enabled_servers)
            await self.init_agent(
                character.agent_config,
                character.persona_prompt,
                llm_entry=llm,
                bound_llm=bound_llm,
            )
        except BaseException:
            self.character_config = previous_character
            self.live2d_model = previous_model
            self.system_config = previous_system
            self.translate_engine = previous_translate
            if tts_engine is not self._character_tts_engine:
                self._close_tts(tts_engine)
            raise
        previous_tts = self._character_tts_engine
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        if previous_tts is not tts_engine:
            if self._owns_tts_engine:
                self._close_tts(previous_tts)
            self._owns_tts_engine = True
        self._character_speech = speech
        self.config = config
        await self.load_thinking_choice()

    async def load_headless(self, config: Config) -> None:
        """Load a connector's character without allocating speech or Live2D."""
        character = config.character_config
        llm, _ = self.resolve_character_models(character, public=True)
        bound_llm = (self.llm_catalog.client(llm), llm.interrupt_method)
        self.config = config
        self.system_config = config.system_config
        self.character_config = character
        self.live2d_model = None
        basic = character.agent_config.agent_settings.basic_memory_agent
        await self._init_mcp_components(basic.use_mcpp, basic.mcp_enabled_servers)
        await self.init_agent(
            character.agent_config,
            character.persona_prompt,
            llm_entry=llm,
            bound_llm=bound_llm,
        )

    def init_live2d(self, live2d_model_name: str) -> None:
        logger.info(f"Initializing Live2D: {live2d_model_name}")
        try:
            self.live2d_model = Live2dModel(live2d_model_name)
            self.character_config.live2d_model_name = live2d_model_name
        except Exception as e:
            logger.critical(f"Error initializing Live2D: {e}")
            logger.critical("Try to proceed without Live2D...")

    @staticmethod
    def _close_tts(engine: TTSInterface | None) -> None:
        if engine is not None:
            try:
                engine.close()
            except Exception as error:
                logger.warning(f"Failed to close TTS engine ({type(error).__name__})")

    async def init_agent(
        self,
        agent_config: AgentConfig,
        persona_prompt: str,
        *,
        llm_entry: LLMModelEntry | None = None,
        bound_llm=None,
    ) -> None:
        """Initialize or update the LLM engine based on agent configuration."""
        logger.info(f"Initializing Agent: {agent_config.conversation_agent_choice}")

        if (
            bound_llm is None
            and self.agent_engine is not None
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
                bound_llm=bound_llm,
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
        self._character_llm_entry = llm_entry
        self._agent_replaced()

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

    def init_translate(
        self,
        translator_config: TranslatorConfig,
        *,
        previous: CharacterConfig | None = None,
    ) -> None:
        """Initialize or update the translation engine based on the configuration."""

        if not translator_config.translate_audio:
            logger.debug("Translation is disabled.")
            # Drop an engine left over from a previous character config.
            self.translate_engine = None
            return

        if (
            not self.translate_engine
            or previous is None
            or previous.tts_preprocessor_config.translator_config != translator_config
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
            await self._apply_character_config(
                character_config_data, public=config_file_name == "conf.yaml"
            )
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

            # These fields are declared by the preset itself, not inherited.
            CharacterModelRefs.model_validate(raw_character_config.get("model_refs"))
            character_config_data = deep_merge(base_config_data, alt_config_data)
            character_config_data["allowed_users"] = raw_character_config.get(
                "allowed_users", []
            )

        if not character_config_data:
            raise ValueError(f"Failed to load configuration from {config_file_name}")

        return character_config_data, raw_character_config

    async def _apply_character_config(
        self, character_config_data: Any, *, public: bool
    ) -> None:
        new_config = validate_config(
            {
                "system_config": self.system_config.model_dump(),
                "character_config": character_config_data,
            }
        )
        await self.load_from_config(new_config, public=public)
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
