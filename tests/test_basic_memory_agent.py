import unittest

from loguru import logger
from pydantic import ValidationError

from open_llm_vtuber.agent.agents.basic_memory_agent import (
    DEFAULT_MAX_TOOL_ROUNDS,
    TOOL_ROUND_LIMIT_NOTICE,
    BasicMemoryAgent,
)
from open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from open_llm_vtuber.agent.stateless_llm.openai_compatible_llm import (
    AsyncLLM as OpenAICompatibleAsyncLLM,
)
from open_llm_vtuber.config_manager.agent import BasicMemoryAgentConfig
from open_llm_vtuber.mcpp.json_detector import StreamJSONDetector
from open_llm_vtuber.mcpp.types import ToolCallFunctionObject, ToolCallObject


class DrainToolExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = BasicMemoryAgent.__new__(BasicMemoryAgent)

    async def test_forwards_updates_and_collects_final_results(self):
        async def executor():
            yield {"type": "tool_call_status", "text": "running"}
            yield {"type": "final_tool_results", "results": [{"content": "ok"}]}
            yield {"type": "ignored_after_final"}

        results = []
        updates = [
            update
            async for update in self.agent._drain_tool_executor(
                executor(), results, "Test executor"
            )
        ]

        self.assertEqual(updates, [{"type": "tool_call_status", "text": "running"}])
        self.assertEqual(results, [{"content": "ok"}])

    async def test_missing_final_marker_leaves_results_empty(self):
        async def executor():
            yield {"type": "tool_call_status", "text": "running"}

        results = []
        updates = [
            update
            async for update in self.agent._drain_tool_executor(
                executor(), results, "Test executor"
            )
        ]

        self.assertEqual(len(updates), 1)
        self.assertEqual(results, [])


class _ClaudeLLM:
    def __init__(self):
        self.calls = 0

    def chat_completion(self, _messages, _system, tools=None):
        self.calls += 1
        if self.calls == 1:

            async def first_round():
                yield {"type": "text_delta", "text": "A"}
                yield {
                    "type": "tool_use_complete",
                    "data": {"name": "tool", "id": "1", "input": {}},
                }
                yield {"type": "message_stop"}

            return first_round()

        async def second_round():
            yield {"type": "text_delta", "text": "B"}
            yield {"type": "message_stop"}

        return second_round()


class _ToolExecutor:
    async def execute_tools(self, tool_calls, caller_mode):
        yield {"type": "tool_call_status", "text": "running"}
        yield {"type": "final_tool_results", "results": [{"content": "ok"}]}


class ToolLoopStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = BasicMemoryAgent.__new__(BasicMemoryAgent)
        self.agent._system = "system"
        self.agent._tool_executor = _ToolExecutor()
        self.added = []
        self.agent._add_message = lambda content, role: self.added.append(
            (content, role)
        )

    async def test_claude_loop_resets_text_between_tool_rounds(self):
        self.agent._llm = _ClaudeLLM()

        _ = [item async for item in self.agent._claude_tool_interaction_loop([], [])]

        self.assertEqual(self.added, [("A", "assistant"), ("B", "assistant")])

    async def test_openai_native_tool_round_feeds_results_back(self):
        agent = self.agent
        agent.prompt_mode_flag = False
        agent._mcp_prompt_string = ""
        agent._json_detector = StreamJSONDetector()
        agent._tool_manager = object()
        llm = _NativeToolLLM()
        agent._llm = llm

        _ = [
            item
            async for item in agent._openai_tool_interaction_loop(
                [{"role": "user", "content": "hi"}], []
            )
        ]

        self.assertFalse(agent.prompt_mode_flag)
        self.assertEqual(self.added, [("done", "assistant")])
        second_round = llm.messages[1]
        self.assertEqual(second_round[-2]["role"], "assistant")
        self.assertEqual(
            second_round[-2]["tool_calls"][0]["function"]["arguments"],
            '{"q": "x"}',
        )
        self.assertEqual(second_round[-1], {"content": "ok"})

    async def test_switches_to_prompt_mode_without_tool_manager_disable(self):
        agent = self.agent
        agent.prompt_mode_flag = False
        agent._mcp_prompt_string = ""
        agent._json_detector = StreamJSONDetector()
        agent._tool_manager = object()
        agent._llm = _UnsupportedToolsLLM()

        _ = [item async for item in agent._openai_tool_interaction_loop([], [])]

        self.assertTrue(agent.prompt_mode_flag)
        self.assertIn(("hello", "assistant"), self.added)

    async def test_prompt_mode_resets_json_detector_after_success(self):
        agent = self.agent
        agent.prompt_mode_flag = True
        agent._mcp_prompt_string = ""
        agent._json_detector = StreamJSONDetector()
        agent._tool_manager = None
        agent._llm = _PromptModeLLM()
        agent._tool_executor = _PromptModeToolExecutor()

        _ = [item async for item in agent._openai_tool_interaction_loop([], [])]

        self.assertEqual(agent._json_detector.completed_jsons, [])
        self.assertNotIn("tool", agent._json_detector.buffer)


