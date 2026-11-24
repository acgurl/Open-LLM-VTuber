"""Vertex AI (Google Cloud) through its native ``generateContent`` API.

Authentication uses a service-account key file as downloaded from the Google
Cloud console: the key signs a JWT, Google's token endpoint trades it for a
short-lived access token, and that token is sent as the bearer of every
request. Tokens are cached and renewed shortly before they expire.

Messages and tools arrive in the format of ``stateless_llm_interface``; the
conversion to and from Gemini ``contents`` happens here.
"""

import json
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

import httpx
from loguru import logger

from ...mcpp.types import ToolCallObject
from ...utils.dicts import deep_merge
from ...utils.google_auth import (
    GoogleCredentialsError,
    ServiceAccountAuth,
    google_error_message as _error_message,
    load_service_account,
    resolve_project_id,
)
from .stateless_llm_interface import (
    LLMError,
    StatelessLLMInterface,
    ThinkMarkers,
    authentication_error,
    connection_error,
    content_text,
    generation_error,
    rate_limit_error,
    split_data_url,
    tool_specs,
)

# Thought signatures kept for tool calls that are still being answered.
_MAX_SIGNATURES = 1024

VertexCredentialsError = GoogleCredentialsError


def vertex_model_url(project_id: str, location: str, model: str) -> str:
    """URL of a model resource; ``model`` may carry its publisher."""
    host = (
        "aiplatform.googleapis.com"
        if location == "global"
        else f"{location}-aiplatform.googleapis.com"
    )
    if model.startswith("publishers/"):
        resource = model
    elif "/" in model:
        publisher, _, name = model.partition("/")
        resource = f"publishers/{publisher}/models/{name}"
    else:
        resource = f"publishers/google/models/{model}"
    return f"https://{host}/v1/projects/{project_id}/locations/{location}/{resource}"


def _content_parts(content: Any) -> list[dict[str, Any]]:
    """Gemini parts for the ``content`` of an OpenAI-style message."""
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return []

    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            if item.get("text"):
                parts.append({"text": item["text"]})
        elif item.get("type") == "image_url":
            image = split_data_url((item.get("image_url") or {}).get("url"))
            if image is None:
                logger.warning("Vertex: skipped an image that is not a data URL")
                continue
            parts.append({"inlineData": {"mimeType": image[0], "data": image[1]}})
    return parts


