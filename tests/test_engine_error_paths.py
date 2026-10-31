import inspect
import unittest
from unittest.mock import patch

from open_llm_vtuber.agent.stateless_llm import stateless_llm_with_template
from open_llm_vtuber.agent.stateless_llm.stateless_llm_with_template import (
    AsyncLLMWithTemplate,
)
from open_llm_vtuber.tts.cartesia_tts import TTSEngine as CartesiaTTSEngine
from open_llm_vtuber.tts.gpt_sovits_tts import TTSEngine as GPTSoVITSTTSEngine


class CartesiaFailureTests(unittest.TestCase):
    def test_missing_client_returns_none_instead_of_error_text(self):
        engine = CartesiaTTSEngine.__new__(CartesiaTTSEngine)
        engine.client = None

        self.assertIsNone(engine.generate_audio("hello"))


class GPTSoVITSDefaultsTests(unittest.TestCase):
    def test_streaming_mode_default_is_boolean_string(self):
        default = (
            inspect.signature(GPTSoVITSTTSEngine.__init__)
            .parameters["streaming_mode"]
            .default
        )

        self.assertEqual(default, "true")


class _FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _make_client(lines=None, fail=False):
    class _Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            if fail:
                raise RuntimeError("boom")
            return _FakeResponse(lines or [])

    return _Client


def _make_template_llm():
    class _Template:
        def render(self, **_kwargs):
            return "prompt"

    llm = AsyncLLMWithTemplate.__new__(AsyncLLMWithTemplate)
    llm.model = "model"
    llm.template = _Template()
    llm.temperature = 1.0
    llm.completion_url = "http://localhost/v1"
    llm.prompt_headers = {}
    llm.eot_token = "<eot>"
    return llm


class TemplateLLMErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_path_uses_existing_completion_url(self):
        llm = _make_template_llm()

        with patch.object(
            stateless_llm_with_template.httpx,
            "AsyncClient",
            _make_client(fail=True),
        ):
            output = [token async for token in llm.chat_completion([], None)]

        self.assertEqual(len(output), 1)
        self.assertIn("Error calling", output[0])

    async def test_streams_lines_from_async_client(self):
        llm = _make_template_llm()
        lines = [
            'data: {"content": "你", "stop": false}',
            'data: {"content": "好", "stop": false}',
            'data: {"content": "", "stop": true}',
        ]

        with patch.object(
            stateless_llm_with_template.httpx,
            "AsyncClient",
            _make_client(lines=lines),
        ):
            output = [token async for token in llm.chat_completion([], None)]

        self.assertEqual(output, ["你", "好"])

    def test_clean_raw_bytes_accepts_bytes_and_text(self):
        llm = _make_template_llm()
        expected = {"content": "x"}

        self.assertEqual(llm._clean_raw_bytes(b'data: {"content": "x"}'), expected)
        self.assertEqual(llm._clean_raw_bytes('data: {"content": "x"}'), expected)


if __name__ == "__main__":
    unittest.main()
