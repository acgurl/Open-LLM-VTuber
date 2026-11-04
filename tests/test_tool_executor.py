import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_llm_vtuber.mcpp import tool_executor as tool_executor_module
from open_llm_vtuber.mcpp.tool_executor import ToolExecutor, ToolRunResult


class ToolStatusTests(unittest.TestCase):
    def test_status_payload_includes_extra_fields(self):
        status = ToolExecutor._tool_status(
            "id", "tool", "completed", "done", browser_view={"url": "x"}
        )

        self.assertEqual(status["type"], "tool_call_status")
        self.assertEqual(status["tool_id"], "id")
        self.assertEqual(status["tool_name"], "tool")
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["content"], "done")
        self.assertEqual(status["browser_view"], {"url": "x"})
        self.assertTrue(status["timestamp"].endswith("Z"))

    def test_claude_gets_image_blocks(self):
        status_content, llm_content = ToolExecutor._split_image_content(
            "Claude",
            "look",
            [{"type": "image", "data": "abc", "mimeType": "image/png"}],
        )

        self.assertEqual(status_content, "look\n[Tool returned 1 image(s)]")
        self.assertEqual(
            llm_content,
            [
                {"type": "text", "text": "look"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "abc",
                    },
                },
            ],
        )

    def test_openai_uses_text_with_image_count(self):
        status_content, llm_content = ToolExecutor._split_image_content(
            "OpenAI",
            "look",
            [{"type": "image", "data": "abc", "mimeType": "image/png"}],
        )

        self.assertEqual(status_content, llm_content)
        self.assertIn("1 image(s)", llm_content)

    def test_text_only_content_is_unchanged(self):
        self.assertEqual(
            ToolExecutor._split_image_content("Claude", "plain", []),
            ("plain", "plain"),
        )


class ExecuteToolsConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def _make_executor(self, run_single_tool):
        executor = object.__new__(ToolExecutor)
        executor.parse_tool_call = lambda call: call
        executor._scoped_status_extra = lambda tool_name: {}
        executor._log_tool_start = lambda *args: None
        executor.run_single_tool = run_single_tool
        executor.format_tool_result = lambda caller_mode, tool_id, content, is_error: {
            "tool_use_id": tool_id,
            "content": content,
        }
        return executor

    @staticmethod
    def _call(name, tool_id):
        return SimpleNamespace(
            tool_name=name, tool_id=tool_id, tool_input={}, parse_error=None
        )

    async def test_tools_from_one_turn_run_concurrently(self):
        second_started = asyncio.Event()

        async def run_single_tool(name, tool_id, tool_input):
            # "slow" cannot finish until "fast" has started, so a serial
            # executor would hit the timeout here instead.
            if name == "slow":
                await asyncio.wait_for(second_started.wait(), timeout=2)
            else:
                second_started.set()
            return ToolRunResult(False, name, {}, [{"type": "text", "text": name}])

        executor = self._make_executor(run_single_tool)
        calls = [self._call("slow", "slow-id"), self._call("fast", "fast-id")]

        updates = [update async for update in executor.execute_tools(calls, "Claude")]

        completed = [
            update["tool_id"]
            for update in updates
            if update.get("status") == "completed"
        ]
        # Statuses follow finish order; LLM results keep the call order.
        self.assertEqual(completed, ["fast-id", "slow-id"])
        self.assertEqual(
            [result["tool_use_id"] for result in updates[-1]["results"]],
            ["slow-id", "fast-id"],
        )

    async def test_concurrency_is_capped(self):
        in_flight = 0
        peak = 0

        async def run_single_tool(name, tool_id, tool_input):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return ToolRunResult(False, name, {}, [{"type": "text", "text": name}])

        executor = self._make_executor(run_single_tool)
        calls = [self._call(f"t{i}", f"id-{i}") for i in range(5)]

        with patch.object(tool_executor_module, "MAX_CONCURRENT_TOOL_CALLS", 2):
            updates = [
                update async for update in executor.execute_tools(calls, "OpenAI")
            ]

        self.assertEqual(peak, 2)
        self.assertEqual(
            [result["tool_use_id"] for result in updates[-1]["results"]],
            [f"id-{i}" for i in range(5)],
        )


if __name__ == "__main__":
    unittest.main()
