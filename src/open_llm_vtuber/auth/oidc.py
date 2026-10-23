"""OpenID Connect authorization-code client.

Only the standard endpoints advertised by the issuer's discovery document are
used, so the same code works with Casdoor, Keycloak, Auth0, etc.
"""

import asyncio
import hmac
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import jwt
from loguru import logger

from ..config_manager.auth import OIDCConfig

# Casdoor behind Cloudflare rejects the default Python-urllib User-Agent with
# HTTP 403 on the JWKS endpoint, so identify as a browser-compatible client.
_JWKS_USER_AGENT = "Mozilla/5.0 (compatible; Open-LLM-VTuber/1.2.1)"


class OIDCError(RuntimeError):
    """Raised when the provider response or token is invalid."""


class OIDCProvider:
    def __init__(
        self,
        config: OIDCConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport
        self._discovery: dict[str, Any] | None = None
        self._jwks_client: jwt.PyJWKClient | None = None

    def _new_client(self) -> httpx.AsyncClient:
        # Login traffic is rare; a short-lived client avoids binding a
        # connection pool to whichever event loop happened to handle the
        # previous request.
        return httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=False,
            transport=self._transport,
        )

    async def close(self) -> None:
        # Kept for a uniform lifecycle; clients are scoped per request.
        return None

    async def discovery(self) -> dict[str, Any]:
        if self._discovery is not None:
            return self._discovery

        url = f"{self.config.issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            async with self._new_client() as client:
                response = await client.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError(f"Failed to load OIDC discovery document: {exc}") from exc
        if not isinstance(data, dict):
            raise OIDCError("OIDC discovery document must be a JSON object")

        missing = [
            key
            for key in (
                "issuer",
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
            )
            if not data.get(key)
        ]
        if missing:
            raise OIDCError("OIDC discovery document is missing: " + ", ".join(missing))

        advertised_issuer = str(data["issuer"]).rstrip("/")
        if advertised_issuer != self.config.issuer.rstrip("/"):
            raise OIDCError(
                "OIDC issuer mismatch: configured "
                f"{self.config.issuer!r}, provider advertises {data['issuer']!r}"
            )

        self._discovery = data
        return data

    async def authorization_url(self, *, state: str, nonce: str) -> str:
        discovery = await self.discovery()
        endpoint = str(discovery["authorization_endpoint"])
        parts = urlsplit(endpoint)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.update(
            {
                "response_type": "code",
                "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri,
                "scope": " ".join(self.config.scopes),
                "state": state,
                "nonce": nonce,
            }
        )
        if self.config.prompt:
            params["prompt"] = self.config.prompt
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
        )

    async def exchange_code(self, code: str) -> dict[str, Any]:
        discovery = await self.discovery()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
        }
        auth = None
        if self.config.token_auth_method == "client_secret_basic":
            auth = (self.config.client_id, self.config.client_secret)
        else:
            data["client_secret"] = self.config.client_secret

        try:
            async with self._new_client() as client:
                response = await client.post(
                    str(discovery["token_endpoint"]),
                    data=data,
                    auth=auth,
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise OIDCError(f"OIDC token request failed: {exc}") from exc

        if response.status_code != 200:
            # The body may contain provider-side diagnostics; never forward it
            # to the client, and keep only a short message in logs.
            logger.warning(
                f"OIDC token endpoint returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
            raise OIDCError("OIDC token exchange was rejected")

        try:
            tokens = response.json()
        except ValueError as exc:
            raise OIDCError("OIDC token response was not JSON") from exc
        if not isinstance(tokens, dict):
            raise OIDCError("OIDC token response must be a JSON object")

        if not tokens.get("id_token"):
            raise OIDCError("OIDC token response is missing id_token")
        return tokens

    async def _signing_algorithms(self) -> list[str]:
        discovery = await self.discovery()
        advertised = discovery.get("id_token_signing_alg_values_supported") or []
        if not isinstance(advertised, list):
            advertised = []
        algorithms = [
            alg
            for alg in advertised
            if isinstance(alg, str) and alg not in {"none"} and not alg.startswith("HS")
        ]
        return algorithms or ["RS256"]

    async def validate_id_token(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        discovery = await self.discovery()
        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(
                str(discovery["jwks_uri"]),
                headers={"User-Agent": _JWKS_USER_AGENT},
                timeout=10,
            )

        try:
            signing_key = await asyncio.to_thread(
                self._jwks_client.get_signing_key_from_jwt, id_token
            )
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=await self._signing_algorithms(),
                audience=self.config.client_id,
                issuer=str(discovery["issuer"]),
                leeway=60,
                options={"require": ["exp", "iat", "sub"]},
            )
        except (jwt.PyJWTError, httpx.HTTPError, OSError, ValueError) as exc:
            raise OIDCError(f"ID token validation failed: {exc}") from exc

        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(
            claims["nonce"], nonce
        ):
            raise OIDCError("ID token nonce does not match the login request")
        return claims

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        discovery = await self.discovery()
        endpoint = discovery.get("userinfo_endpoint")
        if not endpoint:
            return {}
        try:
            async with self._new_client() as client:
                response = await client.get(
                    str(endpoint),
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError(f"OIDC userinfo request failed: {exc}") from exc
        return data if isinstance(data, dict) else {}

    async def end_session_url(self, *, post_logout_redirect_uri: str) -> str | None:
        discovery = await self.discovery()
        endpoint = discovery.get("end_session_endpoint")
        if not endpoint:
            return None
        parts = urlsplit(str(endpoint))
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.update(
            {
                "client_id": self.config.client_id,
                "post_logout_redirect_uri": post_logout_redirect_uri,
            }
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
        )
