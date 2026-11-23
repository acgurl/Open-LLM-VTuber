"""Claude through Anthropic's native Messages API."""

import json
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anthropic
from anthropic import NOT_GIVEN, AsyncAnthropic
from loguru import logger

from .stateless_llm_interface import (
    StatelessLLMInterface,
    ThinkMarkers,
    authentication_error,
    connection_error,
    generation_error,
    rate_limit_error,
    split_data_url,
    tool_specs,
)
from ...mcpp.types import ToolCallObject

# Assistant turns kept verbatim while their tool calls are being answered.
_MAX_KEPT_TURNS = 256


def _visible_thinking(options: dict[str, Any] | None) -> dict[str, Any]:
    """``options`` asking for readable thinking when they turn it on.

    Current models default ``thinking.display`` to ``omitted`` (empty thinking
    text), which the user would see as a long pause; an explicit ``display``
    is kept.
    """
    extra = dict(options or {})
    thinking = extra.get("thinking")
    if (
        isinstance(thinking, dict)
        and thinking.get("type") == "adaptive"
        and "display" not in thinking
    ):
        extra["thinking"] = {**thinking, "display": "summarized"}
    return extra


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    """Claude content blocks for a ``content`` in the internal format."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    if not isinstance(content, list):
        return []
    blocks: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            # The API rejects empty text blocks.
            if (item.get("text") or "").strip():
                blocks.append({"type": "text", "text": item["text"]})
        elif item.get("type") == "image_url":
            image = split_data_url((item.get("image_url") or {}).get("url"))
            if image is None:
                logger.warning("Claude: skipped an image that is not a data URL")
                continue
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image[0],
                        "data": image[1],
                    },
                }
            )
    return blocks


def _tool_result_block(message: dict[str, Any]) -> dict[str, Any]:
    is_error = bool(message.get("is_error"))
    content = message.get("content")
    if isinstance(content, list):
        result: Any = _content_blocks(content)
    else:
        result = content if isinstance(content, str) else str(content or "")
    if not result:
        result = "Error occurred during tool execution." if is_error else "(no output)"
    return {
        "type": "tool_result",
        "tool_use_id": message.get("tool_call_id"),
        "content": result,
        "is_error": is_error,
    }


def claude_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Tools of a Messages request."""
    return [
        {"name": name, "description": description, "input_schema": schema}
        for name, description, schema in tool_specs(tools)
    ]


class ClaudeLLM(StatelessLLMInterface):
    def __init__(
        self,
        model: str,
        llm_api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 16000,
        temperature: float | None = None,
    ):
        """
        Parameters:
        - model: Model name, e.g. ``claude-opus-5-5``.
        - llm_api_key: Anthropic API key.
        - base_url: Root of the API; ``None`` is Anthropic's own.
        - max_tokens: Cap on the tokens of one response.
        - temperature: Sampling temperature. ``None`` (the default) omits it;
          current Claude models reject the parameter.
        """
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.client = AsyncAnthropic(api_key=llm_api_key, base_url=base_url or None)
        # A response that calls tools may carry thinking blocks, which Claude
        # wants back unchanged with the tool results. The agent rebuilds the
        # assistant turn from text and ToolCallObjects, so the original blocks
        # are kept here, by the id of the turn's first tool call.
        self._turns: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

        logger.info(f"Initialized ClaudeLLM with model: {self.model}")

    # ---- request

    def _assistant_blocks(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            kept = self._turns.get(tool_calls[0].get("id"))
            if kept is not None:
                return kept

        blocks = _content_blocks(message.get("content"))
        for call in tool_calls:
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except ValueError:
                arguments = {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.get("id"),
                    "name": function.get("name", ""),
                    "input": arguments if isinstance(arguments, dict) else {},
                }
            )
        return blocks

    def _to_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Claude ``messages``; system-role messages have no place and are dropped."""
        converted: list[dict[str, Any]] = []

        def add(role: str, blocks: list[dict[str, Any]]) -> None:
            if not blocks:
                return
            # All results of one assistant turn must share one user message.
            if converted and converted[-1]["role"] == role == "user":
                converted[-1]["content"].extend(blocks)
            else:
                converted.append({"role": role, "content": list(blocks)})

        for message in messages:
            role = message.get("role")
            if role == "system":
                continue
            if role == "assistant":
                add("assistant", self._assistant_blocks(message))
            elif role == "tool":
                add("user", [_tool_result_block(message)])
            else:
                add("user", _content_blocks(message.get("content")))
        return converted

    # ---- response

    def _tool_calls(self, message: Any) -> list[ToolCallObject]:
        calls = [
            ToolCallObject.from_dict(
                {
                    "id": block.id,
                    "type": "function",
                    "index": index,
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input or {}, ensure_ascii=False),
                    },
                }
            )
            for index, block in enumerate(
                block for block in message.content if block.type == "tool_use"
            )
        ]
        if calls:
            self._turns[calls[0].id] = [
                block.model_dump(exclude_none=True) for block in message.content
            ]
            while len(self._turns) > _MAX_KEPT_TURNS:
                self._turns.popitem(last=False)
        return calls

    @asynccontextmanager
    async def _claude_errors(self) -> AsyncIterator[None]:
        try:
            yield
        except anthropic.APIConnectionError as error:
            logger.error(f"Claude API ({self.model}): connection failed: {error}")
            raise connection_error() from error
        except anthropic.RateLimitError as error:
            logger.error(f"Claude API ({self.model}): rate limit exceeded: {error}")
            raise rate_limit_error() from error
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            logger.error(f"Claude API ({self.model}): credentials rejected: {e}")
            raise authentication_error() from e
        except anthropic.APIError as error:
            logger.error(f"Claude API ({self.model}): {error}")
            raise generation_error() from error

    @staticmethod
    def _delta_outputs(delta: Any, think: ThinkMarkers) -> tuple[list[str], bool]:
        if delta.type == "thinking_delta":
            return list(think.thought(delta.thinking)), False
        if delta.type == "text_delta" and delta.text:
            return [*think.close(), delta.text], True
        return [], False

    def _should_emit_tools(self, message: Any, produced_text: bool) -> bool:
        if message.stop_reason == "refusal":
            logger.warning(f"{self.model} refused the request")
            if not produced_text:
                raise generation_error("The model declined to answer.")
            return False
        if message.stop_reason == "max_tokens":
            logger.warning(
                f"{self.model} stopped at max_tokens ({self.max_tokens}); "
                "the response is cut short"
            )
            # A tool call cut off mid-input is not runnable.
            return False
        return True

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        request_messages = self._to_messages(messages)
        logger.debug(f"Sending {len(request_messages)} messages to {self.model}")

        async with (
            self._claude_errors(),
            self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system or NOT_GIVEN,
                messages=request_messages,
                tools=claude_tools(tools) or NOT_GIVEN,
                temperature=(
                    NOT_GIVEN if self.temperature is None else self.temperature
                ),
                extra_body=_visible_thinking(options) or None,
            ) as stream,
        ):
            produced_text = False
            think = ThinkMarkers()
            async for event in stream:
                if event.type != "content_block_delta":
                    continue
                outputs, wrote_text = self._delta_outputs(event.delta, think)
                produced_text = produced_text or wrote_text
                for item in outputs:
                    yield item
            for item in think.close():
                yield item
            message = await stream.get_final_message()

        if not self._should_emit_tools(message, produced_text):
            return
        calls = self._tool_calls(message)
        if calls:
            logger.info(f"Tool calls requested: {[c.function.name for c in calls]}")
            yield calls

    async def close(self) -> None:
        await self.client.close()
