"""Minimal HMAC-signed cookie encoding.

The payload is readable (it only contains a user id and display metadata);
the signature makes it tamper-proof. No third-party dependency is needed.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class SignedCookie:
    """Encode and verify ``{payload}.{hmac}`` cookie values."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("A signing secret is required")
        self._key = secret.encode("utf-8")

    def dumps(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        body_b64 = _b64encode(body.encode("utf-8"))
        signature = hmac.new(
            self._key, body_b64.encode("ascii"), hashlib.sha256
        ).digest()
        return f"{body_b64}.{_b64encode(signature)}"

    def loads(self, token: str | None, *, max_age: int | None = None) -> dict | None:
        if not token or token.count(".") != 1:
            return None

        body_b64, signature_b64 = token.split(".", 1)
        expected = hmac.new(
            self._key, body_b64.encode("ascii"), hashlib.sha256
        ).digest()
        try:
            supplied = _b64decode(signature_b64)
        except (ValueError, TypeError):
            return None
        if not hmac.compare_digest(expected, supplied):
            return None

        try:
            payload = json.loads(_b64decode(body_b64))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        now = int(time.time())
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        if not isinstance(issued_at, int) or not isinstance(expires_at, int):
            return None
        if issued_at > now + 60 or expires_at <= now:
            return None
        if max_age is not None and now - issued_at > max_age:
            return None
        return payload
