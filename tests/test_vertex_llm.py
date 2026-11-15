import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from open_llm_vtuber.agent import stateless_llm_factory
from open_llm_vtuber.agent.stateless_llm.openai_compatible_llm import (
    OpenAICompatibleLLM,
)
from open_llm_vtuber.agent.stateless_llm.stateless_llm_interface import (
    LLMError,
    ReasoningText,
    StatelessLLMInterface,
)
from open_llm_vtuber.agent.stateless_llm.vertex_llm import (
    VertexCredentialsError,
    VertexLLM,
    load_service_account,
    vertex_model_url,
)
from open_llm_vtuber.config_manager.stateless_llm import VertexConfig
from open_llm_vtuber.mcpp.types import ToolCallObject

TOKEN_URI = "https://oauth2.test/token"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


def _sse(*chunks: dict) -> bytes:
    return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks).encode()


def _text_chunk(text: str) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}


class _Google:
    """Stands in for the token endpoint and the Vertex API."""

    def __init__(self, replies: list[httpx.Response]) -> None:
        self.replies = replies
        self.token_requests: list[httpx.Request] = []
        self.api_requests: list[httpx.Request] = []
        self.token_reply = httpx.Response(
            200, json={"access_token": "token-1", "expires_in": 3600}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            self.token_requests.append(request)
            return self.token_reply
        self.api_requests.append(request)
        return self.replies.pop(0)

    def body(self, index: int = -1) -> dict:
        return json.loads(self.api_requests[index].content)


class VertexLLMTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.path = Path(self._temp_dir.name) / "key.json"
        self.write_key()

    def write_key(self, **overrides):
        info = {
            "type": "service_account",
            "project_id": "demo-project",
            "private_key_id": "key-id",
            "private_key": _PRIVATE_PEM,
            "client_email": "bot@demo-project.iam.gserviceaccount.com",
            "token_uri": TOKEN_URI,
            **overrides,
        }
        self.path.write_text(
            json.dumps({k: v for k, v in info.items() if v is not None}),
            encoding="utf-8",
        )

    def make_llm(self, google: _Google, **kwargs) -> VertexLLM:
        llm = VertexLLM(
            model="gemini-test",
            credentials_file=str(self.path),
            transport=httpx.MockTransport(google),
            **kwargs,
        )
        self.addAsyncCleanup(llm.client.aclose)
        return llm

    @staticmethod
    async def collect(stream) -> list:
        return [item async for item in stream]

    # ---- credentials

    def test_key_file_problems_are_reported_without_its_contents(self):
        with self.assertRaises(VertexCredentialsError):
            load_service_account(str(self.path.with_name("missing.json")))

        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(VertexCredentialsError):
            load_service_account(str(self.path))

        self.write_key(type="authorized_user")
        with self.assertRaises(VertexCredentialsError):
            load_service_account(str(self.path))

        self.write_key(private_key=None)
        with self.assertRaises(VertexCredentialsError) as caught:
            load_service_account(str(self.path))
        self.assertIn("private_key", str(caught.exception))

    def test_project_comes_from_key_file_unless_overridden(self):
        google = _Google([])
        self.assertEqual(
            self.make_llm(google).base_url,
            "https://aiplatform.googleapis.com/v1/projects/demo-project/"
            "locations/global/publishers/google/models/gemini-test",
        )
        self.assertEqual(
            self.make_llm(google, project_id="other", location="us-central1").base_url,
            "https://us-central1-aiplatform.googleapis.com/v1/projects/other/"
            "locations/us-central1/publishers/google/models/gemini-test",
        )

        self.write_key(project_id=None)
        with self.assertRaises(VertexCredentialsError):
            self.make_llm(google)

    def test_model_may_name_its_publisher(self):
        self.assertTrue(
            vertex_model_url("p", "global", "anthropic/claude").endswith(
                "/publishers/anthropic/models/claude"
            )
        )
        self.assertTrue(
            vertex_model_url("p", "global", "publishers/x/models/y").endswith(
                "/locations/global/publishers/x/models/y"
            )
        )

    async def test_token_is_signed_by_the_key_and_reused(self):
        google = _Google(
            [
                httpx.Response(200, content=_sse(_text_chunk("a"))),
                httpx.Response(200, content=_sse(_text_chunk("b"))),
            ]
        )
        llm = self.make_llm(google)
        messages = [{"role": "user", "content": "hi"}]

        self.assertEqual(await self.collect(llm.chat_completion(messages)), ["a"])
        self.assertEqual(await self.collect(llm.chat_completion(messages)), ["b"])

        self.assertEqual(len(google.token_requests), 1)
        form = parse_qs(google.token_requests[0].content.decode())
        claims = jwt.decode(
            form["assertion"][0],
            _KEY.public_key(),
            algorithms=["RS256"],
            audience=TOKEN_URI,
        )
        self.assertEqual(claims["iss"], "bot@demo-project.iam.gserviceaccount.com")
        self.assertEqual(
            claims["scope"], "https://www.googleapis.com/auth/cloud-platform"
        )
        for request in google.api_requests:
            self.assertEqual(request.headers["Authorization"], "Bearer token-1")
            self.assertTrue(request.url.path.endswith(":streamGenerateContent"))
            self.assertEqual(request.url.params["alt"], "sse")

    async def test_rejected_key_raises_an_llm_error(self):
        google = _Google([])
        google.token_reply = httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "bad key"}
        )
        llm = self.make_llm(google)

        with self.assertRaises(LLMError) as raised:
            await self.collect(llm.chat_completion([{"role": "user", "content": "hi"}]))

        self.assertIn("Authentication failed", str(raised.exception))
        self.assertNotIn("bad key", str(raised.exception))
        self.assertEqual(google.api_requests, [])

    async def test_a_401_drops_the_cached_token(self):
        google = _Google(
            [
                httpx.Response(401, json={"error": {"message": "expired"}}),
                httpx.Response(200, content=_sse(_text_chunk("ok"))),
            ]
        )
        llm = self.make_llm(google)
        messages = [{"role": "user", "content": "hi"}]

        with self.assertRaises(LLMError):
            await self.collect(llm.chat_completion(messages))
        self.assertEqual(await self.collect(llm.chat_completion(messages)), ["ok"])
        self.assertEqual(len(google.token_requests), 2)

    # ---- request and response conversion

    async def test_request_uses_native_contents(self):
        google = _Google([httpx.Response(200, content=_sse(_text_chunk("hello")))])
        llm = self.make_llm(google, temperature=0.4)

        await self.collect(
            llm.chat_completion(
                [
                    {"role": "system", "content": "extra rule"},
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "reply"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "look"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,QUJD"},
                            },
                        ],
                    },
                ],
                system="persona",
                tools=[
                    {
                        "name": "lookup",
                        "description": "Look something up",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
            )
        )

        body = google.body()
        self.assertEqual(
            body["systemInstruction"], {"parts": [{"text": "persona\n\nextra rule"}]}
        )
        self.assertEqual(
            body["contents"],
            [
                {"role": "user", "parts": [{"text": "first"}]},
                {"role": "model", "parts": [{"text": "reply"}]},
                {
                    "role": "user",
                    "parts": [
                        {"text": "look"},
                        {"inlineData": {"mimeType": "image/png", "data": "QUJD"}},
                    ],
                },
            ],
        )
        self.assertEqual(body["generationConfig"], {"temperature": 0.4})
        self.assertEqual(
            body["tools"],
            [
                {
                    "functionDeclarations": [
                        {
                            "name": "lookup",
                            "description": "Look something up",
                            "parametersJsonSchema": {
                                "type": "object",
                                "properties": {},
                            },
                        }
                    ]
                }
            ],
        )

    async def test_tool_round_trip_returns_the_thought_signature(self):
        google = _Google(
            [
                httpx.Response(
                    200,
                    content=_sse(
                        _text_chunk("Checking. "),
                        {
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [
                                            {"thought": True, "text": "hidden"},
                                            {
                                                "functionCall": {
                                                    "name": "lookup",
                                                    "args": {"q": "天气"},
                                                },
                                                "thoughtSignature": "sig-1",
                                            },
                                        ]
                                    },
                                    "finishReason": "STOP",
                                }
                            ]
                        },
                    ),
                ),
                httpx.Response(200, content=_sse(_text_chunk("Sunny."))),
            ]
        )
        llm = self.make_llm(google)
        messages = [{"role": "user", "content": "weather?"}]

        first = await self.collect(llm.chat_completion(messages))

        # The thought part is shown folded, closed before the call.
        self.assertEqual(first[:4], ["Checking. ", "<think>", "hidden", "</think>"])
        self.assertTrue(all(isinstance(i, ReasoningText) for i in first[1:4]))
        (call,) = first[4]
        self.assertIsInstance(call, ToolCallObject)
        self.assertEqual(call.function.name, "lookup")
        self.assertEqual(json.loads(call.function.arguments), {"q": "天气"})

        messages += [
            {
                "role": "assistant",
                "content": "Checking. ",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call.id, "content": "sunny"},
        ]
        second = await self.collect(llm.chat_completion(messages))

        self.assertEqual(second, ["Sunny."])
        self.assertEqual(
            google.body()["contents"][1:],
            [
                {
                    "role": "model",
                    "parts": [
                        {"text": "Checking. "},
                        {
                            "functionCall": {"name": "lookup", "args": {"q": "天气"}},
                            "thoughtSignature": "sig-1",
                        },
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "lookup",
                                "response": {"result": "sunny"},
                            }
                        }
                    ],
                },
            ],
        )

    async def test_thought_sections_are_kept_apart(self):
        def thought(text):
            return {
                "candidates": [
                    {"content": {"parts": [{"thought": True, "text": text}]}}
                ]
            }

        google = _Google(
            [
                httpx.Response(
                    200,
                    content=_sse(
                        thought("**Planning**\n\nI am sketching"),
                        thought(" the proof."),  # one section split across chunks
                        thought("**Checking**\n\nAll steps hold."),
                        _text_chunk("Done."),
                    ),
                )
            ]
        )
        llm = self.make_llm(google)

        items = await self.collect(
            llm.chat_completion([{"role": "user", "content": "x"}])
        )

        self.assertEqual(
            "".join(items[1:-2]),
            "**Planning**\n\nI am sketching the proof."
            "\n\n**Checking**\n\nAll steps hold.",
        )
        self.assertEqual(items[-2:], ["</think>", "Done."])

    async def test_thinking_config_asks_for_thoughts(self):
        google = _Google([httpx.Response(200, content=_sse(_text_chunk("Hi.")))])
        llm = self.make_llm(google)
        options = {"generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}}

        await self.collect(
            llm.chat_completion([{"role": "user", "content": "x"}], options=options)
        )

        self.assertEqual(
            google.body()["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "low", "includeThoughts": True},
        )
        # The level's params are shared; they stay as written.
        self.assertEqual(
            options, {"generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}}
        )

    async def test_api_errors_raise_llm_errors(self):
        google = _Google(
            [
                httpx.Response(404, json={"error": {"message": "no such model"}}),
                httpx.Response(429, json=[{"error": {"message": "slow down"}}]),
                httpx.Response(
                    200, content=_sse({"promptFeedback": {"blockReason": "SAFETY"}})
                ),
            ]
        )
        llm = self.make_llm(google)
        messages = [{"role": "user", "content": "hi"}]

        for expected in ("Error occurred", "Rate limit", "SAFETY"):
            with self.assertRaises(LLMError) as raised:
                await self.collect(llm.chat_completion(messages))
            self.assertIn(expected, str(raised.exception))
            # The provider's own wording stays in the log.
            self.assertNotIn("no such model", str(raised.exception))

    async def test_connection_failure_raises_an_llm_error(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable", request=request)

        llm = self.make_llm(refuse)

        with self.assertRaises(LLMError) as raised:
            await self.collect(llm.chat_completion([{"role": "user", "content": "hi"}]))
        self.assertIn("Connection error", str(raised.exception))

    # ---- wiring

    def test_it_implements_the_interface_directly(self):
        llm = self.make_llm(_Google([]))
        self.assertIsInstance(llm, StatelessLLMInterface)
        self.assertNotIsInstance(llm, OpenAICompatibleLLM)

    async def test_close_closes_the_http_client(self):
        llm = self.make_llm(_Google([]))
        await llm.close()
        self.assertTrue(llm.client.is_closed)

    def test_factory_builds_it_from_validated_settings(self):
        settings = VertexConfig(
            credentials_file=str(self.path), model="gemini-test"
        ).model_dump()
        settings.pop("interrupt_method")

        llm = stateless_llm_factory.LLMFactory.create_llm("vertex_llm", **settings)
        self.addAsyncCleanup(llm.client.aclose)

        self.assertIsInstance(llm, VertexLLM)
        self.assertIn("/locations/global/", llm.base_url)
        self.assertEqual(llm.temperature, 1.0)


if __name__ == "__main__":
    unittest.main()
