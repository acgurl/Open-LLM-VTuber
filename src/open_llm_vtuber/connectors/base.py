"""Platform-neutral connector contract.

A connector only speaks its platform's protocol: it turns platform events
into ``InboundMessage`` objects and sends reply text back. Identity, history,
commands, rate limits and the agent turn itself live in the dispatcher, so
every platform gets the same user scoping.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

ChatType = Literal["guild", "direct", "group", "c2c"]
ConnectorState = Literal["stopped", "connecting", "running", "error"]


@dataclass(frozen=True)
class InboundMessage:
    """One user message received from a platform."""

    connector_id: str
    message_id: str
    chat_type: ChatType
    # Where the reply goes (channel, DM session, group or user id).
    chat_id: str
    # Stable id of the sender as seen by this bot. It is what a binding maps
    # to a user, so it must not be a display name or anything the sender can
    # change.
    sender_id: str
    text: str
    sender_name: str | None = None
    # Platform data the connector needs to answer this message (message id
    # for passive replies, guild id, ...). Opaque to the dispatcher.
    reply_context: dict[str, Any] = field(default_factory=dict)

    @property
    def chat_key(self) -> str:
        """Identifies the conversation a message belongs to."""
        return f"{self.chat_type}:{self.chat_id}"


@dataclass(frozen=True)
class ConnectorCapabilities:
    """Limits the dispatcher must respect when formatting replies."""

    max_message_chars: int = 2000
    # Passive replies per inbound message the platform accepts.
    max_replies_per_message: int = 4


InboundHandler = Callable[["Connector", InboundMessage], Awaitable[None]]


class Connector(ABC):
    """A long-running link to one bot account on one platform."""

    platform: str = ""
    capabilities = ConnectorCapabilities()

    def __init__(self, connector_id: str, name: str) -> None:
        self.connector_id = connector_id
        self.name = name
        self.state: ConnectorState = "stopped"
        self.last_error: str | None = None

    @abstractmethod
    async def run(self, on_message: InboundHandler) -> None:
        """Connect and deliver messages until cancelled.

        ``on_message`` must return quickly; the dispatcher queues the turn.
        Raising lets the manager reconnect with backoff.
        """

    @abstractmethod
    async def send_text(self, message: InboundMessage, text: str, index: int) -> None:
        """Send one reply segment for ``message``.

        ``index`` counts the segments already sent for this message, so a
        platform that needs per-reply sequence numbers can derive them.
        """

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release network resources. Called once after ``run`` stops."""

    def status(self) -> dict[str, Any]:
        return {
            "id": self.connector_id,
            "name": self.name,
            "platform": self.platform,
            "state": self.state,
            "last_error": self.last_error,
        }
