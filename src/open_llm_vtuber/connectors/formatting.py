"""Turn an agent reply into plain platform messages.

The browser renders Live2D action tags and think blocks as their own UI;
chat platforms would show them as noise, so they are removed here.
"""

import re

_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_BLANK_LINES = re.compile(r"\n{3,}")
_TRUNCATION_MARK = "……"
# Prefer to split after these, in order.
_SPLIT_POINTS = ("\n\n", "\n", "。", "！", "？", "!", "?", "；", ";", "，", ",", " ")


def _tag_pattern(tags: list[str]) -> re.Pattern | None:
    names = sorted({tag for tag in tags if tag}, key=len, reverse=True)
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(rf"\[(?:{alternatives})\]", re.IGNORECASE)


def live2d_tags(live2d_model) -> list[str]:
    """Expression and motion keywords the model may emit as ``[tag]``."""
    if live2d_model is None:
        return []
    tags: list[str] = []
    for attribute in ("emo_map", "motion_map"):
        mapping = getattr(live2d_model, attribute, None)
        if isinstance(mapping, dict):
            tags.extend(str(key) for key in mapping)
    return tags


def clean_reply(text: str, tags: list[str] | None = None) -> str:
    """Drop think blocks and the model's action tags."""
    text = _THINK_BLOCK.sub("", text or "")
    pattern = _tag_pattern(tags or [])
    if pattern is not None:
        text = pattern.sub("", text)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    text = "\n".join(lines)
    return _BLANK_LINES.sub("\n\n", text).strip()


# Line-level markup consumes its own line break so no blank line is left.
_FENCE = re.compile(r"^[ \t]*```[\w-]*[ \t]*(?:\n|$)", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[*+]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((\S+?)\)")
_RULE = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*(?:\n|$)", re.MULTILINE)


def strip_markdown(text: str) -> str:
    """Render common Markdown as plain text for apps that do not parse it.

    Only unambiguous markup is touched: a single ``*`` or ``_`` inside a
    sentence (math, file names) is left alone.
    """
    text = _FENCE.sub("", text)
    text = _RULE.sub("", text)
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    text = _BULLET.sub(r"\1- ", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _LINK.sub(r"\1 \2", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _split_point(text: str, limit: int) -> int:
    window = text[:limit]
    for marker in _SPLIT_POINTS:
        index = window.rfind(marker)
        # Do not produce tiny leading segments.
        if index >= limit // 3:
            return index + len(marker)
    return limit


def split_reply(text: str, max_chars: int, max_parts: int) -> list[str]:
    """Split ``text`` into at most ``max_parts`` messages of ``max_chars``."""
    if max_chars <= len(_TRUNCATION_MARK) or max_parts < 1:
        raise ValueError("max_chars and max_parts are too small")
    parts: list[str] = []
    remaining = text.strip()
    while remaining and len(parts) < max_parts:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            remaining = ""
            break
        if len(parts) == max_parts - 1:
            cut = max_chars - len(_TRUNCATION_MARK)
            parts.append(remaining[:cut].rstrip() + _TRUNCATION_MARK)
            remaining = ""
            break
        index = _split_point(remaining, max_chars)
        parts.append(remaining[:index].rstrip())
        remaining = remaining[index:].lstrip()
    return [part for part in parts if part]
