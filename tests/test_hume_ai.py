import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.agents.hume_ai import HumeAIAgent
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class HumeBackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawn_tracks_background_task(self):
        agent = HumeAIAgent.__new__(HumeAIAgent)
        agent._background_tasks = set()
        completed = []

        async def work():
            completed.append(True)

        agent._spawn(work())
        await asyncio.sleep(0.01)

        self.assertEqual(completed, [True])
        self.assertEqual(agent._background_tasks, set())

    async def test_close_releases_websocket(self):
        agent = HumeAIAgent.__new__(HumeAIAgent)
        agent._background_tasks = set()
        agent._idle_timer = None
        agent._connected = True
        ws = Mock()
        ws.close = AsyncMock()
        agent._ws = ws

        await agent.close()

        ws.close.assert_awaited_once()
        self.assertIsNone(agent._ws)
        self.assertFalse(agent._connected)


if __name__ == "__main__":
    unittest.main()
