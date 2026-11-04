import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from open_llm_vtuber.tts import edge_tts as edge_tts_module
from open_llm_vtuber.tts import gpt_sovits_tts, x_tts
from open_llm_vtuber.tts.cartesia_tts import TTSEngine as CartesiaTTSEngine
from open_llm_vtuber.tts.elevenlabs_tts import TTSEngine as ElevenLabsTTSEngine
from open_llm_vtuber.tts.pyttsx3_tts import TTSEngine as Pyttsx3TTSEngine


class _Response:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


def _http_engine(module, path: Path):
    engine = module.TTSEngine()
    engine.generate_cache_file_name = lambda _name, _ext: str(path)
    return engine


class SelfHostedHTTPEngineTests(unittest.TestCase):
    cases = ((x_tts, "post"), (gpt_sovits_tts, "get"))

    def test_success_writes_body(self):
        for module, method in self.cases:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "audio.wav"
                    with patch.object(
                        module.requests, method, return_value=_Response(200, b"wav")
                    ):
                        result = _http_engine(module, path).generate_audio("hi")

                    self.assertEqual(result, str(path))
                    self.assertEqual(path.read_bytes(), b"wav")

    def test_error_status_returns_none(self):
        for module, method in self.cases:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "audio.wav"
                    with patch.object(
                        module.requests, method, return_value=_Response(500)
                    ):
                        result = _http_engine(module, path).generate_audio("hi")

                    self.assertIsNone(result)
                    self.assertFalse(path.exists())

    def test_request_exception_returns_none(self):
        for module, method in self.cases:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "audio.wav"
                    with patch.object(
                        module.requests,
                        method,
                        side_effect=requests.ConnectionError("refused"),
                    ):
                        result = _http_engine(module, path).generate_audio("hi")

                    self.assertIsNone(result)

    def test_write_failure_removes_partial_file(self):
        class _BrokenBody:
            status_code = 200

            @property
            def content(self):
                raise OSError("disk full")

        for module, method in self.cases:
            with self.subTest(module=module.__name__):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "audio.wav"
                    with patch.object(
                        module.requests, method, return_value=_BrokenBody()
                    ):
                        result = _http_engine(module, path).generate_audio("hi")

                    self.assertIsNone(result)
                    self.assertFalse(path.exists())


class EdgeTTSFailureTests(unittest.TestCase):
    def test_failure_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.mp3"

            def save_partial(file_name):
                Path(file_name).write_bytes(b"partial")
                raise RuntimeError("blocked")

            communicate = MagicMock()
            communicate.return_value.save_sync.side_effect = save_partial
            engine = edge_tts_module.TTSEngine(voice="voice")
            engine.generate_cache_file_name = lambda _name, _ext: str(path)

            with patch.object(edge_tts_module.edge_tts, "Communicate", communicate):
                result = engine.generate_audio("hi")

            self.assertIsNone(result)
            self.assertFalse(path.exists())


class CosyvoicePredictTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.predict.return_value = "out.wav"
        fake = types.ModuleType("gradio_client")
        fake.Client = MagicMock(return_value=self.client)
        fake.file = lambda url: ("file", url)
        fake.handle_file = lambda url: ("handle_file", url)
        # patch.dict restores the original module table, including the
        # engine modules re-imported below against the fake client.
        patcher = patch.dict(sys.modules, {"gradio_client": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules.pop("open_llm_vtuber.tts.cosyvoice_tts", None)
        sys.modules.pop("open_llm_vtuber.tts.cosyvoice2_tts", None)

    def common(self, wrap):
        url = (
            "https://github.com/gradio-app/gradio/raw/main/test/test_files/"
            "audio_sample.wav"
        )
        return {
            "tts_text": "hi",
            "mode_checkbox_group": "预训练音色",
            "sft_dropdown": "中文女",
            "prompt_text": "",
            "prompt_wav_upload": (wrap, url),
            "prompt_wav_record": (wrap, url),
            "instruct_text": "",
            "seed": 0,
            "api_name": "/generate_audio",
        }

    def test_cosyvoice_predict_arguments(self):
        from open_llm_vtuber.tts.cosyvoice_tts import TTSEngine

        self.assertEqual(TTSEngine().generate_audio("hi"), "out.wav")
        self.client.predict.assert_called_once_with(**self.common("file"))

    def test_cosyvoice2_predict_arguments(self):
        from open_llm_vtuber.tts.cosyvoice2_tts import TTSEngine

        self.assertEqual(TTSEngine().generate_audio("hi"), "out.wav")
        self.client.predict.assert_called_once_with(
            **self.common("handle_file"), stream=False, speed=1.0
        )


def _partial_then_fail():
    yield b"partial"
    raise RuntimeError("stream dropped")


def _bare_engine(cls, path: Path, **attrs):
    engine = cls.__new__(cls)
    for name, value in attrs.items():
        setattr(engine, name, value)
    engine.generate_cache_file_name = lambda _name, _ext: str(path)
    return engine


class SDKEngineFailureTests(unittest.TestCase):
    """SDK engines return None and drop the partial file instead of raising."""

    def test_cartesia_stream_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.wav"
            client = MagicMock()
            client.tts.bytes.return_value = _partial_then_fail()
            engine = _bare_engine(
                CartesiaTTSEngine,
                path,
                client=client,
                output_format="wav",
                voice_id="voice",
                model_id="model",
                language="en",
                volume=1.0,
                speed=1.0,
                emotion="neutral",
            )

            self.assertIsNone(engine.generate_audio("hi"))
            self.assertFalse(path.exists())

    def test_elevenlabs_stream_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.mp3"
            client = MagicMock()
            client.text_to_speech.convert.return_value = _partial_then_fail()
            engine = _bare_engine(
                ElevenLabsTTSEngine,
                path,
                client=client,
                file_extension="mp3",
                voice_id="voice",
                model_id="model",
                output_format="mp3_44100_128",
                stability=0.5,
                similarity_boost=0.5,
                style=0.0,
                use_speaker_boost=True,
            )

            self.assertIsNone(engine.generate_audio("hi"))
            self.assertFalse(path.exists())

    def test_pyttsx3_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.aiff"
            backend = MagicMock()
            backend.save_to_file.side_effect = lambda text, filename: Path(
                filename
            ).write_bytes(b"partial")
            backend.runAndWait.side_effect = RuntimeError("driver crashed")
            engine = _bare_engine(
                Pyttsx3TTSEngine,
                path,
                engine=backend,
                file_extension="aiff",
                lock=threading.Lock(),
            )

            self.assertIsNone(engine.generate_audio("hi"))
            self.assertFalse(path.exists())


class SparkTTSFailureTests(unittest.TestCase):
    def setUp(self):
        fake = types.ModuleType("gradio_client")
        fake.Client = MagicMock()
        fake.file = lambda url: url
        patcher = patch.dict(sys.modules, {"gradio_client": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.modules.pop("open_llm_vtuber.tts.spark_tts", None)

    def test_copy_failure_removes_partial_file(self):
        from open_llm_vtuber.tts import spark_tts

        def copy_partial(_source, target):
            Path(target).write_bytes(b"partial")
            raise OSError("disk full")

        for api_name in ("voice_clone", "voice_creation"):
            with self.subTest(api_name=api_name):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "audio.wav"
                    engine = spark_tts.TTSEngine(api_name=api_name)
                    engine.client.predict.return_value = "source.wav"
                    engine.generate_cache_file_name = MagicMock(return_value=str(path))

                    with patch.object(
                        spark_tts.shutil, "copyfile", side_effect=copy_partial
                    ):
                        result = engine.generate_audio("hi")

                    self.assertIsNone(result)
                    self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
