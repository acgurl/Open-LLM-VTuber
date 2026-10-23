import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
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


if __name__ == "__main__":
    unittest.main()
