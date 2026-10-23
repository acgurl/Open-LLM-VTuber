import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.proxy_message_queue import ProxyMessageQueue
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ProxyMessageQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_forward_task_is_tracked_and_completes(self):
        queue = ProxyMessageQueue()
        calls = []

        async def forward(message, sender_id):
            calls.append((message["type"], sender_id))

        queue.initialize(forward)
        queue.queue_message({"type": "text-input", "text": "hi"}, "client")

        for _ in range(40):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(
            calls,
            [("user-input-transcription", "client"), ("text-input", "client")],
        )
        self.assertEqual(queue._forward_tasks, set())
        queue.stop()

    async def test_stop_cancels_in_flight_forward(self):
        queue = ProxyMessageQueue()
        started = asyncio.Event()

        async def forward(_message, _sender_id):
            started.set()
            await asyncio.Event().wait()

        queue.initialize(forward)
        queue.queue_message({"type": "text-input", "text": "hi"}, "client")
        await asyncio.wait_for(started.wait(), timeout=1.0)
        self.assertTrue(queue._forward_tasks)

        queue.stop()
        await asyncio.sleep(0.01)

        self.assertEqual(queue._forward_tasks, set())


if __name__ == "__main__":
    unittest.main()