def _function_declarations(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    declarations = []
    for name, description, schema in tool_specs(tools):
        declaration: dict[str, Any] = {"name": name, "parametersJsonSchema": schema}
        if description:
            declaration["description"] = description
        declarations.append(declaration)
    return declarations


class VertexLLM(StatelessLLMInterface):
    """Gemini on Vertex AI, authenticated by a service-account key file."""

    def __init__(
        self,
        model: str,
        credentials_file: str,
        project_id: str | None = None,
        location: str | None = None,
        temperature: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        """
        Parameters:
        - model: Model name, e.g. ``gemini-2.5-flash``; ``publisher/model``
          selects a publisher other than Google.
        - credentials_file: Path of the service-account key file (JSON).
        - project_id: Google Cloud project; defaults to the key file's own.
        - location: Vertex AI location; defaults to ``global``.
        - temperature: Sampling temperature, between 0 and 2.
        - transport: Replaces the network layer (tests).
        """
        if not credentials_file:
            raise VertexCredentialsError("vertex_llm needs a credentials_file")
        info = load_service_account(credentials_file)
        project_id = resolve_project_id(info, project_id, credentials_file)

        self.model = model
        self.base_url = vertex_model_url(project_id, location or "global", model)
        self.temperature = 1.0 if temperature is None else temperature
        self.client = httpx.AsyncClient(
            auth=ServiceAccountAuth(info),
            timeout=httpx.Timeout(120.0, connect=15.0),
            transport=transport,
        )
        # Gemini signs the function calls of a thinking model and wants the
        # signature back with the call. The agent rebuilds the assistant turn
        # from ToolCallObjects, which have no place for it, so it is kept here
        # by tool-call id until the turn is over.
        self._signatures: OrderedDict[str, str] = OrderedDict()

        logger.info(
            f"Initialized VertexLLM with the parameters: {self.base_url}, {self.model}"
        )

    # ---- request

    @staticmethod
    def _append_content(
        contents: list[dict[str, Any]], role: str, parts: list[dict[str, Any]]
    ) -> None:
        if not parts:
            return
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})

    def _assistant_parts(
        self, message: dict[str, Any], call_names: dict[str, str]
    ) -> list[dict[str, Any]]:
        parts = _content_parts(message.get("content"))
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name", "")
            call_names[call.get("id")] = name
            try:
                args = json.loads(function.get("arguments") or "{}")
            except ValueError:
                args = {}
            part: dict[str, Any] = {
                "functionCall": {
                    "name": name,
                    "args": args if isinstance(args, dict) else {},
                }
            }
            signature = self._signatures.get(call.get("id"))
            if signature:
                part["thoughtSignature"] = signature
            parts.append(part)
        return parts

    @staticmethod
    def _tool_response_part(
        message: dict[str, Any], call_names: dict[str, str]
    ) -> dict[str, Any]:
        result = content_text(message.get("content"))
        response = {"error": result} if message.get("is_error") else {"result": result}
        return {
            "functionResponse": {
                "name": call_names.get(message.get("tool_call_id"), ""),
                "response": response,
            }
        }

    def _to_contents(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Gemini ``contents`` plus the text of any system messages."""
        contents: list[dict[str, Any]] = []
        system_texts: list[str] = []
        call_names: dict[str, str] = {}

        for message in messages:
            role = message.get("role")
            if role == "system":
                system_texts.extend(
                    part["text"]
                    for part in _content_parts(message.get("content"))
                    if "text" in part
                )
            elif role == "assistant":
                self._append_content(
                    contents, "model", self._assistant_parts(message, call_names)
                )
            elif role == "tool":
                self._append_content(
                    contents, "user", [self._tool_response_part(message, call_names)]
                )
            else:
                self._append_content(
                    contents, "user", _content_parts(message.get("content"))
                )
        return contents, system_texts

    def _request_body(
        self,
        messages: list[dict[str, Any]],
        system: str | None,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        contents, system_texts = self._to_contents(messages)
        if system:
            system_texts.insert(0, system)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature},
        }
        if system_texts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_texts)}]}
        if tools:
            declarations = _function_declarations(tools)
            if declarations:
                body["tools"] = [{"functionDeclarations": declarations}]
        return body

    # ---- response

    def _tool_call(self, part: dict[str, Any], index: int) -> ToolCallObject:
        call = part["functionCall"]
        call_id = f"call_{uuid.uuid4().hex}"
        signature = part.get("thoughtSignature")
        if signature:
            self._signatures[call_id] = signature
            while len(self._signatures) > _MAX_SIGNATURES:
                self._signatures.popitem(last=False)
        return ToolCallObject.from_dict(
            {
                "id": call_id,
                "type": "function",
                "index": index,
                "function": {
                    "name": call.get("name", ""),
                    "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                },
            }
        )

    @staticmethod
    def _parse_sse_chunk(line: str) -> dict[str, Any] | None:
        if not line.startswith("data:"):
            return None
        try:
            return json.loads(line[len("data:") :])
        except ValueError:
            return None

    def _process_part(
        self,
        part: dict[str, Any],
        think: ThinkMarkers,
        tool_calls: list[ToolCallObject],
        last_thought: str,
    ) -> tuple[list[str], str, bool]:
        if part.get("thought"):
            # Thought summaries, sent when ``includeThoughts`` is on.
            # Each one is a section opening with a bold title and
            # no trailing newline; keep sections apart.
            text = part.get("text") or ""
            if think.open and text.startswith("**") and not last_thought.endswith("\n"):
                text = "\n\n" + text
            return list(think.thought(text)), text or last_thought, False
        if part.get("functionCall"):
            closed = list(think.close())
            tool_calls.append(self._tool_call(part, len(tool_calls)))
            return closed, last_thought, False
        if part.get("text"):
            return [*think.close(), part["text"]], last_thought, True
        return [], last_thought, False

    def _process_chunk(
        self,
        chunk: dict[str, Any],
        think: ThinkMarkers,
        tool_calls: list[ToolCallObject],
        last_thought: str,
    ) -> tuple[list[str], str, bool, str | None]:
        block_reason = (chunk.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            logger.warning(f"Vertex blocked the prompt: {block_reason}")
            raise generation_error(f"The request was blocked ({block_reason}).")

        outputs: list[str] = []
        produced_text = False
        finish_reason = None
        for candidate in chunk.get("candidates") or []:
            finish_reason = candidate.get("finishReason") or finish_reason
            for part in (candidate.get("content") or {}).get("parts") or []:
                items, last_thought, wrote_text = self._process_part(
                    part, think, tool_calls, last_thought
                )
                outputs.extend(items)
                produced_text = produced_text or wrote_text
        return outputs, last_thought, produced_text, finish_reason

    async def _stream_response(
        self, response: httpx.Response
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        tool_calls: list[ToolCallObject] = []
        produced_text = False
        finish_reason = None
        think = ThinkMarkers()
        last_thought = ""

        async for line in response.aiter_lines():
            chunk = self._parse_sse_chunk(line)
            if chunk is None:
                continue
            items, last_thought, wrote_text, chunk_finish = self._process_chunk(
                chunk, think, tool_calls, last_thought
            )
            produced_text = produced_text or wrote_text
            finish_reason = chunk_finish or finish_reason
            for item in items:
                yield item

        for item in think.close():
            yield item
        if tool_calls:
            logger.info(f"Complete tool calls: {tool_calls}")
            yield tool_calls
        elif not produced_text:
            logger.warning(
                f"Vertex returned no content (finish reason: {finish_reason})"
            )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        body = self._request_body(messages, system, tools)
        if options:
            body = deep_merge(body, options)
        thinking_config = (body.get("generationConfig") or {}).get("thinkingConfig")
        if (
            isinstance(thinking_config, dict)
            and "includeThoughts" not in thinking_config
        ):
            # Gemini sends its thought summaries only when asked; an explicit
            # ``includeThoughts: false`` is kept.
            body = deep_merge(
                body,
                {"generationConfig": {"thinkingConfig": {"includeThoughts": True}}},
            )
        logger.debug(f"Sending {len(body['contents'])} contents to {self.model}")

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}:streamGenerateContent",
                params={"alt": "sse"},
                json=body,
            ) as response:
                if response.status_code != 200:
                    message = _error_message(await response.aread())
                    logger.error(
                        f"Vertex API error (HTTP {response.status_code}): {message}"
                    )
                    logger.info(f"Model: {self.model}, URL: {self.base_url}")
                    if response.status_code == 429:
                        raise rate_limit_error()
                    if response.status_code in (401, 403):
                        raise authentication_error()
                    raise generation_error()
                async for item in self._stream_response(response):
                    yield item

        except LLMError:
            raise
        except VertexCredentialsError as error:
            logger.error(f"Vertex authentication failed: {error}")
            raise authentication_error() from error
        except httpx.HTTPError as error:
            logger.error(
                f"Vertex API: connection problem ({type(error).__name__}): {error}"
            )
            raise connection_error() from error

    async def close(self) -> None:
        await self.client.aclose()
