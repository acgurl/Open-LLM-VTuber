"""History storage abstraction and implementations."""

from .archive import ArchiveResult, archive_user_histories
from .base import (
    DEFAULT_USER_ID,
    HistoryMessage,
    HistoryNotFoundError,
    HistoryRepository,
    UserMCPServer,
    validate_identity,
    validate_key,
    validate_user_id,
)
from .factory import create_history_repository
from .legacy import LegacyImportResult, import_legacy_histories
from .sqlite import SQLiteHistoryRepository
from .user_store import UserHistoryStore

__all__ = [
    "ArchiveResult",
    "DEFAULT_USER_ID",
    "HistoryMessage",
    "HistoryNotFoundError",
    "HistoryRepository",
    "LegacyImportResult",
    "SQLiteHistoryRepository",
    "UserHistoryStore",
    "UserMCPServer",
    "archive_user_histories",
    "create_history_repository",
    "import_legacy_histories",
    "validate_identity",
    "validate_key",
    "validate_user_id",
]
