"""User-selectable LLM models.

``llm_models.yaml`` (path: ``system_config.llm_models_file``) lists the models
a logged-in user may pick in the web UI instead of the one the character
preset names:

```yaml
models:
  - id: deepseek-chat            # stable key, stored as the user's choice
    name: DeepSeek Chat          # shown in the picker
    description: Fast, general   # optional, shown under the name
    provider: openai_compatible_llm  # any agent_config.llm_configs provider
    base_url: https://api.deepseek.com/v1
    llm_api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
    allowed_users:               # optional; empty or missing means everyone
      - alice@example.com
    thinking:                    # optional; reasoning levels the user picks
      default: off
      levels:
        - id: off
          params: {thinking: {type: disabled}}
        - id: high
          params: {thinking: {type: enabled}, reasoning_effort: high}
```

The remaining keys of an entry are that provider's ``llm_configs`` settings.

``thinking`` lists the reasoning levels offered in the chat input. Each level's
``params`` are extra request-body fields, deep-merged into every request made
at that level, so any vendor's switch can be expressed. A level without
``params`` gets the provider's standard effort field (see
``_effort_shorthand``); ``off`` without ``params`` adds nothing.

The client shows the model's reasoning folded above the reply. Backends ask
for readable reasoning when a request turns it on: Claude's adaptive thinking
gets ``display: summarized``, Vertex's ``thinkingConfig`` gets
``includeThoughts``, and OpenAI Responses reasoning gets ``summary: auto``
(dropped for the key if the API refuses it). An explicit value is kept.
``allowed_users`` follows the character presets' rule (``config_manager/
access.py``): internal user ids or verified login emails, never display names.

A missing file means the feature is off: every session uses its character's
LLM. Edits are picked up without a restart. A file that cannot be parsed keeps
the last good catalog, so a typo cannot widen or drop access.
"""

import os
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import yaml
from loguru import logger
from pydantic import BaseModel, ValidationError

from .agent.stateless_llm.stateless_llm_interface import StatelessLLMInterface
from .agent.stateless_llm_factory import LLMFactory
from .config_manager.access import (
    INVALID,
    is_user_allowed,
    parse_allowed_users,
    warn_unmatched_allowlist_entries,
)
from .config_manager.llm_migration import migrate_model_entry
from .config_manager.stateless_llm import StatelessLLMConfigs
from .config_manager.utils import read_yaml
from .speech_models import (
    SPEECH_KINDS,
    SpeechKind,
    SpeechModelEntry,
    parse_speech_models,
)

DEFAULT_MODELS_FILE = "llm_models.yaml"
# Key of the per-user setting that stores the chosen model id.
MODEL_SETTING_KEY = "llm_model"

_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_MAX_NAME_CHARS = 80
_MAX_DESCRIPTION_CHARS = 200
_ENTRY_KEYS = frozenset(
    {"id", "name", "description", "provider", "allowed_users", "thinking"}
)

# Prefix of the per-user setting that stores the thinking level of one model.
THINKING_SETTING_PREFIX = "llm_thinking:"
# The level id that means "no reasoning"; without ``params`` it adds nothing.
THINKING_OFF = "off"
# Level ids that mean "no reasoning" (``none`` is OpenAI's spelling).
_OFF_IDS = frozenset({THINKING_OFF, "none"})
_LEVEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
_MAX_LEVELS = 8
_MAX_LEVEL_NAME_CHARS = 24


def _effort_shorthand(provider: str, level: str) -> dict[str, Any] | None:
    """Request fields of a level written without ``params``."""
    if level == THINKING_OFF:
        return {}
    if provider == "openai_compatible_llm":
        return {"reasoning_effort": level}
    if provider == "openai_responses_llm":
        return {"reasoning": {"effort": level}}
    if provider == "claude_llm":
        # Adaptive thinking (Claude 4.6+); the backend asks for readable text.
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": level}}
    if provider == "vertex_llm":
        return {"generationConfig": {"thinkingConfig": {"thinkingLevel": level}}}
    return None


