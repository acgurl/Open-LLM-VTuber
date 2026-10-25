import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    from run_server import _frontend_message
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class FrontendMessageTests(unittest.TestCase):
    def test_selects_language_with_english_fallback(self):
        self.assertIn("npm run build", _frontend_message("zh", "missing"))
        self.assertIn("Frontend build", _frontend_message("en", "missing"))
        self.assertIn("Frontend build", _frontend_message("jp", "missing"))


if __name__ == "__main__":
    unittest.main()
