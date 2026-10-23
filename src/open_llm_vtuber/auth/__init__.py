"""OIDC authentication primitives and routes."""

from .manager import AuthError, AuthManager, safe_next_path
from .middleware import AuthRedirectMiddleware
from .oidc import OIDCError, OIDCProvider
from .routes import init_auth_routes
from .types import Identity

__all__ = [
    "AuthError",
    "AuthManager",
    "AuthRedirectMiddleware",
    "Identity",
    "OIDCError",
    "OIDCProvider",
    "init_auth_routes",
    "safe_next_path",
]
