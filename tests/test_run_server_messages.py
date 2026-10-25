import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    from run_server import _frontend_message, ensure_mcp_config
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class FrontendMessageTests(unittest.TestCase):
    def test_selects_language_with_english_fallback(self):
        self.assertIn("npm run build", _frontend_message("zh", "missing"))
        self.assertIn("Frontend build", _frontend_message("en", "missing"))
        self.assertIn("Frontend build", _frontend_message("jp", "missing"))


class McpConfigSeedTests(unittest.TestCase):
    def test_seeds_missing_config_from_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp_servers.json"

            ensure_mcp_config(target)

            self.assertTrue(target.exists())
            self.assertIn("mcp_servers", json.loads(target.read_text("utf-8")))

    def test_never_overwrites_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mcp_servers.json"
            target.write_text('{"mcp_servers": {"prod": {}}}', encoding="utf-8")

            ensure_mcp_config(target)

            self.assertEqual(target.read_text("utf-8"), '{"mcp_servers": {"prod": {}}}')


if __name__ == "__main__":
    unittest.main()
