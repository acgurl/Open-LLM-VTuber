"""Shared Google Cloud service-account authentication and helpers."""

import asyncio
import json
import threading
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any

import httpx
import jwt

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_ASSERTION_LIFETIME = 3600
# Renew this many seconds before the token expires.
_REFRESH_MARGIN = 300


class GoogleCredentialsError(ValueError):
    """The service-account file is unusable, or Google refused the key."""


def load_service_account(path: str) -> dict[str, Any]:
    """Read and validate a Google Cloud service-account key file.

    Error messages name the file and the problem, never the file's contents.
    """
    if not path:
        raise GoogleCredentialsError("Google credentials file path is required")
    try:
        info = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as error:
        raise GoogleCredentialsError(
            f"Google credentials file '{path}' cannot be read ({type(error).__name__})"
        ) from None
    except ValueError:
        raise GoogleCredentialsError(
            f"Google credentials file '{path}' is not valid JSON"
        ) from None

    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise GoogleCredentialsError(
            f"Google credentials file '{path}' is not a service-account key "
            '(expected "type": "service_account")'
        )
    missing = [
        key
        for key in ("client_email", "private_key")
        if not isinstance(info.get(key), str) or not info[key]
    ]
    if missing:
        raise GoogleCredentialsError(
            f"Google credentials file '{path}' lacks {', '.join(missing)}"
        )
    return info


def resolve_project_id(
    info: dict[str, Any], project_id: str | None = None, credentials_file: str = ""
) -> str:
    """Resolve the Google Cloud project ID from explicit config or the key file."""
    resolved = (
        project_id.strip()
        if isinstance(project_id, str) and project_id.strip()
        else info.get("project_id")
    )
    if not isinstance(resolved, str) or not resolved.strip():
        raise GoogleCredentialsError(
            f"Google credentials file '{credentials_file}' has no project_id; "
            "set project_id explicitly"
        )
    return resolved.strip()


def google_error_message(body: bytes) -> str:
    """Extract a concise error message from a Google API JSON error body."""
    try:
        payload = json.loads(body)
    except ValueError:
        return body.decode("utf-8", errors="replace")[:500]
    # Streaming endpoints wrap their error object in a list.
    if isinstance(payload, list) and payload:
        payload = payload[0]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return str(payload)[:500]


class ServiceAccountAuth(httpx.Auth):
    """Adds a Google access token to each request, fetching it when needed.

    Supports both async (`httpx.AsyncClient`) and sync (`httpx.Client`)
    transports. When ``quota_project`` is set, attaches ``x-goog-user-project``
    so Cloud Speech/TTS APIs bill quota to that project.
    """

    def __init__(
        self, info: dict[str, Any], *, quota_project: str | None = None
    ) -> None:
        self._client_email: str = info["client_email"]
        self._private_key: str = info["private_key"]
        self._private_key_id: str | None = info.get("private_key_id")
        self._token_uri: str = info.get("token_uri") or _DEFAULT_TOKEN_URI
        self._quota_project: str | None = (
            quota_project.strip()
            if isinstance(quota_project, str) and quota_project.strip()
            else None
        )
        self._token: str | None = None
        self._expires_at = 0.0
        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()

    def _token_valid(self) -> bool:
        return (
            self._token is not None
            and time.monotonic() < self._expires_at - _REFRESH_MARGIN
        )

    def _apply_headers(self, request: httpx.Request, token: str) -> None:
        request.headers["Authorization"] = f"Bearer {token}"
        if self._quota_project:
            request.headers["x-goog-user-project"] = self._quota_project

    def _token_request(self) -> httpx.Request:
        now = int(time.time())
        try:
            assertion = jwt.encode(
                {
                    "iss": self._client_email,
                    "scope": _SCOPE,
                    "aud": self._token_uri,
                    "iat": now,
                    "exp": now + _ASSERTION_LIFETIME,
                },
                self._private_key,
                algorithm="RS256",
                headers={"kid": self._private_key_id} if self._private_key_id else None,
            )
        except Exception as error:
            # The original message may quote key material.
            raise GoogleCredentialsError(
                "The private key of the Google service account cannot sign "
                f"({type(error).__name__})"
            ) from None
        return httpx.Request(
            "POST",
            self._token_uri,
            data={"grant_type": _JWT_GRANT, "assertion": assertion},
        )

    def _store_token(self, response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        token = payload.get("access_token")
        if response.status_code != 200 or not isinstance(token, str) or not token:
            reason = payload.get("error_description") or payload.get("error") or ""
            raise GoogleCredentialsError(
                "Google rejected the service account "
                f"(HTTP {response.status_code}{': ' + str(reason) if reason else ''})"
            )
        try:
            lifetime = float(payload.get("expires_in", _ASSERTION_LIFETIME))
        except (TypeError, ValueError):
            lifetime = float(_ASSERTION_LIFETIME)
        self._token = token
        self._expires_at = time.monotonic() + lifetime

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        # The lock keeps concurrent pooled clients from each fetching a token.
        with self._sync_lock:
            if not self._token_valid():
                response = yield self._token_request()
                response.read()
                self._store_token(response)
            token = self._token
            assert token is not None

        self._apply_headers(request, token)
        response = yield request
        if response.status_code == 401:
            # Revoked early; the next request starts from a fresh token.
            with self._sync_lock:
                if self._token == token:
                    self._token = None

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        # The lock keeps concurrent conversations from each fetching a token.
        async with self._async_lock:
            if not self._token_valid():
                response = yield self._token_request()
                await response.aread()
                self._store_token(response)
            token = self._token
            assert token is not None

        self._apply_headers(request, token)
        response = yield request
        if response.status_code == 401:
            # Revoked early; the next request starts from a fresh token.
            if self._token == token:
                self._token = None
