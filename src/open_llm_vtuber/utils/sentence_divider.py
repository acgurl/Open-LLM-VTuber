import re
from typing import Any
from collections.abc import AsyncIterator
import pysbd
from loguru import logger
from langdetect import detect
from enum import Enum
from dataclasses import dataclass

# Constants for additional checks
COMMAS = [
    ",",
    "،",
    "，",
    "、",
    "፣",
    "၊",
    ";",
    "΄",
    "‛",
    "।",
    "﹐",
    "꓾",
    "⹁",
    "︐",
    "﹑",
    "､",
    "،",
]

END_PUNCTUATIONS = [".", "!", "?", "。", "！", "？", "...", "。。。"]
ABBREVIATIONS = [
    "Mr.",
    "Mrs.",
    "Dr.",
    "Prof.",
    "Inc.",
    "Ltd.",
    "Jr.",
    "Sr.",
    "e.g.",
    "i.e.",
    "vs.",
    "St.",
    "Rd.",
    "Dr.",
]

# Set of languages directly supported by pysbd
SUPPORTED_LANGUAGES = {
    "am",
    "ar",
    "bg",
    "da",
    "de",
    "el",
    "en",
    "es",
    "fa",
    "fr",
    "hi",
    "hy",
    "it",
    "ja",
    "kk",
    "mr",
    "my",
    "nl",
    "pl",
    "ru",
    "sk",
    "ur",
    "zh",
}

# Sentence punctuation inside URLs must not split a sentence (e.g. example.com).
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'）】)\]},;。！？，；：、]+", re.IGNORECASE
)
_URL_PUNCTUATION = {
    ".": "\ue000",
    "!": "\ue001",
    "?": "\ue002",
    "。": "\ue003",
    "！": "\ue004",
    "？": "\ue005",
}
_URL_TRAILING_PUNCTUATION = ".,!?;:。！？，；："
_URL_PUNCTUATION_RE = re.compile("|".join(re.escape(char) for char in _URL_PUNCTUATION))
_RESTORE_URL_PUNCTUATION = str.maketrans(
    {masked: original for original, masked in _URL_PUNCTUATION.items()}
)


def _mask_url_punctuation(text: str) -> str:
    def mask(match: re.Match) -> str:
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _URL_TRAILING_PUNCTUATION:
            trailing = url[-1] + trailing
            url = url[:-1]

        masked_url = _URL_PUNCTUATION_RE.sub(
            lambda m: _URL_PUNCTUATION[m.group(0)], url
        )
        if trailing and not text[match.end() :].strip():
            # The buffer ends here, so a trailing dot may still be the start of a
            # longer URL (e.g. "example." followed by "com" in the next token).
            trailing = _URL_PUNCTUATION_RE.sub(
                lambda m: _URL_PUNCTUATION[m.group(0)], trailing
            )
        return masked_url + trailing

    return _URL_RE.sub(mask, text)


def _restore_url_punctuation(text: str) -> str:
    return text.translate(_RESTORE_URL_PUNCTUATION)


def detect_language(text: str) -> str:
    """
    Detect text language and check if it's supported by pysbd.
    Returns None for unsupported languages.
    """
    try:
        detected = detect(text)
        return detected if detected in SUPPORTED_LANGUAGES else None
    except Exception as e:
        logger.debug(f"Language detection failed, language not supported by pysdb: {e}")
        return None


def is_complete_sentence(text: str) -> bool:
    """
    Check if text ends with sentence-ending punctuation and not abbreviation.

    Args:
        text: Text to check

    Returns:
        bool: Whether the text is a complete sentence
    """
    text = text.strip()
    if not text:
        return False

    if any(text.endswith(abbrev) for abbrev in ABBREVIATIONS):
        return False

    return any(text.endswith(punct) for punct in END_PUNCTUATIONS)


def contains_comma(text: str) -> bool:
    """
    Check if text contains any comma.

    Args:
        text: Text to check

    Returns:
        bool: Whether the text contains a comma
    """
    return any(comma in text for comma in COMMAS)


def comma_splitter(text: str) -> tuple[str, str]:
    """
    Process text and split it at the first comma outside brackets, parentheses
    and inline code (e.g. inside a Markdown link).
    Returns the split text (including the comma) and the remaining text.

    Args:
        text: Text to split

    Returns:
        Tuple[str, str]: (split text with comma, remaining text)
    """
    if not text:
        return "", ""

    bracket_depth = 0
    parenthesis_depth = 0
    in_code = False

    for index, char in enumerate(text):
        if char == "`":
            in_code = not in_code
        elif not in_code:
            if char in "[【":
                bracket_depth += 1
            elif char in "]】" and bracket_depth > 0:
                bracket_depth -= 1
            elif char in "(（":
                parenthesis_depth += 1
            elif char in ")）" and parenthesis_depth > 0:
                parenthesis_depth -= 1
            elif char in COMMAS and bracket_depth == 0 and parenthesis_depth == 0:
                return text[: index + 1].strip(), text[index + 1 :].strip()

    return text, ""


