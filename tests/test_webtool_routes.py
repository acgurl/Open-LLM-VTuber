import unittest

from fastapi import FastAPI
from starlette.testclient import TestClient

from open_llm_vtuber.routes import init_webtool_routes


class FakeTTSEngine:
    def __init__(self) -> None:
        self.calls = []
        self.fail = False
        self.return_none = False

    async def async_generate_audio(self, text: str, file_name_no_ext: str):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("synthesis failed")
        if self.return_none:
            return None
        return f"audio/{file_name_no_ext}.wav"


class FakeContext:
    def __init__(self) -> None:
        self.tts_engine = FakeTTSEngine()
        self.asr_engine = None


class TTSWebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = FakeContext()
        app = FastAPI()
        app.include_router(init_webtool_routes(self.context))
        self.client = TestClient(app)

    def test_splits_sentences_and_streams_audio(self) -> None:
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "你好. Hello! 世界"})
            messages = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(
            [message["status"] for message in messages],
            ["partial", "partial", "partial", "complete"],
        )
        self.assertEqual(
            [message["text"] for message in messages[:3]],
            ["你好.", "Hello!", "世界."],
        )
        self.assertTrue(
            all(message["audioPath"].startswith("audio/") for message in messages[:3])
        )
        self.assertEqual(
            self.context.tts_engine.calls,
            ["你好.", "Hello!", "世界."],
        )

    def test_rejects_text_over_character_limit(self) -> None:
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "a" * 2001})
            message = websocket.receive_json()

        self.assertEqual(
            message,
            {"status": "error", "message": "Text exceeds the 2000-character limit"},
        )
        self.assertEqual(self.context.tts_engine.calls, [])

    def test_rejects_text_over_sentence_limit(self) -> None:
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "Hello. " * 31})
            message = websocket.receive_json()

        self.assertEqual(message["status"], "error")
        self.assertIn("30-sentence limit", message["message"])
        self.assertEqual(self.context.tts_engine.calls, [])

    def test_reports_generation_failure_and_keeps_connection_open(self) -> None:
        self.context.tts_engine.fail = True
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "Hello."})
            error = websocket.receive_json()

            self.context.tts_engine.fail = False
            websocket.send_json({"text": "Hello."})
            partial = websocket.receive_json()
            complete = websocket.receive_json()

        self.assertEqual(
            error, {"status": "error", "message": "Failed to generate audio"}
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(complete, {"status": "complete"})

    def test_reports_none_audio_as_generation_failure(self) -> None:
        self.context.tts_engine.return_none = True
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "Hello."})
            error = websocket.receive_json()

            self.context.tts_engine.return_none = False
            websocket.send_json({"text": "Hello."})
            partial = websocket.receive_json()
            complete = websocket.receive_json()

        self.assertEqual(
            error, {"status": "error", "message": "Failed to generate audio"}
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(complete, {"status": "complete"})


if __name__ == "__main__":
    unittest.main()
