"""Storage interfaces for conversation history.

All repository methods take ``user_id`` explicitly so a future authentication
layer can bind a connection to a user without changing the storage contract.
"""

from abc import ABC, abstractmethod
import re
from typing import Literal, TypedDict

DEFAULT_USER_ID = "local"
MAX_KEY_LENGTH = 128
MAX_IDENTITY_LENGTH = 512

_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class HistoryMessage(TypedDict, total=False):
    role: Literal["human", "ai", "system"]
    timestamp: str
    content: str
    name: str
    avatar: str


class ToolCallRecord(TypedDict, total=False):
    """A tool execution attached to one turn of a history.

    ``turn_index`` is the 0-based index of the human message whose turn ran the
    tool, so clients can put the card back between the question and the reply.
    """

    tool_id: str
    tool_name: str
    status: Literal["running", "completed", "error"]
    content: str
    timestamp: str
    turn_index: int


class UserMCPServer(TypedDict, total=False):
    """A user-scoped remote MCP server configuration.

    Headers contain user-supplied credentials and are never returned to the
    browser verbatim by the HTTP API.
    """

    id: str
    user_id: str
    name: str
    url: str
    headers: dict[str, str]
    enabled: bool
    mode: str  # "remote" (backend connects) or "local" (browser connects)
    transport: str  # "http" (Streamable HTTP) or "sse" (legacy HTTP+SSE)
    created_at: str
    updated_at: str


class HistoryNotFoundError(LookupError):
    """Raised when a history does not exist for the requested user/character."""


def validate_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not _USER_ID_PATTERN.fullmatch(user_id):
        raise ValueError(
            "user_id must be 1-64 characters of letters, digits, dot, dash or underscore"
        )
    return user_id


def validate_key(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_KEY_LENGTH
    ):
        raise ValueError(
            f"{name} must be a non-empty string up to {MAX_KEY_LENGTH} characters"
        )
    return value


def validate_identity(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_IDENTITY_LENGTH
    ):
        raise ValueError(
            f"{name} must be a non-empty string up to {MAX_IDENTITY_LENGTH} characters"
        )
    return value


class HistoryRepository(ABC):
    """Database-agnostic history storage.

    Implementations must scope every read and write by ``user_id``. The SQLite
    implementation is the default; other backends only need to implement this
    interface and be registered in ``storage.factory``.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Prepare the backend (schema, connection pool, etc.)."""

    @abstractmethod
    async def close(self) -> None:
        """Release backend resources."""

    @abstractmethod
    async def ensure_user(self, user_id: str, display_name: str | None = None) -> None:
        """Create the user row if it does not exist."""

    @abstractmethod
    async def resolve_user_identity(
        self,
        *,
        provider: str,
        subject: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> str:
        """Return the internal user id for an external identity.

        The identity is created on first login. ``provider`` and ``subject``
        come from the OIDC issuer and ID token, never from client input.
        """

    @abstractmethod
    async def list_conf_uids(self, *, user_id: str) -> list[str]:
        """Return every character config that has histories for this user."""

    @abstractmethod
    async def create_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str | None = None,
    ) -> str:
        """Create an empty history and return its id."""

    @abstractmethod
    async def history_exists(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> bool:
        """Return True only if the history belongs to this user and character."""

    @abstractmethod
    async def list_histories(
        self,
        *,
        user_id: str,
        conf_uid: str,
    ) -> list[dict]:
        """Return non-empty histories ordered by latest message (newest first)."""

    @abstractmethod
    async def get_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> list[HistoryMessage]:
        """Return all messages in a history, excluding metadata."""

    @abstractmethod
    async def store_message(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        role: Literal["human", "ai", "system"],
        content: str,
        name: str | None = None,
        avatar: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        """Append a message to a history."""

    @abstractmethod
    async def store_tool_call(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        tool_id: str,
        tool_name: str,
        status: str,
        content: str = "",
        timestamp: str | None = None,
    ) -> None:
        """Insert or update a tool execution for the current turn of a history."""

    @abstractmethod
    async def list_tool_calls(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> list[ToolCallRecord]:
        """Return the tool executions of a history ordered by turn and call order."""

    @abstractmethod
    async def get_metadata(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> dict:
        """Return metadata for a history, or an empty dict."""

    @abstractmethod
    async def update_metadata(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        metadata: dict,
    ) -> bool:
        """Merge fields into a history's metadata."""

    @abstractmethod
    async def delete_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
    ) -> bool:
        """Delete a history and its messages."""

    @abstractmethod
    async def modify_latest_message(
        self,
        *,
        user_id: str,
        conf_uid: str,
        history_uid: str,
        role: Literal["human", "ai", "system"],
        new_content: str,
    ) -> bool:
        """Replace the latest message when its role matches."""

    @abstractmethod
    async def rename_history(
        self,
        *,
        user_id: str,
        conf_uid: str,
        old_history_uid: str,
        new_history_uid: str,
    ) -> bool:
        """Rename a history id."""

    @abstractmethod
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
        """Bulk-insert a history with original timestamps.

        Returns False when the same history id or legacy path already exists.
        """

    # Each user may attach MCP servers that only their own sessions can use.
    # The global mcp_servers.json registry is deliberately not part of this
    # interface: it is deployment configuration, not user data.

    @abstractmethod
    async def list_user_mcp_servers(self, *, user_id: str) -> list[UserMCPServer]:
        """Return every MCP server owned by this user."""

    @abstractmethod
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
        """Create a user MCP server and return it."""

    @abstractmethod
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
        """Replace a user MCP server's fields; returns None when not owned."""

    @abstractmethod
    async def delete_user_mcp_server(self, *, user_id: str, server_id: str) -> bool:
        """Delete a user MCP server; returns False when not owned."""

    @abstractmethod
    async def replace_user_mcp_servers(
        self,
        *,
        user_id: str,
        servers: list[dict],
    ) -> list[UserMCPServer]:
        """Atomically apply a whole user config document.

        Rows whose names are unchanged keep their ids (so local tool
        namespaces stay stable); removed names are deleted.
        """
