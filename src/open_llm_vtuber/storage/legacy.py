"""One-time import of the legacy JSON chat history layout.

The JSON files are copied into the configured repository and then moved to a
backup directory, so a restart cannot resurrect histories the user deleted.
"""

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from loguru import logger

from .base import HistoryMessage, HistoryRepository, validate_key, validate_user_id


@dataclass
class LegacyImportResult:
    imported: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.imported + self.skipped + self.failed


def _is_safe_filename(filename: str) -> bool:
    """Validate filename for safety and allowed characters."""
    if not filename or len(filename) > 255 or filename in {".", ".."}:
        return False
    pattern = re.compile(r"^[\w\-_\u0020-\u007E\u00A0-\uFFFF]+$")
    return bool(pattern.match(filename))


def _sanitize_path_component(component: str) -> str:
    """Sanitize and validate a path component."""
    sanitized = os.path.basename(component.strip())
    if not _is_safe_filename(sanitized):
        raise ValueError(f"Invalid characters in path component: {component}")
    return sanitized


def _get_safe_history_path(
    conf_uid: str,
    history_uid: str,
    base_dir: str = "chat_history",
) -> str:
    """Get a contained path for a legacy history file."""
    safe_conf_uid = _sanitize_path_component(conf_uid)
    safe_history_uid = _sanitize_path_component(history_uid)
    base_path = os.path.abspath(base_dir)
    full_path = os.path.normpath(
        os.path.join(base_path, safe_conf_uid, f"{safe_history_uid}.json")
    )

    try:
        common = os.path.commonpath([base_path, os.path.abspath(full_path)])
    except ValueError as exc:
        raise ValueError("Invalid path: Path traversal detected") from exc
    if os.path.normcase(common) != os.path.normcase(base_path):
        raise ValueError("Invalid path: Path traversal detected")
    return full_path


def _fallback_timestamp(source: Path) -> str:
    return datetime.fromtimestamp(source.stat().st_mtime).isoformat(timespec="seconds")


def _read_legacy_file(
    source: Path,
) -> tuple[dict, list[HistoryMessage], str | None]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("History file must contain a list")

    metadata: dict = {}
    metadata_timestamp = None
    messages: list[HistoryMessage] = []
    fallback = _fallback_timestamp(source)

    for item in data:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        if role == "metadata":
            metadata.update(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"role", "timestamp"}
                }
            )
            if isinstance(item.get("timestamp"), str):
                metadata_timestamp = item["timestamp"]
            continue

        if role not in {"human", "ai", "system"}:
            logger.warning(f"Skipping legacy message with invalid role: {role!r}")
            continue

        content = item.get("content")
        if not isinstance(content, str):
            logger.warning("Skipping legacy message with non-string content")
            continue

        timestamp = item.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            timestamp = fallback

        message: HistoryMessage = {
            "role": role,
            "timestamp": timestamp,
            "content": content,
        }
        if isinstance(item.get("name"), str):
            message["name"] = item["name"]
        if isinstance(item.get("avatar"), str):
            message["avatar"] = item["avatar"]
        messages.append(message)

    return metadata, messages, metadata_timestamp


def _move_to_backup(
    source: Path,
    *,
    conf_uid: str,
    history_uid: str,
    backup_root: Path,
) -> None:
    destination_dir = backup_root / _sanitize_path_component(conf_uid)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{_sanitize_path_component(history_uid)}.json"
    if destination.exists():
        destination = destination.with_name(
            f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}"
        )
    shutil.move(str(source), str(destination))


async def import_legacy_histories(
    repository: HistoryRepository,
    *,
    user_id: str,
    legacy_dir: str = "chat_history",
    backup_dir: str = "data/storage/legacy_history",
) -> LegacyImportResult:
    """Import every legacy JSON history into ``user_id``.

    Files are moved to ``backup_dir`` after they have been imported or were
    already present. Invalid files are left in place and counted as failures.
    """
    validate_user_id(user_id)
    result = LegacyImportResult()
    root = Path(legacy_dir)
    backup_root = Path(backup_dir)

    if not root.is_dir():
        logger.debug(f"Legacy history directory not found: {root}")
        return result

    for conf_dir in sorted(root.iterdir()):
        if not conf_dir.is_dir():
            continue
        try:
            conf_uid = _sanitize_path_component(conf_dir.name)
        except ValueError:
            logger.warning(f"Skipping unsafe legacy character directory: {conf_dir}")
            result.failed += 1
            continue

        for source in sorted(conf_dir.glob("*.json")):
            if source.is_symlink() or not source.is_file():
                logger.warning(f"Skipping unsafe legacy history path: {source}")
                result.failed += 1
                continue

            history_uid = source.stem
            try:
                validate_key(conf_uid, "conf_uid")
                validate_key(history_uid, "history_uid")
                # Validate the path is still contained in the legacy directory.
                _get_safe_history_path(conf_uid, history_uid, str(root))
                metadata, messages, metadata_timestamp = _read_legacy_file(source)
            except Exception as exc:
                logger.error(f"Failed to read legacy history {source}: {exc}")
                result.failed += 1
                continue

            try:
                if messages:
                    imported = await repository.import_history(
                        user_id=user_id,
                        conf_uid=conf_uid,
                        history_uid=history_uid,
                        messages=messages,
                        metadata=metadata,
                        created_at=metadata_timestamp or messages[0]["timestamp"],
                        updated_at=messages[-1]["timestamp"],
                        legacy_path=str(source),
                    )
                    if imported:
                        result.imported += 1
                    else:
                        logger.warning(
                            f"Legacy history already exists, skipping import: {source}"
                        )
                        result.skipped += 1
                else:
                    result.skipped += 1

                _move_to_backup(
                    source,
                    conf_uid=conf_uid,
                    history_uid=history_uid,
                    backup_root=backup_root,
                )
            except Exception as exc:
                logger.error(f"Failed to import legacy history {source}: {exc}")
                result.failed += 1

    logger.info(
        "Legacy history import complete: "
        f"{result.imported} imported, {result.skipped} skipped, "
        f"{result.failed} failed"
    )
    return result
