from typing import Optional, ClassVar
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field


# Type definitions
WebSocketSend = Callable[[str], Awaitable[None]]
BroadcastFunc = Callable[[list[str], dict, str | None], Awaitable[None]]


@dataclass(frozen=True)
class OutboundChannels:
    """Text and audio senders for one connected client."""

    text: WebSocketSend
    audio: WebSocketSend

    @classmethod
    def from_text(cls, send: WebSocketSend) -> "OutboundChannels":
        """Use one socket for both text and audio."""
        return cls(text=send, audio=send)


@dataclass
class BroadcastContext:
    """Context for broadcasting messages in group chat"""

    broadcast_func: BroadcastFunc | None = None
    group_members: list[str] | None = None
    current_client_uid: str | None = None


@dataclass
class GroupConversationState:
    """State for group conversation"""

    # Class variable to track current states
    _states: ClassVar[dict[str, "GroupConversationState"]] = {}

    group_id: str
    conversation_history: list[str] = field(default_factory=list)
    memory_index: dict[str, int] = field(default_factory=dict)
    group_queue: list[str] = field(default_factory=list)
    session_emoji: str = ""
    current_speaker_uid: str | None = None

    def __post_init__(self):
        """Register state instance after initialization"""
        GroupConversationState._states[self.group_id] = self

    @classmethod
    def get_state(cls, group_id: str) -> Optional["GroupConversationState"]:
        """Get conversation state by group_id"""
        return cls._states.get(group_id)

    @classmethod
    def remove_state(cls, group_id: str) -> None:
        """Remove conversation state when done"""
        cls._states.pop(group_id, None)
