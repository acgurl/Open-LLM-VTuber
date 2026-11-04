"""Locking tests for conversation / WebSocket defects (audit car C3)."""

import asyncio
import contextlib
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from open_llm_vtuber.agent.output_types import Actions, DisplayText, SentenceOutput

from open_llm_vtuber.chat_group import ChatGroupManager, broadcast_to_group
from open_llm_vtuber.conversations import conversation_handler
from open_llm_vtuber.conversations import conversation_utils
from open_llm_vtuber.conversations import group_conversation
from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from open_llm_vtuber.conversations.types import (
    GroupConversationState,
    OutboundChannels,
)
from open_llm_vtuber.message_handler import MessageHandler
from open_llm_vtuber.proxy_handler import ProxyHandler
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.websocket_handler import WebSocketHandler


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _never_ending_task() -> asyncio.Task:
    return asyncio.create_task(asyncio.Event().wait())


class GroupRemovalInterruptTests(unittest.IsolatedAsyncioTestCase):
    """D-GRP1: removing a member stops the running group conversation."""

    async def asyncSetUp(self) -> None:
        self.handler = WebSocketHandler(default_context_cache=Mock())
        manager = ChatGroupManager()
        self.handler.chat_group_manager = manager
        for uid in ("owner", "guest", "other"):
            manager.client_group_map[uid] = ""
            self.handler.client_connections[uid] = FakeWebSocket()
        manager.add_client_to_group("owner", "guest")
        self.group_id = manager.get_client_group("owner").group_id
        self.task = _never_ending_task()
        self.handler.current_conversation_tasks[self.group_id] = self.task
        await asyncio.sleep(0)

    async def asyncTearDown(self) -> None:
        if not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def remove(self, remover: str, target: str) -> None:
        await self.handler._handle_group_operation(
            self.handler.client_connections[remover],
            remover,
            {"type": "remove-client-from-group", "target_uid": target},
        )

    async def test_dissolving_the_group_cancels_its_conversation(self):
        await self.remove("owner", "guest")

        self.assertIsNone(
            self.handler.chat_group_manager.get_group_by_id(self.group_id)
        )
        self.assertTrue(self.task.cancelled())
        self.assertNotIn(self.group_id, self.handler.current_conversation_tasks)

    async def test_leaving_the_group_cancels_its_conversation(self):
        await self.remove("guest", "guest")

        self.assertTrue(self.task.cancelled())

    async def test_unauthorized_removal_leaves_the_conversation_running(self):
        manager = self.handler.chat_group_manager
        manager.add_client_to_group("owner", "other")

        await self.remove("other", "guest")

        await asyncio.sleep(0)
        self.assertFalse(self.task.done())
        self.assertIn("guest", manager.get_group_by_id(self.group_id).members)


class SharedGroupManager:
    def __init__(self):
        self.group = SimpleNamespace(
            group_id="group-owner",
            owner_uid="owner",
            members={"owner", "guest"},
        )

    def get_client_group(self, _client_uid):
        return self.group


class GroupMemberSnapshotTests(unittest.IsolatedAsyncioTestCase):
    """D-GRP2: group members are snapshotted before crossing awaits."""

    async def test_group_task_gets_a_snapshot_of_the_members(self):
        manager = SharedGroupManager()

        with patch.object(
            conversation_handler,
            "process_group_conversation",
            new=AsyncMock(),
        ) as process:
            await conversation_handler.handle_conversation_trigger(
                msg_type="text-input",
                data={"type": "text-input", "text": "hello"},
                client_uid="guest",
                context=SimpleNamespace(channels=None),
                websocket=FakeWebSocket(),
                client_contexts={},
                client_connections={},
                chat_group_manager=manager,
                received_data_buffers={},
                current_conversation_tasks={},
                broadcast_to_group=AsyncMock(),
            )
            for _ in range(3):
                await asyncio.sleep(0)

        members = process.await_args.kwargs["group_members"]
        self.assertIsNot(members, manager.group.members)
        self.assertEqual(set(members), {"owner", "guest"})

    async def test_broadcast_survives_membership_change_during_send(self):
        manager = ChatGroupManager()
        for uid in "ABC":
            manager.client_group_map[uid] = ""
        manager.add_client_to_group("A", "B")
        manager.add_client_to_group("A", "C")
        live_members = manager.get_client_group("A").members

        class SlowWebSocket:
            async def send_text(self, _data):
                await asyncio.sleep(0.01)

        async def remove_member():
            await asyncio.sleep(0.005)
            manager.remove_client_from_group("C", "C")

        connections = {uid: SlowWebSocket() for uid in "ABC"}
        await asyncio.gather(
            broadcast_to_group(live_members, {"type": "t"}, connections),
            remove_member(),
        )


