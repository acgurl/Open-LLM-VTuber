"""Protocol conversion and error mapping of the LLM backends."""

import unittest
from types import SimpleNamespace

import anthropic
import httpx
import openai

from open_llm_vtuber.agent.stateless_llm import openai_compatible_llm
from open_llm_vtuber.agent.stateless_llm.claude_llm import ClaudeLLM, claude_tools
from open_llm_vtuber.agent.stateless_llm.openai_compatible_llm import (
    OpenAICompatibleLLM,
)
from open_llm_vtuber.agent.stateless_llm.openai_responses_llm import (
    OpenAIResponsesLLM,
    response_input,
    response_tools,
)
from open_llm_vtuber.agent.stateless_llm.stateless_llm_interface import (
    LLMError,
    LLMToolsUnsupportedError,
    StatelessLLMInterface,
    content_text,
)
from open_llm_vtuber.mcpp.types import ToolCallObject

# A made-up value: nothing here is a real credential.
FAKE_KEY = "fake-key-for-tests"
PNG = "data:image/png;base64,QUJD"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look something up",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
    }
]

# One user turn, a tool-calling assistant turn and its results.
CONVERSATION = [
    {"role": "system", "content": "[Interrupted by user]"},
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image_url", "image_url": {"url": PNG, "detail": "auto"}},
        ],
    },
    {
        "role": "assistant",
        "content": "let me look",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"q": "x"}'},
            },
            {
                "id": "call-2",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            },
        ],
    },
    {"role": "tool", "tool_call_id": "call-1", "content": "found", "is_error": False},
    {
        "role": "tool",
        "tool_call_id": "call-2",
        "content": [
            {"type": "text", "text": "a picture"},
            {"type": "image_url", "image_url": {"url": PNG}},
        ],
        "is_error": True,
    },
]


async def _collect(stream):
    return [item async for item in stream]


def _api_error(cls, status, message):
    request = httpx.Request("POST", "https://llm.example/v1")
    return cls(message, response=httpx.Response(status, request=request), body=None)


class InterfaceTests(unittest.TestCase):
    def test_every_backend_implements_the_interface_directly(self):
        for backend in (OpenAICompatibleLLM, OpenAIResponsesLLM, ClaudeLLM):
            self.assertEqual(backend.__bases__, (StatelessLLMInterface,))

    def test_content_text_counts_images(self):
        self.assertEqual(content_text("plain"), "plain")
        self.assertEqual(content_text(None), "")
        self.assertEqual(
            content_text(CONVERSATION[4]["content"]),
            "a picture\n[1 image(s) omitted]",
        )


class _Completions:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _Stream:
    def __init__(self, items):
        self.items = items
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self.items:
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self):
        self.closed = True


