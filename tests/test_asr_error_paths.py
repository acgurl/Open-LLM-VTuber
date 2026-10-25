import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.asr import azure_asr
    from open_llm_vtuber.asr.azure_asr import VoiceRecognition as AzureASR
    from open_llm_vtuber.asr.sherpa_onnx_asr import (
        VoiceRecognition as SherpaOnnxASR,
    )
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class SherpaModelPathTests(unittest.TestCase):
    def setUp(self):
        self.engine = SherpaOnnxASR.__new__(SherpaOnnxASR)
        self.engine.model_type = "sense_voice"
        self.engine.tokens = "tokens.txt"
        self.engine.num_threads = 1
        self.engine.use_itn = True
        self.engine.debug = False
        self.engine.provider = "cpu"

    def test_missing_sense_voice_path_raises_clear_error(self):
        self.engine.sense_voice = None

        with self.assertRaises(FileNotFoundError):
            self.engine._create_recognizer()

    def test_missing_custom_sense_voice_path_raises_clear_error(self):
        self.engine.sense_voice = "/missing/model.onnx"

        with self.assertRaises(FileNotFoundError):
            self.engine._create_recognizer()

    def test_unknown_model_type_is_rejected(self):
        self.engine.model_type = "unknown"

        with self.assertRaises(ValueError):
            self.engine._create_recognizer()


class AzureConfigTests(unittest.TestCase):
    def test_languages_default_is_not_a_mutable_argument(self):
        default = inspect.signature(AzureASR.__init__).parameters["languages"].default

        self.assertIsNone(default)

    def test_default_languages_are_applied(self):
        with patch.object(
            azure_asr.speechsdk, "SpeechConfig", return_value=Mock()
        ) as speech_config:
            engine = AzureASR("key", "region")

        speech_config.assert_called_once_with(subscription="key", region="region")
        engine.speech_config.set_property.assert_called_once()


class AzureTranscribeTests(unittest.IsolatedAsyncioTestCase):
    async def test_recognition_runs_off_the_event_loop(self):
        engine = AzureASR.__new__(AzureASR)
        engine.speech_config = object()
        result = SimpleNamespace(
            reason=azure_asr.speechsdk.ResultReason.RecognizedSpeech,
            text="你好",
            properties=Mock(get=Mock(return_value="zh-CN")),
        )

        with (
            patch.object(
                azure_asr.asyncio,
                "to_thread",
                new=AsyncMock(return_value=result),
            ) as to_thread,
            patch.object(azure_asr.speechsdk, "SpeechRecognizer", return_value=Mock()),
            patch.object(azure_asr.sf, "write"),
            patch.object(azure_asr.os, "makedirs"),
            patch.object(azure_asr.os.path, "exists", return_value=False),
        ):
            text = await engine.async_transcribe_np(np.zeros(4, dtype=np.float32))

        self.assertEqual(text, "你好")
        to_thread.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
