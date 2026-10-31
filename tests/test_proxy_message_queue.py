import asyncio
import unittest

from open_llm_vtuber.proxy_message_queue import ProxyMessageQueue


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

    async def test_waits_for_conversation_to_finish_before_forwarding(self):
        queue = ProxyMessageQueue()
        calls = []

        async def forward(message, _sender_id):
            calls.append(message["text"])

        queue.initialize(forward)
        queue.conversation_active = True
        queue.queue_message({"type": "text-input", "text": "hi"}, "client")

        await asyncio.sleep(0.05)
        self.assertEqual(calls, [])

        queue.conversation_active = False
        for _ in range(20):
            if calls:
                break
            await asyncio.sleep(0.02)

        self.assertEqual(calls, ["hi", "hi"])
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
