import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.stateless_llm import stateless_llm_with_template
    from open_llm_vtuber.agent.stateless_llm.stateless_llm_with_template import (
        AsyncLLMWithTemplate,
    )
    from open_llm_vtuber.tts.cartesia_tts import TTSEngine as CartesiaTTSEngine
    from open_llm_vtuber.tts.gpt_sovits_tts import TTSEngine as GPTSoVITSTTSEngine
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


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


class TemplateLLMErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_error_path_uses_existing_completion_url(self):
        class _Template:
            def render(self, **_kwargs):
                return "prompt"

        llm = AsyncLLMWithTemplate.__new__(AsyncLLMWithTemplate)
        llm.model = "model"
        llm.template = _Template()
        llm.temperature = 1.0
        llm.completion_url = "http://localhost/v1"
        llm.prompt_headers = {}

        with patch.object(
            stateless_llm_with_template.requests,
            "post",
            side_effect=RuntimeError("boom"),
        ):
            output = [token async for token in llm.chat_completion([], None)]

        self.assertEqual(len(output), 1)
        self.assertIn("Error calling", output[0])


if __name__ == "__main__":
    unittest.main()
