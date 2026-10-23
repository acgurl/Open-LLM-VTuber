import re

_SILENT_TEXT_PATTERN = re.compile(r'[\s.,!?，。！？\'"』」）】\s]+')


def is_silent_text(text: str) -> bool:
    """Return True when the text has no content besides whitespace/punctuation."""
    return not _SILENT_TEXT_PATTERN.sub("", text)
