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
    UserMCPServer,
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

CREATE TABLE IF NOT EXISTS user_mcp_servers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    headers_json TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    mode TEXT NOT NULL DEFAULT 'remote',
    transport TEXT NOT NULL DEFAULT 'http',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_user_mcp_servers_user
    ON user_mcp_servers(user_id, created_at);
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


_MCP_URL_MAX_LENGTH = 2048


def _validate_mcp_fields(
    name: str,
    url: str,
    headers: dict[str, str],
    enabled: bool,
    mode: str,
    transport: str,
) -> None:
    validate_key(name, "name")
    if (
        not isinstance(url, str)
        or not url
        or url != url.strip()
        or len(url) > _MCP_URL_MAX_LENGTH
    ):
        raise ValueError(
            f"url must be a non-empty string up to {_MCP_URL_MAX_LENGTH} characters"
        )
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        raise ValueError("headers must be a mapping of strings to strings")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    if mode not in {"local", "remote"}:
        raise ValueError("mode must be 'local' or 'remote'")
    if transport not in {"http", "sse"}:
        raise ValueError("transport must be 'http' or 'sse'")


def _mcp_server_from_row(row: sqlite3.Row) -> UserMCPServer:
    headers = {
        key: value
        for key, value in _load_json(row["headers_json"]).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "url": row["url"],
        "headers": headers,
        "enabled": bool(row["enabled"]),
        "mode": row["mode"] if "mode" in row.keys() else "remote",
        "transport": row["transport"] if "transport" in row.keys() else "http",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
            # Version 3: per-user MCP servers. Version 4: local/remote mode.
            # Version 5: transport (Streamable HTTP / legacy SSE).
            for version in (1, 2, 3, 4, 5):
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                    "VALUES(?, ?)",
                    (version, applied_at),
                )
            mcp_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(user_mcp_servers)")
            }
            if "mode" not in mcp_columns:
                conn.execute(
                    "ALTER TABLE user_mcp_servers ADD COLUMN mode "
                    "TEXT NOT NULL DEFAULT 'remote'"
                )
            if "transport" not in mcp_columns:
                conn.execute(
                    "ALTER TABLE user_mcp_servers ADD COLUMN transport "
                    "TEXT NOT NULL DEFAULT 'http'"
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

    async def list_user_mcp_servers(self, *, user_id: str) -> list[UserMCPServer]:
        validate_user_id(user_id)
        return await self._run(self._list_user_mcp_servers_sync, user_id)

    def _list_user_mcp_servers_sync(self, user_id: str) -> list[UserMCPServer]:
        rows = self._conn.execute(
            "SELECT id, user_id, name, url, headers_json, enabled, mode, "
            "transport, created_at, updated_at FROM user_mcp_servers "
            "WHERE user_id = ? ORDER BY created_at, id",
            (user_id,),
        ).fetchall()
        return [_mcp_server_from_row(row) for row in rows]

    async def create_user_mcp_server(
        self,
        *,
        user_id: str,
        name: str,
        url: str,
        headers: dict[str, str],
        enabled: bool = True,
        mode: str = "remote",
        transport: str = "http",
    ) -> UserMCPServer:
        validate_user_id(user_id)
        _validate_mcp_fields(name, url, headers, enabled, mode, transport)
        return await self._run(
            self._create_user_mcp_server_sync,
            user_id,
            name,
            url,
            headers,
            enabled,
            mode,
            transport,
        )

    def _insert_user_mcp_server_row(
        self,
        *,
        server_id: str,
        user_id: str,
        name: str,
        url: str,
        headers: dict[str, str],
        enabled: bool,
        mode: str,
        transport: str,
        now: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO user_mcp_servers("
            "id, user_id, name, url, headers_json, enabled, mode, "
            "transport, created_at, updated_at"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                server_id,
                user_id,
                name,
                url,
                json.dumps(headers, ensure_ascii=False),
                1 if enabled else 0,
                mode,
                transport,
                now,
                now,
            ),
        )

    def _update_user_mcp_server_row(
        self,
        *,
        server_id: str,
        user_id: str,
        url: str,
        headers: dict[str, str],
        enabled: bool,
        mode: str,
        transport: str,
        now: str,
        name: str | None = None,
    ) -> int:
        """Update a row; ``name`` is only rewritten when explicitly given."""
        if name is None:
            cursor = self._conn.execute(
                "UPDATE user_mcp_servers SET "
                "url = ?, headers_json = ?, enabled = ?, mode = ?, "
                "transport = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    url,
                    json.dumps(headers, ensure_ascii=False),
                    1 if enabled else 0,
                    mode,
                    transport,
                    now,
                    server_id,
                    user_id,
                ),
            )
        else:
            cursor = self._conn.execute(
                "UPDATE user_mcp_servers SET "
                "name = ?, url = ?, headers_json = ?, enabled = ?, "
                "mode = ?, transport = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    name,
                    url,
                    json.dumps(headers, ensure_ascii=False),
                    1 if enabled else 0,
                    mode,
                    transport,
                    now,
                    server_id,
                    user_id,
                ),
            )
        return cursor.rowcount

    def _create_user_mcp_server_sync(
        self,
        user_id: str,
        name: str,
        url: str,
        headers: dict[str, str],
        enabled: bool,
        mode: str,
        transport: str,
    ) -> UserMCPServer:
        server_id = uuid.uuid4().hex
        now = _now_iso()
        with self._conn:
            self._ensure_user_sync(self._conn, user_id)
            try:
                self._insert_user_mcp_server_row(
                    server_id=server_id,
                    user_id=user_id,
                    name=name,
                    url=url,
                    headers=headers,
                    enabled=enabled,
                    mode=mode,
                    transport=transport,
                    now=now,
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("An MCP server with this name already exists") from exc

        return {
            "id": server_id,
            "user_id": user_id,
            "name": name,
            "url": url,
            "headers": dict(headers),
            "enabled": enabled,
            "mode": mode,
            "transport": transport,
            "created_at": now,
            "updated_at": now,
        }

    async def update_user_mcp_server(
        self,
        *,
        user_id: str,
        server_id: str,
        name: str,
        url: str,
        headers: dict[str, str],
        enabled: bool,
        mode: str = "remote",
        transport: str = "http",
    ) -> UserMCPServer | None:
        validate_user_id(user_id)
        validate_key(server_id, "server_id")
        _validate_mcp_fields(name, url, headers, enabled, mode, transport)
        return await self._run(
            self._update_user_mcp_server_sync,
            user_id,
            server_id,
            name,
            url,
            headers,
            enabled,
            mode,
            transport,
        )

    def _update_user_mcp_server_sync(
        self,
        user_id: str,
        server_id: str,
        name: str,
        url: str,
        headers: dict[str, str],
        enabled: bool,
        mode: str,
        transport: str,
    ) -> UserMCPServer | None:
        now = _now_iso()
        with self._conn:
            try:
                updated = self._update_user_mcp_server_row(
                    server_id=server_id,
                    user_id=user_id,
                    name=name,
                    url=url,
                    headers=headers,
                    enabled=enabled,
                    mode=mode,
                    transport=transport,
                    now=now,
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("An MCP server with this name already exists") from exc
            if updated == 0:
                return None

            row = self._conn.execute(
                "SELECT id, user_id, name, url, headers_json, enabled, mode, "
                "transport, created_at, updated_at FROM user_mcp_servers "
                "WHERE id = ? AND user_id = ?",
                (server_id, user_id),
            ).fetchone()
        return _mcp_server_from_row(row) if row is not None else None

    async def delete_user_mcp_server(self, *, user_id: str, server_id: str) -> bool:
        validate_user_id(user_id)
        validate_key(server_id, "server_id")
        return await self._run(self._delete_user_mcp_server_sync, user_id, server_id)

    def _delete_user_mcp_server_sync(self, user_id: str, server_id: str) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM user_mcp_servers WHERE id = ? AND user_id = ?",
                (server_id, user_id),
            )
        return cursor.rowcount > 0

    async def replace_user_mcp_servers(
        self,
        *,
        user_id: str,
        servers: list[dict],
    ) -> list[UserMCPServer]:
        validate_user_id(user_id)
        if not isinstance(servers, list):
            raise ValueError("servers must be a list")

        prepared: list[tuple[str, str, dict[str, str], bool, str, str]] = []
        names: set[str] = set()
        for entry in servers:
            if not isinstance(entry, dict):
                raise ValueError("each MCP server must be an object")
            name = entry.get("name")
            url = entry.get("url")
            headers = entry.get("headers", {})
            enabled = entry.get("enabled", True)
            mode = entry.get("mode", "remote")
            transport = entry.get("transport", "http")
            _validate_mcp_fields(name, url, headers, enabled, mode, transport)
            if name in names:
                raise ValueError(f"duplicate MCP server name: {name}")
            names.add(name)
            prepared.append((name, url, headers, enabled, mode, transport))

        return await self._run(self._replace_user_mcp_servers_sync, user_id, prepared)

    def _replace_user_mcp_servers_sync(
        self,
        user_id: str,
        prepared: list[tuple[str, str, dict[str, str], bool, str, str]],
    ) -> list[UserMCPServer]:
        now = _now_iso()
        with self._conn:
            self._ensure_user_sync(self._conn, user_id)
            existing = {
                row["name"]: row["id"]
                for row in self._conn.execute(
                    "SELECT id, name FROM user_mcp_servers WHERE user_id = ?",
                    (user_id,),
                )
            }

            keep: set[str] = set()
            for name, url, headers, enabled, mode, transport in prepared:
                keep.add(name)
                server_id = existing.get(name)
                if server_id is not None:
                    self._update_user_mcp_server_row(
                        server_id=server_id,
                        user_id=user_id,
                        url=url,
                        headers=headers,
                        enabled=enabled,
                        mode=mode,
                        transport=transport,
                        now=now,
                    )
                else:
                    self._insert_user_mcp_server_row(
                        server_id=uuid.uuid4().hex,
                        user_id=user_id,
                        name=name,
                        url=url,
                        headers=headers,
                        enabled=enabled,
                        mode=mode,
                        transport=transport,
                        now=now,
                    )

            for name, server_id in existing.items():
                if name not in keep:
                    self._conn.execute(
                        "DELETE FROM user_mcp_servers WHERE id = ? AND user_id = ?",
                        (server_id, user_id),
                    )

        return self._list_user_mcp_servers_sync(user_id)
