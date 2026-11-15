"""Vertex AI (Google Cloud) through its native ``generateContent`` API.

Authentication uses a service-account key file as downloaded from the Google
Cloud console: the key signs a JWT, Google's token endpoint trades it for a
short-lived access token, and that token is sent as the bearer of every
request. Tokens are cached and renewed shortly before they expire.

Messages and tools arrive in the format of ``stateless_llm_interface``; the
conversion to and from Gemini ``contents`` happens here.
"""

import asyncio
import json
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import jwt
from loguru import logger

from .stateless_llm_interface import (
    LLMError,
    StatelessLLMInterface,
    authentication_error,
    connection_error,
    content_text,
    generation_error,
    rate_limit_error,
    split_data_url,
    tool_specs,
)
from ...mcpp.types import ToolCallObject

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_ASSERTION_LIFETIME = 3600
# Renew this many seconds before the token expires.
_REFRESH_MARGIN = 300
# Thought signatures kept for tool calls that are still being answered.
_MAX_SIGNATURES = 1024


class VertexCredentialsError(ValueError):
    """The service-account file is unusable, or Google refused the key."""


def load_service_account(path: str) -> dict[str, Any]:
    """Read and check a service-account key file.

    Error messages name the file and the problem, never the file's contents.
    """
    try:
        info = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as error:
        raise VertexCredentialsError(
            f"Vertex credentials file '{path}' cannot be read ({type(error).__name__})"
        ) from None
    except ValueError:
        raise VertexCredentialsError(
            f"Vertex credentials file '{path}' is not valid JSON"
        ) from None

    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise VertexCredentialsError(
            f"Vertex credentials file '{path}' is not a service-account key "
            '(expected "type": "service_account")'
        )
    missing = [
        key
        for key in ("client_email", "private_key")
        if not isinstance(info.get(key), str) or not info[key]
    ]
    if missing:
        raise VertexCredentialsError(
            f"Vertex credentials file '{path}' lacks {', '.join(missing)}"
        )
    return info


class ServiceAccountAuth(httpx.Auth):
    """Adds a Google access token to each request, fetching it when needed."""

    def __init__(self, info: dict[str, Any]) -> None:
        self._client_email: str = info["client_email"]
        self._private_key: str = info["private_key"]
        self._private_key_id: str | None = info.get("private_key_id")
        self._token_uri: str = info.get("token_uri") or _DEFAULT_TOKEN_URI
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def _token_request(self) -> httpx.Request:
        now = int(time.time())
        try:
            assertion = jwt.encode(
                {
                    "iss": self._client_email,
                    "scope": _SCOPE,
                    "aud": self._token_uri,
                    "iat": now,
                    "exp": now + _ASSERTION_LIFETIME,
                },
                self._private_key,
                algorithm="RS256",
                headers={"kid": self._private_key_id} if self._private_key_id else None,
            )
        except Exception as error:
            # The original message may quote key material.
            raise VertexCredentialsError(
                "The private key of the Vertex service account cannot sign "
                f"({type(error).__name__})"
            ) from None
        return httpx.Request(
            "POST",
            self._token_uri,
            data={"grant_type": _JWT_GRANT, "assertion": assertion},
        )

    def _store_token(self, response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        token = payload.get("access_token")
        if response.status_code != 200 or not isinstance(token, str) or not token:
            reason = payload.get("error_description") or payload.get("error") or ""
            raise VertexCredentialsError(
                "Google rejected the Vertex service account "
                f"(HTTP {response.status_code}{': ' + str(reason) if reason else ''})"
            )
        try:
            lifetime = float(payload.get("expires_in", _ASSERTION_LIFETIME))
        except (TypeError, ValueError):
            lifetime = float(_ASSERTION_LIFETIME)
        self._token = token
        self._expires_at = time.monotonic() + lifetime

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        # The lock keeps concurrent conversations from each fetching a token.
        async with self._lock:
            if (
                self._token is None
                or time.monotonic() >= self._expires_at - _REFRESH_MARGIN
            ):
                response = yield self._token_request()
                await response.aread()
                self._store_token(response)
            token = self._token

        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            # Revoked early; the next request starts from a fresh token.
            self._token = None


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


def _error_message(body: bytes) -> str:
    """The message of a Google API error response."""
    try:
        payload = json.loads(body)
    except ValueError:
        return body.decode("utf-8", errors="replace")[:500]
    # A streaming endpoint wraps its error object in a list.
    if isinstance(payload, list) and payload:
        payload = payload[0]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return str(payload)[:500]


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
        project_id = project_id or info.get("project_id")
        if not project_id:
            raise VertexCredentialsError(
                f"Vertex credentials file '{credentials_file}' has no project_id; "
                "set project_id in the vertex_llm settings"
            )

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

    def _to_contents(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Gemini ``contents`` plus the text of any system messages."""
        contents: list[dict[str, Any]] = []
        system_texts: list[str] = []
        call_names: dict[str, str] = {}

        def add(role: str, parts: list[dict[str, Any]]) -> None:
            if not parts:
                return
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})

        for message in messages:
            role = message.get("role")
            if role == "system":
                system_texts.extend(
                    part["text"]
                    for part in _content_parts(message.get("content"))
                    if "text" in part
                )
            elif role == "assistant":
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
                add("model", parts)
            elif role == "tool":
                result = content_text(message.get("content"))
                add(
                    "user",
                    [
                        {
                            "functionResponse": {
                                "name": call_names.get(message.get("tool_call_id"), ""),
                                "response": (
                                    {"error": result}
                                    if message.get("is_error")
                                    else {"result": result}
                                ),
                            }
                        }
                    ],
                )
            else:
                add("user", _content_parts(message.get("content")))
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

    async def _stream_response(
        self, response: httpx.Response
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        tool_calls: list[ToolCallObject] = []
        produced_text = False
        finish_reason = None

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                chunk = json.loads(line[len("data:") :])
            except ValueError:
                continue

            block_reason = (chunk.get("promptFeedback") or {}).get("blockReason")
            if block_reason:
                logger.warning(f"Vertex blocked the prompt: {block_reason}")
                raise generation_error(f"The request was blocked ({block_reason}).")

            for candidate in chunk.get("candidates") or []:
                finish_reason = candidate.get("finishReason") or finish_reason
                for part in (candidate.get("content") or {}).get("parts") or []:
                    if part.get("thought"):
                        continue
                    if part.get("functionCall"):
                        tool_calls.append(self._tool_call(part, len(tool_calls)))
                    elif part.get("text"):
                        produced_text = True
                        yield part["text"]

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
    ) -> AsyncIterator[str | list[ToolCallObject]]:
        body = self._request_body(messages, system, tools)
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
