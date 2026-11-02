"""HTTP access control for OIDC mode.

WebSockets are authenticated inside their route handlers; this middleware only
guards regular HTTP requests and redirects browser navigations to the login
endpoint while leaving static assets available.
"""

from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from .manager import AuthManager

_PUBLIC_PATHS = {"/healthz", "/api/session", "/favicon.ico"}
# Character assets are public unless a preset's allowed_users makes them
# private (enforced by the static handler); /cache holds generated TTS audio
# and stays behind authentication.
_IDENTITY_AWARE_PREFIXES = ("/live2d-models/", "/avatars/")
_PUBLIC_PREFIXES = (
    "/auth/",
    "/assets/",
    "/libs/",
    "/live2d-models/",
    "/bg/",
    "/avatars/",
)
# Session-scoped responses: never store them in the browser or a shared edge
# cache. /cache holds per-user TTS audio, /api and /auth carry session state,
# /web-tool sits behind login.
_NO_STORE_PREFIXES = ("/auth/", "/api/", "/cache/", "/web-tool/")
_NO_STORE_PATHS = {"/model_dict.json"}

# Set on the ASGI scope so static file handlers can enforce ownership.
IDENTITY_SCOPE_KEY = "vtuber_identity"


class AuthRedirectMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth: AuthManager) -> None:
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        response = await self._authorize(request, call_next, path)
        if self._is_no_store(path):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def _authorize(self, request: Request, call_next, path: str):
        if not self.auth.enabled or request.method == "OPTIONS":
            return await call_next(request)

        if self._is_public(path):
            # Public character assets can still be private to some users; the
            # static handler decides, so pass the identity along when present.
            if path.startswith(_IDENTITY_AWARE_PREFIXES):
                self._attach_identity(request)
            return await call_next(request)

        if self._attach_identity(request) is not None:
            return await call_next(request)

        if self._wants_html(request):
            next_path = path
            if request.url.query:
                next_path = f"{next_path}?{request.url.query}"
            return RedirectResponse(
                "/auth/login?next=" + quote(next_path, safe=""),
                status_code=302,
            )

        return JSONResponse({"error": "Authentication required"}, status_code=401)

    def _attach_identity(self, request: Request):
        identity = self.auth.resolve_identity(request.cookies)
        if identity is not None:
            request.state.identity = identity
            request.scope[IDENTITY_SCOPE_KEY] = identity
        return identity

    @staticmethod
    def _is_public(path: str) -> bool:
        return path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)

    @staticmethod
    def _is_no_store(path: str) -> bool:
        return path in _NO_STORE_PATHS or path.startswith(_NO_STORE_PREFIXES)

    @staticmethod
    def _wants_html(request: Request) -> bool:
        accept = request.headers.get("accept", "")
        return "text/html" in accept or "application/xhtml+xml" in accept
