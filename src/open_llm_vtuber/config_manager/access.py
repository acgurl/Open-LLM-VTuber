# config_manager/access.py
"""Per-character access control.

A character preset can be limited to specific accounts:

```yaml
character_config:
  allowed_users:
    - "<user id shown in Settings / returned by /api/session>"
    - "<display name>"
```

A missing or empty list keeps the character public. Tokens are compared
case-insensitively against both the internal user id and the OIDC display
name, because the name is what an operator usually has at hand when editing
YAML while the id is the stable key.
"""

from typing import Any, Optional

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
    user_id: Optional[str],
    display_name: Optional[str],
) -> bool:
    """Return True when a character with this allowlist is available to the user."""
    scope = parse_allowed_users(allowed_users)
    if scope is INVALID:
        return False
    if not scope:
        return True

    for candidate in (user_id, display_name):
        if isinstance(candidate, str) and normalize_user_token(candidate) in scope:
            return True
    return False