def contains_end_punctuation(text: str) -> bool:
    """
    Check if text contains any sentence-ending punctuation.

    Args:
        text: Text to check

    Returns:
        bool: Whether the text contains ending punctuation
    """
    return any(punct in text for punct in END_PUNCTUATIONS)


def segment_text_by_regex(text: str) -> tuple[list[str], str]:
    """
    Segment text into complete sentences using regex pattern matching.
    More efficient but less accurate than pysbd.

    Args:
        text: Text to segment into sentences

    Returns:
        Tuple[List[str], str]: (list of complete sentences, remaining incomplete text)
    """
    if not text:
        return [], ""

    complete_sentences = []
    remaining_text = _mask_url_punctuation(text).strip()

    # Create pattern for matching sentences ending with any end punctuation
    escaped_punctuations = [re.escape(p) for p in END_PUNCTUATIONS]
    pattern = r"(.*?(?:[" + "|".join(escaped_punctuations) + r"]))"

    while remaining_text:
        match = re.search(pattern, remaining_text)
        if not match:
            break

        end_pos = match.end(1)
        potential_sentence = remaining_text[:end_pos].strip()

        # Skip if sentence ends with abbreviation
        if any(potential_sentence.endswith(abbrev) for abbrev in ABBREVIATIONS):
            remaining_text = remaining_text[end_pos:].lstrip()
            continue

        complete_sentences.append(_restore_url_punctuation(potential_sentence))
        remaining_text = remaining_text[end_pos:].lstrip()

    return complete_sentences, _restore_url_punctuation(remaining_text)


def segment_text_by_pysbd(text: str) -> tuple[list[str], str]:
    """
    Segment text into complete sentences and remaining text.
    Uses pysbd for supported languages, falls back to regex for others.

    Args:
        text: Text to segment into sentences

    Returns:
        Tuple[List[str], str]: (list of complete sentences, remaining incomplete text)
    """
    if not text:
        return [], ""

    try:
        # Detect language
        lang = detect_language(text)

        if lang is not None:
            # Use pysbd for supported languages
            segmenter = pysbd.Segmenter(language=lang, clean=False)
            sentences = segmenter.segment(_mask_url_punctuation(text))

            if not sentences:
                return [], text

            # Process all but the last sentence
            complete_sentences = []
            for sent in sentences[:-1]:
                sent = _restore_url_punctuation(sent.strip())
                if sent:
                    complete_sentences.append(sent)

            # Handle the last sentence
            last_sent = sentences[-1].strip()
            if is_complete_sentence(last_sent):
                complete_sentences.append(_restore_url_punctuation(last_sent))
                remaining = ""
            else:
                remaining = _restore_url_punctuation(last_sent)

        else:
            # Use regex for unsupported languages
            return segment_text_by_regex(text)

        logger.debug(
            f"Processed sentences: {complete_sentences}, Remaining: {remaining}"
        )
        return complete_sentences, remaining

    except Exception as e:
        logger.error(f"Error in sentence segmentation: {e}")
        # Fallback to regex on any error
        return segment_text_by_regex(text)


class TagState(Enum):
    """State of a tag in text"""

    START = "start"  # <tag>
    INSIDE = "inside"  # text between tags
    END = "end"  # </tag>
    SELF_CLOSING = "self"  # <tag/>
    NONE = "none"  # no tag


@dataclass
class TagInfo:
    """Information about a tag"""

    name: str
    state: TagState

    def __str__(self) -> str:
        """String representation of tag info"""
        if self.state == TagState.NONE:
            return "none"
        return f"{self.name}:{self.state.value}"


@dataclass
class SentenceWithTags:
    """A sentence with its tag information, supporting nested tags"""

    text: str
    tags: list[TagInfo]  # List of tags from outermost to innermost


