import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from open_llm_vtuber.config_manager.connectors import ConnectorsConfig
from open_llm_vtuber.connectors import commands, dispatcher as dispatcher_module
from open_llm_vtuber.connectors.base import (
    Connector,
    ConnectorCapabilities,
    InboundMessage,
)
from open_llm_vtuber.connectors.binding import BindCodeStore
from open_llm_vtuber.connectors.dispatcher import ConnectorDispatcher
from open_llm_vtuber.storage import SQLiteHistoryRepository, UserHistoryStore


class _FakeConnector(Connector):
    platform = "fake"
    capabilities = ConnectorCapabilities(
        max_message_chars=200, max_replies_per_message=3
    )

    def __init__(self):
        super().__init__("qq", "QQ")
        self.sent: list[tuple[str, str, int]] = []

    async def run(self, on_message):
        raise NotImplementedError

    async def send_text(self, message, text, index):
        self.sent.append((message.message_id, text, index))

    def texts(self) -> list[str]:
        return [text for _, text, _ in self.sent]


class _FakeContext:
    """The parts of ServiceContext the dispatcher and run_agent_turn touch."""

    def __init__(self, repository, identity, channels):
        self.user_id = identity.user_id
        self.identity = identity
        self.channels = channels
        self.character_config = SimpleNamespace(
            conf_uid="conf", human_name="Human", character_name="AI", avatar=None
        )
        self.history = UserHistoryStore(repository, identity.user_id)
        self.history_uid = ""
        self.turn_history_uid = None
        self.turn_response_persisted = False
        self.live2d_model = SimpleNamespace(emo_map={"joy": 1}, motion_map={})
        self.agent_engine = SimpleNamespace(
            set_memory=AsyncMock(), handle_interrupt=Mock()
        )
        self.loaded: list[str] = []
        self.close = AsyncMock()

    async def load_history(self, history_uid):
        if not await self.history.history_exists("conf", history_uid):
            raise ValueError(history_uid)
        self.loaded.append(history_uid)
        self.history_uid = history_uid

    async def store_history_message(
        self, role, content, name=None, avatar=None, history_uid=None
    ):
        await self.history.store_message(
            "conf", history_uid, role=role, content=content
        )


def _message(
    text, *, message_id=None, chat_type="direct", sender="u:1", chat_id="dm-1"
):
    _message.counter += 1
    return InboundMessage(
        connector_id="qq",
        message_id=message_id or f"m{_message.counter}",
        chat_type=chat_type,
        chat_id=chat_id,
        sender_id=sender,
        sender_name="小A",
        text=text,
        reply_context={},
    )


_message.counter = 0


class ConnectorDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(Path(self._temp_dir.name) / "h.db")
        await self.repository.initialize()
        self.alice = await self.repository.resolve_user_identity(
            provider="https://sso.example",
            subject="alice",
            display_name="Alice",
            email="alice@cuc.edu.cn",
        )
        self.outsider = await self.repository.resolve_user_identity(
            provider="https://sso.example",
            subject="eve",
            display_name="Eve",
            email="eve@qq.com",
        )
        self.contexts: list[_FakeContext] = []
        self.builder_calls: list[dict] = []

        async def builder(default_context_cache, **kwargs):
            self.builder_calls.append(kwargs)
            context = _FakeContext(
                self.repository, kwargs["identity"], kwargs["channels"]
            )
            self.contexts.append(context)
            return context

        self.config = ConnectorsConfig(enabled=True, rate_limit_per_minute=3)
        self.codes = BindCodeStore()
        self.dispatcher = ConnectorDispatcher(
            SimpleNamespace(history_repository=self.repository),
            self.config,
            self.codes,
            session_builder=builder,
        )
        self.connector = _FakeConnector()
        self.turn_inputs: list[tuple[str, str | None]] = []

        async def fake_turn(context, *, input_text, turn_history_uid, **_kwargs):
            self.turn_inputs.append((input_text, turn_history_uid))
            await context.store_history_message(
                "human", input_text, history_uid=turn_history_uid
            )
            return f"[joy]收到：{input_text}"

        patcher = patch.object(dispatcher_module, "run_agent_turn", new=fake_turn)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        await self.dispatcher.close()
        await self.repository.close()
        self._temp_dir.cleanup()

    async def send(self, message):
        await self.dispatcher.handle(self.connector, message)
        await self.dispatcher.join()

    async def bind_alice(self):
        code, _ = self.codes.issue(self.alice)
        await self.send(_message(f"/bind {code}"))

    async def test_unbound_account_is_asked_to_bind_and_never_reaches_the_agent(self):
        await self.send(_message("你好"))
        self.assertEqual(self.connector.texts(), [commands.unbound_text("")])
        self.assertEqual(self.builder_calls, [])

    async def test_bind_then_chat_runs_as_the_bound_user(self):
        await self.bind_alice()
        self.assertEqual(self.connector.texts(), [commands.BIND_OK_TEXT])

        await self.send(_message("你好"))
        self.assertEqual(self.connector.texts()[-1], "收到：你好")
        call = self.builder_calls[0]
        self.assertEqual(call["identity"].user_id, self.alice)
        self.assertFalse(call["include_local_mcp"])

        history_uid = self.turn_inputs[0][1]
        self.assertTrue(history_uid)
        self.assertEqual(
            await self.repository.get_connector_conversation(
                connector_id="qq",
                chat_key="direct:dm-1",
                user_id=self.alice,
                conf_uid="conf",
            ),
            history_uid,
        )

    async def test_bind_is_refused_in_shared_channels(self):
        code, _ = self.codes.issue(self.alice)
        await self.send(_message(f"/bind {code}", chat_type="guild", chat_id="ch-1"))
        self.assertIn("私聊", self.connector.texts()[0])
        # The code was not consumed, so the owner can still use it privately.
        await self.send(_message(f"/bind {code}"))
        self.assertEqual(self.connector.texts()[-1], commands.BIND_OK_TEXT)

    async def test_account_without_campus_email_cannot_bind(self):
        code, _ = self.codes.issue(self.outsider)
        await self.send(_message(f"/bind {code}"))
        self.assertEqual(self.connector.texts(), [commands.INELIGIBLE_TEXT])
        self.assertIsNone(
            await self.repository.resolve_connector_identity(
                connector_id="qq", external_id="u:1"
            )
        )

    async def test_eligibility_is_rechecked_for_existing_bindings(self):
        await self.repository.bind_connector_identity(
            connector_id="qq", external_id="u:1", user_id=self.outsider
        )
        await self.send(_message("你好"))
        self.assertEqual(self.connector.texts(), [commands.INELIGIBLE_TEXT])
        self.assertEqual(self.turn_inputs, [])

    async def test_session_resumes_the_mapped_history_after_eviction(self):
        await self.bind_alice()
        await self.send(_message("第一句"))
        first_history = self.turn_inputs[0][1]

        await self.dispatcher.close_sender_sessions("qq", "u:1")
        await self.send(_message("第二句"))

        self.assertEqual(len(self.contexts), 2)
        self.assertEqual(self.contexts[1].loaded, [first_history])
        self.assertEqual(self.turn_inputs[1][1], first_history)
        self.contexts[0].close.assert_awaited()

    async def test_new_command_starts_a_fresh_history(self):
        await self.bind_alice()
        await self.send(_message("第一句"))
        await self.send(_message("/new"))
        await self.send(_message("第二句"))

        self.assertEqual(self.connector.texts()[2], commands.NEW_CHAT_TEXT)
        self.assertNotEqual(self.turn_inputs[0][1], self.turn_inputs[1][1])
        self.contexts[0].agent_engine.set_memory.assert_awaited_with([], {})

    async def test_unbind_closes_the_session(self):
        await self.bind_alice()
        await self.send(_message("你好"))
        await self.send(_message("/unbind"))
        self.assertEqual(self.connector.texts()[-1], commands.UNBIND_OK_TEXT)
        self.contexts[0].close.assert_awaited()
        await self.send(_message("还在吗"))
        self.assertEqual(self.connector.texts()[-1], commands.unbound_text(""))

    async def test_duplicate_deliveries_are_handled_once(self):
        await self.bind_alice()
        await self.send(_message("你好", message_id="same"))
        await self.send(_message("你好", message_id="same"))
        self.assertEqual(len(self.turn_inputs), 1)

    async def test_rate_limit_per_account(self):
        await self.bind_alice()
        for index in range(4):
            await self.send(_message(f"消息{index}"))
        self.assertEqual(len(self.turn_inputs), 3)
        self.assertEqual(self.connector.texts()[-1], commands.RATE_LIMITED_TEXT)

    async def test_overlong_message_is_rejected(self):
        await self.bind_alice()
        await self.send(_message("长" * (self.config.max_input_chars + 1)))
        self.assertEqual(self.connector.texts()[-1], commands.TOO_LONG_TEXT)
        self.assertEqual(self.turn_inputs, [])

    async def test_timeout_resets_the_agent_turn(self):
        await self.bind_alice()
        self.config.reply_timeout_seconds = 0.05

        async def slow_turn(context, **_kwargs):
            await asyncio.sleep(1)
            return "太晚了"

        with patch.object(dispatcher_module, "run_agent_turn", new=slow_turn):
            await self.send(_message("你好"))

        self.assertEqual(self.connector.texts()[-1], commands.TIMEOUT_TEXT)
        self.contexts[0].agent_engine.handle_interrupt.assert_called_once_with("")

    async def test_messages_of_one_chat_run_in_order(self):
        await self.bind_alice()
        order = []

        async def ordered_turn(context, *, input_text, **_kwargs):
            order.append(f"start {input_text}")
            await asyncio.sleep(0.01)
            order.append(f"end {input_text}")
            return input_text

        with patch.object(dispatcher_module, "run_agent_turn", new=ordered_turn):
            await self.dispatcher.handle(self.connector, _message("一"))
            await self.dispatcher.handle(self.connector, _message("二"))
            await self.dispatcher.join()

        self.assertEqual(order, ["start 一", "end 一", "start 二", "end 二"])


class HeadlessSessionContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_headless_sessions_get_remote_but_not_local_user_mcp(self):
        from open_llm_vtuber import session_factory
        from open_llm_vtuber.auth import Identity
        from open_llm_vtuber.service_context import ServiceContext

        default_context = SimpleNamespace(
            history_repository=AsyncMock(),
            config=Mock(),
            system_config=Mock(),
            character_config=Mock(),
            live2d_model=None,
            asr_engine=None,
            tts_engine=None,
            agent_engine=None,
            translate_engine=None,
            mcp_server_registry=None,
            tool_adapter=None,
        )
        remote, local = [{"id": "r"}], [{"id": "l"}]
        with (
            patch.object(
                session_factory,
                "load_user_mcp_servers",
                new=AsyncMock(return_value=(remote, local)),
            ),
            patch.object(ServiceContext, "load_cache", new=AsyncMock()) as load_cache,
            patch.object(ServiceContext, "init_session_agent", new=AsyncMock()),
        ):
            await session_factory.build_session_context(
                default_context,
                channels=None,
                client_uid="connector-x",
                identity=Identity("alice", "Alice"),
                include_local_mcp=False,
            )

        kwargs = load_cache.await_args.kwargs
        self.assertEqual(kwargs["user_id"], "alice")
        self.assertEqual(kwargs["user_mcp_servers"], remote)
        self.assertEqual(kwargs["local_mcp_servers"], [])


if __name__ == "__main__":
    unittest.main()
