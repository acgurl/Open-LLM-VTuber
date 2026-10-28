"""Authentication orchestration: signed sessions and OIDC login."""

import hmac
import secrets
import time
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from loguru import logger

from ..config_manager.auth import AuthConfig
from ..storage import HistoryRepository, validate_identity, validate_user_id
from .cookies import SignedCookie
from .oidc import OIDCError, OIDCProvider
from .types import Identity


class AuthError(RuntimeError):
    """Raised when a login cannot be completed safely."""


# Readable by the frontend so localStorage keys can be scoped per account.
# It only carries the opaque internal user id; the session cookie stays HttpOnly.
UID_COOKIE_NAME = "vtuber_uid"


class AuthManager:
    def __init__(self, config: AuthConfig, default_user_id: str) -> None:
        self.config = config
        self.default_user_id = default_user_id
        self.repository: HistoryRepository | None = None

        self._signer: SignedCookie | None = None
        self._oidc: OIDCProvider | None = None
        if self.enabled:
            self._signer = SignedCookie(config.signing_secret)
            self._oidc = OIDCProvider(config.oidc)

    @property
    def enabled(self) -> bool:
        return self.config.mode == "oidc"

    @property
    def oidc(self) -> OIDCProvider:
        if self._oidc is None:
            raise AuthError("OIDC is not enabled")
        return self._oidc

    @property
    def session_max_age(self) -> int:
        return self.config.session_max_age_days * 24 * 60 * 60

    def resolve_identity(self, cookies: Mapping[str, str]) -> Identity | None:
        """Resolve a request/WebSocket identity without trusting client data."""
        if not self.enabled:
            return Identity(self.default_user_id, "Local User")

        token = cookies.get(self.config.session_cookie_name)
        payload = self._signer.loads(token, max_age=self.session_max_age)
        if payload is None or payload.get("v") != 1:
            return None

        user_id = payload.get("uid")
        if not isinstance(user_id, str):
            return None
        try:
            validate_user_id(user_id)
        except ValueError:
            return None

        display_name = payload.get("name")
        return Identity(
            user_id=user_id,
            display_name=display_name if isinstance(display_name, str) else None,
        )

    def issue_session(self, identity: Identity) -> str:
        if self._signer is None:
            raise AuthError("OIDC is not enabled")
        now = int(time.time())
        payload: dict[str, Any] = {
            "v": 1,
            "uid": identity.user_id,
            "iat": now,
            "exp": now + self.session_max_age,
        }
        if identity.display_name:
            payload["name"] = identity.display_name
        return self._signer.dumps(payload)

    def _cookie_kwargs(
        self,
        name: str,
        value: str | None = None,
        max_age: int | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "key": name,
            "httponly": True,
            "secure": self.config.cookie_secure,
            "samesite": "lax",
            "path": "/",
        }
        if value is not None:
            kwargs["value"] = value
        if max_age is not None:
            kwargs["max_age"] = max_age
        return kwargs

    def session_cookie_kwargs(self, value: str) -> dict[str, Any]:
        return self._cookie_kwargs(
            self.config.session_cookie_name, value, self.session_max_age
        )

    def session_cookie_delete_kwargs(self) -> dict[str, Any]:
        return self._cookie_kwargs(self.config.session_cookie_name)

    def uid_cookie_kwargs(self, user_id: str) -> dict[str, Any]:
        kwargs = self._cookie_kwargs(UID_COOKIE_NAME, user_id, self.session_max_age)
        kwargs["httponly"] = False
        return kwargs

    def uid_cookie_delete_kwargs(self) -> dict[str, Any]:
        kwargs = self._cookie_kwargs(UID_COOKIE_NAME)
        kwargs["httponly"] = False
        return kwargs

    def redirect_uri_for(self, host: str | None) -> str:
        """Pick the registered callback that matches the requested host."""
        candidates = self.config.oidc.redirect_uris or [self.config.oidc.redirect_uri]
        wanted = (host or "").split(":")[0].strip().lower()
        if wanted:
            for uri in candidates:
                if (urlsplit(uri).hostname or "").lower() == wanted:
                    return uri
        return self.config.oidc.redirect_uri or candidates[0]

    def issue_state(
        self,
        *,
        state: str,
        nonce: str,
        next_path: str,
        redirect_uri: str | None = None,
    ) -> str:
        if self._signer is None:
            raise AuthError("OIDC is not enabled")
        now = int(time.time())
        payload = {
            "v": 1,
            "state": state,
            "nonce": nonce,
            "next": safe_next_path(next_path),
            "iat": now,
            "exp": now + self.config.state_max_age_seconds,
        }
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri
        return self._signer.dumps(payload)

    def verify_state(self, token: str | None, state: str) -> dict | None:
        if self._signer is None:
            return None
        payload = self._signer.loads(token, max_age=self.config.state_max_age_seconds)
        if payload is None or payload.get("v") != 1:
            return None
        stored_state = payload.get("state")
        if not isinstance(stored_state, str) or not hmac.compare_digest(
            stored_state, state
        ):
            return None
        if not isinstance(payload.get("nonce"), str):
            return None
        return payload

    def state_cookie_kwargs(self, value: str) -> dict[str, Any]:
        return self._cookie_kwargs(
            self.config.state_cookie_name, value, self.config.state_max_age_seconds
        )

    def state_cookie_delete_kwargs(self) -> dict[str, Any]:
        return self._cookie_kwargs(self.config.state_cookie_name)

    def new_state(self) -> str:
        return secrets.token_urlsafe(32)

    def new_nonce(self) -> str:
        return secrets.token_urlsafe(32)

    async def authenticate_code(
        self, code: str, *, nonce: str, redirect_uri: str | None = None
    ) -> Identity:
        """Exchange an authorization code and map the subject to a local user."""
        tokens = await self.oidc.exchange_code(code, redirect_uri=redirect_uri)
        claims = await self.oidc.validate_id_token(tokens["id_token"], nonce=nonce)

        if not claims.get("name") or not claims.get("email"):
            access_token = tokens.get("access_token")
            if isinstance(access_token, str) and access_token:
                try:
                    info = await self.oidc.userinfo(access_token)
                except OIDCError as exc:
                    logger.warning(f"OIDC userinfo lookup failed: {exc}")
                else:
                    info_subject = info.get("sub")
                    if (
                        isinstance(info_subject, str)
                        and isinstance(claims.get("sub"), str)
                        and info_subject != claims["sub"]
                    ):
                        raise AuthError(
                            "OIDC userinfo subject does not match the ID token"
                        )
                    for key in (
                        "name",
                        "preferred_username",
                        "displayName",
                        "email",
                    ):
                        if not claims.get(key) and info.get(key):
                            claims[key] = info[key]

        return await self.resolve_claims(claims)

    async def resolve_claims(self, claims: Mapping[str, Any]) -> Identity:
        if self.repository is None:
            raise AuthError("History storage is not initialized")

        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise AuthError("ID token is missing the subject claim")
        validate_identity(subject, "subject")

        discovery = await self.oidc.discovery()
        provider = str(discovery["issuer"])
        validate_identity(provider, "provider")

        display_name = _first_string(
            claims.get("name"),
            claims.get("preferred_username"),
            claims.get("displayName"),
            claims.get("email"),
        )
        email = _first_string(claims.get("email"))

        user_id = await self.repository.resolve_user_identity(
            provider=provider,
            subject=subject,
            display_name=display_name,
            email=email,
        )
        return Identity(
            user_id=user_id,
            display_name=display_name,
            email=email,
            provider=provider,
        )

    async def close(self) -> None:
        if self._oidc is not None:
            await self._oidc.close()


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def safe_next_path(value: str | None) -> str:
    """Allow only same-origin absolute paths as post-login destinations."""
    if not value or not isinstance(value, str):
        return "/"
    if len(value) > 2048 or not value.startswith("/") or value.startswith("//"):
        return "/"
    decoded = unquote(value)
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or "\r" in decoded
        or "\n" in decoded
    ):
        return "/"
    if decoded.startswith("/auth/"):
        return "/"
    return decoded
