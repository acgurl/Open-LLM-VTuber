import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.websocket_handler import WebSocketHandler
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


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


if __name__ == "__main__":
    unittest.main()
