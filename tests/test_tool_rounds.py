import socket
import unittest
from types import SimpleNamespace
from unittest import mock

from open_llm_vtuber.agent.agents.basic_memory_agent import (
    TOOL_EXECUTOR_MISSING_NOTICE,
    BasicMemoryAgent,
)
from open_llm_vtuber.agent.stateless_llm import claude_llm
from open_llm_vtuber.agent.stateless_llm.openai_compatible_llm import (
    AsyncLLM as OpenAICompatibleAsyncLLM,
)
from open_llm_vtuber.mcpp import user_servers
from open_llm_vtuber.mcpp.json_detector import StreamJSONDetector
from open_llm_vtuber.mcpp.types import ToolCallFunctionObject, ToolCallObject


class _OneRoundLLM:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def chat_completion(self, _messages, _system, tools=None):
        self.calls += 1

        async def stream():
            for item in self.items:
                yield item

        return stream()


def _agent(llm, *, prompt_mode=False):
    agent = BasicMemoryAgent.__new__(BasicMemoryAgent)
    agent._system = "system"
    agent._tool_executor = None
    agent._llm = llm
    agent.prompt_mode_flag = prompt_mode
    agent._mcp_prompt_string = "MCP"
    agent._json_detector = StreamJSONDetector()
    agent._tool_manager = None
    agent.added = []
    agent._add_message = lambda content, role: agent.added.append((content, role))
    return agent


class MissingToolExecutorTests(unittest.IsolatedAsyncioTestCase):
    """Every tool path reports the same error and leaves memory untouched."""

    async def _run(self, agent, loop):
        items = [item async for item in loop([{"role": "user", "content": "hi"}], [])]
        self.assertEqual(items[-1], TOOL_EXECUTOR_MISSING_NOTICE)
        self.assertIn("not configured", items[-1])
        self.assertEqual(agent.added, [])
        self.assertEqual(agent._llm.calls, 1)

    async def test_claude(self):
        llm = _OneRoundLLM(
            [
                {"type": "text_delta", "text": "let me check"},
                {
                    "type": "tool_use_complete",
                    "data": {"name": "t", "id": "1", "input": {}},
                },
                {"type": "message_stop"},
            ]
        )
        agent = _agent(llm)
        await self._run(agent, agent._claude_tool_interaction_loop)

    async def test_openai_native(self):
        call = ToolCallObject(
            id="1", function=ToolCallFunctionObject(name="t", arguments="{}")
        )
        agent = _agent(_OneRoundLLM(["let me check", [call]]))
        await self._run(agent, agent._openai_tool_interaction_loop)

    async def test_prompt_mode(self):
        llm = _OneRoundLLM(['{"mcp_server": "kb", "tool": "t", "arguments": {}}'])
        agent = _agent(llm, prompt_mode=True)
        await self._run(agent, agent._openai_tool_interaction_loop)
        self.assertEqual(agent._json_detector.buffer, "")


def _delta(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tool_delta(index, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=id,
        type="function" if id else None,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class OpenAIStreamChunkTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_fragments_are_merged_before_following_text(self):
        llm = OpenAICompatibleAsyncLLM.__new__(OpenAICompatibleAsyncLLM)
        llm.support_tools = True

        async def stream():
            yield SimpleNamespace(choices=[])
            yield _delta("pre")
            yield _delta(tool_calls=[_tool_delta(0, "c1", "search", '{"q"')])
            yield _delta(tool_calls=[_tool_delta(0, arguments=': "x"}')])
            yield _delta(tool_calls=[_tool_delta(1, "c2", "other", "{}")])
            yield _delta(None)
            yield _delta("post")

        items = [item async for item in llm._stream_chunks(stream())]

        self.assertEqual(items[0], "pre")
        calls = items[1]
        self.assertEqual([c.id for c in calls], ["c1", "c2"])
        self.assertEqual(calls[0].function.name, "search")
        self.assertEqual(calls[0].function.arguments, '{"q": "x"}')
        self.assertEqual(items[2:], ["", "post"])


class ClaudeStreamEventTests(unittest.TestCase):
    def test_tool_use_block_is_completed_on_its_stop(self):
        state = claude_llm._StreamState()
        start = SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(type="tool_use", id="t1", name="f"),
        )
        delta = SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"a": 1}'),
        )
        stop = SimpleNamespace(type="content_block_stop", index=1)

        outputs = []
        for event in (start, delta, stop, stop):
            outputs.extend(claude_llm._EVENT_HANDLERS[event.type](event, state))

        self.assertEqual(
            [output["type"] for output in outputs],
            ["tool_use_start", "tool_use_complete"],
        )
        self.assertEqual(outputs[1]["data"]["input"], {"a": 1})
        self.assertIsNone(state.tool_call)


def _resolve_to(address):
    def getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    return getaddrinfo


class HostSuffixPolicyTests(unittest.TestCase):
    """The two URL checks deliberately use different suffix lists."""

    def test_lan_suffixes_are_local_but_not_blocked_by_name(self):
        with mock.patch.object(socket, "getaddrinfo", _resolve_to("93.184.216.34")):
            for host in ("box.corp", "box.home", "box.lan"):
                url = f"https://{host}/mcp"
                self.assertEqual(user_servers.classify_mcp_url(url), "local")
                self.assertEqual(user_servers.validate_public_https_url(url), url)

    def test_reserved_suffixes_are_rejected_without_lookup(self):
        with mock.patch.object(socket, "getaddrinfo") as getaddrinfo:
            for host in ("box.internal", "box.local", "a.localhost", "x.home.arpa"):
                url = f"https://{host}/mcp"
                self.assertEqual(user_servers.classify_mcp_url(url), "local")
                with self.assertRaisesRegex(ValueError, "public host"):
                    user_servers.validate_public_https_url(url)
            getaddrinfo.assert_not_called()

    def test_private_resolution_is_local_and_rejected(self):
        with mock.patch.object(socket, "getaddrinfo", _resolve_to("10.0.0.1")):
            url = "https://intranet.example/mcp"
            self.assertEqual(user_servers.classify_mcp_url(url), "local")
            with self.assertRaisesRegex(ValueError, "private or reserved"):
                user_servers.validate_public_https_url(url)


if __name__ == "__main__":
    unittest.main()
