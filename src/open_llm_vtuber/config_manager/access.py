# config_manager/access.py
"""Per-character access control.

A character preset can be limited to specific accounts:

```yaml
character_config:
  allowed_users:
    - "<user id shown in Settings / returned by /api/session>"
    - "<verified login email>"
```

A missing or empty list keeps the character public. Tokens are compared
case-insensitively against the internal user id and the user's verified login
emails. Display names are never matched: a user can change theirs at the
identity provider and would then pass as someone else.
"""

import re
from collections.abc import Iterable
from typing import Any

from loguru import logger

# Internal user ids minted at first OIDC login (``uuid4().hex``).
_GENERATED_USER_ID = re.compile(r"[0-9a-f]{32}")

# Returned by parse_allowed_users when the YAML value is neither a string nor a
# list of strings; callers deny access instead of guessing.
INVALID = object()


def normalize_user_token(value: str) -> str:
    return value.strip().casefold()


def parse_allowed_users(value: Any) -> tuple[str, ...] | object:
    """Normalize an ``allowed_users`` value into comparison tokens.

    Returns an empty tuple for a missing/empty list, or ``INVALID`` when the
    value has an unsupported shape.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return INVALID

    tokens = []
    for item in value:
        if not isinstance(item, str):
            return INVALID
        token = normalize_user_token(item)
        if token:
            tokens.append(token)
    return tuple(tokens)


def is_user_allowed(
    allowed_users: Any,
    user_id: str | None,
    emails: str | Iterable[str] | None,
) -> bool:
    """Return True when a character with this allowlist is available to the user.

    ``emails`` are the user's verified login emails (one string or several).
    """
    scope = parse_allowed_users(allowed_users)
    if scope is INVALID:
        return False
    if not scope:
        return True

    if isinstance(emails, str) or emails is None:
        emails = (emails,)
    for candidate in (user_id, *emails):
        if isinstance(candidate, str) and normalize_user_token(candidate) in scope:
            return True
    return False


def warn_unmatched_allowlist_entries(allowed_users: Any, source: str) -> None:
    """Log entries that look like neither a generated user id nor an email.

    Such entries used to match display names; they now only match a user id
    spelled exactly like them, so operators should replace them.
    """
    scope = parse_allowed_users(allowed_users)
    if scope is INVALID:
        return
    for token in scope:
        if "@" not in token and not _GENERATED_USER_ID.fullmatch(token):
            logger.warning(
                f"{source}: allowed_users entry {token!r} is neither a user id "
                "nor an email; display names are no longer matched, use the "
                "user id from Settings or a verified email instead"
            )
