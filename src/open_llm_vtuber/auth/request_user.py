"""Resolve which user an HTTP request acts as."""

from typing import Any

from fastapi import Request

from ..storage import DEFAULT_USER_ID
from .manager import AuthManager


def default_user_id(default_context_cache: Any) -> str:
    """User id for unauthenticated (single-user) deployments."""
    return getattr(default_context_cache, "user_id", None) or DEFAULT_USER_ID


def request_user_id(
    request: Request,
    auth: AuthManager | None,
    default_context_cache: Any,
) -> str | None:
    """Return the caller's user id, or None when OIDC requires a login.

    The identity is the one ``AuthRedirectMiddleware`` attached to the
    request; without authentication every request is the default user.
    """
    identity = getattr(request.state, "identity", None)
    if identity is not None:
        return identity.user_id
    if auth is not None and auth.enabled:
        return None
    return default_user_id(default_context_cache)
