import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from open_llm_vtuber.websocket_handler import WebSocketHandler


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class RawAudioWithoutVADTests(unittest.IsolatedAsyncioTestCase):
    async def test_ignores_raw_audio_when_vad_is_disabled(self):
        handler = WebSocketHandler(default_context_cache=Mock())
        handler.client_contexts["client"] = SimpleNamespace(vad_engine=None)
        handler.received_data_buffers["client"] = np.array([])
        websocket = FakeWebSocket()

        await handler._handle_raw_audio_data(websocket, "client", {"audio": [0.1, 0.2]})

        self.assertEqual(websocket.sent, [])


class FakeVADEngine:
    def __init__(self, segments) -> None:
        self._segments = segments

    def detect_speech(self, audio_data):
        yield from self._segments


class RawAudioNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalizes_vad_segments_to_the_asr_float_range(self):
        pcm = (np.full(600, 16384, dtype=np.float32)).astype(np.int16).tobytes()
        handler = WebSocketHandler(default_context_cache=Mock())
        handler.client_contexts["client"] = SimpleNamespace(
            vad_engine=FakeVADEngine([b"<|PAUSE|>", pcm])
        )
        handler.received_data_buffers["client"] = np.array([])
        websocket = FakeWebSocket()

        await handler._handle_raw_audio_data(
            websocket, "client", {"audio": [0.1] * 512}
        )

        buffer = handler.received_data_buffers["client"]
        self.assertEqual(len(buffer), 600)
        self.assertTrue(np.allclose(buffer, 0.5))
        self.assertEqual(
            [message["text"] for message in websocket.sent],
            ["interrupt", "mic-audio-end"],
        )


if __name__ == "__main__":
    unittest.main()
