import inspect
import unittest

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


if __name__ == "__main__":
    unittest.main()
