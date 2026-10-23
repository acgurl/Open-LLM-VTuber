"""Export a user's histories to a standalone JSON archive.

Used when switching from the historical single-user mode to OIDC: the
``local`` account is kept in the database but no session is bound to it, and
its histories are exported so they remain auditable and recoverable.
"""

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path

from loguru import logger

from .base import HistoryRepository
from .user_store import UserHistoryStore

DEFAULT_ARCHIVE_FILENAME = "local-history-archive.json"


@dataclass(frozen=True)
class ArchiveResult:
    path: Path
    history_count: int
    message_count: int
    created: bool


def _existing_archive(path: Path) -> ArchiveResult | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return ArchiveResult(
        path=path,
        history_count=int(data.get("history_count", 0)),
        message_count=int(data.get("message_count", 0)),
        created=False,
    )


async def archive_user_histories(
    repository: HistoryRepository,
    *,
    user_id: str,
    archive_dir: str | Path,
    filename: str = DEFAULT_ARCHIVE_FILENAME,
) -> ArchiveResult | None:
    """Write every non-empty history of ``user_id`` to one JSON file.

    The archive is idempotent: once the file exists it is left untouched so a
    restart cannot overwrite the original export. Returns ``None`` when the
    user has no histories.
    """
    directory = Path(archive_dir)
    path = directory / filename

    if path.exists():
        existing = _existing_archive(path)
        if existing is not None:
            logger.info(
                f"Legacy history archive already exists at {path} "
                f"({existing.history_count} histories, "
                f"{existing.message_count} messages)"
            )
            return existing

    store = UserHistoryStore(repository, user_id)
    histories: list[dict] = []
    message_count = 0

    for conf_uid in await repository.list_conf_uids(user_id=user_id):
        for item in await store.list_histories(conf_uid):
            history_uid = item["uid"]
            messages = await store.get_history(conf_uid, history_uid)
            if not messages:
                continue
            metadata = await store.get_metadata(conf_uid, history_uid)
            histories.append(
                {
                    "conf_uid": conf_uid,
                    "history_uid": history_uid,
                    "metadata": metadata,
                    "messages": messages,
                }
            )
            message_count += len(messages)

    if not histories:
        return None

    payload = {
        "archive_version": 1,
        "user_id": user_id,
        "archived_at": datetime.now().isoformat(timespec="seconds"),
        "history_count": len(histories),
        "message_count": message_count,
        "histories": histories,
    }

    directory.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    logger.info(
        f"Archived {len(histories)} histories ({message_count} messages) "
        f"for user {user_id!r} to {path}"
    )
    return ArchiveResult(
        path=path,
        history_count=len(histories),
        message_count=message_count,
        created=True,
    )
