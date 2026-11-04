"""Description: This file contains the implementation of the `AsyncLLM` class.
This class is responsible for handling asynchronous interaction with OpenAI API compatible
endpoints for language generation.
"""

from typing import Any
from collections.abc import AsyncIterator
from openai import (
    AsyncStream,
    AsyncOpenAI,
    APIError,
    APIConnectionError,
    RateLimitError,
    NotGiven,
    NOT_GIVEN,
)
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from loguru import logger

from .stateless_llm_interface import StatelessLLMInterface
from ...mcpp.types import ToolCallObject


class AsyncLLM(StatelessLLMInterface):
    def __init__(
        self,
        model: str,
        base_url: str,
        llm_api_key: str = "z",
        organization_id: str = "z",
        project_id: str = "z",
        temperature: float = 1.0,
    ):
        """
        Initializes an instance of the `AsyncLLM` class.

        Parameters:
        - model (str): The model to be used for language generation.
        - base_url (str): The base URL for the OpenAI API.
        - organization_id (str, optional): The organization ID for the OpenAI API. Defaults to "z".
        - project_id (str, optional): The project ID for the OpenAI API. Defaults to "z".
        - llm_api_key (str, optional): The API key for the OpenAI API. Defaults to "z".
        - temperature (float, optional): What sampling temperature to use, between 0 and 2. Defaults to 1.0.
        """
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(
            base_url=base_url,
            organization=organization_id,
            project=project_id,
            api_key=llm_api_key,
        )
        self.support_tools = True

        logger.info(
            f"Initialized AsyncLLM with the parameters: {self.base_url}, {self.model}"
        )

    @staticmethod
    def _accumulate_tool_call_deltas(
        accumulated: dict[int, dict[str, Any]],
        delta_tool_calls: list[ChoiceDeltaToolCall],
    ) -> None:
        """Merge one chunk's streamed tool-call fragments into ``accumulated``."""
        for tool_call in delta_tool_calls:
            index = tool_call.index if hasattr(tool_call, "index") else 0

            if index not in accumulated:
                accumulated[index] = {
                    "index": index,
                    "id": getattr(tool_call, "id", None),
                    "type": getattr(tool_call, "type", None),
                    "function": {"name": "", "arguments": ""},
                }
            entry = accumulated[index]

            if getattr(tool_call, "id", None):
                entry["id"] = tool_call.id
            if getattr(tool_call, "type", None):
                entry["type"] = tool_call.type

            function = getattr(tool_call, "function", None)
            if getattr(function, "name", None):
                entry["function"]["name"] = function.name
            if getattr(function, "arguments", None):
                entry["function"]["arguments"] += function.arguments

    @staticmethod
    def _complete_tool_calls(
        accumulated: dict[int, dict[str, Any]],
    ) -> list[ToolCallObject]:
        return [
            ToolCallObject.from_dict(tool_data) for tool_data in accumulated.values()
        ]

    async def _stream_chunks(
        self, stream: AsyncStream[ChatCompletionChunk]
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        """Yield content strings, and accumulated tool calls once each call ends."""
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        in_tool_call = False

        async for chunk in stream:
            # Guard against chunks with missing choices field (e.g., from OpenWebUI)
            if not chunk.choices:
                continue

            if self.support_tools:
                delta_tool_calls = getattr(chunk.choices[0].delta, "tool_calls", None)
                if delta_tool_calls:
                    logger.debug(f"Tool calls detected in chunk: {delta_tool_calls}")
                    in_tool_call = True
                    self._accumulate_tool_call_deltas(
                        accumulated_tool_calls, delta_tool_calls
                    )
                    continue

                # The tool call ended; emit it before the regular content.
                if in_tool_call:
                    in_tool_call = False
                    logger.info(f"Complete tool calls: {accumulated_tool_calls}")
                    yield self._complete_tool_calls(accumulated_tool_calls)
                    accumulated_tool_calls = {}  # Reset for potential future tool calls

            # Process regular content chunks
            if chunk.choices[0].delta.content is None:
                chunk.choices[0].delta.content = ""
            yield chunk.choices[0].delta.content

        # If stream ends while still in a tool call, make sure to yield the tool call
        if in_tool_call and accumulated_tool_calls:
            logger.info(f"Final tool call at stream end: {accumulated_tool_calls}")
            yield self._complete_tool_calls(accumulated_tool_calls)

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | NotGiven = NOT_GIVEN,
    ) -> AsyncIterator[str | list[ChoiceDeltaToolCall]]:
        """
        Generates a chat completion using the OpenAI API asynchronously.

        Parameters:
        - messages (List[Dict[str, Any]]): The list of messages to send to the API.
        - system (str, optional): System prompt to use for this completion.
        - tools (List[Dict[str, str]], optional): List of tools to use for this completion.

        Yields:
        - str: The content of each chunk from the API response.
        - List[ChoiceDeltaToolCall]: The tool calls detected in the response.

        Raises:
        - APIConnectionError: When the server cannot be reached
        - RateLimitError: When a 429 status code is received
        - APIError: For other API-related errors
        """
        stream = None

        try:
            # If system prompt is provided, add it to the messages
            messages_with_system = messages
            if system:
                messages_with_system = [
                    {"role": "system", "content": system},
                    *messages,
                ]
            logger.debug(
                f"Sending {len(messages_with_system)} messages to {self.model}"
            )

            available_tools = tools if self.support_tools else NOT_GIVEN

            stream: AsyncStream[
                ChatCompletionChunk
            ] = await self.client.chat.completions.create(
                messages=messages_with_system,
                model=self.model,
                stream=True,
                temperature=self.temperature,
                tools=available_tools,
            )
            logger.debug(
                f"Tool Support: {self.support_tools}, Available tools: {available_tools}"
            )

            async for item in self._stream_chunks(stream):
                yield item

        except APIConnectionError as e:
            logger.error(
                f"Error calling the chat endpoint: Connection error. Failed to connect to the LLM API. \nCheck the configurations and the reachability of the LLM backend. \nSee the logs for details. \nTroubleshooting with documentation: https://open-llm-vtuber.github.io/docs/faq#%E9%81%87%E5%88%B0-error-calling-the-chat-endpoint-%E9%94%99%E8%AF%AF%E6%80%8E%E4%B9%88%E5%8A%9E \n{e.__cause__}"
            )
            yield "Error calling the chat endpoint: Connection error. Failed to connect to the LLM API. Check the configurations and the reachability of the LLM backend. See the logs for details. Troubleshooting with documentation: [https://open-llm-vtuber.github.io/docs/faq#%E9%81%87%E5%88%B0-error-calling-the-chat-endpoint-%E9%94%99%E8%AF%AF%E6%80%8E%E4%B9%88%E5%8A%9E]"

        except RateLimitError as e:
            logger.error(
                f"Error calling the chat endpoint: Rate limit exceeded: {e.response}"
            )
            yield "Error calling the chat endpoint: Rate limit exceeded. Please try again later. See the logs for details."

        except APIError as e:
            if "does not support tools" in str(e):
                self.support_tools = False
                logger.warning(
                    f"{self.model} does not support tools. Disabling tool support."
                )
                yield "__API_NOT_SUPPORT_TOOLS__"
                return
            logger.error(f"LLM API: Error occurred: {e}")
            logger.info(f"Base URL: {self.base_url}")
            logger.info(f"Model: {self.model}")
            logger.info(f"Message count: {len(messages)}")
            logger.info(f"temperature: {self.temperature}")
            yield "Error calling the chat endpoint: Error occurred while generating response. See the logs for details."

        finally:
            # make sure the stream is properly closed
            # so when interrupted, no more tokens will being generated.
            if stream:
                logger.debug("Chat completion finished.")
                await stream.close()
                logger.debug("Stream closed.")
