"""Description: This file contains the implementation of the `AsyncLLM` class for Claude API.
This class is responsible for handling asynchronous interaction with Claude API endpoints
for language generation.
"""

import json
from typing import Any
from collections.abc import AsyncIterator

from loguru import logger
from anthropic import AsyncAnthropic, NOT_GIVEN

from .stateless_llm_interface import StatelessLLMInterface


class AsyncLLM(StatelessLLMInterface):
    def __init__(
        self,
        model: str = "claude-3-haiku-latest",
        base_url: str | None = None,
        llm_api_key: str | None = None,
        system: str | None = None,
    ):
        """
        Initialize Claude LLM.

        Args:
            model (str): Model name
            base_url (str): Base URL for Claude API
            llm_api_key (str): Claude API key
            system (str): System prompt
        """
        self.model = model
        self.system = system

        # Initialize Claude client
        self.client = AsyncAnthropic(
            api_key=llm_api_key, base_url=base_url if base_url else None
        )

        logger.info(f"Initialized Claude AsyncLLM with model: {self.model}")
        logger.debug(f"Base URL: {base_url}")

    def _convert_message_format(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert message format to Claude's expected format."""
        # Handle potential tool_result content blocks
        if isinstance(message.get("content"), list):
            new_content = []
            is_tool_result = False
            for content_item in message["content"]:
                if content_item.get("type") == "image_url":
                    # Extract media type and base64 data from data URL
                    data_url = content_item["image_url"]["url"]
                    # Split 'data:image/jpeg;base64,/9j/4AAQ...' into parts
                    header, base64_data = data_url.split(",", 1)
                    # Extract media type from 'data:image/jpeg;base64'
                    media_type = header.split(":")[1].split(";")[0]

                    new_content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_data,
                            },
                        }
                    )
                elif content_item.get("type") == "tool_result":
                    is_tool_result = True
                    # Keep tool_result block as is, Anthropic SDK handles it
                    new_content.append(content_item)
                else:
                    # Assume text or other standard types
                    new_content.append(content_item)

            # For tool_result messages, the role should be 'user'
            # Ensure the role is correctly set before returning
            role = "user" if is_tool_result else message["role"]
            return {"role": role, "content": new_content}

        # Handle plain text content or non-list content
        return message

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Generates a chat completion using the Claude API asynchronously,
        handling text generation and tool use.

        Parameters:
        - messages (List[Dict[str, Any]]): The list of messages to send to the API.
        - system (str, optional): System prompt to use for this completion.
        - tools (List[Dict[str, Any]], optional): List of tools available.

        Yields:
        - Dict[str, Any]: Events representing text deltas, tool use, or errors.
          Possible event types:
            - {"type": "message_start", "data": ...}
            - {"type": "text_delta", "text": "..."}
            - {"type": "tool_use_start", "data": {"id": ..., "name": ..., "input": None}}
            - {"type": "tool_input_delta", "tool_id": ..., "partial_json": "..."} # Optional
            - {"type": "tool_use_complete", "data": {"id": ..., "name": ..., "input": {...}}}
            - {"type": "message_delta", "data": ...} # e.g., stop_reason
            - {"type": "message_stop"}
            - {"type": "error", "message": "..."}
        """
        try:
            # Filter out system messages and convert message format
            converted_messages = [
                self._convert_message_format(msg)
                for msg in messages
                if msg["role"] != "system"
            ]

            logger.debug(f"Sending {len(converted_messages)} messages to Claude API")
            logger.debug(f"Tools provided: {tools}")

            async with self.client.messages.stream(
                messages=converted_messages,
                system=system if system else (self.system if self.system else ""),
                model=self.model,
                max_tokens=1024,
                tools=tools if tools else NOT_GIVEN,
            ) as stream:
                state = _StreamState()
                async for event in stream:
                    handler = _EVENT_HANDLERS.get(event.type)
                    if handler is None:
                        # Anthropic SDK might raise errors directly, or via
                        # event.type == 'error'. The outer try/except handles
                        # SDK-level errors.
                        continue
                    for output in handler(event, state):
                        yield output

        except Exception as e:
            logger.error(f"Claude API error occurred: {e!s}")
            logger.info(f"Model: {self.model}")
            # Yield an error event before raising
            yield {"type": "error", "message": f"Claude API error: {e!s}"}
            raise

        # No finally block needed for stream.close() due to async with
        logger.debug("Chat completion stream processing finished.")


class _StreamState:
    """The tool_use block being streamed, if any."""

    def __init__(self) -> None:
        self.tool_call: dict[str, Any] | None = None
        self.partial_json = ""


def _on_message_start(event, _state: _StreamState) -> list[dict[str, Any]]:
    logger.debug("Stream: message_start")
    return [
        {
            "type": "message_start",
            "data": event.message.model_dump(exclude_none=True),
        }
    ]


def _on_content_block_start(event, state: _StreamState) -> list[dict[str, Any]]:
    logger.debug(
        f"Stream: content_block_start - Index: {event.index}, Type: {event.content_block.type}"
    )
    # Text blocks are handled by text_delta.
    if event.content_block.type != "tool_use":
        return []
    state.tool_call = {
        "id": event.content_block.id,
        "name": event.content_block.name,
        "input": None,
        "index": event.index,  # Store index
    }
    state.partial_json = ""
    logger.debug(
        f"Stream: tool_use started - ID: {state.tool_call['id']}, Name: {state.tool_call['name']}"
    )
    return [{"type": "tool_use_start", "data": state.tool_call.copy()}]


def _on_content_block_delta(event, state: _StreamState) -> list[dict[str, Any]]:
    logger.debug(
        f"Stream: content_block_delta - Index: {event.index}, Delta Type: {event.delta.type}"
    )
    if event.delta.type == "text_delta":
        return [{"type": "text_delta", "text": event.delta.text}]
    if event.delta.type == "input_json_delta":
        if state.tool_call and event.index == state.tool_call["index"]:
            state.partial_json += event.delta.partial_json
            logger.trace(
                f"Stream: input_json_delta - Tool ID: {state.tool_call['id']}, Partial: {event.delta.partial_json}"
            )
        else:
            logger.warning(
                f"Received input_json_delta but no active tool call matching index {event.index}"
            )
    return []


def _on_content_block_stop(event, state: _StreamState) -> list[dict[str, Any]]:
    logger.debug(f"Stream: content_block_stop - Index: {event.index}")
    tool_call = state.tool_call
    # Only a stop for the active tool call completes it.
    if not tool_call or event.index != tool_call["index"]:
        return []
    partial_json = state.partial_json
    # Reset regardless of success or failure for this index
    state.tool_call = None
    state.partial_json = ""
    try:
        if not partial_json.strip():
            logger.warning(
                f"Empty JSON input received for tool ID: {tool_call['id']}. Using empty object."
            )
            tool_input = {}
        else:
            tool_input = json.loads(partial_json)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode tool input JSON: {partial_json}. Error: {e}")
        return [
            {
                "type": "error",
                "message": f"Failed to parse tool input JSON for tool ID {tool_call['id']}",
            }
        ]
    tool_call["input"] = tool_input
    logger.debug(
        f"Stream: tool_use completed - ID: {tool_call['id']}, Input: {tool_input}"
    )
    return [{"type": "tool_use_complete", "data": tool_call.copy()}]


def _on_message_delta(event, _state: _StreamState) -> list[dict[str, Any]]:
    logger.debug(
        f"Stream: message_delta - Delta: {event.delta.model_dump(exclude_none=True)}, Usage: {event.usage}"
    )
    return [
        {
            "type": "message_delta",
            "data": {
                "delta": event.delta.model_dump(exclude_none=True),
                "usage": event.usage.model_dump(),
            },
        }
    ]


def _on_message_stop(_event, _state: _StreamState) -> list[dict[str, Any]]:
    logger.debug("Stream: message_stop")
    # No need to break here, the context manager handles the end
    return [{"type": "message_stop"}]


def _on_ping(_event, _state: _StreamState) -> list[dict[str, Any]]:
    logger.trace("Stream: ping")
    return []


_EVENT_HANDLERS = {
    "message_start": _on_message_start,
    "content_block_start": _on_content_block_start,
    "content_block_delta": _on_content_block_delta,
    "content_block_stop": _on_content_block_stop,
    "message_delta": _on_message_delta,
    "message_stop": _on_message_stop,
    "ping": _on_ping,
}