class GroupMemberTurnFinalizeTests(unittest.IsolatedAsyncioTestCase):
    """D-GRP3: every member turn ends with the closing frames."""

    def setUp(self) -> None:
        self.state = GroupConversationState(
            group_id="group-test",
            conversation_history=["Human: hi"],
            memory_index={"owner": 0, "guest": 0},
            group_queue=[],
        )
        self.context = SimpleNamespace(
            channels=None,
            character_config=SimpleNamespace(character_name="AI", avatar=""),
            history_uid=None,
            store_history_message=AsyncMock(),
        )
        self.owner_ws = FakeWebSocket()
        self.broadcast = AsyncMock()

    def tearDown(self) -> None:
        GroupConversationState.remove_state("group-test")

    async def run_turn(self, tts_manager: TTSTaskManager) -> None:
        with (
            patch.object(
                group_conversation,
                "process_member_response",
                new=AsyncMock(return_value="text only"),
            ),
            patch.object(
                conversation_utils.message_handler,
                "wait_for_response",
                new=AsyncMock(return_value={}),
            ),
        ):
            await group_conversation.handle_group_member_turn(
                current_member_uid="owner",
                state=self.state,
                client_contexts={"owner": self.context, "guest": self.context},
                client_connections={"owner": self.owner_ws},
                broadcast_func=self.broadcast,
                group_members=["owner", "guest"],
                images=None,
                tts_manager=tts_manager,
            )

    async def test_turn_without_tts_still_sends_closing_frames(self):
        await self.run_turn(TTSTaskManager())

        sent = [(m["type"], m.get("text")) for m in self.owner_ws.sent]
        self.assertIn(("force-new-message", None), sent)
        self.assertIn(("control", "conversation-chain-end"), sent)
        broadcast = [
            (call.args[1]["type"], call.args[1].get("text"))
            for call in self.broadcast.await_args_list
        ]
        self.assertIn(("force-new-message", None), broadcast)
        self.assertIn(("control", "conversation-chain-end"), broadcast)

    async def test_finished_tts_tasks_are_dropped_after_the_turn(self):
        tts_manager = TTSTaskManager()
        done = asyncio.create_task(asyncio.sleep(0))
        await done
        tts_manager.task_list.append(done)

        await self.run_turn(tts_manager)

        self.assertEqual(tts_manager.task_list, [])


class TranslateDisableTests(unittest.TestCase):
    """D-CTX1: disabling translation drops the previous engine."""

    def test_disabled_translation_clears_the_old_engine(self):
        context = ServiceContext()
        context.translate_engine = Mock(name="old_translator")

        context.init_translate(SimpleNamespace(translate_audio=False))

        self.assertIsNone(context.translate_engine)


class MessageHandlerCleanupTests(unittest.IsolatedAsyncioTestCase):
    """D-WS1: a waiter must not re-create entries for a cleaned-up client."""

    async def test_waiter_does_not_resurrect_cleaned_up_client(self):
        handler = MessageHandler()
        waiter = asyncio.create_task(
            handler.wait_for_response("c1", "frontend-playback-complete", timeout=5)
        )
        await asyncio.sleep(0)

        handler.cleanup_client("c1")

        self.assertIsNone(await waiter)
        self.assertNotIn("c1", handler._response_events)
        self.assertNotIn("c1", handler._response_data)


class IndividualInterruptOrderingTests(unittest.IsolatedAsyncioTestCase):
    """D-WS2: the running task is fully stopped before its state is read."""

    async def test_reply_persisted_while_cancelling_is_not_stored_twice(self):
        context = SimpleNamespace(
            agent_engine=Mock(),
            history_uid="history",
            turn_history_uid="history",
            turn_response_persisted=False,
            character_config=SimpleNamespace(character_name="AI", avatar=""),
            store_history_message=AsyncMock(),
        )

        async def turn():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # The reply write was already in flight and completes while
                # the task unwinds.
                await asyncio.sleep(0)
                context.turn_response_persisted = True
                raise

        task = asyncio.create_task(turn())
        await asyncio.sleep(0)

        await conversation_handler.handle_individual_interrupt(
            "client", {"client": task}, context, "heard part"
        )

        self.assertTrue(task.done())
        context.store_history_message.assert_not_awaited()
        context.agent_engine.handle_interrupt.assert_not_called()


class _SentenceAgent:
    def chat(self, _batch_input):
        async def stream():
            yield SentenceOutput(
                display_text=DisplayText(text="full reply"),
                tts_text="full reply",
                actions=Actions(),
            )

        return stream()


