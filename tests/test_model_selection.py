import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from open_llm_vtuber import llm_catalog
from open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
from open_llm_vtuber.llm_catalog import MODEL_SETTING_KEY, LLMModelCatalog
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.storage import SQLiteHistoryRepository
from open_llm_vtuber.websocket_handler import WebSocketHandler

CATALOG = """
models:
  - id: open
    name: Open Model
    provider: openai_compatible_llm
    base_url: https://llm.example/v1
    llm_api_key: key
    model: open-1
  - id: vip
    name: VIP Model
    provider: openai_compatible_llm
    base_url: https://llm.example/v1
    llm_api_key: key
    model: vip-1
    interrupt_method: system
    allowed_users: ['alice']
"""


class FakeLLM:
    def __init__(self, name: str):
        self.name = name


def fake_create_llm(llm_provider, **kwargs):
    return FakeLLM(kwargs["model"])


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    def of_type(self, message_type: str) -> list[dict]:
        return [message for message in self.sent if message["type"] == message_type]


class UserSettingStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "history.db"
        self.repository = SQLiteHistoryRepository(self.db_path)
        await self.repository.initialize()
        await self.repository.ensure_user("alice", "Alice")
        await self.repository.ensure_user("bob", "Bob")

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_schema_version_8_is_recorded(self):
        conn = sqlite3.connect(self.db_path)
        try:
            versions = {
                row[0] for row in conn.execute("SELECT version FROM schema_migrations")
            }
        finally:
            conn.close()
        self.assertIn(8, versions)

    async def test_settings_are_per_user(self):
        get = self.repository.get_user_setting
        self.assertIsNone(await get(user_id="alice", key="llm_model"))
        await self.repository.set_user_setting(
            user_id="alice", key="llm_model", value="vip"
        )
        self.assertEqual(await get(user_id="alice", key="llm_model"), "vip")
        self.assertIsNone(await get(user_id="bob", key="llm_model"))

    async def test_set_replaces_and_none_removes(self):
        for value in ("open", "vip"):
            await self.repository.set_user_setting(
                user_id="alice", key="llm_model", value=value
            )
        self.assertEqual(
            await self.repository.get_user_setting(user_id="alice", key="llm_model"),
            "vip",
        )
        await self.repository.set_user_setting(
            user_id="alice", key="llm_model", value=None
        )
        self.assertIsNone(
            await self.repository.get_user_setting(user_id="alice", key="llm_model")
        )

    async def test_rejects_oversized_or_non_string_values(self):
        for value in ("x" * 2000, 5):
            with self.assertRaises(ValueError):
                await self.repository.set_user_setting(
                    user_id="alice", key="llm_model", value=value
                )


class ModelSelectionTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        root = Path(self._temp_dir.name)
        self.catalog_path = root / "llm_models.yaml"
        self.catalog_path.write_text(CATALOG, "utf-8")
        self.catalog = LLMModelCatalog(str(self.catalog_path), refresh_interval=0)
        self.repository = SQLiteHistoryRepository(root / "history.db")
        await self.repository.initialize()
        await self.repository.ensure_user("alice", "Alice")
        await self.repository.ensure_user("bob", "Bob")
        patcher = patch.object(llm_catalog.LLMFactory, "create_llm", fake_create_llm)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    def make_context(self, user_id: str = "alice") -> ServiceContext:
        context = ServiceContext()
        context.client_uid = f"client-{user_id}"
        context.set_history_storage(self.repository, user_id)
        context.llm_catalog = self.catalog
        context.agent_engine = BasicMemoryAgent(
            llm=FakeLLM("character"),
            system="You are a character.",
            live2d_model=None,
            interrupt_method="user",
        )
        context._agent_replaced()
        return context

    def llm_name(self, context: ServiceContext) -> str:
        return context.agent_engine.llm.name


