import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from open_llm_vtuber.config_manager import read_yaml, validate_config
from open_llm_vtuber.config_manager.character import CharacterModelRefs
from open_llm_vtuber.conversations.conversation_utils import sync_turn_model
from open_llm_vtuber.llm_catalog import LLMModelCatalog
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.storage import SQLiteHistoryRepository
from open_llm_vtuber.websocket_handler import WebSocketHandler

from test_model_selection import CATALOG as LLM_CATALOG, FakeWebSocket, fake_create_llm

TTS_CATALOG = """
tts_models:
  - id: voice
    name: Edge voice
    provider: edge_tts
    settings: {voice: zh-CN-XiaoxiaoNeural}
  - id: character-voice
    provider: edge_tts
    settings: {voice: zh-CN-XiaoyiNeural}
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
"""

ASR_CATALOG = """
asr_models:
  - id: voice
    name: Whisper
    provider: groq_whisper_asr
    settings: {api_key: test-asr-secret, model: whisper-large-v3-turbo, lang: zh}
  - id: character-asr
    provider: groq_whisper_asr
    settings: {api_key: base-asr-key, lang: en}
"""


class SpeechModelSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.llm_path = root / "language.yaml"
        self.tts_path = root / "voices.yaml"
        self.asr_path = root / "recognizers.yaml"
        self.llm_path.write_text(LLM_CATALOG, encoding="utf-8")
        self.tts_path.write_text(TTS_CATALOG, encoding="utf-8")
        self.asr_path.write_text(ASR_CATALOG, encoding="utf-8")
        self.catalog = LLMModelCatalog(
            str(self.llm_path),
            refresh_interval=0,
            tts_path=str(self.tts_path),
            asr_path=str(self.asr_path),
        )
        self.repository = SQLiteHistoryRepository(Path(temporary.name) / "db.sqlite3")
        await self.repository.initialize()
        self.addAsyncCleanup(self.repository.close)
        await self.repository.ensure_user("alice", "Alice")
        await self.repository.ensure_user("bob", "Bob")
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
        _, context._character_speech = self.catalog.character_models(
            CharacterModelRefs(llm="open", tts="character-voice", asr="character-asr")
        )
        context.tts_engine = self.character_tts
        context.asr_engine = self.character_asr
        self.addAsyncCleanup(context.close)
        return context

    def handler_for(self, context):
        handler = WebSocketHandler(ServiceContext())
        handler.client_contexts["client"] = context
        return handler

    async def test_bad_tts_reload_does_not_block_llm_or_asr_updates(self):
        self.assertEqual(
            self.catalog.available_speech("tts", None, ())[0].name, "Edge voice"
        )
        self.tts_path.write_text("tts_models: [unclosed", encoding="utf-8")
        self.llm_path.write_text(
            LLM_CATALOG.replace("Open Model", "New model"), encoding="utf-8"
        )
        self.asr_path.write_text(
            ASR_CATALOG.replace("Whisper", "New ASR"), encoding="utf-8"
        )

        llm, speech = self.catalog.character_models(
            CharacterModelRefs(llm="open", tts="voice", asr="voice")
        )
        self.assertEqual(llm.name, "New model")
        self.assertEqual(speech["tts"].name, "Edge voice")
        self.assertEqual(speech["asr"].name, "New ASR")

    async def test_missing_speech_file_does_not_use_legacy_combined_catalog(self):
        refs = CharacterModelRefs(llm="open", tts="voice", asr="voice")
        self.catalog.character_models(refs)
        self.tts_path.unlink()
        self.llm_path.write_text(LLM_CATALOG + TTS_CATALOG, encoding="utf-8")
        self.assertEqual(self.catalog.available_speech("tts", None, ()), [])
        self.assertIsNotNone(self.catalog.resolve("open", None, ()))
        with self.assertRaisesRegex(
            ValueError, r"voices\.yaml: character model_refs\.tts"
        ):
            self.catalog.character_models(refs)

    async def test_catalog_references_control_all_engines_on_load_and_switch(self):
        context = ServiceContext()
        context.llm_catalog = self.catalog
        self.addAsyncCleanup(context.close)
        data = read_yaml("config_templates/conf.default.yaml")
        data["system_config"]["tool_prompts"] = {}
        data["character_config"]["model_refs"] = {
            "llm": "open",
            "tts": "character-voice",
            "asr": "character-asr",
        }
        with (
            patch(
                "open_llm_vtuber.llm_catalog.LLMFactory.create_llm",
                side_effect=fake_create_llm,
            ),
            patch.object(ServiceContext, "init_live2d"),
        ):
            await context.load_from_config(validate_config(data))
            self.assertEqual(context.agent_engine.llm.name, "open-1")
            self.make_tts.assert_called_once_with(
                "edge_tts", voice="zh-CN-XiaoyiNeural"
            )
            self.make_asr.assert_called_once_with(
                "groq_whisper_asr",
                api_key="base-asr-key",
                model="whisper-large-v3-turbo",
                lang="en",
            )
            old_config = context.config
            data["character_config"]["model_refs"] = {
                "llm": "vip",
                "tts": "voice",
                "asr": "voice",
            }
            with self.assertRaisesRegex(ValueError, "does not cover"):
                await context.load_from_config(validate_config(data))
            self.assertIs(context.config, old_config)
            self.assertEqual(context.agent_engine.llm.name, "open-1")
            data["character_config"]["allowed_users"] = ["alice"]
            context.user_id = "alice"
            await context.load_from_config(validate_config(data), public=False)
            self.assertEqual(context.agent_engine.llm.name, "vip-1")
            self.assertEqual(
                self.make_tts.call_args.kwargs["voice"], "zh-CN-XiaoxiaoNeural"
            )
            self.assertEqual(self.make_asr.call_args.kwargs["lang"], "zh")
            self.assertEqual(context.model_list_payload()["default_model"]["id"], "vip")
            self.assertEqual(
                context.model_list_payload()["tts_default_model"]["id"], "voice"
            )
            self.assertEqual(
                context.model_list_payload()["asr_default_model"]["id"], "voice"
            )

    async def test_defaults_and_listing_only_expose_allowed_configured_options(self):
        alice = self.new_context()
        await sync_turn_model(alice)
        payload = alice.model_list_payload()
        self.assertIs(alice.tts_engine, self.character_tts)
        self.assertIs(alice.asr_engine, self.character_asr)
        self.assertIsNone(payload["tts_current"])
        self.assertIsNone(payload["asr_current"])
        self.assertEqual(
            payload["tts_default_model"],
            {"id": "character-voice", "name": "character-voice", "description": ""},
        )
        self.assertEqual(
            payload["asr_default_model"],
            {"id": "character-asr", "name": "character-asr", "description": ""},
        )
        self.assertEqual(
            [entry["id"] for entry in payload["tts_models"]],
            ["voice", "character-voice", "private-voice"],
        )
        self.assertEqual(
            payload["asr_models"],
            [
                {"id": "voice", "name": "Whisper", "description": ""},
                {"id": "character-asr", "name": "character-asr", "description": ""},
            ],
        )
        self.assertNotIn("test-asr-secret", json.dumps(payload))
        bob = self.new_context("bob")
        self.assertEqual(
            [entry["id"] for entry in bob.model_list_payload()["tts_models"]],
            ["voice", "character-voice"],
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
        context.tts_engine = other_voice
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
        self.tts_path.write_text(
            TTS_CATALOG.replace("alice@example.test", "other@example.test"),
            encoding="utf-8",
        )
        await sync_turn_model(context)
        self.assertIs(context.tts_engine, self.character_tts)
        self.assertIsNone(context.model_list_payload()["tts_current"])
        self.selected_tts.close.assert_called_once()
        self.character_tts.close.assert_not_called()
