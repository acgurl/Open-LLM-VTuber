"""History storage abstraction and implementations."""

from .base import (
    DEFAULT_USER_ID,
    HistoryMessage,
    HistoryNotFoundError,
    HistoryRepository,
    validate_key,
    validate_user_id,
)
from .factory import create_history_repository
from .legacy import LegacyImportResult, import_legacy_histories
from .sqlite import SQLiteHistoryRepository
from .user_store import UserHistoryStore

__all__ = [
    "DEFAULT_USER_ID",
    "HistoryMessage",
    "HistoryNotFoundError",
    "HistoryRepository",
    "LegacyImportResult",
    "SQLiteHistoryRepository",
    "UserHistoryStore",
    "create_history_repository",
    "import_legacy_histories",
    "validate_key",
    "validate_user_id",
]