def _chunk(content=None):
    delta = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class OpenAICompatibleTests(unittest.IsolatedAsyncioTestCase):
    def make(self, outcome, **kwargs):
        llm = OpenAICompatibleLLM(
            model="m", base_url="https://llm.example/v1", llm_api_key=FAKE_KEY, **kwargs
        )
        self.addAsyncCleanup(llm.close)
        completions = _Completions(outcome)
        llm.client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions), close=llm.client.close
        )
        return llm, completions

    async def test_request_carries_system_tools_and_clean_tool_messages(self):
        stream = _Stream([_chunk("hi")])
        llm, completions = self.make(stream, temperature=0.3)

        items = await _collect(llm.chat_completion(CONVERSATION, "SYS", TOOLS))

        self.assertEqual(items, ["hi"])
        self.assertTrue(stream.closed)
        request = completions.requests[0]
        self.assertEqual(request["temperature"], 0.3)
        self.assertEqual(request["tools"], TOOLS)
        messages = request["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "SYS"})
        # Internal keys are not sent, and tool results are text.
        self.assertEqual(
            messages[-2],
            {"role": "tool", "tool_call_id": "call-1", "content": "found"},
        )
        self.assertEqual(messages[-1]["content"], "a picture\n[1 image(s) omitted]")

    async def test_no_tools_and_no_temperature_are_omitted(self):
        llm, completions = self.make(_Stream([]), temperature=None)

        await _collect(llm.chat_completion([{"role": "user", "content": "hi"}]))

        request = completions.requests[0]
        self.assertIs(request["tools"], openai.NOT_GIVEN)
        self.assertIs(request["temperature"], openai.NOT_GIVEN)

    async def test_errors_are_raised_never_yielded(self):
        request = httpx.Request("POST", "https://llm.example/v1")
        cases = [
            (openai.APIConnectionError(request=request), "Connection error"),
            (_api_error(openai.RateLimitError, 429, "slow down"), "Rate limit"),
            (_api_error(openai.AuthenticationError, 401, "bad key"), "Authentication"),
            (
                _api_error(openai.BadRequestError, 400, "secret detail"),
                "Error occurred",
            ),
        ]
        for error, expected in cases:
            llm, _ = self.make(error)
            with self.assertRaises(LLMError) as raised:
                await _collect(llm.chat_completion([{"role": "user", "content": "x"}]))
            self.assertIn(expected, str(raised.exception))
            self.assertNotIn("secret detail", str(raised.exception))
            self.assertNotIsInstance(raised.exception, LLMToolsUnsupportedError)

    async def test_error_in_the_middle_of_the_stream_is_raised(self):
        error = _api_error(openai.InternalServerError, 500, "boom")
        llm, _ = self.make(_Stream([_chunk("partial"), error]))

        items = []
        with self.assertRaises(LLMError):
            async for item in llm.chat_completion([{"role": "user", "content": "x"}]):
                items.append(item)
        self.assertEqual(items, ["partial"])

    async def test_refused_tools_raise_and_leave_the_client_unchanged(self):
        error = _api_error(
            openai.BadRequestError, 400, "registry.ollama.ai/x does not support tools"
        )
        llm, completions = self.make(error)
        messages = [{"role": "user", "content": "x"}]

        with self.assertRaises(LLMToolsUnsupportedError):
            await _collect(llm.chat_completion(messages, tools=TOOLS))
        # The client is shared between sessions: nothing is remembered on it.
        self.assertFalse(hasattr(llm, "support_tools"))
        with self.assertRaises(LLMToolsUnsupportedError):
            await _collect(llm.chat_completion(messages, tools=TOOLS))
        self.assertEqual(completions.requests[1]["tools"], TOOLS)

        # Without tools in the request the same text is an ordinary failure.
        with self.assertRaises(LLMError) as raised:
            await _collect(llm.chat_completion(messages))
        self.assertNotIsInstance(raised.exception, LLMToolsUnsupportedError)

    def test_placeholder_defaults_are_gone(self):
        self.assertFalse(hasattr(openai_compatible_llm, "AsyncLLM"))
        llm = OpenAICompatibleLLM(model="m", base_url="http://x/v1", llm_api_key="k")
        self.assertIsNone(llm.client.organization)
        self.assertIsNone(llm.client.project)


def _event(kind, **fields):
    return SimpleNamespace(type=kind, **fields)


class OpenAIResponsesTests(unittest.IsolatedAsyncioTestCase):
    def make(self, outcome, **kwargs):
        llm = OpenAIResponsesLLM(model="m", llm_api_key=FAKE_KEY, **kwargs)
        self.addAsyncCleanup(llm.close)
        responses = _Completions(outcome)
        llm.client = SimpleNamespace(responses=responses, close=llm.client.close)
        return llm, responses

    def test_input_items(self):
        items = response_input(CONVERSATION)

        self.assertEqual(
            items,
            [
                {"role": "system", "content": "[Interrupted by user]"},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "what is this?"},
                        {"type": "input_image", "image_url": PNG, "detail": "auto"},
                    ],
                },
                {"role": "assistant", "content": "let me look"},
                {
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "lookup",
                    "arguments": '{"q": "x"}',
                },
                {
                    "type": "function_call",
                    "call_id": "call-2",
                    "name": "lookup",
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "found",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call-2",
                    "output": "a picture\n[1 image(s) omitted]",
                },
            ],
        )

    def test_tools_are_flattened(self):
        (tool,) = response_tools(TOOLS)
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["name"], "lookup")
        self.assertEqual(tool["parameters"], TOOLS[0]["function"]["parameters"])
        self.assertNotIn("function", tool)

    async def test_stream_yields_text_then_tool_calls(self):
        call = SimpleNamespace(
            type="function_call", call_id="call-9", name="lookup", arguments='{"q": 1}'
        )
        stream = _Stream(
            [
                _event("response.created"),
                _event("response.output_text.delta", delta="he"),
                _event("response.output_text.delta", delta="llo"),
                _event(
                    "response.output_item.done", item=SimpleNamespace(type="message")
                ),
                _event("response.output_item.done", item=call),
                _event("response.completed"),
            ]
        )
        llm, responses = self.make(stream, reasoning_effort="low")

        items = await _collect(llm.chat_completion(CONVERSATION, "SYS", TOOLS))

        self.assertEqual(items[:2], ["he", "llo"])
        (calls,) = items[2:]
        self.assertIsInstance(calls[0], ToolCallObject)
        self.assertEqual(calls[0].id, "call-9")
        self.assertEqual(calls[0].function.arguments, '{"q": 1}')
        request = responses.requests[0]
        self.assertEqual(request["instructions"], "SYS")
        self.assertEqual(request["reasoning"], {"effort": "low"})
        self.assertIs(request["temperature"], openai.NOT_GIVEN)
        self.assertFalse(request["store"])
        self.assertTrue(stream.closed)

    async def test_failures_are_raised(self):
        failed = _event("response.failed", response=SimpleNamespace(error="quota"))
        for outcome in (
            _Stream([failed]),
            _Stream([_event("error", code="x", message="secret detail")]),
            _api_error(openai.RateLimitError, 429, "slow down"),
        ):
            llm, _ = self.make(outcome)
            with self.assertRaises(LLMError) as raised:
                await _collect(llm.chat_completion([{"role": "user", "content": "x"}]))
            self.assertNotIn("secret detail", str(raised.exception))


