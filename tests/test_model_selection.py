import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from open_llm_vtuber import llm_catalog
from open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
from open_llm_vtuber.llm_catalog import (
    MODEL_SETTING_KEY,
    THINKING_SETTING_PREFIX,
    LLMModelCatalog,
    parse_models,
)
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
  - id: thinker
    name: Thinker
    provider: openai_compatible_llm
    base_url: https://llm.example/v1
    llm_api_key: key
    model: thinker-1
    allowed_users: [alice]
    thinking:
      default: off
      levels:
        - id: off
          params: {thinking: {type: disabled}}
        - id: high
          name: Deep
          params: {thinking: {type: enabled}, reasoning_effort: high}
        - max
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
        self.assertEqual([m["id"] for m in alice["models"]], ["open", "vip", "thinker"])
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
            {"type": "model-list", "models": [], "current": None, "thinking": None},
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
        self.assertEqual(
            [m["id"] for m in payload["models"]], ["open", "vip", "thinker"]
        )
        self.assertEqual(payload["current"], "open")
        self.assertNotIn("key", json.dumps(payload))

    async def test_switch_model_confirms(self):
        context = self.make_context()
        websocket = FakeWebSocket()

        await self.make_handler(context)._route_message(
            websocket, "client", {"type": "switch-model", "model": "vip"}
        )

        self.assertEqual(
            websocket.sent,
            [{"type": "model-switched", "model": "vip", "thinking": None}],
        )
        self.assertEqual(self.llm_name(context), "vip-1")

    async def test_switch_to_null_restores_the_character_llm(self):
        context = self.make_context()
        await context.select_model("open")
        websocket = FakeWebSocket()

        await self.make_handler(context)._route_message(
            websocket, "client", {"type": "switch-model", "model": None}
        )

        self.assertEqual(
            websocket.sent,
            [{"type": "model-switched", "model": None, "thinking": None}],
        )
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


class ThinkingCatalogTests(unittest.TestCase):
    def parse(self, provider: str, thinking) -> object:
        entry = {
            "id": "m",
            "provider": provider,
            "llm_api_key": "key",
            "model": "m-1",
            "thinking": thinking,
        }
        if provider == "openai_compatible_llm":
            entry["base_url"] = "https://llm.example/v1"
        if provider == "vertex_llm":
            entry = {
                "id": "m",
                "provider": provider,
                "credentials_file": "x.json",
                "model": "m-1",
                "thinking": thinking,
            }
        return parse_models({"models": [entry]}, "test")["m"]

    def test_explicit_params_and_shorthand(self):
        entry = parse_models(yaml.safe_load(CATALOG), "test")["thinker"]
        self.assertEqual(
            [level.id for level in entry.thinking_levels], ["off", "high", "max"]
        )
        self.assertEqual(entry.thinking_default, "off")
        self.assertEqual(
            entry.thinking_level("off").params, {"thinking": {"type": "disabled"}}
        )
        self.assertEqual(
            entry.thinking_level("max").params, {"reasoning_effort": "max"}
        )
        self.assertEqual(entry.thinking_level("bogus").id, "off")
        info = entry.public_info()
        self.assertEqual(
            info["thinking"],
            {
                "levels": [
                    {"id": "off", "name": ""},
                    {"id": "high", "name": "Deep"},
                    {"id": "max", "name": ""},
                ],
                "default": "off",
            },
        )
        self.assertNotIn("params", json.dumps(info))

    def test_shorthand_per_provider(self):
        cases = {
            "openai_responses_llm": {"reasoning": {"effort": "low"}},
            "claude_llm": {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "low"},
            },
            "vertex_llm": {
                "generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}}
            },
        }
        for provider, expected in cases.items():
            entry = self.parse(provider, {"levels": ["off", "low"]})
            self.assertEqual(entry.thinking_level("low").params, expected, provider)
            self.assertEqual(entry.thinking_level("off").params, {}, provider)

    def test_invalid_block_keeps_the_model_without_levels(self):
        for thinking in (
            {"levels": "high"},
            {"levels": [{"id": "bad id"}]},
            {"levels": ["a", "a"]},
            {"levels": [{"id": "x", "params": 3}]},
        ):
            entry = self.parse("claude_llm", thinking)
            self.assertEqual(entry.thinking_levels, (), thinking)
            self.assertNotIn("thinking", entry.public_info())

    def test_default_falls_back_to_off(self):
        entry = self.parse(
            "claude_llm", {"levels": ["high", {"id": "off", "params": {}}]}
        )
        self.assertEqual(entry.thinking_default, "off")
        entry = self.parse(
            "claude_llm", {"default": "bogus", "levels": ["low", "none"]}
        )
        self.assertEqual(entry.thinking_default, "none")
        entry = self.parse("claude_llm", {"levels": ["low", "high"]})
        self.assertEqual(entry.thinking_default, "low")

    def test_single_level_is_reported_as_locked(self):
        entry = self.parse("claude_llm", {"levels": ["high"]})
        self.assertEqual(entry.thinking_level(None).id, "high")
        self.assertEqual(
            entry.public_info()["thinking"],
            {"levels": [{"id": "high", "name": ""}], "default": "high"},
        )


