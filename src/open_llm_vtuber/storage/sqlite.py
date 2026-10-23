"""SQLite implementation of the history repository."""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
import uuid

from .base import (
    HistoryMessage,
    HistoryNotFoundError,
    HistoryRepository,
    validate_identity,
    validate_key,
    validate_user_id,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    display_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,
    created_at TEXT NOT NULL,
    last_login_at TEXT NOT NULL,
    PRIMARY KEY (provider, subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user_id
    ON user_identities(user_id);

CREATE TABLE IF NOT EXISTS histories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conf_uid TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_path TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_histories_user_conf_updated
    ON histories(user_id, conf_uid, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_id TEXT NOT NULL
        REFERENCES histories(id) ON DELETE CASCADE ON UPDATE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('human', 'ai', 'system')),
    content TEXT NOT NULL,
    name TEXT,
    avatar TEXT,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_history_id
    ON messages(history_id, id);
"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_history_uid() -> str:
    return f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{uuid.uuid4().hex}"


def _load_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _message_from_row(row: sqlite3.Row) -> HistoryMessage:
    message: HistoryMessage = {
        "role": row["role"],
        "timestamp": row["timestamp"],
        "content": row["content"],
    }
    if row["name"] is not None:
        message["name"] = row["name"]
    if row["avatar"] is not None:
        message["avatar"] = row["avatar"]
    return message


def _validate_message(
    message: HistoryMessage,
) -> tuple[str, str, str, str | None, str | None]:
    role = message.get("role")
    if role not in {"human", "ai", "system"}:
        raise ValueError(f"Invalid message role: {role!r}")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Message content must be a string")
    timestamp = message.get("timestamp") or _now_iso()
    name = message.get("name")
    avatar = message.get("avatar")
    return role, content, timestamp, name, avatar


class SQLiteHistoryRepository(HistoryRepository):
    """History repository backed by a single SQLite database.

    A single connection is serialized with a thread lock. This is sufficient
    for the server's current single-process deployment and keeps the adapter
    dependency-free. A future backend can use a real connection pool without
    changing the interface.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                return

            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=5.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(_SCHEMA)
            applied_at = _now_iso()
            # Version 1: histories/messages/users. Version 2: OIDC identities.
            for version in (1, 2):
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES(?, ?)",
                    (version, applied_at),
                )
            conn.commit()
            self._conn = conn

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    async def _run(self, func, *args, **kwargs):
        def invoke():
            with self._lock:
                if self._conn is None:
                    raise RuntimeError("History repository is not initialized")
                return func(*args, **kwargs)

        return await asyncio.to_thread(invoke)

    @staticmethod
    def _ensure_user_sync(
        conn: sqlite3.Connection,
        user_id: str,
        display_name: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO users(id, display_name, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "display_name = COALESCE(excluded.display_name, users.display_name)",
            (user_id, display_name, _now_iso()),
        )

    async def ensure_user(self, user_id: str, display_name: str | None = None) -> None:
        validate_user_id(user_id)
        await self._run(self._ensure_user_for_user_sync, user_id, display_name)

    def _ensure_user_for_user_sync(
        self, user_id: str, display_name: str | None
    ) -> None:
        with self._conn:
            self._ensure_user_sync(self._conn, user_id, display_name)

    async def resolve_user_identity(
        self,
        *,
        provider: str,
        subject: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> str:
        validate_identity(provider, "provider")
        validate_identity(subject, "subject")
        return await self._run(
            self._resolve_user_identity_sync,
            provider,
            subject,
            display_name,
            email,
        )

    def _resolve_user_identity_sync(
        self,
        provider: str,
        subject: str,
        display_name: str | None,
        email: str | None,
    ) -> str:
        now = _now_iso()
        with self._conn:
            row = self._conn.execute(
                "SELECT user_id FROM user_identities "
                "WHERE provider = ? AND subject = ?",
                (provider, subject),
            ).fetchone()

            if row is not None:
                user_id = row["user_id"]
                self._ensure_user_sync(self._conn, user_id, display_name)
                self._conn.execute(
                    "UPDATE user_identities SET email = COALESCE(?, email), "
                    "last_login_at = ? WHERE provider = ? AND subject = ?",
                    (email, now, provider, subject),
                )
                return user_id

            user_id = uuid.uuid4().hex
            self._ensure_user_sync(self._conn, user_id, display_name)
            self._conn.execute(
                "INSERT INTO user_identities("
                "provider, subject, user_id, email, created_at, last_login_at"
                ") VALUES(?, ?, ?, ?, ?, ?)",
                (provider, subject, user_id, email, now, now),
            )
            return user_id

    async def list_conf_uids(self, *, user_id: str) -> list[str]:
        validate_user_id(user_id)
        return await self._run(self._list_conf_uids_sync, user_id)

    def _list_conf_uids_sync(self, user_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT conf_uid FROM histories "
            "WHERE user_id = ? ORDER BY conf_uid",
            (user_id,),
        ).fetchall()
        return [row["conf_uid"] for row in rows]

    async def create_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str | None = None,
    ) -> str:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        if history_uid is not None:
            validate_key(history_uid, "history_uid")
        return await self._run(
            self._create_history_sync, user_id, conf_uid, history_uid
        )

    def _create_history_sync(
        self,
        user_id: str,
        conf_uid: str,
        history_uid: str | None,
    ) -> str:
        history_uid = history_uid or _new_history_uid()
        now = _now_iso()
        with self._conn:
            self._ensure_user_sync(self._conn, user_id)
            self._conn.execute(
                "INSERT INTO histories("
                "id, user_id, conf_uid, metadata_json, created_at, updated_at"
                ") VALUES(?, ?, ?, NULL, ?, ?)",
                (history_uid, user_id, conf_uid, now, now),
            )
        return history_uid

    async def history_exists(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> bool:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        return await self._run(
            self._history_exists_sync, user_id, conf_uid, history_uid
        )

    def _history_exists_sync(
        self, user_id: str, conf_uid: str, history_uid: str
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM histories WHERE id = ? AND user_id = ? AND conf_uid = ?",
            (history_uid, user_id, conf_uid),
        ).fetchone()
        return row is not None

    async def list_histories(self, *, user_id: str, conf_uid: str) -> list[dict]:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        return await self._run(self._list_histories_sync, user_id, conf_uid)

    def _list_histories_sync(self, user_id: str, conf_uid: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT h.id, m.role, m.content, m.name, m.avatar, m.timestamp "
            "FROM histories h "
            "JOIN messages m ON m.id = ("
            "  SELECT m2.id FROM messages m2 "
            "  WHERE m2.history_id = h.id ORDER BY m2.id DESC LIMIT 1"
            ") "
            "WHERE h.user_id = ? AND h.conf_uid = ? "
            "ORDER BY m.timestamp DESC, h.id DESC",
            (user_id, conf_uid),
        ).fetchall()

        return [
            {
                "uid": row["id"],
                "latest_message": _message_from_row(row),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    async def get_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> list[HistoryMessage]:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        return await self._run(self._get_history_sync, user_id, conf_uid, history_uid)

    def _get_history_sync(
        self, user_id: str, conf_uid: str, history_uid: str
    ) -> list[HistoryMessage]:
        rows = self._conn.execute(
            "SELECT m.role, m.timestamp, m.content, m.name, m.avatar "
            "FROM messages m "
            "JOIN histories h ON h.id = m.history_id "
            "WHERE h.id = ? AND h.user_id = ? AND h.conf_uid = ? "
            "ORDER BY m.id",
            (history_uid, user_id, conf_uid),
        ).fetchall()

        return [_message_from_row(row) for row in rows]

    async def store_message(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        role: str,
        content: str,
        name: str | None = None,
        avatar: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        if role not in {"human", "ai", "system"}:
            raise ValueError(f"Invalid message role: {role!r}")
        await self._run(
            self._store_message_sync,
            user_id,
            conf_uid,
            history_uid,
            role,
            content,
            name,
            avatar,
            timestamp or _now_iso(),
        )

    def _store_message_sync(
        self,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        role: str,
        content: str,
        name: str | None,
        avatar: str | None,
        timestamp: str,
    ) -> None:
        with self._conn:
            row = self._conn.execute(
                "SELECT user_id, conf_uid FROM histories WHERE id = ?",
                (history_uid,),
            ).fetchone()

            if row is None:
                self._ensure_user_sync(self._conn, user_id)
                self._conn.execute(
                    "INSERT INTO histories("
                    "id, user_id, conf_uid, metadata_json, created_at, updated_at"
                    ") VALUES(?, ?, ?, NULL, ?, ?)",
                    (history_uid, user_id, conf_uid, timestamp, timestamp),
                )
            elif row["user_id"] != user_id or row["conf_uid"] != conf_uid:
                raise HistoryNotFoundError(history_uid)

            self._conn.execute(
                "INSERT INTO messages("
                "history_id, role, content, name, avatar, timestamp"
                ") VALUES(?, ?, ?, ?, ?, ?)",
                (history_uid, role, content, name, avatar, timestamp),
            )
            self._conn.execute(
                "UPDATE histories SET updated_at = ? WHERE id = ?",
                (timestamp, history_uid),
            )

    async def get_metadata(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> dict:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        return await self._run(self._get_metadata_sync, user_id, conf_uid, history_uid)

    def _get_metadata_sync(self, user_id: str, conf_uid: str, history_uid: str) -> dict:
        row = self._conn.execute(
            "SELECT created_at, metadata_json FROM histories "
            "WHERE id = ? AND user_id = ? AND conf_uid = ?",
            (history_uid, user_id, conf_uid),
        ).fetchone()
        if row is None:
            return {}

        metadata = {"role": "metadata", "timestamp": row["created_at"]}
        metadata.update(_load_json(row["metadata_json"]))
        return metadata

    async def update_metadata(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        metadata: dict,
    ) -> bool:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a dict")
        return await self._run(
            self._update_metadata_sync,
            user_id,
            conf_uid,
            history_uid,
            metadata,
        )

    def _update_metadata_sync(
        self,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        metadata: dict,
    ) -> bool:
        with self._conn:
            row = self._conn.execute(
                "SELECT metadata_json FROM histories "
                "WHERE id = ? AND user_id = ? AND conf_uid = ?",
                (history_uid, user_id, conf_uid),
            ).fetchone()
            if row is None:
                return False

            merged = _load_json(row["metadata_json"])
            merged.update(metadata)
            self._conn.execute(
                "UPDATE histories SET metadata_json = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), history_uid),
            )
        return True

    async def delete_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> bool:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        return await self._run(
            self._delete_history_sync, user_id, conf_uid, history_uid
        )

    def _delete_history_sync(
        self, user_id: str, conf_uid: str, history_uid: str
    ) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM histories WHERE id = ? AND user_id = ? AND conf_uid = ?",
                (history_uid, user_id, conf_uid),
            )
        return cursor.rowcount > 0

    async def modify_latest_message(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        role: str,
        new_content: str,
    ) -> bool:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        if role not in {"human", "ai", "system"}:
            raise ValueError(f"Invalid message role: {role!r}")
        return await self._run(
            self._modify_latest_message_sync,
            user_id,
            conf_uid,
            history_uid,
            role,
            new_content,
        )

    def _modify_latest_message_sync(
        self,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        role: str,
        new_content: str,
    ) -> bool:
        with self._conn:
            row = self._conn.execute(
                "SELECT m.id, m.role FROM messages m "
                "JOIN histories h ON h.id = m.history_id "
                "WHERE h.id = ? AND h.user_id = ? AND h.conf_uid = ? "
                "ORDER BY m.id DESC LIMIT 1",
                (history_uid, user_id, conf_uid),
            ).fetchone()
            if row is None or row["role"] != role:
                return False
            self._conn.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                (new_content, row["id"]),
            )
        return True

    async def rename_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        old_history_uid: str,
        new_history_uid: str,
    ) -> bool:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(old_history_uid, "old_history_uid")
        validate_key(new_history_uid, "new_history_uid")
        return await self._run(
            self._rename_history_sync,
            user_id,
            conf_uid,
            old_history_uid,
            new_history_uid,
        )

    def _rename_history_sync(
        self,
        user_id: str,
        conf_uid: str,
        old_history_uid: str,
        new_history_uid: str,
    ) -> bool:
        if old_history_uid == new_history_uid:
            return self._history_exists_sync(user_id, conf_uid, old_history_uid)

        with self._conn:
            row = self._conn.execute(
                "SELECT 1 FROM histories WHERE id = ? AND user_id = ? AND conf_uid = ?",
                (old_history_uid, user_id, conf_uid),
            ).fetchone()
            if row is None:
                return False
            if self._conn.execute(
                "SELECT 1 FROM histories WHERE id = ?", (new_history_uid,)
            ).fetchone():
                return False

            # messages.history_id uses ON UPDATE CASCADE.
            self._conn.execute(
                "UPDATE histories SET id = ? WHERE id = ?",
                (new_history_uid, old_history_uid),
            )
        return True

    async def import_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        messages: list[HistoryMessage],
        metadata: dict | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        legacy_path: str | None = None,
    ) -> bool:
        validate_user_id(user_id)
        validate_key(conf_uid, "conf_uid")
        validate_key(history_uid, "history_uid")
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be a dict")

        prepared = [_validate_message(message) for message in messages]
        created_at = created_at or (prepared[0][2] if prepared else _now_iso())
        updated_at = updated_at or (prepared[-1][2] if prepared else created_at)
        return await self._run(
            self._import_history_sync,
            user_id,
            conf_uid,
            history_uid,
            prepared,
            metadata or {},
            created_at,
            updated_at,
            legacy_path,
        )

    def _import_history_sync(
        self,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        prepared: list[tuple[str, str, str, str | None, str | None]],
        metadata: dict,
        created_at: str,
        updated_at: str,
        legacy_path: str | None,
    ) -> bool:
        with self._conn:
            self._ensure_user_sync(self._conn, user_id)
            try:
                self._conn.execute(
                    "INSERT INTO histories("
                    "id, user_id, conf_uid, metadata_json, created_at, "
                    "updated_at, legacy_path"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        history_uid,
                        user_id,
                        conf_uid,
                        json.dumps(metadata, ensure_ascii=False),
                        created_at,
                        updated_at,
                        legacy_path,
                    ),
                )
            except sqlite3.IntegrityError:
                return False

            if prepared:
                self._conn.executemany(
                    "INSERT INTO messages("
                    "history_id, role, content, name, avatar, timestamp"
                    ") VALUES(?, ?, ?, ?, ?, ?)",
                    [
                        (history_uid, role, content, name, avatar, timestamp)
                        for role, content, timestamp, name, avatar in prepared
                    ],
                )
        return True
