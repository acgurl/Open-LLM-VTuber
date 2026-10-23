"""History repository factory.

Adding another database means implementing ``HistoryRepository`` and adding a
case here. The rest of the application only depends on the interface.
"""

from .base import HistoryRepository
from .sqlite import SQLiteHistoryRepository


def create_history_repository(
    *,
    backend: str,
    sqlite_path: str,
) -> HistoryRepository:
    normalized = backend.strip().lower()
    if normalized == "sqlite":
        return SQLiteHistoryRepository(sqlite_path)
    raise ValueError(f"Unsupported history storage backend: {backend!r}")