class _NativeToolLLM:
    def __init__(self):
        self.calls = 0
        self.messages = []

    def chat_completion(self, messages, _system, tools=None):
        self.calls += 1
        self.messages.append([dict(message) for message in messages])
        if self.calls == 1:

            async def tool_round():
                yield [
                    ToolCallObject(
                        id="call-1",
                        function=ToolCallFunctionObject(
                            name="tool", arguments='{"q": "x"}'
                        ),
                    )
                ]

            return tool_round()

        async def text_round():
            yield "done"

        return text_round()


class _PromptModeLLM:
    def __init__(self):
        self.calls = 0

    def chat_completion(self, _messages, _system, tools=None):
        self.calls += 1
        if self.calls == 1:

            async def tool_round():
                yield '{"name": "tool", "arguments": {}}'

            return tool_round()

        async def text_round():
            yield "hello"

        return text_round()


class _PromptModeToolExecutor:
    def process_tool_from_prompt_json(self, _detected):
        return []


class _UnsupportedToolsLLM:
    def __init__(self):
        self.calls = 0

    def chat_completion(self, _messages, _system, tools=None):
        self.calls += 1
        if self.calls == 1:

            async def unsupported():
                yield "__API_NOT_SUPPORT_TOOLS__"

            return unsupported()

        async def text_round():
            yield "hello"

        return text_round()


class _AlwaysToolLLM:
    """Native tool calls on every round, as a misbehaving model would."""

    def __init__(self):
        self.calls = 0

    def chat_completion(self, _messages, _system, tools=None):
        self.calls += 1

        async def tool_round():
            yield [
                ToolCallObject(
                    id=f"call-{self.calls}",
                    function=ToolCallFunctionObject(name="tool", arguments="{}"),
                )
            ]

        return tool_round()


class ToolLoopTerminationTests(unittest.IsolatedAsyncioTestCase):
    def _agent(self, llm, tool_executor):
        agent = BasicMemoryAgent.__new__(BasicMemoryAgent)
        agent._system = "system"
        agent.prompt_mode_flag = False
        agent._mcp_prompt_string = ""
        agent._json_detector = StreamJSONDetector()
        agent._tool_executor = tool_executor
        agent._llm = llm
        agent._add_message = lambda _content, _role: None
        return agent

    async def test_openai_loop_stops_without_tool_executor(self):
        llm = _AlwaysToolLLM()
        agent = self._agent(llm, None)

        items = [item async for item in agent._openai_tool_interaction_loop([], [])]

        self.assertEqual(llm.calls, 1)
        self.assertIn("not configured", items[-1])

    async def test_openai_loop_is_bounded(self):
        llm = _AlwaysToolLLM()
        agent = self._agent(llm, _ToolExecutor())

        items = [item async for item in agent._openai_tool_interaction_loop([], [])]

        self.assertEqual(llm.calls, DEFAULT_MAX_TOOL_ROUNDS)
        self.assertEqual(items[-1], TOOL_ROUND_LIMIT_NOTICE)

    async def test_configured_round_limit_is_used(self):
        llm = _AlwaysToolLLM()
        agent = self._agent(llm, _ToolExecutor())
        agent._max_tool_rounds = 3

        items = [item async for item in agent._openai_tool_interaction_loop([], [])]

        self.assertEqual(llm.calls, 3)
        self.assertEqual(items[-1], TOOL_ROUND_LIMIT_NOTICE)


class _ScriptedPromptLLM:
    """Replies with the given chunks, one list per round, recording requests."""

    def __init__(self, rounds):
        self.rounds = rounds
        self.requests = []

    def chat_completion(self, messages, system, tools=None):
        self.requests.append(([dict(m) for m in messages], system, tools))
        chunks = self.rounds[min(len(self.requests), len(self.rounds)) - 1]

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


class _PromptToolExecutor:
    def __init__(self, parsed):
        self.parsed = parsed

    def process_tool_from_prompt_json(self, _detected):
        return self.parsed

    async def execute_tools(self, tool_calls, caller_mode):
        yield {"type": "final_tool_results", "results": [{"content": "result"}]}


