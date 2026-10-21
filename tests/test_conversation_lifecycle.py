import asyncio
import contextlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber import websocket_handler as websocket_handler_module
    from open_llm_vtuber.conversations import conversation_handler
    from open_llm_vtuber.websocket_handler import WebSocketHandler
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class NoGroupManager:
    def __init__(self) -> None:
        self.client_group_map = {}

    def get_client_group(self, client_uid: str):
        return None


class FakeContext:
    def __init__(self) -> None:
        self.closed = False
        self.system_config = Mock()
        self.system_config.tool_prompts = {}

    async def close(self) -> None:
        self.closed = True


async def drain_task_queue() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


class ConversationTriggerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.pending_tasks = []
        self.websocket = FakeWebSocket()
        self.group_manager = NoGroupManager()

    async def asyncTearDown(self) -> None:
        for task in self.pending_tasks:
            if not task.done():
                task.cancel()
        if self.pending_tasks:
            await asyncio.gather(*self.pending_tasks, return_exceptions=True)

    def fill_tasks(self, tasks: dict, count: int) -> None:
        for index in range(count):
            task = asyncio.create_task(asyncio.Event().wait())
            self.pending_tasks.append(task)
            tasks[f"other-{index}"] = task

    async def trigger(self, msg_type: str, data: dict, tasks: dict, context=None):
        await conversation_handler.handle_conversation_trigger(
            msg_type=msg_type,
            data=data,
            client_uid="client",
            context=context or FakeContext(),
            websocket=self.websocket,
            client_contexts={},
            client_connections={},
            chat_group_manager=self.group_manager,
            received_data_buffers={},
            current_conversation_tasks=tasks,
            broadcast_to_group=AsyncMock(),
        )

    async def test_rejects_when_conversation_capacity_is_reached(self) -> None:
        tasks = {}
        self.fill_tasks(tasks, conversation_handler.MAX_CONCURRENT_CONVERSATIONS)

        await self.trigger(
            "text-input", {"type": "text-input", "text": "hello"}, tasks
        )

        self.assertEqual(
            self.websocket.sent,
            [
                {
                    "type": "error",
                    "message": "Server is busy, please try again shortly",
                }
            ],
        )
        self.assertNotIn("client", tasks)

    async def test_starts_conversation_below_capacity(self) -> None:
        tasks = {}
        self.fill_tasks(tasks, conversation_handler.MAX_CONCURRENT_CONVERSATIONS - 1)
        context = FakeContext()

        with patch.object(
            conversation_handler,
            "process_single_conversation",
            new=AsyncMock(),
        ) as process:
            await self.trigger(
                "text-input",
                {"type": "text-input", "text": "hello"},
                tasks,
                context,
            )
            await drain_task_queue()

        process.assert_awaited_once()
        kwargs = process.await_args.kwargs
        self.assertEqual(kwargs["user_input"], "hello")
        self.assertIs(kwargs["context"], context)
        self.assertIsNone(kwargs["metadata"])
        self.assertNotIn("client", tasks)
        self.assertEqual(self.websocket.sent, [])

    async def test_proactive_speak_sets_skip_metadata(self) -> None:
        context = FakeContext()
        context.system_config.tool_prompts = {"proactive_speak_prompt": "prompt.txt"}

        with patch.object(
            conversation_handler.prompt_loader,
            "load_util",
            return_value="Say hello",
        ) as load_prompt, patch.object(
            conversation_handler,
            "process_single_conversation",
            new=AsyncMock(),
        ) as process:
            await self.trigger(
                "ai-speak-signal", {"type": "ai-speak-signal"}, {}, context
            )
            await drain_task_queue()

        kwargs = process.await_args.kwargs
        self.assertEqual(kwargs["user_input"], "Say hello")
        self.assertEqual(
            kwargs["metadata"],
            {
                "proactive_speak": True,
                "skip_memory": True,
                "skip_history": True,
            },
        )
        self.assertEqual(
            self.websocket.sent,
            [{"type": "full-text", "text": "AI wants to speak something..."}],
        )
        load_prompt.assert_called_once_with("prompt.txt")


class ConnectionCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.handler = WebSocketHandler(default_context_cache=Mock())
        self.handler.chat_group_manager = NoGroupManager()
        self.context = FakeContext()
        self.task = None

    async def asyncSetUp(self) -> None:
        self.task = asyncio.create_task(asyncio.Event().wait())
        await asyncio.sleep(0)

    async def asyncTearDown(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    def seed_client(self, client_uid: str) -> None:
        self.handler.client_connections[client_uid] = FakeWebSocket()
        self.handler.client_contexts[client_uid] = self.context
        self.handler.received_data_buffers[client_uid] = np.array([])
        self.handler.current_conversation_tasks[client_uid] = self.task

    def assert_cleaned_up(self, client_uid: str) -> None:
        self.assertTrue(self.task.cancelled())
        self.assertTrue(self.context.closed)
        self.assertNotIn(client_uid, self.handler.client_contexts)
        self.assertNotIn(client_uid, self.handler.received_data_buffers)
        self.assertNotIn(client_uid, self.handler.current_conversation_tasks)

    async def test_failed_connection_cleanup_cancels_task_and_closes_context(self):
        self.seed_client("client")

        with patch.object(
            websocket_handler_module.message_handler, "cleanup_client"
        ) as cleanup:
            await self.handler._cleanup_failed_connection("client")

        self.assert_cleaned_up("client")
        cleanup.assert_called_once_with("client")

    async def test_disconnect_cleanup_cancels_task_and_closes_context(self):
        self.seed_client("client")

        with patch.object(
            websocket_handler_module, "handle_client_disconnect", new=AsyncMock()
        ), patch.object(
            websocket_handler_module.message_handler, "cleanup_client"
        ) as cleanup:
            await self.handler.handle_disconnect("client")

        self.assert_cleaned_up("client")
        cleanup.assert_called_once_with("client")


if __name__ == "__main__":
    unittest.main()
