"""The contract every LLM backend implements.

"Stateless" means the backend keeps no memory, system prompt or user messages:
each call answers from its arguments alone. Agents add memory, prompts and
tools on top.

One message format goes in, whatever the wire protocol behind it (the
OpenAI Chat Completions shape, which is also what the agent stores):

- ``{"role": "user" | "system", "content": str | parts}`` where a part is
  ``{"type": "text", "text": ...}`` or
  ``{"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}``
- ``{"role": "assistant", "content": str | None, "tool_calls": [...]}`` with
  calls shaped ``{"id", "type": "function", "function": {"name", "arguments"}}``
  (``arguments`` is a JSON string)
- ``{"role": "tool", "tool_call_id", "content": str | parts, "is_error": bool}``

Tools are the MCP definitions as their servers publish them:
``{"name", "description", "input_schema"}``. ``input_schema`` is the server's
JSON Schema, untouched; every backend places it in its API's own tool field,
so the model sees the schema the server wrote.

Each backend converts the messages to its own protocol and back.
"""

import abc
from collections.abc import AsyncIterator
from typing import Any

from ...mcpp.types import ToolCallObject

_ERROR_PREFIX = "Error calling the chat endpoint: "

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


class ReasoningText(str):
    """Streamed text of the model's reasoning, or its ``<think>`` markers.

    A backend that receives reasoning apart from the answer yields it wrapped
    as ``ReasoningText("<think>")``, the reasoning chunks, then
    ``ReasoningText("</think>")``. Agents show it (the client folds it, TTS
    skips it) but never store it as what the assistant said.
    """

    __slots__ = ()


class ThinkMarkers:
    """Wraps one response's reasoning chunks in ``<think>`` markers."""

    def __init__(self) -> None:
        self.open = False

    def thought(self, text: str) -> list[ReasoningText]:
        """The chunks to yield for one piece of reasoning."""
        if not text:
            return []
        chunks = [] if self.open else [ReasoningText(THINK_OPEN)]
        self.open = True
        chunks.append(ReasoningText(text))
        return chunks

    def close(self) -> list[ReasoningText]:
        """The closing marker, when reasoning is open; yield before an answer."""
        if not self.open:
            return []
        self.open = False
        return [ReasoningText(THINK_CLOSE)]


class LLMError(Exception):
    """A completion failed.

    ``str(error)`` is shown, and spoken, to the user: it names the kind of
    problem and nothing else. Keys, URLs and provider payloads go to the log.
    """


class LLMToolsUnsupportedError(LLMError):
    """The model or endpoint rejected the request because it carried tools."""


def connection_error() -> LLMError:
    return LLMError(
        f"{_ERROR_PREFIX}Connection error. Failed to connect to the LLM API. "
        "Check the configurations and the reachability of the LLM backend. "
        "See the logs for details."
    )


def rate_limit_error() -> LLMError:
    return LLMError(
        f"{_ERROR_PREFIX}Rate limit exceeded. Please try again later. "
        "See the logs for details."
    )


def authentication_error() -> LLMError:
    return LLMError(
        f"{_ERROR_PREFIX}Authentication failed. Check the credentials of the "
        "LLM backend. See the logs for details."
    )


def generation_error(detail: str = "") -> LLMError:
    return LLMError(
        f"{_ERROR_PREFIX}{detail or 'Error occurred while generating response.'} "
        "See the logs for details."
    )


def split_data_url(url: Any) -> tuple[str, str] | None:
    """``(mime type, base64 data)`` of a ``data:`` URL, else ``None``."""
    if not isinstance(url, str):
        return None
    header, _, data = url.partition(",")
    if not header.startswith("data:") or not data:
        return None
    return header[len("data:") :].split(";")[0], data


def content_text(content: Any) -> str:
    """The text of a message ``content``, for protocols that take no images.

    Images are counted in a trailing note so the model knows they existed.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    texts = []
    images = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
        elif part.get("type") == "image_url":
            images += 1
    if images:
        texts.append(f"[{images} image(s) omitted]")
    return "\n".join(texts)


_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def tool_specs(tools: Any) -> list[tuple[str, str, dict[str, Any]]]:
    """``(name, description, input schema)`` of each usable tool definition."""
    specs = []
    for tool in tools or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        schema = tool.get("input_schema")
        specs.append(
            (
                tool["name"],
                tool.get("description") or "",
                schema if isinstance(schema, dict) and schema else _EMPTY_SCHEMA,
            )
        )
    return specs


class StatelessLLMInterface(metaclass=abc.ABCMeta):
    """A language model reached over some API."""

    @abc.abstractmethod
    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        """Stream one completion.

        Parameters:
        - messages: The conversation, in the format of this module.
        - system: System prompt of this completion.
        - tools: Tools the model may call; ``None`` or empty offers none.
        - options: Extra fields of the request body in the API's own names
          (e.g. a thinking level), merged over what the backend builds.

        Yields:
        - ``str``: text, in the chunks the API delivers.
        - ``list[ToolCallObject]``: the tool calls of the response, once, as
          the last item. Absent when the model called no tool.

        Raises:
        - ``LLMToolsUnsupportedError``: tools were offered and refused.
        - ``LLMError``: any other failure. Nothing else escapes, and a
          failure is never reported as text.
        """
        raise NotImplementedError

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release the network client. The instance is unusable afterwards."""
