"""Loads configurations written for LLM providers that no longer exist.

``deepseek_llm``, ``ollama_llm`` and the like were ``openai_compatible_llm``
with another default ``base_url``. They are mapped onto it, with the defaults
they used to imply filled in, wherever a configuration names one: the
``agent_config`` of conf.yaml and of character files, and the entries of
``llm_models.yaml``. The mapping happens on the loaded data at validation
time; the files on disk are left as they are.
"""

from collections.abc import MutableMapping
from typing import Any

from loguru import logger

OPENAI_COMPATIBLE = "openai_compatible_llm"

# What each removed provider implied when its section left the key out.
LEGACY_OPENAI_COMPATIBLE: dict[str, dict[str, Any]] = {
    "openai_llm": {
        "base_url": "https://api.openai.com/v1",
        "interrupt_method": "system",
    },
    "ollama_llm": {
        "base_url": "http://localhost:11434/v1",
        "llm_api_key": "default_api_key",
        "interrupt_method": "system",
    },
    "lmstudio_llm": {
        "base_url": "http://localhost:1234/v1",
        "llm_api_key": "default_api_key",
        "interrupt_method": "system",
    },
    "gemini_llm": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
    "zhipu_llm": {"base_url": "https://open.bigmodel.cn/api/paas/v4/"},
    "deepseek_llm": {"base_url": "https://api.deepseek.com/v1"},
    "groq_llm": {
        "base_url": "https://api.groq.com/openai/v1",
        "interrupt_method": "system",
    },
    "mistral_llm": {"base_url": "https://api.mistral.ai/v1"},
    # Its prompt templates are gone; chat-template handling is the server's job.
    "stateless_llm_with_template": {},
}

# Settings only the removed backends understood.
_DROPPED_SETTINGS = ("keep_alive", "unload_at_exit", "template")

_warned: set[str] = set()


def _warn_once(provider: str, source: str) -> None:
    if provider in _warned:
        return
    _warned.add(provider)
    logger.warning(
        f"{source}: LLM provider '{provider}' was merged into "
        f"'{OPENAI_COMPATIBLE}' and is mapped to it automatically. "
        f"Rename it to '{OPENAI_COMPATIBLE}' (with its base_url) to silence this."
    )


def legacy_settings(provider: str, settings: Any) -> dict[str, Any]:
    """``openai_compatible_llm`` settings equal to a removed provider's."""
    merged = dict(settings) if isinstance(settings, MutableMapping) else {}
    for key in _DROPPED_SETTINGS:
        merged.pop(key, None)
    for key, value in LEGACY_OPENAI_COMPATIBLE[provider].items():
        if merged.get(key) is None:
            merged[key] = value
    return merged


def migrate_model_entry(provider: Any, settings: dict[str, Any], source: str):
    """Provider and settings of an ``llm_models.yaml`` entry, mapped if legacy."""
    if not isinstance(provider, str) or provider not in LEGACY_OPENAI_COMPATIBLE:
        return provider, settings
    _warn_once(provider, source)
    return OPENAI_COMPATIBLE, legacy_settings(provider, settings)


def migrate_agent_config(agent_config: Any, source: str = "agent_config") -> list[str]:
    """Map removed providers in an ``agent_config`` mapping, in place.

    The provider the agent selects becomes the ``openai_compatible_llm``
    section; sections of removed providers nobody selects are dropped.
    Returns what was changed, for logging.
    """
    if not isinstance(agent_config, MutableMapping):
        return []
    changes: list[str] = []

    settings = agent_config.get("agent_settings")
    basic = (
        settings.get("basic_memory_agent")
        if isinstance(settings, MutableMapping)
        else None
    )
    selected = basic.get("llm_provider") if isinstance(basic, MutableMapping) else None
    pool = agent_config.get("llm_configs")
    if not isinstance(pool, MutableMapping):
        pool = None

    if isinstance(selected, str) and selected in LEGACY_OPENAI_COMPATIBLE:
        _warn_once(selected, source)
        basic["llm_provider"] = OPENAI_COMPATIBLE
        changes.append(f"llm_provider: {selected} -> {OPENAI_COMPATIBLE}")
        if pool is not None:
            original = pool.get(selected)
            section = legacy_settings(selected, original)
            existing = pool.get(OPENAI_COMPATIBLE)
            if isinstance(existing, MutableMapping):
                if not (
                    isinstance(original, MutableMapping) and original.get("llm_api_key")
                ):
                    # A partial override (say, a character file changing only
                    # the model) of settings that were already migrated.
                    section = {**existing, **section}
                else:
                    changes.append(
                        f"llm_configs.{OPENAI_COMPATIBLE} replaced by the "
                        f"settings of {selected}"
                    )
            pool[OPENAI_COMPATIBLE] = section

    if pool is not None:
        for name in LEGACY_OPENAI_COMPATIBLE:
            if name in pool:
                del pool[name]
                changes.append(f"llm_configs.{name} removed")
    return changes
