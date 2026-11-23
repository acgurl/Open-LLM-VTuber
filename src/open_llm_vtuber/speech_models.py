"""Speech presets advertised by the model menu, separate from character defaults."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError

from .config_manager.access import INVALID, parse_allowed_users
from .config_manager.asr import ASRConfig
from .config_manager.tts import TTSConfig

SpeechKind = Literal["tts", "asr"]
SPEECH_KINDS: tuple[SpeechKind, ...] = ("tts", "asr")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


@dataclass(frozen=True)
class SpeechModelEntry:
    id: str
    name: str
    description: str
    provider: str
    kind: SpeechKind
    # None reuses the provider's settings from the server's base config.
    config: TTSConfig | ASRConfig | None = field(repr=False)
    allowed_users: Any = field(repr=False)

    def public_info(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description}


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def parse_speech_models(
    data: Any, kind: SpeechKind, source: str
) -> dict[str, SpeechModelEntry]:
    """Read one optional catalog section, without starting any engines."""
    key = f"{kind}_models"
    rows = data.get(key) if isinstance(data, dict) else None
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise ValueError(f"'{key}' must be a list")

    result = {}
    config_class = TTSConfig if kind == "tts" else ASRConfig
    selector = f"{kind}_model"
    for row in rows:
        model_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(model_id, str) or not _ID.fullmatch(model_id):
            logger.error(f"{source}: invalid id in {key}; skipped")
            continue
        where = f"{source} ({key}: {model_id})"
        if model_id in result:
            logger.error(f"{where}: duplicate id; skipped")
            continue
        provider = row.get("provider")
        if provider not in config_class.model_fields[selector].annotation.__args__:
            logger.error(f"{where}: unknown provider; skipped")
            continue
        options = row.get("allowed_users")
        if parse_allowed_users(options) is INVALID:
            logger.error(f"{where}: malformed allowed_users; skipped")
            continue
        config = None
        if "settings" in row:
            try:
                if not isinstance(row["settings"], dict):
                    raise ValueError
                config = config_class.model_validate(
                    {selector: provider, provider: row["settings"]}
                )
            except (ValidationError, ValueError):
                logger.error(f"{where}: invalid settings; skipped")
                continue
        result[model_id] = SpeechModelEntry(
            id=model_id,
            name=_text(row.get("name"), 80) or model_id,
            description=_text(row.get("description"), 200),
            provider=provider,
            kind=kind,
            config=config,
            allowed_users=options,
        )
    return result


def speech_config_for(
    entry: SpeechModelEntry, base_config: TTSConfig | ASRConfig
) -> TTSConfig | ASRConfig | None:
    """Resolve explicit settings, or the provider already configured in conf.yaml."""
    if entry.config is not None:
        return entry.config
    settings = getattr(base_config, entry.provider, None)
    if settings is None:
        if isinstance(base_config, TTSConfig) and entry.provider == "pyttsx3_tts":
            return TTSConfig(tts_model="pyttsx3_tts")
        return None
    return base_config