def _provider_config_classes() -> dict[str, type[BaseModel]]:
    """Map each ``llm_configs`` provider to its settings class."""
    classes = {}
    for name, info in StatelessLLMConfigs.model_fields.items():
        for candidate in getattr(info.annotation, "__args__", ()):
            if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                classes[name] = candidate
    return classes


_PROVIDER_CONFIGS = _provider_config_classes()


@dataclass(frozen=True)
class ThinkingLevel:
    """One reasoning level of a model."""

    id: str
    name: str
    # Extra request-body fields; compared so an edit replaces the entry.
    params: dict[str, Any] = field(default_factory=dict)

    def public_info(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


@dataclass(frozen=True)
class LLMModelEntry:
    """One selectable model."""

    id: str
    name: str
    description: str
    provider: str
    # Kept as written in YAML; ``is_user_allowed`` denies malformed values.
    allowed_users: Any = field(compare=False, hash=False)
    scope: tuple[str, ...] = ()
    settings: tuple[tuple[str, Any], ...] = ()
    thinking_levels: tuple[ThinkingLevel, ...] = ()
    thinking_default: str | None = None

    @property
    def interrupt_method(self) -> str:
        return dict(self.settings).get("interrupt_method", "user")

    def thinking_level(self, level_id: Any) -> ThinkingLevel | None:
        """The level ``level_id``, else the default one; None without levels."""
        by_id = {level.id: level for level in self.thinking_levels}
        if isinstance(level_id, str) and level_id in by_id:
            return by_id[level_id]
        return by_id.get(self.thinking_default) if self.thinking_default else None

    def public_info(self) -> dict[str, Any]:
        """What a client may know; never the endpoint, the key or the params."""
        info: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }
        # A single level is still reported so the UI can show the (locked)
        # state: the model always thinks, or never does, and cannot be changed.
        if self.thinking_levels:
            info["thinking"] = {
                "levels": [level.public_info() for level in self.thinking_levels],
                "default": self.thinking_default,
            }
        return info


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _parse_thinking(
    raw: Any, provider: str, where: str
) -> tuple[tuple[ThinkingLevel, ...], str | None]:
    """The levels and default of a ``thinking`` block; empty when invalid."""
    if raw is None:
        return (), None
    if not isinstance(raw, dict) or not isinstance(raw.get("levels"), list):
        logger.error(f"{where}: 'thinking' needs a 'levels' list; ignored")
        return (), None

    levels: list[ThinkingLevel] = []
    for item in raw["levels"][:_MAX_LEVELS]:
        spec = {"id": item} if isinstance(item, str) else item
        # YAML 1.1 reads a bare ``off`` as False.
        if isinstance(spec, dict) and spec.get("id") is False:
            spec = {**spec, "id": THINKING_OFF}
        if item is False:
            spec = {"id": THINKING_OFF}
        level_id = spec.get("id") if isinstance(spec, dict) else None
        if not isinstance(level_id, str) or not _LEVEL_ID.fullmatch(level_id):
            logger.error(f"{where}: thinking level {level_id!r} is invalid; ignored")
            return (), None
        if any(level.id == level_id for level in levels):
            logger.error(f"{where}: duplicate thinking level '{level_id}'; ignored")
            return (), None
        params = spec.get("params")
        if params is None:
            params = _effort_shorthand(provider, level_id)
        if not isinstance(params, dict):
            logger.error(
                f"{where}: thinking level '{level_id}' needs 'params' (a mapping "
                "of request fields); ignored"
            )
            return (), None
        levels.append(
            ThinkingLevel(
                id=level_id,
                name=_text(spec.get("name"), _MAX_LEVEL_NAME_CHARS),
                params=params,
            )
        )
    if not levels:
        return (), None

    default = raw.get("default")
    if default is False:
        default = THINKING_OFF
    if not any(level.id == default for level in levels):
        # Without a (valid) default nobody thinks until they ask to: the
        # "off" level when there is one, else the first level.
        fallback = next(
            (level.id for level in levels if level.id in _OFF_IDS), levels[0].id
        )
        if default is not None:
            logger.warning(
                f"{where}: thinking default {default!r} is not a level; "
                f"using '{fallback}'"
            )
        default = fallback
    return tuple(levels), default


