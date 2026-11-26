"""Hot-reloaded system announcements loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re
import threading
from typing import Any, Literal

import yaml
from loguru import logger

AnnouncementLevel = Literal["info", "warning", "important"]

_VALID_LEVELS: frozenset[str] = frozenset({"info", "warning", "important"})
_ANNOUNCEMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_MAX_TITLE_CHARS = 120
_MAX_CONTENT_CHARS = 8000


@dataclass(frozen=True)
class AnnouncementEntry:
    """Validated announcement entry loaded from ``announcements.yaml``."""

    id: str
    title: str
    content: str
    level: AnnouncementLevel
    pinned: bool
    popup: bool
    enabled: bool
    starts_at: datetime | None
    ends_at: datetime | None
    updated_at: datetime
    updated_at_text: str
    order: int

    def is_active(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.starts_at is not None and now < self.starts_at:
            return False
        return self.ends_at is None or now < self.ends_at

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "level": self.level,
            "pinned": self.pinned,
            "popup": self.popup,
            "starts_at": (
                self.starts_at.astimezone(timezone.utc).isoformat()
                if self.starts_at is not None
                else None
            ),
            "ends_at": (
                self.ends_at.astimezone(timezone.utc).isoformat()
                if self.ends_at is not None
                else None
            ),
            "updated_at": self.updated_at_text,
        }


def _local_tz():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_local_tz())
    return dt


def _parse_datetime(value: Any, *, field_name: str, where: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value).astimezone(timezone.utc)
    if isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=_local_tz())
        return dt.astimezone(timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning(f"{where}: invalid {field_name} datetime {value!r}; ignored")
            return None
        return _ensure_aware(dt).astimezone(timezone.utc)
    logger.warning(f"{where}: invalid {field_name} value {value!r}; ignored")
    return None


def _coerce_id(raw_id: Any) -> str | None:
    if isinstance(raw_id, str):
        candidate = raw_id.strip()
    elif isinstance(raw_id, int) and not isinstance(raw_id, bool):
        candidate = str(raw_id)
    elif isinstance(raw_id, date) and not isinstance(raw_id, datetime):
        candidate = raw_id.isoformat()
    else:
        return None
    if not _ANNOUNCEMENT_ID.fullmatch(candidate):
        return None
    return candidate


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _parse_entry(
    raw: Any,
    index: int,
    seen_ids: set[str],
    fallback_time: datetime,
    source: str,
) -> AnnouncementEntry | None:
    where = f"{source}#{index}"
    if not isinstance(raw, dict):
        logger.warning(f"{where}: announcement entry must be a mapping; skipped")
        return None

    ann_id = _coerce_id(raw.get("id"))
    if ann_id is None:
        logger.warning(f"{where}: missing or invalid announcement id; skipped")
        return None
    if ann_id in seen_ids:
        logger.warning(f"{where}: duplicate announcement id {ann_id!r}; skipped")
        return None

    raw_title = raw.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    if not title:
        logger.warning(f"{where} ({ann_id}): missing title; skipped")
        return None
    if len(title) > _MAX_TITLE_CHARS:
        logger.warning(
            f"{where} ({ann_id}): title exceeds {_MAX_TITLE_CHARS} chars; truncated"
        )
        title = title[:_MAX_TITLE_CHARS]

    raw_content = raw.get("content")
    content = raw_content.strip() if isinstance(raw_content, str) else ""
    if not content:
        logger.warning(f"{where} ({ann_id}): missing content; skipped")
        return None
    if len(content) > _MAX_CONTENT_CHARS:
        logger.warning(
            f"{where} ({ann_id}): content exceeds {_MAX_CONTENT_CHARS} chars; truncated"
        )
        content = content[:_MAX_CONTENT_CHARS]

    raw_level = raw.get("level", "info")
    if isinstance(raw_level, str) and raw_level.strip().lower() in _VALID_LEVELS:
        level: AnnouncementLevel = raw_level.strip().lower()  # type: ignore[assignment]
    else:
        logger.warning(
            f"{where} ({ann_id}): invalid level {raw_level!r}; defaulting to 'info'"
        )
        level = "info"

    starts_at = _parse_datetime(
        raw.get("starts_at"), field_name="starts_at", where=f"{where} ({ann_id})"
    )
    ends_at = _parse_datetime(
        raw.get("ends_at"), field_name="ends_at", where=f"{where} ({ann_id})"
    )
    updated_at = _parse_datetime(
        raw.get("updated_at"), field_name="updated_at", where=f"{where} ({ann_id})"
    )
    effective_updated = updated_at or starts_at or fallback_time

    seen_ids.add(ann_id)
    return AnnouncementEntry(
        id=ann_id,
        title=title,
        content=content,
        level=level,
        pinned=_parse_bool(raw.get("pinned"), False),
        popup=_parse_bool(raw.get("popup"), False),
        enabled=_parse_bool(raw.get("enabled"), True),
        starts_at=starts_at,
        ends_at=ends_at,
        updated_at=effective_updated,
        updated_at_text=effective_updated.astimezone(timezone.utc).isoformat(),
        order=index,
    )


class AnnouncementStore:
    """Thread-safe, mtime-cached loader for ``announcements.yaml``."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._mtime_ns: int | None = None
        self._size: int | None = None
        self._entries: tuple[AnnouncementEntry, ...] = ()

    def _parse_document(
        self, data: Any, fallback_time: datetime
    ) -> tuple[AnnouncementEntry, ...] | None:
        if data is None:
            return ()
        if not isinstance(data, dict):
            logger.warning(
                f"{self.path}: root must be a YAML mapping; "
                "keeping previous announcements"
            )
            return None
        raw_list = data.get("announcements")
        if raw_list is None:
            return ()
        if not isinstance(raw_list, list):
            logger.warning(
                f"{self.path}: 'announcements' must be a list; "
                "keeping previous announcements"
            )
            return None
        seen_ids: set[str] = set()
        parsed: list[AnnouncementEntry] = []
        for idx, item in enumerate(raw_list):
            entry = _parse_entry(item, idx, seen_ids, fallback_time, str(self.path))
            if entry is not None:
                parsed.append(entry)
        return tuple(parsed)

    def _reload_if_needed(self) -> tuple[AnnouncementEntry, ...]:
        with self._lock:
            try:
                stat = os.stat(self.path)
            except FileNotFoundError:
                self._mtime_ns = None
                self._size = None
                self._entries = ()
                return self._entries
            except OSError as exc:
                logger.warning(f"Failed to stat {self.path}: {exc}")
                return self._entries

            if self._mtime_ns == stat.st_mtime_ns and self._size == stat.st_size:
                return self._entries

            try:
                raw_text = self.path.read_text(encoding="utf-8")
                data = yaml.safe_load(raw_text)
            except Exception as exc:
                logger.warning(
                    f"Failed to load announcements from {self.path}: {exc}; "
                    "keeping previous announcements"
                )
                return self._entries

            fallback_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            entries = self._parse_document(data, fallback_time)
            if entries is None:
                return self._entries

            self._mtime_ns = stat.st_mtime_ns
            self._size = stat.st_size
            self._entries = entries
            return self._entries

    def list_active(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return currently active announcements ordered by pinned then newest."""
        current = (
            _ensure_aware(now).astimezone(timezone.utc)
            if now
            else datetime.now(timezone.utc)
        )
        entries = self._reload_if_needed()
        active = [entry for entry in entries if entry.is_active(current)]
        # Sort by pinned desc, then updated_at desc, then YAML order asc.
        active.sort(key=lambda e: e.order)
        active.sort(key=lambda e: e.updated_at, reverse=True)
        active.sort(key=lambda e: e.pinned, reverse=True)
        return [entry.to_public_dict() for entry in active]
