"""Shared authentication value objects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """A server-verified user identity bound to a session."""

    user_id: str
    display_name: str | None = None
    email: str | None = None
    provider: str | None = None
