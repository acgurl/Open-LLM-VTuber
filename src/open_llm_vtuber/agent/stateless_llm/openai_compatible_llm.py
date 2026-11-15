"""OpenAI Chat Completions (``/v1/chat/completions``), official or compatible.

Covers every endpoint that speaks the protocol: OpenAI, DeepSeek, Gemini's
OpenAI layer, Zhipu, Groq, Mistral, Ollama, LM Studio, vLLM, gateways.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from openai import (
    NOT_GIVEN,
    APIConnectionError,
    APIError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from .stateless_llm_interface import (
    LLMError,
    LLMToolsUnsupportedError,
    StatelessLLMInterface,
    authentication_error,
    connection_error,
    content_text,
    generation_error,
    rate_limit_error,
)
from ...mcpp.types import ToolCallObject

# How servers word "this model cannot take tools" (Ollama, vLLM, gateways).
_TOOLS_UNSUPPORTED_MARKERS = (
    "does not support tools",
    "does not support function",
    "tool calling is not supported",
    "tools is not supported",
)


@asynccontextmanager
async def openai_errors(model: str, base_url: str, has_tools: bool):
    """Turn the OpenAI SDK's errors into ``LLMError`` (logging the detail)."""
    try:
        yield
    except LLMError:
        raise
    except APIConnectionError as error:
        logger.error(
            f"LLM API ({model} at {base_url}): connection failed: {error.__cause__}"
        )
        raise connection_error() from error
    except RateLimitError as error:
        logger.error(f"LLM API ({model}): rate limit exceeded: {error}")
        raise rate_limit_error() from error
    except (AuthenticationError, PermissionDeniedError) as error:
        logger.error(f"LLM API ({model} at {base_url}): credentials rejected: {error}")
        raise authentication_error() from error
    except APIError as error:
        text = str(error).lower()
        if has_tools and any(marker in text for marker in _TOOLS_UNSUPPORTED_MARKERS):
            logger.warning(f"{model} does not support tools")
            raise LLMToolsUnsupportedError(
                f"{model} does not support tool calling."
            ) from error
        logger.error(f"LLM API ({model} at {base_url}): {error}")
        raise generation_error() from error


def _chat_messages(
    messages: list[dict[str, Any]], system: str | None
) -> list[dict[str, Any]]:
    """The request's ``messages``: the internal format minus internal keys."""
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": system})
    for message in messages:
        role = message.get("role")
        if role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id"),
                    # The protocol takes text only as a tool result.
                    "content": content_text(message.get("content")),
                }
            )
        elif role == "assistant" and message.get("tool_calls"):
            converted.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or None,
                    "tool_calls": message["tool_calls"],
                }
            )
        else:
            converted.append({"role": role, "content": message.get("content")})
    return converted


class OpenAICompatibleLLM(StatelessLLMInterface):
    def __init__(
        self,
        model: str,
        base_url: str,
        llm_api_key: str,
        organization_id: str | None = None,
        project_id: str | None = None,
        temperature: float | None = 1.0,
    ):
        """
        Parameters:
        - model: Model name.
        - base_url: Root of the API, e.g. ``https://api.openai.com/v1``.
        - llm_api_key: API key; any non-empty text for servers without auth.
        - organization_id, project_id: Sent to OpenAI when set.
        - temperature: Sampling temperature; ``None`` leaves the API default.
        """
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(
            base_url=base_url,
            organization=organization_id or None,
            project=project_id or None,
            api_key=llm_api_key,
        )
        logger.info(f"Initialized OpenAICompatibleLLM: {self.base_url}, {self.model}")

    @staticmethod
    def _merge_tool_call_deltas(
        accumulated: dict[int, dict[str, Any]], delta_tool_calls: list[Any]
    ) -> None:
        """Merge one chunk's streamed tool-call fragments into ``accumulated``."""
        for tool_call in delta_tool_calls:
            index = getattr(tool_call, "index", None) or 0
            entry = accumulated.setdefault(
                index,
                {
                    "index": index,
                    "id": None,
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if getattr(tool_call, "id", None):
                entry["id"] = tool_call.id
            if getattr(tool_call, "type", None):
                entry["type"] = tool_call.type
            function = getattr(tool_call, "function", None)
            if getattr(function, "name", None):
                entry["function"]["name"] = function.name
            if getattr(function, "arguments", None):
                entry["function"]["arguments"] += function.arguments

    async def _stream_chunks(
        self, stream: AsyncIterator[Any]
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        """Text as it arrives, then the merged tool calls of the response."""
        accumulated: dict[int, dict[str, Any]] = {}
        async for chunk in stream:
            # Some servers (e.g. OpenWebUI) send chunks without choices.
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            delta_tool_calls = getattr(delta, "tool_calls", None)
            if delta_tool_calls:
                self._merge_tool_call_deltas(accumulated, delta_tool_calls)
            content = getattr(delta, "content", None)
            if content:
                yield content

        if accumulated:
            calls = [
                ToolCallObject.from_dict(accumulated[index])
                for index in sorted(accumulated)
            ]
            logger.info(f"Tool calls requested: {[c.function.name for c in calls]}")
            yield calls

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        request_messages = _chat_messages(messages, system)
        logger.debug(f"Sending {len(request_messages)} messages to {self.model}")

        stream = None
        try:
            async with openai_errors(self.model, self.base_url, bool(tools)):
                stream = await self.client.chat.completions.create(
                    messages=request_messages,
                    model=self.model,
                    stream=True,
                    temperature=(
                        NOT_GIVEN if self.temperature is None else self.temperature
                    ),
                    tools=tools or NOT_GIVEN,
                )
                async for item in self._stream_chunks(stream):
                    yield item
        finally:
            # Closing stops generation when the turn is interrupted.
            if stream is not None:
                await stream.close()

    async def close(self) -> None:
        await self.client.close()
