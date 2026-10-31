import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_llm_vtuber.tts import minimax_tts
from open_llm_vtuber.tts.minimax_tts import TTSEngine as MinimaxTTSEngine
from open_llm_vtuber.tts.siliconflow_tts import SiliconFlowTTS


class _Response:
    def __init__(self, chunks):
        self.raw = chunks


class MinimaxWriteTests(unittest.TestCase):
    def make_engine(self, path: Path):
        engine = MinimaxTTSEngine.__new__(MinimaxTTSEngine)
        engine.group_id = "group"
        engine.api_key = "key"
        engine.model = "model"
        engine.voice_id = "voice"
        engine.pronunciation_dict = ""
        engine.file_extension = "mp3"
        engine.generate_cache_file_name = lambda _name, _ext: str(path)
        return engine

    def test_writes_decoded_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.mp3"
            response = _Response([b'data:{"data": {"audio": "6869"}}'])

            with patch.object(minimax_tts.requests, "request", return_value=response):
                result = self.make_engine(path).generate_audio("hi")

            self.assertEqual(result, str(path))
            self.assertEqual(path.read_bytes(), b"hi")

    def test_empty_audio_returns_none_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.mp3"
            response = _Response([b'data:{"data": {}}'])

            with patch.object(minimax_tts.requests, "request", return_value=response):
                result = self.make_engine(path).generate_audio("hi")

            self.assertIsNone(result)
            self.assertFalse(path.exists())

    def test_failure_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.mp3"
            path.write_bytes(b"partial")

            with patch.object(
                minimax_tts.requests,
                "request",
                side_effect=RuntimeError("boom"),
            ):
                result = self.make_engine(path).generate_audio("hi")

            self.assertIsNone(result)
            self.assertFalse(path.exists())


class SiliconFlowFailureTests(unittest.TestCase):
    def test_missing_api_url_returns_none(self):
        engine = SiliconFlowTTS.__new__(SiliconFlowTTS)
        engine.api_url = None
        engine.response_format = "mp3"
        engine.sample_rate = 32000
        engine.stream = False
        engine.speed = 1.0
        engine.gain = 0
        engine.default_model = "model"
        engine.default_voice = "voice"
        engine.api_key = "key"

        self.assertIsNone(engine.generate_audio("hi"))


if __name__ == "__main__":
    unittest.main()
