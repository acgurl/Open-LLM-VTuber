import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, create_autospec

from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

from open_llm_vtuber.agent.agents.hume_ai import HumeAIAgent
from open_llm_vtuber.agent.input_types import BatchInput


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


def _agent_with_socket(state):
    agent = HumeAIAgent.__new__(HumeAIAgent)
    agent._connected = True
    agent._chat_group_id = "group"
    # Autospec the real websockets class so attribute drift (e.g. the removed
    # `.closed`) fails here instead of in production.
    agent._ws = create_autospec(ClientConnection, instance=True)
    agent._ws.state = state
    agent.connect = AsyncMock()
    return agent


class HumeConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_socket_is_reused(self):
        agent = _agent_with_socket(State.OPEN)

        await agent._ensure_connection()

        agent.connect.assert_not_awaited()

    async def test_closed_socket_reconnects_to_same_group(self):
        agent = _agent_with_socket(State.CLOSED)

        await agent._ensure_connection()

        agent.connect.assert_awaited_once_with("group")

    async def test_connection_closed_is_retried_only_once(self):
        agent = HumeAIAgent.__new__(HumeAIAgent)
        agent._connected = True
        attempts = []

        async def drop(_batch_input):
            attempts.append(True)
            raise ConnectionClosed(None, None)
            yield  # pragma: no cover - makes this an async generator

        agent._chat_once = drop

        with self.assertRaises(ConnectionClosed):
            async for _ in agent.chat(BatchInput(texts=[])):
                pass

        self.assertEqual(len(attempts), 2)
        self.assertFalse(agent._connected)

    async def test_connection_closed_after_output_is_not_resent(self):
        agent = HumeAIAgent.__new__(HumeAIAgent)
        attempts = []

        async def partial(_batch_input):
            attempts.append(True)
            yield "first"
            raise ConnectionClosed(None, None)

        agent._chat_once = partial

        received = []
        with self.assertRaises(ConnectionClosed):
            async for item in agent.chat(BatchInput(texts=[])):
                received.append(item)

        self.assertEqual(received, ["first"])
        self.assertEqual(len(attempts), 1)


class HumeCacheCleanupTests(unittest.TestCase):
    def test_cleanup_removes_only_files_this_agent_wrote(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            mine = cache / "evi_audio_mine.wav"
            other = cache / "evi_audio_other.wav"
            mine.write_bytes(b"a")
            other.write_bytes(b"b")
            agent = HumeAIAgent.__new__(HumeAIAgent)
            agent.cache_dir = cache
            agent._audio_files = {mine}

            agent.__del__()

            self.assertFalse(mine.exists())
            self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()