class PromptModeRoundTests(unittest.IsolatedAsyncioTestCase):
    TOOL_JSON = '{"mcp_server": "kb", "tool": "search", "arguments": {}}'

    def _agent(self, llm, tool_executor):
        agent = BasicMemoryAgent.__new__(BasicMemoryAgent)
        agent._system = "system"
        agent.prompt_mode_flag = True
        agent._mcp_prompt_string = "MCP"
        agent._json_detector = StreamJSONDetector()
        agent._tool_manager = None
        agent._tool_executor = tool_executor
        agent._llm = llm
        agent._add_message = lambda _content, _role: None
        return agent

    async def test_tool_call_response_is_kept_before_result(self):
        llm = _ScriptedPromptLLM([[self.TOOL_JSON], ["answer"]])
        executor = _PromptToolExecutor(
            [{"name": "search", "server": "kb", "args": {}, "id": "prompt_tool_0"}]
        )
        agent = self._agent(llm, executor)

        _ = [
            item
            async for item in agent._openai_tool_interaction_loop(
                [{"role": "user", "content": "hi"}], []
            )
        ]

        second_round = llm.requests[1][0]
        self.assertEqual(
            second_round[-2], {"role": "assistant", "content": self.TOOL_JSON}
        )
        self.assertEqual(second_round[-1], {"role": "user", "content": "result"})

    async def test_json_without_tool_call_ends_the_turn(self):
        llm = _ScriptedPromptLLM([['{"not": "a tool call"}']])
        agent = self._agent(llm, _PromptToolExecutor([]))

        items = [item async for item in agent._openai_tool_interaction_loop([], [])]

        self.assertEqual(len(llm.requests), 1)
        self.assertNotIn(TOOL_ROUND_LIMIT_NOTICE, items)


class _FakeToolManager:
    def get_formatted_tools(self, _mode):
        return [{"type": "function", "function": {"name": "search"}}]


class ToolModeSelectionTests(unittest.IsolatedAsyncioTestCase):
    def _agent(self, llm, **kwargs):
        return BasicMemoryAgent(
            llm=llm,
            system="system",
            live2d_model=None,
            use_mcpp=True,
            tool_manager=_FakeToolManager(),
            tool_executor=_PromptToolExecutor([]),
            mcp_prompt_string="MCP PROMPT",
            **kwargs,
        )

    @staticmethod
    def _openai_llm(support_tools):
        llm = OpenAICompatibleAsyncLLM.__new__(OpenAICompatibleAsyncLLM)
        llm.model = "m"
        llm.support_tools = support_tools
        scripted = _ScriptedPromptLLM([["hello"]])
        llm.chat_completion = scripted.chat_completion
        return llm, scripted

    async def _chat(self, agent):
        batch = BatchInput(texts=[TextData(source=TextSource.INPUT, content="hi")])
        return [item async for item in agent.chat(batch)]

    async def test_tools_unsupported_llm_starts_in_prompt_mode(self):
        llm, scripted = self._openai_llm(support_tools=False)
        agent = self._agent(llm)

        await self._chat(agent)

        _messages, system, tools = scripted.requests[0]
        self.assertTrue(agent.prompt_mode_flag)
        self.assertIn("MCP PROMPT", system)
        self.assertIsNone(tools)

    async def test_tools_supported_llm_starts_native(self):
        llm, scripted = self._openai_llm(support_tools=True)
        agent = self._agent(llm)

        await self._chat(agent)

        _messages, system, tools = scripted.requests[0]
        self.assertFalse(agent.prompt_mode_flag)
        self.assertNotIn("MCP PROMPT", system)
        self.assertEqual(tools, _FakeToolManager().get_formatted_tools("OpenAI"))


class McpComponentWarningTests(unittest.TestCase):
    def test_no_warning_when_mcp_disabled_without_components(self):
        warnings = []
        handler_id = logger.add(
            lambda message: warnings.append(str(message)), level="WARNING"
        )
        try:
            BasicMemoryAgent(llm=object(), system="s", live2d_model=None)
        finally:
            logger.remove(handler_id)

        self.assertFalse(any("MCP components" in w for w in warnings))


class MaxToolRoundsConfigTests(unittest.TestCase):
    def test_default_and_validation(self):
        config = BasicMemoryAgentConfig(llm_provider="openai_llm")
        self.assertEqual(config.max_tool_rounds, DEFAULT_MAX_TOOL_ROUNDS)
        with self.assertRaises(ValidationError):
            BasicMemoryAgentConfig(llm_provider="openai_llm", max_tool_rounds=0)

    def test_clone_for_session_keeps_limit(self):
        agent = BasicMemoryAgent(
            llm=object(), system="s", live2d_model=None, max_tool_rounds=4
        )

        clone = agent.clone_for_session(system="s")

        self.assertEqual(clone._max_tool_rounds, 4)


if __name__ == "__main__":
    unittest.main()
