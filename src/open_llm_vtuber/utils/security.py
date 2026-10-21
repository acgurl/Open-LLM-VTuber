"""Helpers for path containment and safe logging."""

import re
from pathlib import Path
from typing import Any, Iterable


_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
    "credential",
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_URL_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)=([^&\s]+)"
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _redact_string(value: str) -> str:
    value = _BEARER_RE.sub(r"\1***", value)
    return _URL_SECRET_RE.sub(r"\1=***", value)


def redact_secrets(value: Any) -> Any:
    """Recursively replace values of secret-looking keys for logging."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()

    if isinstance(value, dict):
        return {
            key: "***" if _is_sensitive_key(key) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def resolve_existing_file_within(
    base_dir: str | Path,
    relative_path: str,
    allowed_suffixes: Iterable[str] | None = None,
) -> Path:
    """Resolve a client-supplied relative path, rejecting anything outside base_dir."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("Path must be a non-empty string")
    if "\x00" in relative_path:
        raise ValueError("Invalid path")

    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    base = Path(base_dir).resolve()
    target = (base / candidate).resolve()

    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("Path escapes the allowed directory") from exc

    if target == base or not target.is_file():
        raise ValueError("File not found")

    if allowed_suffixes:
        allowed = {suffix.lower() for suffix in allowed_suffixes}
        if target.suffix.lower() not in allowed:
            raise ValueError(f"Unsupported file type: {target.suffix or '(none)'}")

    return target