class SentenceDivider:
    def __init__(
        self,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        valid_tags: list[str] | None = None,
    ):
        """
        Initialize the SentenceDivider.

        Args:
            faster_first_response: Whether to split first sentence at commas
            segment_method: Method for segmenting sentences
            valid_tags: List of valid tag names to detect
        """
        self.faster_first_response = faster_first_response
        self.segment_method = segment_method
        self.valid_tags = valid_tags or ["think"]
        self._is_first_sentence = True
        self._buffer = ""
        # Replace active_tags dict with a stack to handle nesting
        self._tag_stack = []
        self._full_response = []

    def _get_current_tags(self) -> list[TagInfo]:
        """
        Get all current active tags from outermost to innermost.

        Returns:
            List[TagInfo]: List of active tags
        """
        return [TagInfo(tag.name, TagState.INSIDE) for tag in self._tag_stack]

    def _find_first_tag(self, text: str) -> tuple[re.Match | None, TagInfo | None]:
        """Find the earliest valid tag in text."""
        first_tag = None
        first_pos = len(text)
        tag_type = None
        matched_tag = None

        for state, template in (
            (TagState.SELF_CLOSING, "<{tag}/>"),
            (TagState.START, "<{tag}>"),
            (TagState.END, "</{tag}>"),
        ):
            for tag in self.valid_tags:
                match = re.search(template.format(tag=tag), text)
                if match and match.start() < first_pos:
                    first_pos = match.start()
                    first_tag = match
                    tag_type = state
                    matched_tag = tag

        if not first_tag:
            return None, None
        return first_tag, TagInfo(matched_tag, tag_type)

    def _extract_tag(self, text: str) -> tuple[TagInfo | None, str]:
        """
        Extract the first tag from text if present.
        Handles nested tags by maintaining a tag stack.

        Args:
            text: Text to check for tags

        Returns:
            Tuple of (TagInfo if tag found else None, remaining text)
        """
        first_tag, tag_info = self._find_first_tag(text)
        if not first_tag:
            return None, text

        if tag_info.state == TagState.START:
            self._tag_stack.append(TagInfo(tag_info.name, TagState.START))
        elif tag_info.state == TagState.END:
            if not self._tag_stack or self._tag_stack[-1].name != tag_info.name:
                logger.warning(f"Mismatched closing tag: {tag_info.name}")
            else:
                self._tag_stack.pop()

        return tag_info, text[first_tag.end() :].lstrip()

    def _make_sentence(
        self, text: str, tags: list[TagInfo] | None = None
    ) -> SentenceWithTags:
        return SentenceWithTags(
            text=text.strip(),
            tags=tags or [TagInfo("", TagState.NONE)],
        )

    def _find_next_tag(self, text: str) -> tuple[int, str | None]:
        next_tag_pos = len(text)
        tag_pattern_found = None
        for tag in self.valid_tags:
            for pattern in (f"<{tag}>", f"</{tag}>", f"<{tag}/>"):
                pos = text.find(pattern)
                if pos != -1 and pos < next_tag_pos:
                    next_tag_pos = pos
                    tag_pattern_found = pattern
        return next_tag_pos, tag_pattern_found

    def _consume_tag_at_start(self) -> list[SentenceWithTags] | None:
        tag_info, remaining = self._extract_tag(self._buffer)
        if not tag_info:
            return None

        processed_text = self._buffer[: len(self._buffer) - len(remaining)]
        self._buffer = remaining
        return [SentenceWithTags(text=processed_text.strip(), tags=[tag_info])]

    def _consume_text_before_tag(
        self, next_tag_pos: int, tag_pattern_found: str | None
    ) -> list[SentenceWithTags] | None:
        text_before_tag = self._buffer[:next_tag_pos]
        current_tags = self._get_current_tags()

        if contains_end_punctuation(text_before_tag):
            sentences, _ = self._segment_text(text_before_tag)
            self._buffer = self._buffer[len(text_before_tag) :]
            return [
                self._make_sentence(sentence, current_tags)
                for sentence in sentences
                if sentence.strip()
            ]

        if text_before_tag.strip() and tag_pattern_found:
            self._buffer = self._buffer[len(text_before_tag) :]
            return [self._make_sentence(text_before_tag, current_tags)]

        return None

    def _consume_tag_anywhere(self) -> list[SentenceWithTags] | None:
        tag_info, remaining = self._extract_tag(self._buffer)
        if not tag_info:
            return None

        processed_tag_text = self._buffer[: len(self._buffer) - len(remaining)]
        self._buffer = remaining
        return [SentenceWithTags(text=processed_tag_text.strip(), tags=[tag_info])]

    def _consume_first_comma_sentence(self) -> list[SentenceWithTags] | None:
        if not (
            self._is_first_sentence
            and self.faster_first_response
            and contains_comma(self._buffer)
        ):
            return None

        sentence, remaining = comma_splitter(self._buffer)
        if not (sentence.strip() and remaining.strip()):
            return None

        current_tags = self._get_current_tags()
        self._buffer = remaining
        self._is_first_sentence = False
        return [self._make_sentence(sentence, current_tags)]

    def _consume_sentences(self) -> list[SentenceWithTags] | None:
        if not contains_end_punctuation(self._buffer):
            return None

        current_tags = self._get_current_tags()
        sentences, remaining = self._segment_text(self._buffer)
        if not sentences:
            return None

        self._buffer = remaining
        self._is_first_sentence = False
        return [
            self._make_sentence(sentence, current_tags)
            for sentence in sentences
            if sentence.strip()
        ]

    async def _process_buffer(self) -> AsyncIterator[SentenceWithTags]:
        """
        Process the current buffer, yielding complete sentences with tags.
        This is now an async generator.
        It consumes processed parts from self._buffer.
        """
        while self._buffer.strip():
            next_tag_pos, tag_pattern_found = self._find_next_tag(self._buffer)

            if next_tag_pos == 0:
                emitted = self._consume_tag_at_start()
                if emitted is not None:
                    for sentence in emitted:
                        yield sentence
                    continue

            elif next_tag_pos < len(self._buffer):
                emitted = self._consume_text_before_tag(next_tag_pos, tag_pattern_found)
                if emitted is not None:
                    for sentence in emitted:
                        yield sentence
                    continue

                emitted = self._consume_tag_anywhere()
                if emitted is not None:
                    for sentence in emitted:
                        yield sentence
                    continue

            emitted = self._consume_first_comma_sentence()
            if emitted is not None:
                for sentence in emitted:
                    yield sentence
                continue

            emitted = self._consume_sentences()
            if emitted is not None:
                for sentence in emitted:
                    yield sentence
                continue

            break

    async def _flush_buffer(self) -> AsyncIterator[SentenceWithTags]:
        """
        Process and yield all remaining content in the buffer at the end of the stream.
        """
        logger.debug(f"Flushing remaining buffer: '{self._buffer}'")
        # First, run _process_buffer to yield any standard sentences/tags
        async for sentence in self._process_buffer():
            yield sentence

        # After processing standard structures, if anything is left, yield it as a final fragment
        if self._buffer.strip():
            logger.debug(
                f"Yielding final fragment from buffer: '{self._buffer.strip()}'"
            )
            current_tags = self._get_current_tags()
            yield SentenceWithTags(
                text=self._buffer.strip(),
                tags=current_tags or [TagInfo("", TagState.NONE)],
            )
            self._buffer = ""  # Clear buffer after flushing

    async def process_stream(
        self, segment_stream: AsyncIterator[str | dict[str, Any]]
    ) -> AsyncIterator[SentenceWithTags | dict[str, Any]]:
        """
        Process a stream of tokens (strings) and dictionaries.
        Yields complete sentences with tags (SentenceWithTags) or dictionaries directly.

        Args:
            segment_stream: An async iterator yielding strings or dictionaries.

        Yields:
            Union[SentenceWithTags, Dict[str, Any]]: Complete sentences/tags or original dictionaries.
        """
        self._full_response = []
        self.reset()  # Ensure state is clean

        async for item in segment_stream:
            if isinstance(item, dict):
                # Before yielding the dict, process and yield any complete sentences formed so far
                async for sentence in self._process_buffer():
                    self._full_response.append(
                        sentence.text
                    )  # Track for complete response
                    yield sentence
                # Now yield the dictionary
                yield item
            elif isinstance(item, str):
                self._buffer += item
                # Process the buffer incrementally as string chunks arrive
                async for sentence in self._process_buffer():
                    self._full_response.append(
                        sentence.text
                    )  # Track for complete response
                    yield sentence
            else:
                logger.warning(
                    f"SentenceDivider received unexpected type: {type(item)}"
                )

        # After the stream finishes, flush any remaining text in the buffer
        async for sentence in self._flush_buffer():
            self._full_response.append(sentence.text)
            yield sentence

    @property
    def complete_response(self) -> str:
        """Get the complete response accumulated so far"""
        return "".join(self._full_response)

    def _segment_text(self, text: str) -> tuple[list[str], str]:
        """Segment text using the configured method"""
        if self.segment_method == "regex":
            return segment_text_by_regex(text)
        return segment_text_by_pysbd(text)

    def reset(self):
        """Reset the divider state for a new conversation"""
        self._is_first_sentence = True
        self._buffer = ""
        self._tag_stack = []
