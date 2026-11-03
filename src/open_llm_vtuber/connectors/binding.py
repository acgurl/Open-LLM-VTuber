"""One-time codes that bind a platform account to a web account.

The logged-in web session asks for a code; the user sends it to the bot from
the platform account. Only then does the dispatcher store the binding, so a
binding always proves control of both sides. Codes live in memory: they are
short-lived, and the server runs a single worker.
"""

import hashlib
import secrets
import time
from collections import deque
from dataclasses import dataclass

# No 0/O, 1/I/L: the code is typed on a phone.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
MAX_FAILED_ATTEMPTS = 5
FAILED_ATTEMPT_WINDOW_SECONDS = 600


def email_domain_allowed(email: str, allowed_domains: list[str]) -> bool:
    """Whether ``email`` is in one of the domains or their subdomains."""
    if not isinstance(email, str) or email.count("@") != 1:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower().rstrip(".")
    return any(
        domain == allowed or domain.endswith(f".{allowed}")
        for allowed in allowed_domains
    )


def user_eligible(profile: dict | None, allowed_domains: list[str]) -> bool:
    """A user may use global bots when a login email is in an allowed domain."""
    if profile is None:
        return False
    return any(
        email_domain_allowed(email, allowed_domains)
        for email in profile.get("emails") or []
    )


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _digest(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


@dataclass
class _PendingCode:
    user_id: str
    expires_at: float


class BindCodeStore:
    """Issues and redeems single-use binding codes."""

    def __init__(self, ttl_seconds: int = 600, clock=time.monotonic) -> None:
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._codes: dict[str, _PendingCode] = {}
        self._failures: dict[str, deque[float]] = {}

    def issue(self, user_id: str) -> tuple[str, int]:
        """Return a new code for ``user_id`` and its lifetime in seconds.

        Issuing a code revokes the user's previous one.
        """
        self._prune()
        for digest, pending in list(self._codes.items()):
            if pending.user_id == user_id:
                del self._codes[digest]
        while True:
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))
            digest = _digest(code)
            if digest not in self._codes:
                break
        self._codes[digest] = _PendingCode(user_id, self._clock() + self.ttl_seconds)
        return f"{code[:4]}-{code[4:]}", self.ttl_seconds

    def is_locked(self, attempt_key: str) -> bool:
        """Whether ``attempt_key`` (a platform account) used up its attempts."""
        failures = self._recent_failures(attempt_key)
        return len(failures) >= MAX_FAILED_ATTEMPTS

    def redeem(self, code: str, attempt_key: str) -> str | None:
        """Consume ``code`` and return its user id, or None.

        Failed attempts are counted per platform account so the code space
        cannot be brute-forced from one account.
        """
        if self.is_locked(attempt_key):
            return None
        self._prune()
        pending = (
            self._codes.pop(_digest(code), None)
            if len(normalize_code(code)) == CODE_LENGTH
            else None
        )
        if pending is None:
            self._recent_failures(attempt_key).append(self._clock())
            return None
        self._failures.pop(attempt_key, None)
        return pending.user_id

    def _recent_failures(self, attempt_key: str) -> deque[float]:
        failures = self._failures.setdefault(attempt_key, deque())
        cutoff = self._clock() - FAILED_ATTEMPT_WINDOW_SECONDS
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures

    def _prune(self) -> None:
        now = self._clock()
        for digest, pending in list(self._codes.items()):
            if pending.expires_at <= now:
                del self._codes[digest]
        for key in [key for key, value in self._failures.items() if not value]:
            del self._failures[key]
