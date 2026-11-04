import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from open_llm_vtuber.tts import edge_tts as edge_tts_module
from open_llm_vtuber.tts import gpt_sovits_tts, x_tts


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


if __name__ == "__main__":
    unittest.main()
