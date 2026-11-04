import unittest
from unittest.mock import Mock, patch

from open_llm_vtuber.translate import deeplx, tencent
from open_llm_vtuber.translate.deeplx import DeepLXTranslate
from open_llm_vtuber.translate.tencent import TencentTranslate


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

    def test_body_is_sent_as_content_not_deprecated_data(self):
        translator = DeepLXTranslate("http://localhost/translate", "JA")
        response = Mock(text='{"translations": [{"text": "你好"}]}')

        with patch.object(deeplx.httpx, "post", return_value=response) as post:
            translator.translate("hello")

        self.assertNotIn("data", post.call_args.kwargs)
        self.assertIn('"hello"', post.call_args.kwargs["content"])


class TencentTranslateTests(unittest.TestCase):
    def setUp(self):
        self.translator = TencentTranslate("secret-id", "secret-key")

    def test_success_returns_target_text_with_timeout(self):
        response = Mock()
        response.json.return_value = {"Response": {"TargetText": "こんにちは"}}

        with patch.object(tencent.httpx, "post", return_value=response) as post:
            result = self.translator.translate("你好")

        self.assertEqual(result, "こんにちは")
        self.assertEqual(post.call_args.kwargs["timeout"], 10.0)
        self.assertNotIn("data", post.call_args.kwargs)
        self.assertIn("SourceText", post.call_args.kwargs["content"])

    def test_api_error_raises_instead_of_returning_placeholder_text(self):
        response = Mock()
        response.json.return_value = {
            "Response": {
                "Error": {"Code": "AuthFailure", "Message": "bad key"},
                "RequestId": "r",
            }
        }

        with patch.object(tencent.httpx, "post", return_value=response):
            with self.assertRaises(RuntimeError) as raised:
                self.translator.translate("你好")

        self.assertIn("AuthFailure", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
