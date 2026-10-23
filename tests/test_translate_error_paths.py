import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.translate import deeplx
    from open_llm_vtuber.translate.deeplx import DeepLXTranslate
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class DeepLXFailureTests(unittest.TestCase):
    def test_request_failure_keeps_original_exception(self):
        translator = DeepLXTranslate("http://localhost/translate", "JA")

        with patch.object(deeplx.httpx, "post", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                translator.translate("hello")

    def test_request_has_timeout(self):
        translator = DeepLXTranslate("http://localhost/translate", "JA")
        response = Mock(text='{"translations": [{"text": "你好"}]}')

        with patch.object(deeplx.httpx, "post", return_value=response) as post:
            result = translator.translate("hello")

        self.assertEqual(result, "你好")
        self.assertEqual(post.call_args.kwargs["timeout"], 10.0)


if __name__ == "__main__":
    unittest.main()
