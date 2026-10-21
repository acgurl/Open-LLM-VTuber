import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber import service_context as service_context_module
    from open_llm_vtuber.service_context import ServiceContext
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


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
            "nested": {"a": 1, "b": 2},
        }
        self.alt_character_config = {
            "character_name": "Alt",
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
                    "nested": {"a": 1, "b": 3},
                },
            }
        )
        load_from_config.assert_awaited_once_with(self.validated)
        self.assertEqual(
            self.websocket.sent,
            [
                {
                    "type": "set-model-and-conf",
                    "model_info": {"name": "model"},
                    "conf_name": "Alt",
                    "conf_uid": "base",
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
        load_from_config.assert_awaited_once_with(self.validated)

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
            await self.context.handle_config_switch(
                self.websocket, "../outside.yaml"
            )

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


if __name__ == "__main__":
    unittest.main()
