"""OIDC authentication primitives and routes."""

from .manager import AuthError, AuthManager, safe_next_path
from .middleware import AuthRedirectMiddleware
from .oidc import OIDCError, OIDCProvider
from .request_user import default_user_id, request_user_id
from .routes import init_auth_routes
from .types import Identity

__all__ = [
    "AuthError",
    "AuthManager",
    "AuthRedirectMiddleware",
    "Identity",
    "OIDCError",
    "OIDCProvider",
    "default_user_id",
    "init_auth_routes",
    "request_user_id",
    "safe_next_path",
]
