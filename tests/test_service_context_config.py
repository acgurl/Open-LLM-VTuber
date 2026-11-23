import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_llm_vtuber import service_context as service_context_module
from open_llm_vtuber.config_manager import read_yaml, validate_config
from open_llm_vtuber.llm_catalog import LLMModelCatalog
from open_llm_vtuber.service_context import ServiceContext


DEFAULT_REFS = {"llm": "local-qwen", "tts": "edge-default", "asr": "groq-whisper"}


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class HandleConfigSwitchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.presets = self.root / "characters"
        self.presets.mkdir()
        self.alt_path = self.presets / "alt.yaml"
        self.alt_path.write_text("character_config: {}\n", encoding="utf-8")

        self.base_character_config = {
            "conf_uid": "base",
            "character_name": "Base",
            "allowed_users": ["owner"],
            "model_refs": DEFAULT_REFS.copy(),
            "nested": {"a": 1, "b": 2},
        }
        self.alt_character_config = {
            "character_name": "Alt",
            "model_refs": {**DEFAULT_REFS, "llm": "deepseek-chat"},
            "nested": {"b": 3},
        }

        self.context = ServiceContext()
        self.context.system_config = SimpleNamespace(
            config_alts_dir=str(self.presets),
            model_dump=lambda: {"host": "127.0.0.1"},
        )
        self.context.live2d_model = SimpleNamespace(model_info={"name": "model"})
        self.context.character_config = SimpleNamespace(
            conf_name="Alt",
            conf_uid="base",
            character_name="Alt",
            welcome_message="Welcome!",
            starter_prompts=["How do I apply?"],
        )
        self.websocket = FakeWebSocket()
        self.validated = object()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def read_yaml(self, path: str):
        if path == "conf.yaml":
            return {"character_config": self.base_character_config}
        if path == str(self.alt_path):
            return {"character_config": self.alt_character_config}
        raise AssertionError(f"Unexpected config path: {path}")

    async def test_merges_alt_config_over_base_then_notifies(self) -> None:
        with (
            patch.object(
                service_context_module, "read_yaml", side_effect=self.read_yaml
            ),
            patch.object(
                service_context_module,
                "validate_config",
                return_value=self.validated,
            ) as validate_config,
            patch.object(
                ServiceContext, "load_from_config", new=AsyncMock()
            ) as load_from_config,
        ):
            await self.context.handle_config_switch(self.websocket, "alt.yaml")

        validate_config.assert_called_once_with(
            {
                "system_config": {"host": "127.0.0.1"},
                "character_config": {
                    "conf_uid": "base",
                    "character_name": "Alt",
                    "allowed_users": [],
                    "model_refs": {**DEFAULT_REFS, "llm": "deepseek-chat"},
                    "nested": {"a": 1, "b": 3},
                },
            }
        )
        load_from_config.assert_awaited_once_with(self.validated, public=False)
        self.assertEqual(
            self.websocket.sent,
            [
                {
                    "type": "set-model-and-conf",
                    "model_info": {"name": "model"},
                    "conf_name": "Alt",
                    "conf_uid": "base",
                    "welcome_message": "Welcome!",
                    "starter_prompts": ["How do I apply?"],
                },
                {
                    "type": "config-switched",
                    "message": "Switched to config: alt.yaml",
                },
            ],
        )

    async def test_switches_to_base_config(self) -> None:
        with (
            patch.object(
                service_context_module, "read_yaml", side_effect=self.read_yaml
            ),
            patch.object(
                service_context_module,
                "validate_config",
                return_value=self.validated,
            ) as validate_config,
            patch.object(
                ServiceContext, "load_from_config", new=AsyncMock()
            ) as load_from_config,
        ):
            await self.context.handle_config_switch(self.websocket, "conf.yaml")

        validate_config.assert_called_once_with(
            {
                "system_config": {"host": "127.0.0.1"},
                "character_config": self.base_character_config,
            }
        )
        load_from_config.assert_awaited_once_with(self.validated, public=True)

    async def test_preset_cannot_inherit_missing_model_refs(self) -> None:
        for refs in (None, {"llm": "local-qwen", "tts": "edge-default"}):
            with self.subTest(refs=refs):
                if refs is None:
                    del self.alt_character_config["model_refs"]
                else:
                    self.alt_character_config["model_refs"] = refs
                self.websocket.sent.clear()
                with (
                    patch.object(
                        service_context_module, "read_yaml", side_effect=self.read_yaml
                    ),
                    patch.object(service_context_module, "validate_config") as validate,
                    patch.object(ServiceContext, "load_from_config") as load,
                ):
                    await self.context.handle_config_switch(self.websocket, "alt.yaml")

                self.assertEqual(
                    self.websocket.sent,
                    [{"type": "error", "message": "Failed to switch configuration"}],
                )
                validate.assert_not_called()
                load.assert_not_awaited()

    async def test_rejects_path_outside_presets_with_generic_error(self) -> None:
        with (
            patch.object(
                service_context_module, "read_yaml", side_effect=self.read_yaml
            ),
            patch.object(
                service_context_module,
                "validate_config",
                return_value=self.validated,
            ) as validate_config,
            patch.object(
                ServiceContext, "load_from_config", new=AsyncMock()
            ) as load_from_config,
        ):
            await self.context.handle_config_switch(self.websocket, "../outside.yaml")

        self.assertEqual(
            self.websocket.sent,
            [{"type": "error", "message": "Failed to switch configuration"}],
        )
        validate_config.assert_not_called()
        load_from_config.assert_not_awaited()

    async def test_empty_base_config_sends_generic_error(self) -> None:
        with (
            patch.object(
                service_context_module,
                "read_yaml",
                return_value={"character_config": {}},
            ),
            patch.object(
                service_context_module,
                "validate_config",
                return_value=self.validated,
            ) as validate_config,
            patch.object(
                ServiceContext, "load_from_config", new=AsyncMock()
            ) as load_from_config,
        ):
            await self.context.handle_config_switch(self.websocket, "conf.yaml")

        self.assertEqual(
            self.websocket.sent,
            [{"type": "error", "message": "Failed to switch configuration"}],
        )
        validate_config.assert_not_called()
        load_from_config.assert_not_awaited()


class ModelConfPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ServiceContext()
        self.context.live2d_model = SimpleNamespace(model_info={"name": "model"})
        self.context.character_config = SimpleNamespace(
            conf_name="Conf",
            conf_uid="conf-uid",
            welcome_message="Hello",
            starter_prompts=[],
        )

    def test_payload_includes_client_uid_when_given(self):
        self.assertEqual(
            self.context.model_conf_payload("client"),
            {
                "type": "set-model-and-conf",
                "model_info": {"name": "model"},
                "conf_name": "Conf",
                "conf_uid": "conf-uid",
                "welcome_message": "Hello",
                "starter_prompts": [],
                "client_uid": "client",
            },
        )

    def test_payload_omits_client_uid_by_default(self):
        payload = self.context.model_conf_payload()

        self.assertNotIn("client_uid", payload)


class CharacterEngineLoadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.context = ServiceContext()
        self.config_data = read_yaml("config_templates/conf.default.yaml")
        catalogs = {
            kind: read_yaml(f"config_templates/{kind}_models.default.yaml")
            for kind in ("llm", "tts", "asr")
        }
        catalogs["tts"]["tts_models"].append(
            {"id": "pyttsx3-default", "provider": "pyttsx3_tts"}
        )
        catalogs["asr"]["asr_models"][0]["settings"]["api_key"] = "test-groq-key"
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        paths = {}
        for kind, catalog in catalogs.items():
            path = Path(temp_dir.name) / f"{kind}_models.yaml"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            paths[kind] = str(path)
        self.context.llm_catalog = LLMModelCatalog(
            paths["llm"], tts_path=paths["tts"], asr_path=paths["asr"]
        )

    async def load_character(self, tts_ref):
        self.config_data["character_config"]["model_refs"]["tts"] = tts_ref
        config = validate_config(self.config_data)
        with (
            patch.object(self.context.llm_catalog, "client"),
            patch.object(self.context, "init_live2d"),
            patch.object(self.context, "_init_mcp_components"),
            patch.object(self.context, "init_agent"),
            patch.object(service_context_module.TTSFactory, "get_tts_engine") as tts,
            patch.object(service_context_module.ASRFactory, "get_asr_system") as asr,
        ):
            await self.context.load_from_config(config)

        asr.assert_called_once_with(
            "groq_whisper_asr",
            api_key="test-groq-key",
            model="whisper-large-v3-turbo",
            lang=None,
        )
        self.assertIs(self.context.asr_engine, asr.return_value)
        self.assertIs(self.context.tts_engine, tts.return_value)
        self.assertEqual(self.context.character_config.model_refs.tts, tts_ref)
        return tts

    async def test_tts_engine_without_sub_config_gets_no_kwargs(self):
        tts = await self.load_character("pyttsx3-default")

        tts.assert_called_once_with("pyttsx3_tts")

    async def test_tts_engine_with_sub_config_gets_its_fields(self):
        tts = await self.load_character("edge-default")

        tts.assert_called_once_with("edge_tts", voice="en-US-AvaMultilingualNeural")


if __name__ == "__main__":
    unittest.main()