class ServiceContextModelTests(ModelSelectionTestCase):
    async def test_default_is_the_character_llm(self):
        context = self.make_context()
        await context.sync_model_selection()
        self.assertEqual(self.llm_name(context), "character")
        self.assertIsNone(context.model_list_payload()["current"])

    async def test_list_only_contains_models_the_user_may_use(self):
        alice = self.make_context("alice").model_list_payload()
        bob = self.make_context("bob").model_list_payload()
        self.assertEqual([m["id"] for m in alice["models"]], ["open", "vip"])
        self.assertEqual([m["id"] for m in bob["models"]], ["open"])
        self.assertEqual(set(alice["models"][0]), {"id", "name", "description"})

    async def test_select_switches_llm_stores_choice_and_keeps_memory(self):
        context = self.make_context()
        context.agent_engine._memory.append({"role": "user", "content": "hi"})

        self.assertTrue(await context.select_model("vip"))

        self.assertEqual(self.llm_name(context), "vip-1")
        self.assertEqual(context.model_list_payload()["current"], "vip")
        self.assertEqual(context.agent_engine._memory[0]["content"], "hi")
        self.assertEqual(
            await self.repository.get_user_setting(
                user_id="alice", key=MODEL_SETTING_KEY
            ),
            "vip",
        )

    async def test_interrupt_method_follows_the_model(self):
        context = self.make_context()
        agent = context.agent_engine
        self.assertIn("[interrupted by user]", agent._system)

        await context.select_model("vip")
        self.assertEqual(agent.interrupt_method, "system")
        self.assertEqual(agent._system, "You are a character.")

        await context.select_model(None)
        self.assertEqual(agent.interrupt_method, "user")
        self.assertIn("[interrupted by user]", agent._system)

    async def test_restricted_or_unknown_model_is_rejected(self):
        context = self.make_context("bob")
        for model_id in ("vip", "missing"):
            self.assertFalse(await context.select_model(model_id))
        self.assertEqual(self.llm_name(context), "character")
        self.assertIsNone(
            await self.repository.get_user_setting(user_id="bob", key=MODEL_SETTING_KEY)
        )

    async def test_none_returns_to_the_character_llm(self):
        context = self.make_context()
        await context.select_model("open")
        self.assertTrue(await context.select_model(None))
        self.assertEqual(self.llm_name(context), "character")
        self.assertIsNone(
            await self.repository.get_user_setting(
                user_id="alice", key=MODEL_SETTING_KEY
            )
        )

    async def test_choice_from_another_session_applies_on_sync(self):
        first, second = self.make_context(), self.make_context()
        await first.select_model("open")
        self.assertEqual(self.llm_name(second), "character")
        await second.sync_model_selection()
        self.assertEqual(self.llm_name(second), "open-1")

    async def test_revoked_access_falls_back_on_next_sync(self):
        context = self.make_context()
        await context.select_model("vip")
        self.catalog_path.write_text(CATALOG.replace("['alice']", "['bob']"), "utf-8")
        self.catalog._signature = ()

        await context.sync_model_selection()

        self.assertEqual(self.llm_name(context), "character")
        self.assertIsNone(context.model_list_payload()["current"])

    async def test_choice_survives_an_agent_replacement(self):
        context = self.make_context()
        await context.select_model("open")
        context.agent_engine = BasicMemoryAgent(
            llm=FakeLLM("other character"), system="s", live2d_model=None
        )
        context._agent_replaced()
        self.assertEqual(self.llm_name(context), "open-1")
        await context.select_model(None)
        self.assertEqual(self.llm_name(context), "other character")

    async def test_client_failure_keeps_the_character_llm(self):
        context = self.make_context()

        def broken(llm_provider, **kwargs):
            raise RuntimeError("boom")

        with patch.object(llm_catalog.LLMFactory, "create_llm", broken):
            await context.select_model("open")
        self.assertEqual(self.llm_name(context), "character")
        self.assertIsNone(context.model_list_payload()["current"])

    async def test_without_a_catalog_nothing_is_selectable(self):
        context = self.make_context()
        context.llm_catalog = None
        self.assertFalse(await context.select_model("open"))
        self.assertEqual(
            context.model_list_payload(),
            {"type": "model-list", "models": [], "current": None},
        )


class ModelWebSocketTests(ModelSelectionTestCase):
    def make_handler(self, context: ServiceContext) -> WebSocketHandler:
        handler = WebSocketHandler(SimpleNamespace())
        handler.client_contexts["client"] = context
        return handler

    async def test_fetch_models_reports_list_and_current(self):
        context = self.make_context()
        await self.repository.set_user_setting(
            user_id="alice", key=MODEL_SETTING_KEY, value="open"
        )
        websocket = FakeWebSocket()

        await self.make_handler(context)._route_message(
            websocket, "client", {"type": "fetch-models"}
        )

        (payload,) = websocket.of_type("model-list")
        self.assertEqual([m["id"] for m in payload["models"]], ["open", "vip"])
        self.assertEqual(payload["current"], "open")
        self.assertNotIn("key", json.dumps(payload))

    async def test_switch_model_confirms(self):
        context = self.make_context()
        websocket = FakeWebSocket()

        await self.make_handler(context)._route_message(
            websocket, "client", {"type": "switch-model", "model": "vip"}
        )

        self.assertEqual(websocket.sent, [{"type": "model-switched", "model": "vip"}])
        self.assertEqual(self.llm_name(context), "vip-1")

    async def test_switch_to_null_restores_the_character_llm(self):
        context = self.make_context()
        await context.select_model("open")
        websocket = FakeWebSocket()

        await self.make_handler(context)._route_message(
            websocket, "client", {"type": "switch-model", "model": None}
        )

        self.assertEqual(websocket.sent, [{"type": "model-switched", "model": None}])
        self.assertEqual(self.llm_name(context), "character")

    async def test_forbidden_model_returns_error_and_fresh_list(self):
        context = self.make_context("bob")
        websocket = FakeWebSocket()
        handler = self.make_handler(context)

        for model in ("vip", 42):
            await handler._route_message(
                websocket, "client", {"type": "switch-model", "model": model}
            )

        errors = websocket.of_type("error")
        self.assertEqual(
            [error["message"] for error in errors], ["Model not available"] * 2
        )
        (payload,) = websocket.of_type("model-list")
        self.assertEqual([m["id"] for m in payload["models"]], ["open"])
        self.assertEqual(self.llm_name(context), "character")


if __name__ == "__main__":
    unittest.main()
