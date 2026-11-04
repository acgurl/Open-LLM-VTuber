import asyncio
import datetime
import json
import re
import unittest
from pathlib import Path
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


class StatusTimestampTests(unittest.TestCase):
    def test_timestamp_is_valid_utc_iso_string(self):
        timestamp = ToolExecutor._tool_status("id", "tool", "running", "")["timestamp"]

        self.assertTrue(timestamp.endswith("Z"))
        self.assertNotIn("+00:00", timestamp)
        parsed = datetime.datetime.fromisoformat(timestamp[:-1] + "+00:00")
        self.assertEqual(parsed.utcoffset(), datetime.timedelta(0))


class PromptJsonParsingTests(unittest.TestCase):
    def setUp(self):
        self.executor = object.__new__(ToolExecutor)

    def _parse(self, arguments):
        return self.executor.process_tool_from_prompt_json(
            [{"mcp_server": "kb", "tool": "search", "arguments": arguments}]
        )

    def test_object_arguments_are_accepted(self):
        parsed = self._parse({"query": "x"})

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "search")
        self.assertEqual(parsed[0]["args"], {"query": "x"})

    def test_json_string_arguments_are_accepted(self):
        self.assertEqual(self._parse('{"query": "x"}')[0]["args"], {"query": "x"})

    def test_empty_arguments_are_accepted(self):
        self.assertEqual(self._parse({})[0]["args"], {})
        self.assertEqual(self._parse(None)[0]["args"], {})

    def test_malformed_arguments_are_skipped(self):
        self.assertEqual(self._parse("{not json"), [])
        self.assertEqual(self._parse([1, 2]), [])

    def test_missing_server_or_tool_is_skipped(self):
        parsed = self.executor.process_tool_from_prompt_json(
            [{"tool": "search", "arguments": {}}, "not a dict"]
        )

        self.assertEqual(parsed, [])


class McpPromptTemplateTests(unittest.TestCase):
    """The prompt-mode example must stay valid JSON the parser accepts."""

    def test_example_json_parses_into_a_tool_call(self):
        prompt_path = (
            Path(__file__).resolve().parents[1] / "prompts" / "utils" / "mcp_prompt.txt"
        )
        text = prompt_path.read_text(encoding="utf-8")
        example = re.search(r"### JSON Response Format:\s*(\{.*?\n\})", text, re.S)
        self.assertIsNotNone(example)

        data = json.loads(example.group(1).replace("<value>", "1"))
        parsed = object.__new__(ToolExecutor).process_tool_from_prompt_json([data])

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "<tool_name>")


if __name__ == "__main__":
    unittest.main()