def _parse_entry(raw: Any, source: str) -> LLMModelEntry | None:
    if not isinstance(raw, dict):
        logger.error(f"{source}: a model entry is not a mapping; skipped")
        return None

    model_id = raw.get("id")
    if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
        logger.error(
            f"{source}: model id {model_id!r} is invalid (letters, digits and "
            "._:- only, at most 64 characters); skipped"
        )
        return None

    settings = {key: value for key, value in raw.items() if key not in _ENTRY_KEYS}
    # Providers that were folded into openai_compatible_llm still load.
    provider, settings = migrate_model_entry(raw.get("provider"), settings, source)
    config_class = (
        _PROVIDER_CONFIGS.get(provider) if isinstance(provider, str) else None
    )
    if config_class is None:
        logger.error(
            f"{source}: model '{model_id}' has an unknown provider; expected one "
            f"of {', '.join(sorted(_PROVIDER_CONFIGS))}; skipped"
        )
        return None

    allowed_users = raw.get("allowed_users")
    scope = parse_allowed_users(allowed_users)
    if scope is INVALID:
        # Kept in the catalog but usable by nobody: dropping it would turn a
        # typo into a missing model without telling the operator why.
        logger.error(
            f"{source}: model '{model_id}' has a malformed allowed_users; "
            "nobody can use it until that is fixed"
        )
        scope = ()
    else:
        warn_unmatched_allowlist_entries(allowed_users, f"{source} ({model_id})")

    try:
        validated = config_class.model_validate(settings)
    except ValidationError as error:
        # The message of a ValidationError can quote the offending value,
        # which here may be an API key; log only where the problem is.
        problems = ", ".join(
            f"{'.'.join(str(part) for part in item['loc']) or 'entry'}: {item['type']}"
            for item in error.errors()
        )
        logger.error(
            f"{source}: model '{model_id}' has invalid settings ({problems}); skipped"
        )
        return None

    thinking_levels, thinking_default = _parse_thinking(
        raw.get("thinking"), provider, f"{source} ({model_id})"
    )

    return LLMModelEntry(
        id=model_id,
        name=_text(raw.get("name"), _MAX_NAME_CHARS) or model_id,
        description=_text(raw.get("description"), _MAX_DESCRIPTION_CHARS),
        provider=provider,
        allowed_users=allowed_users,
        scope=scope,
        settings=tuple(sorted(validated.model_dump().items())),
        thinking_levels=thinking_levels,
        thinking_default=thinking_default,
    )


def parse_models(data: Any, source: str) -> dict[str, LLMModelEntry]:
    """Build the catalog from a parsed ``llm_models.yaml`` document."""
    models = data.get("models") if isinstance(data, dict) else None
    if models is None:
        return {}
    if not isinstance(models, list):
        raise ValueError("'models' must be a list")

    entries: dict[str, LLMModelEntry] = {}
    for raw in models:
        entry = _parse_entry(raw, source)
        if entry is None:
            continue
        if entry.id in entries:
            logger.error(f"{source}: duplicate model id '{entry.id}'; skipped")
            continue
        entries[entry.id] = entry
    return entries


