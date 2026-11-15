import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loguru import logger

from open_llm_vtuber import llm_catalog
from open_llm_vtuber.llm_catalog import LLMModelCatalog, parse_models

SECRET = "sk-very-secret-key"

CATALOG = f"""
models:
  - id: public-model
    name: Public Model
    description: For everyone
    provider: openai_compatible_llm
    base_url: https://llm.example/v1
    llm_api_key: {SECRET}
    model: public-1
  - id: private-model
    name: Private Model
    provider: deepseek_llm
    llm_api_key: {SECRET}
    model: private-1
    interrupt_method: system
    allowed_users:
      - Alice@Example.com
      - u-bob
"""


class ParseModelsTests(unittest.TestCase):
    def setUp(self):
        self.messages: list[str] = []
        self._sink = logger.add(self.messages.append, format="{message}")

    def tearDown(self):
        logger.remove(self._sink)

    def parse(self, models):
        return parse_models({"models": models}, "llm_models.yaml")

    def entry(self, **overrides):
        entry = {
            "id": "m1",
            "provider": "openai_compatible_llm",
            "base_url": "https://llm.example/v1",
            "llm_api_key": SECRET,
            "model": "m-1",
        }
        entry.update(overrides)
        return entry

    def test_missing_models_key_is_an_empty_catalog(self):
        self.assertEqual(parse_models({}, "f"), {})
        self.assertEqual(parse_models(None, "f"), {})

    def test_models_must_be_a_list(self):
        with self.assertRaises(ValueError):
            parse_models({"models": {"id": "m1"}}, "f")

    def test_entry_defaults_and_provider_settings(self):
        entry = self.parse([self.entry()])["m1"]
        self.assertEqual(entry.name, "m1")
        self.assertEqual(entry.description, "")
        self.assertEqual(entry.interrupt_method, "user")
        settings = dict(entry.settings)
        self.assertEqual(settings["model"], "m-1")
        self.assertEqual(settings["temperature"], 1.0)

    def test_provider_defaults_apply(self):
        raw = self.entry(provider="deepseek_llm")
        del raw["base_url"]
        entry = self.parse([raw])["m1"]
        self.assertEqual(
            dict(entry.settings)["base_url"], "https://api.deepseek.com/v1"
        )

    def test_public_info_never_exposes_the_endpoint_or_key(self):
        info = self.parse([self.entry(name="Nice", description="Fast")])["m1"]
        self.assertEqual(
            info.public_info(), {"id": "m1", "name": "Nice", "description": "Fast"}
        )

    def test_invalid_entries_are_skipped(self):
        entries = self.parse(
            [
                "not a mapping",
                self.entry(id="bad id"),
                self.entry(id=""),
                self.entry(id="no-provider", provider="nope_llm"),
                self.entry(id="ok"),
            ]
        )
        self.assertEqual(list(entries), ["ok"])

    def test_duplicate_id_keeps_the_first(self):
        entries = self.parse([self.entry(name="first"), self.entry(name="second")])
        self.assertEqual(entries["m1"].name, "first")

    def test_invalid_settings_are_skipped_without_logging_values(self):
        entries = self.parse([self.entry(temperature=SECRET)])
        self.assertEqual(entries, {})
        logged = "\n".join(self.messages)
        self.assertIn("temperature", logged)
        self.assertNotIn(SECRET, logged)

    def test_malformed_allowed_users_denies_everyone(self):
        entry = self.parse([self.entry(allowed_users={"u1": True})])["m1"]
        catalog = LLMModelCatalog("unused.yaml")
        catalog._entries = {"m1": entry}
        catalog._checked_at = float("inf")
        self.assertEqual(catalog.available("u1", None), [])
        self.assertIsNone(catalog.resolve("m1", "u1", None))


class CatalogFileTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self._temp_dir.name) / "llm_models.yaml"
        self.catalog = LLMModelCatalog(str(self.path), refresh_interval=0)

    def tearDown(self):
        self._temp_dir.cleanup()

    def write(self, text: str) -> None:
        self.path.write_text(text, "utf-8")
        # Some filesystems have coarse mtimes; make every write a new version.
        stat = self.path.stat()
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + self._bump()))

    def _bump(self) -> int:
        self._writes = getattr(self, "_writes", 0) + 1
        return self._writes * 1_000_000_000

    def ids(self, user_id=None, emails=None):
        return [entry.id for entry in self.catalog.available(user_id, emails)]

    def test_missing_file_disables_selection(self):
        self.assertEqual(self.ids("u1"), [])
        self.assertIsNone(self.catalog.resolve("public-model", "u1", None))

    def test_allowed_users_match_user_id_or_verified_email(self):
        self.write(CATALOG)
        self.assertEqual(self.ids("u-other"), ["public-model"])
        self.assertEqual(self.ids("u-bob"), ["public-model", "private-model"])
        self.assertEqual(
            self.ids("u-other", ("alice@example.com",)),
            ["public-model", "private-model"],
        )
        self.assertEqual(self.ids(None, None), ["public-model"])

    def test_resolve_enforces_the_allowlist(self):
        self.write(CATALOG)
        self.assertIsNone(self.catalog.resolve("private-model", "u-other", None))
        self.assertIsNone(self.catalog.resolve("missing", "u-bob", None))
        self.assertIsNone(self.catalog.resolve(["private-model"], "u-bob", None))
        entry = self.catalog.resolve("private-model", "u-bob", None)
        self.assertEqual(entry.interrupt_method, "system")

    def test_edits_are_picked_up_and_revoke_access(self):
        self.write(CATALOG)
        self.assertIsNotNone(self.catalog.resolve("private-model", "u-bob", None))
        self.write(CATALOG.replace("      - u-bob\n", ""))
        self.assertIsNone(self.catalog.resolve("private-model", "u-bob", None))

    def test_unparseable_file_keeps_the_previous_catalog(self):
        self.write(CATALOG)
        self.assertEqual(self.ids("u-other"), ["public-model"])
        self.write("models: [unclosed\n")
        self.assertEqual(self.ids("u-other"), ["public-model"])
        self.assertIsNone(self.catalog.resolve("private-model", "u-other", None))

    def test_removed_file_clears_the_catalog(self):
        self.write(CATALOG)
        self.assertEqual(self.ids("u-bob"), ["public-model", "private-model"])
        self.path.unlink()
        self.assertEqual(self.ids("u-bob"), [])

    def test_environment_variables_are_substituted(self):
        with patch.dict(os.environ, {"TEST_CATALOG_KEY": "from-env"}):
            self.write(CATALOG.replace(SECRET, "${TEST_CATALOG_KEY}"))
            entry = self.catalog.resolve("public-model", "u1", None)
        self.assertEqual(dict(entry.settings)["llm_api_key"], "from-env")

    def test_client_is_shared_and_rebuilt_when_the_entry_changes(self):
        self.write(CATALOG)
        created = []

        def create_llm(llm_provider, **kwargs):
            created.append((llm_provider, kwargs))
            return object()

        with patch.object(llm_catalog.LLMFactory, "create_llm", create_llm):
            entry = self.catalog.resolve("public-model", "u1", None)
            first = self.catalog.client(entry)
            self.assertIs(self.catalog.client(entry), first)
            self.assertEqual(len(created), 1)
            provider, kwargs = created[0]
            self.assertEqual(provider, "openai_compatible_llm")
            self.assertEqual(kwargs["model"], "public-1")
            self.assertEqual(kwargs["llm_api_key"], SECRET)
            self.assertNotIn("interrupt_method", kwargs)

            self.write(CATALOG.replace("public-1", "public-2"))
            changed = self.catalog.resolve("public-model", "u1", None)
            self.assertIsNot(self.catalog.client(changed), first)
            self.assertEqual(created[-1][1]["model"], "public-2")


if __name__ == "__main__":
    unittest.main()
