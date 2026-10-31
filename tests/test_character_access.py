import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from open_llm_vtuber.config_manager.access import (
    is_user_allowed,
    parse_allowed_users,
)
from open_llm_vtuber.config_manager.utils import (
    scan_config_alts_directory,
)


class IsUserAllowedTests(unittest.TestCase):
    def test_missing_or_empty_list_is_public(self) -> None:
        for value in (None, [], "", [""], ["   "]):
            with self.subTest(value=value):
                self.assertTrue(is_user_allowed(value, "u1", "Alice"))

    def test_matches_user_id(self) -> None:
        self.assertTrue(is_user_allowed(["u1"], "u1", "Alice"))
        self.assertFalse(is_user_allowed(["u2"], "u1", "Alice"))

    def test_matches_display_name_ignoring_case_and_spaces(self) -> None:
        self.assertTrue(is_user_allowed([" alice "], "u1", "Alice"))
        self.assertTrue(is_user_allowed(["刘豫森"], "u1", "刘豫森"))

    def test_missing_identity_is_denied(self) -> None:
        self.assertFalse(is_user_allowed(["u1"], None, None))
        self.assertFalse(is_user_allowed(["u1"], None, ""))

    def test_scalar_string_is_accepted_as_single_token(self) -> None:
        self.assertTrue(is_user_allowed("u1", "u1", None))

    def test_malformed_allowlist_denies_access(self) -> None:
        for value in ({"u1": True}, 42, ["u1", 7], [None]):
            with self.subTest(value=value):
                self.assertFalse(is_user_allowed(value, "u1", "Alice"))

    def test_parse_returns_normalized_tokens(self) -> None:
        self.assertEqual(parse_allowed_users([" Alice ", "u1"]), ("alice", "u1"))


class FilteredScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.alts = self.root / "characters"
        self.alts.mkdir()

        (self.root / "conf.yaml").write_text(
            "character_config:\n  conf_name: Default\n  allowed_users: ['only-owner']\n",
            encoding="utf-8",
        )
        (self.alts / "open.yaml").write_text(
            "character_config:\n  conf_name: Open\n",
            encoding="utf-8",
        )
        (self.alts / "private.yaml").write_text(
            "character_config:\n"
            "  conf_name: Private\n"
            "  allowed_users: ['u1', 'Alice']\n",
            encoding="utf-8",
        )
        (self.alts / "broken.yaml").write_text(
            "character_config: [unclosed\n", encoding="utf-8"
        )

        self.original_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def scan(self, user_id, display_name):
        return scan_config_alts_directory(
            str(self.alts),
            is_allowed=lambda character_config: is_user_allowed(
                character_config.get("allowed_users"), user_id, display_name
            ),
        )

    def test_hides_restricted_presets_for_other_users(self) -> None:
        filenames = [item["filename"] for item in self.scan("u2", "Bob")]

        self.assertEqual(filenames, ["conf.yaml", "broken.yaml", "open.yaml"])

    def test_keeps_restricted_presets_for_listed_users(self) -> None:
        filenames = [item["filename"] for item in self.scan("u1", "Alice")]

        self.assertEqual(
            filenames, ["conf.yaml", "broken.yaml", "open.yaml", "private.yaml"]
        )

    def test_default_character_is_never_filtered(self) -> None:
        for user in (("u1", "Alice"), ("u2", "Bob")):
            with self.subTest(user=user):
                self.assertEqual(self.scan(*user)[0]["filename"], "conf.yaml")


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


try:
    from open_llm_vtuber import service_context as service_context_module
    from open_llm_vtuber.service_context import ServiceContext
    from open_llm_vtuber.websocket_handler import WebSocketHandler

    HAS_RUNTIME = True
except ImportError:  # pragma: no cover - depends on optional engines
    HAS_RUNTIME = False