class _Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return dict(vars(self))


class _ClaudeStream:
    def __init__(self, texts, message):
        self.texts = texts
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    @property
    def text_stream(self):
        async def stream():
            for text in self.texts:
                yield text

        return stream()

    async def get_final_message(self):
        return self.message


class _ClaudeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class ClaudeTests(unittest.IsolatedAsyncioTestCase):
    def make(self, outcome, **kwargs):
        llm = ClaudeLLM(model="claude-test", llm_api_key=FAKE_KEY, **kwargs)
        self.addAsyncCleanup(llm.close)
        messages = _ClaudeMessages(outcome)
        llm.client = SimpleNamespace(messages=messages, close=llm.client.close)
        return llm, messages

    def test_messages_are_converted_to_content_blocks(self):
        llm, _ = self.make(None)

        converted = llm._to_messages(CONVERSATION)

        # The system-role message is dropped; both results share one user turn.
        self.assertEqual([m["role"] for m in converted], ["user", "assistant", "user"])
        self.assertEqual(
            converted[0]["content"][1],
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
            },
        )
        self.assertEqual(
            converted[1]["content"],
            [
                {"type": "text", "text": "let me look"},
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "lookup",
                    "input": {"q": "x"},
                },
                {"type": "tool_use", "id": "call-2", "name": "lookup", "input": {}},
            ],
        )
        first, second = converted[2]["content"]
        self.assertEqual(
            first,
            {
                "type": "tool_result",
                "tool_use_id": "call-1",
                "content": "found",
                "is_error": False,
            },
        )
        self.assertTrue(second["is_error"])
        self.assertEqual(
            [block["type"] for block in second["content"]], ["text", "image"]
        )

    def test_blank_text_is_not_sent(self):
        llm, _ = self.make(None)
        converted = llm._to_messages(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "  \n"},
                {"role": "tool", "tool_call_id": "c", "content": "", "is_error": True},
            ]
        )
        # The blank assistant turn vanishes, so the user turns merge.
        (message,) = converted
        self.assertEqual(message["role"], "user")
        self.assertEqual(
            message["content"][-1]["content"],
            "Error occurred during tool execution.",
        )

    def test_tools_use_input_schema(self):
        self.assertEqual(
            claude_tools(TOOLS),
            [
                {
                    "name": "lookup",
                    "description": "Look something up",
                    "input_schema": TOOLS[0]["function"]["parameters"],
                }
            ],
        )

    async def test_request_uses_configured_limits(self):
        final = SimpleNamespace(stop_reason="end_turn", content=[])
        llm, messages = self.make(_ClaudeStream(["hi"], final), max_tokens=2048)

        items = await _collect(llm.chat_completion(CONVERSATION, "SYS", TOOLS))

        self.assertEqual(items, ["hi"])
        request = messages.requests[0]
        self.assertEqual(request["max_tokens"], 2048)
        self.assertEqual(request["system"], "SYS")
        self.assertEqual(request["tools"], claude_tools(TOOLS))
        # Unset by default: current Claude models reject the parameter.
        self.assertIs(request["temperature"], anthropic.NOT_GIVEN)

        llm, messages = self.make(_ClaudeStream([], final), temperature=0.2)
        await _collect(llm.chat_completion([{"role": "user", "content": "x"}]))
        self.assertEqual(messages.requests[0]["temperature"], 0.2)
        self.assertIs(messages.requests[0]["tools"], anthropic.NOT_GIVEN)

    async def test_tool_use_turn_is_returned_and_replayed_verbatim(self):
        thinking = _Block(type="thinking", thinking="", signature="sig")
        text = _Block(type="text", text="checking")
        tool_use = _Block(
            type="tool_use", id="toolu_1", name="lookup", input={"q": "x"}
        )
        final = SimpleNamespace(
            stop_reason="tool_use", content=[thinking, text, tool_use]
        )
        llm, _ = self.make(_ClaudeStream(["checking"], final))

        items = await _collect(
            llm.chat_completion([{"role": "user", "content": "x"}], tools=TOOLS)
        )

        self.assertEqual(items[0], "checking")
        (call,) = items[1]
        self.assertEqual(
            (call.id, call.function.name, call.function.arguments),
            ("toolu_1", "lookup", '{"q": "x"}'),
        )

        # The agent rebuilds the turn from text and calls; the thinking block
        # still goes back with it.
        converted = llm._to_messages(
            [
                {"role": "user", "content": "x"},
                {
                    "role": "assistant",
                    "content": "checking",
                    "tool_calls": [
                        {
                            "id": "toolu_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"q": "x"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "toolu_1", "content": "ok"},
            ]
        )
        self.assertEqual(
            [block["type"] for block in converted[1]["content"]],
            ["thinking", "text", "tool_use"],
        )
        self.assertEqual(converted[1]["content"][0]["signature"], "sig")

    async def test_errors_are_raised_once(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [
            (anthropic.APIConnectionError(request=request), "Connection error"),
            (_api_error(anthropic.RateLimitError, 429, "slow down"), "Rate limit"),
            (_api_error(anthropic.AuthenticationError, 401, "bad"), "Authentication"),
            (
                _api_error(anthropic.BadRequestError, 400, "secret detail"),
                "Error occurred",
            ),
        ]
        for error, expected in cases:
            llm, _ = self.make(error)
            items = []
            with self.assertRaises(LLMError) as raised:
                async for item in llm.chat_completion(
                    [{"role": "user", "content": "x"}]
                ):
                    items.append(item)
            # Nothing is yielded on the way out: the failure is the exception.
            self.assertEqual(items, [])
            self.assertIn(expected, str(raised.exception))
            self.assertNotIn("secret detail", str(raised.exception))

    async def test_refusal_without_text_is_an_error(self):
        final = SimpleNamespace(stop_reason="refusal", content=[])
        llm, _ = self.make(_ClaudeStream([], final))

        with self.assertRaises(LLMError) as raised:
            await _collect(llm.chat_completion([{"role": "user", "content": "x"}]))
        self.assertIn("declined", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
