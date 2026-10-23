import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
    from open_llm_vtuber.mcpp.json_detector import StreamJSONDetector
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


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


if __name__ == "__main__":
    unittest.main()