class ThinkingSelectionTests(ModelSelectionTestCase):
    def make_handler(self, context: ServiceContext) -> WebSocketHandler:
        handler = WebSocketHandler(SimpleNamespace())
        handler.client_contexts["client"] = context
        return handler

    async def test_default_level_is_applied_to_requests(self):
        context = self.make_context()
        await context.select_model("thinker")
        self.assertEqual(context.model_list_payload()["thinking"], "off")
        self.assertEqual(
            context.agent_engine.request_options, {"thinking": {"type": "disabled"}}
        )

    async def test_level_is_stored_per_model_and_applied(self):
        context = self.make_context()
        await context.select_model("thinker")
        self.assertTrue(await context.select_thinking("high"))
        self.assertEqual(
            context.agent_engine.request_options,
            {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        )
        self.assertEqual(
            await self.repository.get_user_setting(
                user_id="alice", key=THINKING_SETTING_PREFIX + "thinker"
            ),
            "high",
        )
        # A model without levels sends nothing extra.
        await context.select_model("open")
        self.assertIsNone(context.agent_engine.request_options)
        self.assertIsNone(context.model_list_payload()["thinking"])
        # Another session of the same user gets the stored level back.
        await self.repository.set_user_setting(
            user_id="alice", key=MODEL_SETTING_KEY, value="thinker"
        )
        other = self.make_context()
        await other.sync_model_selection()
        self.assertEqual(other.model_list_payload()["thinking"], "high")
        self.assertEqual(other.agent_engine.request_options["reasoning_effort"], "high")

    async def test_unknown_level_or_model_without_levels_is_rejected(self):
        context = self.make_context()
        self.assertFalse(await context.select_thinking("high"))
        await context.select_model("thinker")
        self.assertFalse(await context.select_thinking("ultra"))

    async def test_set_thinking_over_websocket(self):
        context = self.make_context()
        await context.select_model("thinker")
        handler = self.make_handler(context)
        websocket = FakeWebSocket()

        await handler._route_message(
            websocket, "client", {"type": "set-thinking", "level": "max"}
        )
        await handler._route_message(
            websocket, "client", {"type": "set-thinking", "level": 5}
        )

        lists = websocket.of_type("model-list")
        self.assertEqual([payload["thinking"] for payload in lists], ["max", "max"])
        self.assertEqual(
            [error["message"] for error in websocket.of_type("error")],
            ["Thinking level not available"],
        )
        thinker = next(m for m in lists[0]["models"] if m["id"] == "thinker")
        self.assertEqual(len(thinker["thinking"]["levels"]), 3)

    async def test_switch_model_reports_the_stored_level(self):
        await self.repository.set_user_setting(
            user_id="alice", key=THINKING_SETTING_PREFIX + "thinker", value="high"
        )
        context = self.make_context()
        websocket = FakeWebSocket()

        await self.make_handler(context)._route_message(
            websocket, "client", {"type": "switch-model", "model": "thinker"}
        )

        self.assertEqual(
            websocket.sent,
            [{"type": "model-switched", "model": "thinker", "thinking": "high"}],
        )
        self.assertEqual(
            context.agent_engine.request_options["reasoning_effort"], "high"
        )


if __name__ == "__main__":
    unittest.main()
