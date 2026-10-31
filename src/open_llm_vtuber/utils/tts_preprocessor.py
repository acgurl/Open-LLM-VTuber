import html
import re
import unicodedata
from collections.abc import Callable
from loguru import logger


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE_LINE_RE = re.compile(r"^[ \t]*```.*$", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REFERENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]]*\]")
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_EMPTY_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*$", re.MULTILINE)
_HORIZONTAL_RULE_RE = re.compile(r"^[ \t]{0,3}(?:[-*_][ \t]*){3,}$", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
_BULLET_RE = re.compile(r"^[ \t]{0,3}[-*+][ \t]+", re.MULTILINE)
_ORDERED_LIST_RE = re.compile(r"^[ \t]{0,3}\d{1,9}[.)][ \t]+", re.MULTILINE)
_TASK_LIST_RE = re.compile(r"^[ \t]{0,3}\[[ xX]\][ \t]+", re.MULTILINE)
_TABLE_SEPARATOR_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$",
    re.MULTILINE,
)
_TABLE_PIPE_RE = re.compile(r"[ \t]*\|[ \t]*")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_INLINE_CODE_RE = re.compile(r"`+([^`\n]*)`+")
_STRIKETHROUGH_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_TRIPLE_EMPHASIS_RE = re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*", re.DOTALL)
_STRONG_STAR_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL)
_STRONG_UNDERSCORE_RE = re.compile(
    r"(?<![A-Za-z0-9_])__(?=\S)(.+?)(?<=\S)__(?![A-Za-z0-9_])", re.DOTALL
)
_EMPHASIS_STAR_RE = re.compile(r"(?<!\*)\*(?=\S)(.+?)(?<=\S)\*(?!\*)", re.DOTALL)
_EMPHASIS_UNDERSCORE_RE = re.compile(
    r"(?<![A-Za-z0-9_])_(?=\S)(.+?)(?<=\S)_(?![A-Za-z0-9_])", re.DOTALL
)
_LEFTOVER_MARKER_RE = re.compile(
    r"\*{1,3}|`+|~{2,}|(?<![A-Za-z0-9_])_{1,2}(?![A-Za-z0-9_])"
)
_LEFTOVER_MARKER_KEEP_SINGLE_STAR_RE = re.compile(
    r"\*{2,}|`+|~{2,}|(?<![A-Za-z0-9_])_{1,2}(?![A-Za-z0-9_])"
)


