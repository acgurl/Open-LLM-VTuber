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
# Character assets are public; /cache holds generated TTS audio and stays
# behind authentication.
_PUBLIC_PREFIXES = (
    "/auth/",
    "/assets/",
    "/libs/",
    "/live2d-models/",
    "/bg/",
    "/avatars/",
)


class AuthRedirectMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth: AuthManager) -> None:
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next):
        if not self.auth.enabled or request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if self._is_public(path):
            return await call_next(request)

        identity = self.auth.resolve_identity(request.cookies)
        if identity is not None:
            request.state.identity = identity
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

    @staticmethod
    def _is_public(path: str) -> bool:
        return path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)

    @staticmethod
    def _wants_html(request: Request) -> bool:
        accept = request.headers.get("accept", "")
        return "text/html" in accept or "application/xhtml+xml" in accept
