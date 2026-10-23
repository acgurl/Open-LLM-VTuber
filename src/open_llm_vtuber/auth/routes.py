"""HTTP endpoints for the OAuth authorization-code flow."""

from fastapi import APIRouter, Request
from loguru import logger
from starlette.responses import JSONResponse, RedirectResponse

from .manager import AuthError, AuthManager, safe_next_path
from .oidc import OIDCError


def init_auth_routes(auth: AuthManager) -> APIRouter:
    router = APIRouter()

    @router.get("/auth/login")
    async def login(request: Request):
        next_path = safe_next_path(request.query_params.get("next"))
        if not auth.enabled:
            return RedirectResponse(next_path, status_code=302)

        if auth.resolve_identity(request.cookies) is not None:
            return RedirectResponse(next_path, status_code=302)

        state = auth.new_state()
        nonce = auth.new_nonce()
        try:
            authorization_url = await auth.oidc.authorization_url(
                state=state, nonce=nonce
            )
        except OIDCError as exc:
            logger.error(f"OIDC login initialization failed: {exc}")
            return JSONResponse(
                {"error": "Authentication provider unavailable"},
                status_code=503,
            )

        response = RedirectResponse(authorization_url, status_code=302)
        response.set_cookie(
            **auth.state_cookie_kwargs(
                auth.issue_state(state=state, nonce=nonce, next_path=next_path)
            )
        )
        return response

    @router.get("/auth/callback")
    async def callback(request: Request):
        if not auth.enabled:
            return RedirectResponse("/", status_code=302)

        provider_error = request.query_params.get("error")
        if provider_error:
            logger.warning(f"OIDC provider returned an error: {provider_error}")
            return JSONResponse({"error": "Login was not completed"}, status_code=400)

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return JSONResponse(
                {"error": "Missing OAuth callback parameters"}, status_code=400
            )

        state_payload = auth.verify_state(
            request.cookies.get(auth.config.state_cookie_name), state
        )
        if state_payload is None:
            logger.warning("OIDC state validation failed")
            return JSONResponse(
                {"error": "Invalid or expired login state"}, status_code=400
            )

        try:
            identity = await auth.authenticate_code(code, nonce=state_payload["nonce"])
        except (OIDCError, AuthError, ValueError) as exc:
            logger.error(f"OIDC callback failed: {exc}")
            return JSONResponse({"error": "Login failed"}, status_code=401)

        response = RedirectResponse(
            safe_next_path(state_payload.get("next")), status_code=302
        )
        response.delete_cookie(**auth.state_cookie_delete_kwargs())
        response.set_cookie(**auth.session_cookie_kwargs(auth.issue_session(identity)))
        logger.info(
            f"OIDC login succeeded for user {identity.user_id} "
            f"({identity.display_name or 'unnamed'})"
        )
        return response

    @router.get("/auth/logout")
    async def logout(request: Request):
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie(**auth.session_cookie_delete_kwargs())
        if not auth.enabled or not auth.config.oidc.post_logout_redirect_uri:
            return response

        try:
            end_session_url = await auth.oidc.end_session_url(
                post_logout_redirect_uri=auth.config.oidc.post_logout_redirect_uri
            )
        except OIDCError as exc:
            logger.warning(f"OIDC end-session lookup failed: {exc}")
            return response

        if not end_session_url:
            return response
        provider_response = RedirectResponse(end_session_url, status_code=302)
        provider_response.delete_cookie(**auth.session_cookie_delete_kwargs())
        return provider_response

    @router.get("/api/session")
    async def session(request: Request):
        identity = auth.resolve_identity(request.cookies)
        if identity is None:
            return JSONResponse(
                {"authenticated": False, "mode": auth.config.mode},
                status_code=401,
            )
        return {
            "authenticated": True,
            "mode": auth.config.mode,
            "user_id": identity.user_id,
            "display_name": identity.display_name,
        }

    return router
