import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.mcpp.tool_executor import ToolExecutor
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ToolStatusTests(unittest.TestCase):
    def test_status_payload_includes_extra_fields(self):
        status = ToolExecutor._tool_status(
            "id", "tool", "completed", "done", browser_view={"url": "x"}
        )

        self.assertEqual(status["type"], "tool_call_status")
        self.assertEqual(status["tool_id"], "id")
        self.assertEqual(status["tool_name"], "tool")
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["content"], "done")
        self.assertEqual(status["browser_view"], {"url": "x"})
        self.assertTrue(status["timestamp"].endswith("Z"))

    def test_claude_gets_image_blocks(self):
        status_content, llm_content = ToolExecutor._split_image_content(
            "Claude",
            "look",
            [{"type": "image", "data": "abc", "mimeType": "image/png"}],
        )

        self.assertEqual(status_content, "look\n[Tool returned 1 image(s)]")
        self.assertEqual(
            llm_content,
            [
                {"type": "text", "text": "look"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "abc",
                    },
                },
            ],
        )

    def test_openai_uses_text_with_image_count(self):
        status_content, llm_content = ToolExecutor._split_image_content(
            "OpenAI",
            "look",
            [{"type": "image", "data": "abc", "mimeType": "image/png"}],
        )

        self.assertEqual(status_content, llm_content)
        self.assertIn("1 image(s)", llm_content)

    def test_text_only_content_is_unchanged(self):
        self.assertEqual(
            ToolExecutor._split_image_content("Claude", "plain", []),
            ("plain", "plain"),
        )


if __name__ == "__main__":
    unittest.main()