def markdown_to_plain_text(text: str, keep_single_asterisk_content: bool = True) -> str:
    """
    Flatten Markdown into speakable plain text without dropping the visible content.

    Args:
        text: The Markdown text to flatten.
        keep_single_asterisk_content: Keep the content of *...* spans. When False,
            single-asterisk spans are left for ``filter_asterisks`` so that
            role-play actions can still be skipped.

    Returns:
        The plain text.
    """
    if not text:
        return text

    text = _HTML_COMMENT_RE.sub("", text)
    text = _FENCE_LINE_RE.sub("", text)

    text = _IMAGE_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _REFERENCE_LINK_RE.sub(r"\1", text)
    text = _FOOTNOTE_RE.sub("", text)

    text = _TABLE_SEPARATOR_RE.sub("", text)
    text = _EMPTY_HEADING_RE.sub("", text)
    text = _HEADING_RE.sub("", text)
    text = _HORIZONTAL_RULE_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _ORDERED_LIST_RE.sub("", text)
    text = _TASK_LIST_RE.sub("", text)
    text = _TABLE_PIPE_RE.sub(" ", text)

    text = _HTML_TAG_RE.sub("", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)

    text = _STRIKETHROUGH_RE.sub(r"\1", text)
    text = _TRIPLE_EMPHASIS_RE.sub(r"\1", text)
    text = _STRONG_STAR_RE.sub(r"\1", text)
    text = _STRONG_UNDERSCORE_RE.sub(r"\1", text)
    if keep_single_asterisk_content:
        text = _EMPHASIS_STAR_RE.sub(r"\1", text)
    text = _EMPHASIS_UNDERSCORE_RE.sub(r"\1", text)

    if keep_single_asterisk_content:
        text = _LEFTOVER_MARKER_RE.sub("", text)
    else:
        text = _LEFTOVER_MARKER_KEEP_SINGLE_STAR_RE.sub("", text)

    text = html.unescape(text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _apply_filter(
    text: str,
    label: str,
    func: Callable[..., str],
    **kwargs,
) -> str:
    """Run one speech filter, keeping the input when the filter fails."""
    try:
        return func(text, **kwargs)
    except Exception as e:
        logger.warning(f"Error {label}: {e}")
        logger.warning(f"Text: {text}")
        logger.warning("Skipping...")
        return text


def tts_filter(
    text: str,
    remove_special_char: bool,
    ignore_brackets: bool,
    ignore_parentheses: bool,
    ignore_asterisks: bool,
    ignore_angle_brackets: bool,
) -> str:
    """
    Filter or do anything to the text before TTS generates the audio.
    Changes here do not affect displayed text or LLM's memory. The generated
    audio is the only affected thing.

    Args:
        text (str): The text to filter.
        remove_special_char (bool): Whether to remove special characters.
        ignore_brackets (bool): Whether to ignore text within brackets.
        ignore_parentheses (bool): Whether to ignore text within parentheses.
        ignore_asterisks (bool): Whether to ignore text within single asterisks
            (role-play actions). Markdown emphasis is flattened beforehand, so its
            content is still spoken.

    Returns:
        str: The filtered text.
    """
    text = _apply_filter(
        text,
        "flattening markdown",
        markdown_to_plain_text,
        keep_single_asterisk_content=not ignore_asterisks,
    )

    if ignore_asterisks:
        text = _apply_filter(text, "ignoring asterisks", filter_asterisks)
    if ignore_brackets:
        text = _apply_filter(text, "ignoring brackets", filter_brackets)
    if ignore_parentheses:
        text = _apply_filter(text, "ignoring parentheses", filter_parentheses)
    if ignore_angle_brackets:
        text = _apply_filter(text, "ignoring angle brackets", filter_angle_brackets)
    if remove_special_char:
        text = _apply_filter(
            text, "removing special characters", remove_special_characters
        )
    logger.debug(f"Filtered text: {text}")
    return text


def remove_special_characters(text: str) -> str:
    """
    Filter text to remove all non-letter, non-number, and non-punctuation characters.

    Args:
        text (str): The text to filter.

    Returns:
        str: The filtered text.
    """
    normalized_text = unicodedata.normalize("NFKC", text)

    def is_valid_char(char: str) -> bool:
        category = unicodedata.category(char)
        return category.startswith(("L", "N", "P")) or char.isspace()

    filtered_text = "".join(char for char in normalized_text if is_valid_char(char))
    return filtered_text


def _filter_nested(text: str, left: str, right: str) -> str:
    """
    Generic function to handle nested symbols.

    Args:
        text (str): The text to filter.
        left (str): The left symbol (e.g. '[' or '(').
        right (str): The right symbol (e.g. ']' or ')').

    Returns:
        str: The filtered text.
    """
    if not isinstance(text, str):
        raise TypeError("Input must be a string")
    if not text:
        return text

    result = []
    depth = 0
    for char in text:
        if char == left:
            depth += 1
        elif char == right:
            if depth > 0:
                depth -= 1
        else:
            if depth == 0:
                result.append(char)
    filtered_text = "".join(result)
    filtered_text = re.sub(r"\s+", " ", filtered_text).strip()
    return filtered_text


def filter_brackets(text: str) -> str:
    """
    Filter text to remove all text within brackets, handling nested cases.

    Args:
        text (str): The text to filter.

    Returns:
        str: The filtered text.
    """
    return _filter_nested(text, "[", "]")


def filter_parentheses(text: str) -> str:
    """
    Filter text to remove all text within parentheses, handling nested cases.

    Args:
        text (str): The text to filter.

    Returns:
        str: The filtered text.
    """
    return _filter_nested(text, "(", ")")


def filter_angle_brackets(text: str) -> str:
    """
    Filter text to remove all text within angle brackets, handling nested cases.

    Args:
        text (str): The text to filter.

    Returns:
        str: The filtered text.
    """
    return _filter_nested(text, "<", ">")


def filter_asterisks(text: str) -> str:
    """
    Removes text enclosed within asterisks of any length (*, **, ***, etc.) from a string.

    Args:
        text: The input string.

    Returns:
        The string with asterisk-enclosed text removed.
    """
    # Handle asterisks of any length (*, **, ***, etc.)
    filtered_text = re.sub(r"\*{1,}((?!\*).)*?\*{1,}", "", text)

    # Clean up any extra spaces
    filtered_text = re.sub(r"\s+", " ", filtered_text).strip()

    return filtered_text
