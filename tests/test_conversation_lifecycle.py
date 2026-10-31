import asyncio
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from open_llm_vtuber import websocket_handler as websocket_handler_module
from open_llm_vtuber.conversations import conversation_handler
from open_llm_vtuber.websocket_handler import WebSocketHandler


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []
        self.closed = False

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


class NoGroupManager:
    def __init__(self) -> None:
        self.client_group_map = {}

    def get_client_group(self, client_uid: str):
        return None


class FakeContext:
    def __init__(self) -> None:
        self.closed = False
        self.channels = None
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

        await self.trigger("text-input", {"type": "text-input", "text": "hello"}, tasks)

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

        with (
            patch.object(
                conversation_handler.prompt_loader,
                "load_util",
                return_value="Say hello",
            ) as load_prompt,
            patch.object(
                conversation_handler,
                "process_single_conversation",
                new=AsyncMock(),
            ) as process,
        ):
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


class SharedGroupManager:
    def __init__(self):
        self.group = SimpleNamespace(
            group_id="group-owner",
            owner_uid="owner",
            members={"owner", "guest"},
        )

    def get_client_group(self, _client_uid):
        return self.group


class GroupConversationTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_trigger_passes_the_real_group_id(self):
        manager = SharedGroupManager()
        tasks = {}
        websocket = FakeWebSocket()

        with patch.object(
            conversation_handler,
            "process_group_conversation",
            new=AsyncMock(),
        ) as process:
            await conversation_handler.handle_conversation_trigger(
                msg_type="text-input",
                data={"type": "text-input", "text": "hello"},
                client_uid="guest",
                context=FakeContext(),
                websocket=websocket,
                client_contexts={},
                client_connections={},
                chat_group_manager=manager,
                received_data_buffers={},
                current_conversation_tasks=tasks,
                broadcast_to_group=AsyncMock(),
            )
            await drain_task_queue()

        kwargs = process.await_args.kwargs
        self.assertEqual(kwargs["group_id"], "group-owner")
        self.assertEqual(kwargs["initiator_client_uid"], "guest")


def _interrupt_context():
    return SimpleNamespace(
        agent_engine=Mock(),
        history_uid="history",
        character_config=SimpleNamespace(
            conf_uid="conf", character_name="AI", avatar=""
        ),
        store_history_message=AsyncMock(),
    )


class InterruptHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_individual_interrupt_stores_nothing(self):
        context = _interrupt_context()
        tasks = {"client": None}

        await conversation_handler.handle_individual_interrupt(
            "client", tasks, context, ""
        )

        context.store_history_message.assert_not_awaited()

    async def test_partial_individual_interrupt_stores_ai_and_marker(self):
        context = _interrupt_context()
        tasks = {"client": None}

        await conversation_handler.handle_individual_interrupt(
            "client", tasks, context, "partial answer"
        )

        self.assertEqual(
            [
                call.kwargs["role"]
                for call in context.store_history_message.await_args_list
            ],
            ["ai", "system"],
        )
        self.assertEqual(
            {
                call.kwargs.get("history_uid")
                for call in context.store_history_message.await_args_list
            },
            {"history"},
        )

    async def test_completed_turn_interrupt_keeps_the_stored_reply(self):
        context = _interrupt_context()
        context.turn_response_persisted = True
        context.turn_history_uid = "history"

        await conversation_handler.handle_individual_interrupt(
            "client", {"client": None}, context, "heard part"
        )

        context.store_history_message.assert_not_awaited()
        context.agent_engine.handle_interrupt.assert_not_called()

    async def test_partial_interrupt_writes_to_the_turn_history(self):
        context = _interrupt_context()
        context.history_uid = "history-b"
        context.turn_history_uid = "history-a"

        await conversation_handler.handle_individual_interrupt(
            "client", {"client": None}, context, "partial answer"
        )

        self.assertEqual(
            [
                call.kwargs.get("history_uid")
                for call in context.store_history_message.await_args_list
            ],
            ["history-a", "history-a"],
        )

    async def test_proactive_interrupt_writes_nothing(self):
        context = _interrupt_context()
        context.turn_history_uid = None

        await conversation_handler.handle_individual_interrupt(
            "client", {"client": None}, context, "heard part"
        )

        context.store_history_message.assert_not_awaited()

    async def test_empty_group_interrupt_stores_nothing(self):
        task = asyncio.create_task(asyncio.Event().wait())
        tasks = {"group": task}
        context = _interrupt_context()
        manager = Mock()
        manager.get_group_by_id.return_value = SimpleNamespace(members={"client"})

        await conversation_handler.handle_group_interrupt(
            group_id="group",
            heard_response="",
            current_conversation_tasks=tasks,
            chat_group_manager=manager,
            client_contexts={"client": context},
            broadcast_to_group=AsyncMock(),
        )

        context.store_history_message.assert_not_awaited()
        self.assertTrue(task.cancelled())


class GroupInterruptMissingGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_group_skips_broadcast(self):
        task = asyncio.create_task(asyncio.Event().wait())
        tasks = {"group": task}
        manager = Mock()
        manager.get_group_by_id.return_value = None
        broadcast = AsyncMock()

        await conversation_handler.handle_group_interrupt(
            group_id="group",
            heard_response="",
            current_conversation_tasks=tasks,
            chat_group_manager=manager,
            client_contexts={},
            broadcast_to_group=broadcast,
        )

        self.assertTrue(task.cancelled())
        self.assertNotIn("group", tasks)
        broadcast.assert_not_awaited()


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
        self.audio_websocket = FakeWebSocket()
        self.handler.client_connections[client_uid] = FakeWebSocket()
        self.handler.client_audio_connections[client_uid] = self.audio_websocket
        self.handler.client_contexts[client_uid] = self.context
        self.handler.received_data_buffers[client_uid] = np.array([])
        self.handler.current_conversation_tasks[client_uid] = self.task

    def assert_cleaned_up(self, client_uid: str) -> None:
        self.assertTrue(self.task.cancelled())
        self.assertTrue(self.context.closed)
        self.assertTrue(self.audio_websocket.closed)
        self.assertNotIn(client_uid, self.handler.client_contexts)
        self.assertNotIn(client_uid, self.handler.client_audio_connections)
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

        with (
            patch.object(
                websocket_handler_module, "handle_client_disconnect", new=AsyncMock()
            ),
            patch.object(
                websocket_handler_module.message_handler, "cleanup_client"
            ) as cleanup,
        ):
            await self.handler.handle_disconnect("client")

        self.assert_cleaned_up("client")
        cleanup.assert_called_once_with("client")


if __name__ == "__main__":
    unittest.main()