class InterruptDuringReplyWriteTests(unittest.IsolatedAsyncioTestCase):
    """D-WS2: interrupting while the reply write is in a worker thread."""

    async def test_reply_is_stored_exactly_once(self):
        stored = []
        write_started = threading.Event()
        release_write = threading.Event()
        blocked_once = []

        def blocking_write(role, content):
            if role == "ai" and not blocked_once:
                blocked_once.append(True)
                write_started.set()
                release_write.wait(5)
            stored.append((role, content))

        async def store(role, content, name=None, avatar=None, history_uid=None):
            await asyncio.to_thread(blocking_write, role, content)

        context = SimpleNamespace(
            character_config=SimpleNamespace(
                character_name="AI", avatar="", human_name="Human"
            ),
            agent_engine=_SentenceAgent(),
            live2d_model=None,
            tts_engine=None,
            translate_engine=None,
            history_uid="history",
            turn_history_uid="history",
            turn_response_persisted=False,
            store_history_message=store,
        )
        turn = asyncio.create_task(
            conversation_utils.run_agent_turn(
                context,
                channels=OutboundChannels(text=AsyncMock(), audio=AsyncMock()),
                tts_manager=None,
                input_text="hi",
                turn_history_uid="history",
            )
        )
        try:
            self.assertTrue(await asyncio.to_thread(write_started.wait, 5))

            interrupt = asyncio.create_task(
                conversation_handler.handle_individual_interrupt(
                    "client", {"client": turn}, context, "full"
                )
            )
            await asyncio.sleep(0.05)
            release_write.set()
            await asyncio.wait_for(interrupt, timeout=5)
            for _ in range(100):
                if any(content == "full reply" for _, content in stored):
                    break
                await asyncio.sleep(0.01)
        finally:
            release_write.set()
            if not turn.done():
                turn.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await turn

        self.assertTrue(turn.cancelled())
        self.assertEqual(
            [entry for entry in stored if entry[0] != "human"],
            [("ai", "full reply")],
        )
        self.assertTrue(context.turn_response_persisted)


class _FakeServerWebSocket:
    def __init__(self, frames, on_receive) -> None:
        self._frames = list(frames)
        self._on_receive = on_receive
        self.closed = False
        self.sent = []

    async def receive(self):
        self._on_receive()
        if self._frames:
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT, data=json.dumps(self._frames.pop(0))
            )
        self.closed = True
        return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=None)

    async def send_json(self, message) -> None:
        self.sent.append(message)


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    """D-PRX1 / D-PRX2."""

    async def test_broadcast_survives_client_joining_during_send(self):
        handler = ProxyHandler("ws://localhost/client-ws")

        class JoiningWebSocket:
            async def send_json(self, _message):
                handler.clients["late"] = FakeWebSocket()
                await asyncio.sleep(0)

        handler.clients["first"] = JoiningWebSocket()

        await handler.broadcast_to_clients({"type": "full-text", "text": "hi"})

        self.assertIn("late", handler.clients)

    async def test_error_frame_releases_the_queue(self):
        handler = ProxyHandler("ws://localhost/client-ws")
        handler.connected = True
        handler.message_queue.conversation_active = True
        observed = []
        handler.server_ws = _FakeServerWebSocket(
            [{"type": "error", "message": "Server is busy, please try again shortly"}],
            lambda: observed.append(handler.message_queue.conversation_active),
        )

        await handler.forward_server_messages()

        # Second receive happens after the error frame was handled.
        self.assertEqual(observed[:2], [True, False])

    async def test_transcription_is_broadcast_but_not_sent_to_server(self):
        handler = ProxyHandler("ws://localhost/client-ws")
        handler.forward_to_server = AsyncMock()
        sender, other = FakeWebSocket(), FakeWebSocket()
        handler.clients = {"sender": sender, "other": other}

        await handler.forward_with_broadcast(
            {"type": "user-input-transcription", "text": "hi"}, "sender"
        )

        handler.forward_to_server.assert_not_awaited()
        self.assertEqual(
            other.sent, [{"type": "user-input-transcription", "text": "hi"}]
        )
        self.assertEqual(sender.sent, [])


class TranslateOffLoopTests(unittest.IsolatedAsyncioTestCase):
    """P-TR1: synchronous translators run off the event loop thread."""

    async def test_translate_runs_in_a_worker_thread(self):
        loop_thread = threading.get_ident()
        translate_threads = []

        def translate(text):
            translate_threads.append(threading.get_ident())
            return f"translated {text}"

        translate_engine = Mock()
        translate_engine.translate.side_effect = translate
        tts_manager = Mock()
        tts_manager.speak = AsyncMock()

        async def output():
            yield SimpleNamespace(text="hello"), "hello", None

        await conversation_utils.handle_sentence_output(
            output(),
            live2d_model=None,
            tts_engine=Mock(),
            channels=OutboundChannels(text=AsyncMock(), audio=AsyncMock()),
            tts_manager=tts_manager,
            translate_engine=translate_engine,
        )

        self.assertEqual(len(translate_threads), 1)
        self.assertNotEqual(translate_threads[0], loop_thread)
        self.assertEqual(
            tts_manager.speak.await_args.kwargs["tts_text"], "translated hello"
        )


if __name__ == "__main__":
    unittest.main()
