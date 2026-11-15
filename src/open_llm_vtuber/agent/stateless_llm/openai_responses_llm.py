"""OpenAI Responses API (``/v1/responses``).

The conversation is sent in full on every request (``store=False``), so the
API keeps no state and the agent's own memory stays the only one.
"""

from collections.abc import AsyncIterator
from typing import Any

from loguru import logger
from openai import NOT_GIVEN, AsyncOpenAI

from .openai_compatible_llm import openai_errors
from ...utils.dicts import deep_merge
from .stateless_llm_interface import (
    StatelessLLMInterface,
    content_text,
    generation_error,
    tool_specs,
)
from ...mcpp.types import ToolCallObject


def _input_content(content: Any) -> str | list[dict[str, Any]]:
    """``content`` of a user/system message as Responses input parts."""
    if not isinstance(content, list):
        return content_text(content)
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text"):
            parts.append({"type": "input_text", "text": item["text"]})
        elif item.get("type") == "image_url":
            image = item.get("image_url") or {}
            if image.get("url"):
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": image["url"],
                        "detail": image.get("detail", "auto"),
                    }
                )
    return parts


def response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Responses ``input`` items for messages in the internal format."""
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id"),
                    "output": content_text(message.get("content")),
                }
            )
        elif role == "assistant":
            text = content_text(message.get("content"))
            if text:
                items.append({"role": "assistant", "content": text})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id"),
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments") or "{}",
                    }
                )
        else:
            content = _input_content(message.get("content"))
            if content:
                items.append(
                    {
                        "role": "system" if role == "system" else "user",
                        "content": content,
                    }
                )
    return items


def response_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Function tools of a Responses request."""
    return [
        {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": schema,
            "strict": False,
        }
        for name, description, schema in tool_specs(tools)
    ]


class OpenAIResponsesLLM(StatelessLLMInterface):
    def __init__(
        self,
        model: str,
        llm_api_key: str,
        base_url: str = "https://api.openai.com/v1",
        organization_id: str | None = None,
        project_id: str | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ):
        """
        Parameters:
        - model: Model name.
        - llm_api_key: API key.
        - base_url: Root of the API.
        - organization_id, project_id: Sent to OpenAI when set.
        - temperature: Sampling temperature. ``None`` (the default) omits it;
          reasoning models reject the parameter.
        - reasoning_effort: Effort of a reasoning model, e.g. ``low``.
        - max_output_tokens: Cap on generated tokens, reasoning included.
        """
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.client = AsyncOpenAI(
            base_url=base_url,
            organization=organization_id or None,
            project=project_id or None,
            api_key=llm_api_key,
        )
        logger.info(f"Initialized OpenAIResponsesLLM: {self.base_url}, {self.model}")

    async def _stream_events(
        self, stream: AsyncIterator[Any]
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        calls: list[ToolCallObject] = []
        async for event in stream:
            kind = event.type
            if kind == "response.output_text.delta":
                if event.delta:
                    yield event.delta
            elif kind == "response.output_item.done":
                item = event.item
                if getattr(item, "type", None) == "function_call":
                    calls.append(
                        ToolCallObject.from_dict(
                            {
                                "id": item.call_id,
                                "type": "function",
                                "index": len(calls),
                                "function": {
                                    "name": item.name,
                                    "arguments": item.arguments or "{}",
                                },
                            }
                        )
                    )
            elif kind == "response.refusal.done":
                logger.warning(f"{self.model} refused the request")
                raise generation_error("The model declined to answer.")
            elif kind == "response.failed":
                error = getattr(event.response, "error", None)
                logger.error(f"Responses API ({self.model}): request failed: {error}")
                raise generation_error()
            elif kind == "error":
                logger.error(
                    f"Responses API ({self.model}): {event.code}: {event.message}"
                )
                raise generation_error()
            elif kind == "response.incomplete":
                details = getattr(event.response, "incomplete_details", None)
                logger.warning(f"Responses API ({self.model}): incomplete: {details}")

        if calls:
            logger.info(f"Tool calls requested: {[c.function.name for c in calls]}")
            yield calls

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        items = response_input(messages)
        logger.debug(f"Sending {len(items)} input items to {self.model}")
        function_tools = response_tools(tools)

        reasoning: Any = (
            {"effort": self.reasoning_effort} if self.reasoning_effort else NOT_GIVEN
        )
        extra = dict(options or {})
        if isinstance(extra.get("reasoning"), dict):
            # A thinking level refines the configured reasoning settings.
            reasoning = deep_merge(
                reasoning if isinstance(reasoning, dict) else {},
                extra.pop("reasoning"),
            )

        stream = None
        try:
            async with openai_errors(self.model, self.base_url, bool(function_tools)):
                stream = await self.client.responses.create(
                    model=self.model,
                    input=items,
                    instructions=system or NOT_GIVEN,
                    tools=function_tools or NOT_GIVEN,
                    temperature=(
                        NOT_GIVEN if self.temperature is None else self.temperature
                    ),
                    reasoning=reasoning,
                    max_output_tokens=self.max_output_tokens or NOT_GIVEN,
                    store=False,
                    stream=True,
                    extra_body=extra or None,
                )
                async for item in self._stream_events(stream):
                    yield item
        finally:
            if stream is not None:
                await stream.close()

    async def close(self) -> None:
        await self.client.close()
