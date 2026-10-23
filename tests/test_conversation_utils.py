import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.input_types import ImageSource
    from open_llm_vtuber.conversations.conversation_utils import create_batch_input
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ImagePayloadTests(unittest.TestCase):
    def test_raw_base64_becomes_data_url(self):
        batch = create_batch_input(
            "hi",
            [{"source": "camera", "mime_type": "image/jpeg", "data": "/9j/4AAQ"}],
            "Human",
        )
        self.assertEqual(batch.images[0].source, ImageSource.CAMERA)
        self.assertEqual(batch.images[0].data, "data:image/jpeg;base64,/9j/4AAQ")

    def test_existing_data_url_is_untouched(self):
        payload = "data:image/png;base64,AAAA"
        batch = create_batch_input(
            "hi",
            [{"source": "upload", "mime_type": "image/png", "data": payload}],
            "Human",
        )
        self.assertEqual(batch.images[0].data, payload)

    def test_remote_url_is_not_prefixed(self):
        url = "https://example.com/a.jpg"
        batch = create_batch_input(
            "hi",
            [{"source": "shared", "mime_type": "image/jpeg", "data": url}],
            "Human",
        )
        self.assertEqual(batch.images[0].data, url)

    def test_no_images(self):
        batch = create_batch_input("hi", None, "Human")
        self.assertIsNone(batch.images)


if __name__ == "__main__":
    unittest.main()