@unittest.skipUnless(HAS_RUNTIME, "Full runtime dependencies are unavailable")
class SwitchAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.presets = self.root / "characters"
        self.presets.mkdir()
        self.alt_path = self.presets / "private.yaml"
        self.alt_path.write_text("character_config: {}\n", encoding="utf-8")

        self.base_character_config = {"conf_uid": "base", "character_name": "Base"}
        self.alt_character_config = {
            "character_name": "Private",
            "allowed_users": ["u1"],
        }

        self.context = ServiceContext()
        self.context.system_config = SimpleNamespace(
            config_alts_dir=str(self.presets),
            model_dump=lambda: {"host": "127.0.0.1"},
        )
        self.context.live2d_model = SimpleNamespace(model_info={"name": "model"})
        self.context.character_config = SimpleNamespace(
            conf_name="Private",
            conf_uid="base",
            character_name="Private",
            welcome_message="",
        )
        self.websocket = FakeWebSocket()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def read_yaml(self, path: str):
        if path == "conf.yaml":
            return {"character_config": self.base_character_config}
        if path == str(self.alt_path):
            return {"character_config": self.alt_character_config}
        raise AssertionError(f"Unexpected config path: {path}")

    async def run_switch(self):
        with (
            patch.object(
                service_context_module, "read_yaml", side_effect=self.read_yaml
            ),
            patch.object(
                service_context_module,
                "validate_config",
                return_value=object(),
            ) as validate_config,
            patch.object(
                ServiceContext, "load_from_config", new=AsyncMock()
            ) as load_from_config,
        ):
            await self.context.handle_config_switch(self.websocket, "private.yaml")
        return validate_config, load_from_config

    async def test_denies_switch_for_unlisted_user(self) -> None:
        self.context.user_id = "u2"
        self.context.user_display_name = "Bob"

        validate_config, load_from_config = await self.run_switch()

        self.assertEqual(
            self.websocket.sent,
            [{"type": "error", "message": "Character not available"}],
        )
        validate_config.assert_not_called()
        load_from_config.assert_not_awaited()

    async def test_allows_switch_by_display_name(self) -> None:
        self.context.user_id = "someone-else"
        self.context.user_display_name = "U1"

        validate_config, load_from_config = await self.run_switch()

        validate_config.assert_called_once()
        load_from_config.assert_awaited_once()
        self.assertEqual(self.websocket.sent[-1]["type"], "config-switched")

    async def test_allows_switch_for_public_preset(self) -> None:
        self.alt_character_config.pop("allowed_users")
        self.context.user_id = "u2"
        self.context.user_display_name = "Bob"

        validate_config, load_from_config = await self.run_switch()

        validate_config.assert_called_once()
        load_from_config.assert_awaited_once()


@unittest.skipUnless(HAS_RUNTIME, "Full runtime dependencies are unavailable")
class FetchConfigsHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.alts = self.root / "characters"
        self.alts.mkdir()

        (self.root / "conf.yaml").write_text(
            "character_config:\n  conf_name: Default\n", encoding="utf-8"
        )
        (self.alts / "open.yaml").write_text(
            "character_config:\n  conf_name: Open\n", encoding="utf-8"
        )
        (self.alts / "private.yaml").write_text(
            "character_config:\n  conf_name: Private\n  allowed_users: ['u1']\n",
            encoding="utf-8",
        )

        self.original_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    async def fetch_filenames(self, user_id: str, display_name: str):
        handler = WebSocketHandler(default_context_cache=Mock())
        handler.client_contexts["client"] = SimpleNamespace(
            system_config=SimpleNamespace(config_alts_dir=str(self.alts)),
            character_allowed=lambda character_config: is_user_allowed(
                character_config.get("allowed_users"), user_id, display_name
            ),
        )
        websocket = FakeWebSocket()

        await handler._handle_fetch_configs(websocket, "client", {})

        return [item["filename"] for item in websocket.sent[0]["configs"]]

    async def test_filters_private_preset_for_unlisted_user(self) -> None:
        self.assertEqual(
            await self.fetch_filenames("u2", "Bob"),
            ["conf.yaml", "open.yaml"],
        )

    async def test_keeps_private_preset_for_listed_user(self) -> None:
        self.assertEqual(
            await self.fetch_filenames("u1", "Alice"),
            ["conf.yaml", "open.yaml", "private.yaml"],
        )


if __name__ == "__main__":
    unittest.main()
