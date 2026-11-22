import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from open_llm_vtuber.asr import azure_asr, groq_whisper_asr
from open_llm_vtuber.asr.azure_asr import VoiceRecognition as AzureASR
from open_llm_vtuber.asr.groq_whisper_asr import VoiceRecognition as GroqWhisperASR


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


class GroqWhisperASRTests(unittest.TestCase):
    def test_empty_lang_omits_language_param(self):
        mock_client = Mock()
        mock_client.audio.transcriptions.create.return_value = "hello"
        with patch.object(groq_whisper_asr, "Groq", return_value=mock_client):
            engine = GroqWhisperASR("k", model="whisper-large-v3", lang="")
            out = engine.transcribe_np(np.zeros(160, dtype=np.float32))

        self.assertEqual(out, "hello")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        self.assertNotIn("language", kwargs)
        self.assertNotIn("prompt", kwargs)

    def test_zh_lang_sets_language_and_simplified_prompt(self):
        mock_client = Mock()
        mock_client.audio.transcriptions.create.return_value = "怎么选课"
        with patch.object(groq_whisper_asr, "Groq", return_value=mock_client):
            engine = GroqWhisperASR("k", model="whisper-large-v3", lang="zh")
            out = engine.transcribe_np(np.zeros(160, dtype=np.float32))

        self.assertEqual(out, "怎么选课")
        kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(kwargs["language"], "zh")
        self.assertEqual(kwargs["prompt"], "简体中文。")


if __name__ == "__main__":
    unittest.main()
