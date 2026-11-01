"""Timestamp helpers for data sent to clients."""

import re
from datetime import datetime

# Python 3.10 fromisoformat only takes 3- or 6-digit fractions; the wire format
# is whole seconds anyway, so fractions are dropped before parsing.
_FRACTION = re.compile(r"(\d{2}:\d{2}:\d{2})\.\d+")


def to_wire_timestamp(value):
    """Give a stored timestamp an explicit UTC offset before it goes to a client.

    History rows store naive server-local time (``datetime.now()``). Clients run
    in other time zones (production containers run in UTC), so a naive value is
    ambiguous on the wire. Naive values are interpreted as server-local time and
    returned as ISO-8601 with an offset; values that already carry one keep it.
    Anything unparseable is returned unchanged.
    """
    if not isinstance(value, str) or not value:
        return value
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    text = _FRACTION.sub(r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.isoformat(timespec="seconds")


def with_wire_timestamp(item):
    """Return a copy of a dict with its ``timestamp`` field normalized."""
    if not isinstance(item, dict) or "timestamp" not in item:
        return item
    return {**item, "timestamp": to_wire_timestamp(item["timestamp"])}
