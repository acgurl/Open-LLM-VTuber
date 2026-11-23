import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from open_llm_vtuber.config_manager import ASRConfig, TTSConfig
from open_llm_vtuber.conversations.conversation_utils import sync_turn_model
from open_llm_vtuber.llm_catalog import LLMModelCatalog
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.storage import SQLiteHistoryRepository
from open_llm_vtuber.websocket_handler import WebSocketHandler

from test_model_selection import FakeWebSocket

CATALOG = """
tts_models:
  - id: voice
    name: Edge voice
    provider: edge_tts
  - id: private-voice
    provider: edge_tts
    allowed_users: [alice@example.test]
    settings: {voice: zh-CN-YunxiNeural}
  - id: missing-settings
    provider: azure_tts
  - id: invalid-settings
    provider: edge_tts
    settings: {voice: [not, a, string]}
  - id: invalid-access
    provider: edge_tts
    allowed_users: {alice: true}
asr_models:
  - id: voice
    name: Whisper
    provider: groq_whisper_asr
    settings: {api_key: test-asr-secret, model: whisper-large-v3-turbo, lang: zh}
"""


class SpeechModelSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.catalog_path = Path(temporary.name) / "llm_models.yaml"
        self.catalog_path.write_text(CATALOG, encoding="utf-8")
        self.catalog = LLMModelCatalog(str(self.catalog_path), refresh_interval=0)
        self.repository = SQLiteHistoryRepository(Path(temporary.name) / "db.sqlite3")
        await self.repository.initialize()
        self.addAsyncCleanup(self.repository.close)
        await self.repository.ensure_user("alice", "Alice")
        await self.repository.ensure_user("bob", "Bob")
        self.base_tts_config = TTSConfig(
            tts_model="edge_tts", edge_tts={"voice": "zh-CN-XiaoxiaoNeural"}
        )
        self.base_asr_config = ASRConfig(
            asr_model="groq_whisper_asr",
            groq_whisper_asr={"api_key": "base-asr-key", "lang": "en"},
        )
        self.character_tts = Mock(name="character_tts")
        self.character_asr = Mock(name="character_asr")
        self.selected_tts = Mock(name="selected_tts")
        self.selected_asr = Mock(name="selected_asr")
        tts_patch = patch(
            "open_llm_vtuber.service_context.TTSFactory.get_tts_engine",
            return_value=self.selected_tts,
        )
        asr_patch = patch(
            "open_llm_vtuber.service_context.ASRFactory.get_asr_system",
            return_value=self.selected_asr,
        )
        self.make_tts = tts_patch.start()
        self.make_asr = asr_patch.start()
        self.addCleanup(tts_patch.stop)
        self.addCleanup(asr_patch.stop)

    def new_context(self, user="alice"):
        context = ServiceContext()
        context.set_history_storage(self.repository, user)
        context.user_emails = ("alice@example.test",) if user == "alice" else ()
        context.llm_catalog = self.catalog
        context.base_speech_config = SimpleNamespace(
            asr_config=self.base_asr_config, tts_config=self.base_tts_config
        )
        context.character_config = SimpleNamespace(
            asr_config=self.base_asr_config, tts_config=self.base_tts_config
        )
        context.tts_engine = self.character_tts
        context.asr_engine = self.character_asr
        self.addAsyncCleanup(context.close)
        return context

    def handler_for(self, context):
        handler = WebSocketHandler(ServiceContext())
        handler.client_contexts["client"] = context
        return handler

    async def test_defaults_and_listing_only_expose_allowed_configured_options(self):
        alice = self.new_context()
        await sync_turn_model(alice)
        payload = alice.model_list_payload()
        self.assertIs(alice.tts_engine, self.character_tts)
        self.assertIs(alice.asr_engine, self.character_asr)
        self.assertEqual(payload["models"], [])
        self.assertIsNone(payload["tts_current"])
        self.assertIsNone(payload["asr_current"])
        self.assertEqual(
            payload["tts_default_model"], {"name": "Edge voice", "matches": ["voice"]}
        )
        self.assertEqual(
            payload["asr_default_model"],
            {"name": "whisper-large-v3-turbo", "matches": []},
        )
        self.assertEqual(
            [entry["id"] for entry in payload["tts_models"]], ["voice", "private-voice"]
        )
        self.assertEqual(
            payload["asr_models"],
            [{"id": "voice", "name": "Whisper", "description": ""}],
        )
        self.assertNotIn("test-asr-secret", json.dumps(payload))
        bob = self.new_context("bob")
        self.assertEqual(
            [entry["id"] for entry in bob.model_list_payload()["tts_models"]], ["voice"]
        )
        self.assertFalse(
            await bob.select_speech_model("tts", "private-voice", apply=True)
        )
        self.make_tts.assert_not_called()
        self.make_asr.assert_not_called()

    async def test_independent_switches_persist_and_null_restores_latest_character(
        self,
    ):
        context = self.new_context()
        context.history_uid = "keep-current-history"
        self.assertTrue(await context.select_speech_model("tts", "voice", apply=True))
        self.assertTrue(await context.select_speech_model("asr", "voice", apply=True))
        self.make_tts.assert_called_once_with("edge_tts", voice="zh-CN-XiaoxiaoNeural")
        self.make_asr.assert_called_once_with(
            "groq_whisper_asr",
            api_key="test-asr-secret",
            model="whisper-large-v3-turbo",
            lang="zh",
        )
        self.assertIs(context.tts_engine, self.selected_tts)
        self.assertIs(context.asr_engine, self.selected_asr)
        self.assertEqual(context.history_uid, "keep-current-history")

        second_tab = self.new_context()
        await sync_turn_model(second_tab)
        self.assertEqual(second_tab.model_list_payload()["tts_current"], "voice")
        self.assertEqual(second_tab.model_list_payload()["asr_current"], "voice")
        self.assertIs(self.new_context("bob").tts_engine, self.character_tts)

        other_voice = Mock(name="other_character_tts")
        self.make_tts.return_value = other_voice
        context.init_tts(
            TTSConfig(tts_model="edge_tts", edge_tts={"voice": "zh-CN-XiaoyiNeural"})
        )
        self.assertIs(context.tts_engine, self.selected_tts)
        self.assertTrue(await context.select_speech_model("tts", None, apply=True))
        self.assertIs(context.tts_engine, other_voice)
        self.assertIs(context.asr_engine, self.selected_asr)
        self.selected_tts.close.assert_called_once()
        self.character_tts.close.assert_not_called()
        self.assertIsNone(
            await self.repository.get_user_setting(user_id="alice", key="tts_model")
        )

    async def test_busy_switch_is_deferred_without_cancelling_current_turn(self):
        context = self.new_context()
        websocket = FakeWebSocket()
        handler = self.handler_for(context)
        running = asyncio.get_running_loop().create_future()
        handler.current_conversation_tasks["client"] = running
        await handler._route_message(
            websocket,
            "client",
            {"type": "switch-model", "kind": "tts", "model": "voice"},
        )
        self.assertEqual(
            websocket.sent,
            [{"type": "model-switched", "kind": "tts", "model": "voice"}],
        )
        self.assertFalse(running.done())
        await handler._route_message(websocket, "client", {"type": "fetch-models"})
        self.assertIsNone(websocket.of_type("model-list")[-1]["tts_current"])
        self.make_tts.assert_not_called()
        running.set_result(None)
        await sync_turn_model(context)
        self.assertIs(context.tts_engine, self.selected_tts)

    async def test_failed_factory_does_not_replace_saved_choice_and_revocation_restores_default(
        self,
    ):
        context = self.new_context()
        self.assertTrue(
            await context.select_speech_model("tts", "private-voice", apply=True)
        )
        self.make_tts.side_effect = RuntimeError("sensitive provider error")
        websocket = FakeWebSocket()
        await self.handler_for(context)._route_message(
            websocket,
            "client",
            {"type": "switch-model", "kind": "tts", "model": "voice"},
        )
        self.assertEqual(
            websocket.sent[0],
            {"type": "error", "kind": "tts", "message": "Model not available"},
        )
        self.assertEqual(websocket.sent[1]["tts_current"], "private-voice")
        self.assertIs(context.tts_engine, self.selected_tts)
        self.catalog_path.write_text(
            CATALOG.replace("alice@example.test", "other@example.test"),
            encoding="utf-8",
        )
        await sync_turn_model(context)
        self.assertIs(context.tts_engine, self.character_tts)
        self.assertIsNone(context.model_list_payload()["tts_current"])
        self.selected_tts.close.assert_called_once()
        self.character_tts.close.assert_not_called()
