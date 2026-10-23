import sys
import unittest
from pathlib import Path
from typing import get_args, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.asr.asr_factory import _ASR_BUILDERS, ASRFactory
    from open_llm_vtuber.config_manager.asr import ASRConfig
    from open_llm_vtuber.config_manager.tts_preprocessor import TranslatorConfig
    from open_llm_vtuber.config_manager.vad import VADConfig
    from open_llm_vtuber.translate.translate_factory import (
        _TRANSLATOR_BUILDERS,
        TranslateFactory,
    )
    from open_llm_vtuber.vad.vad_factory import _VAD_BUILDERS, VADFactory
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


def _literal_values(annotation) -> set:
    args = get_args(annotation)
    if args and getattr(args[0], "__origin__", None) is Literal:
        return set(get_args(args[0]))
    return {arg for arg in args if isinstance(arg, str)}


class FactoryRegistryTests(unittest.TestCase):
    def test_asr_registry_covers_config_choices(self):
        choices = _literal_values(ASRConfig.model_fields["asr_model"].annotation)
        self.assertTrue(choices <= set(_ASR_BUILDERS))

    def test_vad_registry_covers_config_choices(self):
        choices = _literal_values(VADConfig.model_fields["vad_model"].annotation)
        self.assertTrue(choices <= set(_VAD_BUILDERS))

    def test_translate_registry_covers_config_choices(self):
        choices = _literal_values(
            TranslatorConfig.model_fields["translate_provider"].annotation
        )
        self.assertTrue(choices <= set(_TRANSLATOR_BUILDERS))

    def test_unknown_asr_choice_raises(self):
        with self.assertRaises(ValueError):
            ASRFactory.get_asr_system("missing")

    def test_unknown_vad_choice_raises(self):
        with self.assertRaises(ValueError):
            VADFactory.get_vad_engine("missing")

    def test_unknown_translator_choice_raises(self):
        with self.assertRaises(ValueError):
            TranslateFactory.get_translator("missing", {})


if __name__ == "__main__":
    unittest.main()