class LLMModelCatalog:
    """The selectable models plus one shared LLM client per model."""

    def __init__(
        self,
        path: str = DEFAULT_MODELS_FILE,
        refresh_interval: float = 5.0,
    ) -> None:
        self.path = path
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._checked_at: float | None = None
        self._signature: tuple | None = ()
        self._entries: dict[str, LLMModelEntry] = {}
        self._speech_entries: dict[SpeechKind, dict[str, SpeechModelEntry]] = {}
        # Clients are shared by every session using the model, like the
        # character's own LLM client is.
        self._clients: dict[str, tuple[LLMModelEntry, StatelessLLMInterface]] = {}

    # ---- loading

    def _file_signature(self) -> tuple | None:
        try:
            stat = os.stat(self.path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _current(self) -> dict[str, LLMModelEntry]:
        with self._lock:
            now = time.monotonic()
            if (
                self._checked_at is not None
                and now - self._checked_at < self.refresh_interval
            ):
                return self._entries
            self._checked_at = now

            signature = self._file_signature()
            if signature == self._signature:
                return self._entries
            self._signature = signature

            if signature is None:
                if self._entries:
                    logger.warning(
                        f"{self.path} is gone; model selection is now disabled"
                    )
                self._entries = {}
                self._speech_entries = {}
                self._clients.clear()
                return self._entries

            try:
                data = read_yaml(self.path)
                entries = parse_models(data, self.path)
                speech_entries = {
                    kind: parse_speech_models(data, kind, self.path)
                    for kind in SPEECH_KINDS
                }
            except (OSError, ValueError, yaml.YAMLError) as error:
                logger.error(
                    f"{self.path} cannot be loaded ({type(error).__name__}); "
                    "keeping the previous model list"
                )
                return self._entries

            self._entries = entries
            self._speech_entries = speech_entries
            for model_id in list(self._clients):
                if entries.get(model_id) != self._clients[model_id][0]:
                    del self._clients[model_id]
            logger.info(f"Loaded {len(entries)} selectable LLM model(s)")
            return self._entries

    # ---- queries

    def available(
        self,
        user_id: str | None,
        emails: str | Iterable[str] | None,
    ) -> list[LLMModelEntry]:
        """Models this user may pick, in file order."""
        if emails is not None and not isinstance(emails, str):
            emails = tuple(emails)
        return [
            entry
            for entry in self._current().values()
            if is_user_allowed(entry.allowed_users, user_id, emails)
        ]

    def resolve(
        self,
        model_id: Any,
        user_id: str | None,
        emails: str | Iterable[str] | None,
    ) -> LLMModelEntry | None:
        """The entry for ``model_id`` when it exists and the user may use it."""
        if not isinstance(model_id, str):
            return None
        entry = self._current().get(model_id)
        if entry is None:
            return None
        if emails is not None and not isinstance(emails, str):
            emails = tuple(emails)
        if not is_user_allowed(entry.allowed_users, user_id, emails):
            return None
        return entry

    def available_speech(
        self, kind: SpeechKind, user_id: str | None, emails: tuple[str, ...]
    ) -> list[SpeechModelEntry]:
        self._current()  # Refresh both sections from the same file snapshot.
        return [
            entry
            for entry in self._speech_entries.get(kind, {}).values()
            if is_user_allowed(entry.allowed_users, user_id, emails)
        ]

    def client(self, entry: LLMModelEntry) -> StatelessLLMInterface:
        """The shared LLM client of a model, created on first use."""
        with self._lock:
            cached = self._clients.get(entry.id)
            if cached is not None and cached[0] == entry:
                return cached[1]
            llm = LLMFactory.create_llm(
                llm_provider=entry.provider,
                **{
                    key: value
                    for key, value in entry.settings
                    if key != "interrupt_method"
                },
            )
            self._clients[entry.id] = (entry, llm)
            return llm

    async def close(self) -> None:
        """Close every client; for server shutdown, when no session uses them."""
        with self._lock:
            clients = [llm for _entry, llm in self._clients.values()]
            self._clients.clear()
        for llm in clients:
            try:
                await llm.close()
            except Exception as error:
                logger.warning(f"Closing an LLM client failed ({type(error).__name__})")
