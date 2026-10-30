import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.input_types import ImageSource
    from open_llm_vtuber.conversations.conversation_utils import (
        consume_agent_stream,
        create_batch_input,
        should_store_history,
    )
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


class HistoryWriteTests(unittest.TestCase):
    def test_requires_an_open_history(self):
        self.assertTrue(should_store_history(SimpleNamespace(history_uid="h")))
        self.assertFalse(should_store_history(SimpleNamespace(history_uid=None)))

    def test_proactive_turns_are_skipped(self):
        context = SimpleNamespace(history_uid="h")
        self.assertFalse(should_store_history(context, skip_history=True))


class ToolCallPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_status_is_forwarded_then_persisted(self):
        forwarded = []
        stored = []

        class Context:
            character_config = SimpleNamespace(character_name="AIRI", avatar="a.png")
            turn_history_uid = "history-1"

            async def store_history_tool_call(self, **kwargs):
                stored.append(kwargs)
                return True

        async def stream():
            yield {
                "type": "tool_call_status",
                "tool_id": "t1",
                "tool_name": "kb_search",
                "status": "completed",
                "content": '{"ok": true}',
                "timestamp": "2026-10-30T04:40:00Z",
            }

        async def send(message):
            forwarded.append(message)

        await consume_agent_stream(
            stream(),
            context=Context(),
            channels=None,
            tts_manager=None,
            send_text_delta=send,
        )

        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0]["name"], "AIRI")
        self.assertEqual(
            stored,
            [
                {
                    "tool_id": "t1",
                    "tool_name": "kb_search",
                    "status": "completed",
                    "content": '{"ok": true}',
                    "timestamp": "2026-10-30T04:40:00Z",
                    "history_uid": "history-1",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
