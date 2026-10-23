import sys
import unittest
from pathlib import Path
from typing import get_args, Literal
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.asr.asr_factory import _ASR_BUILDERS, ASRFactory
    from open_llm_vtuber.config_manager.asr import ASRConfig
    from open_llm_vtuber.config_manager.tts import TTSConfig
    from open_llm_vtuber.config_manager.tts_preprocessor import TranslatorConfig
    from open_llm_vtuber.config_manager.vad import VADConfig
    from open_llm_vtuber.translate.translate_factory import (
        _TRANSLATOR_BUILDERS,
        TranslateFactory,
    )
    from open_llm_vtuber.tts.tts_factory import _TTS_ENGINE_BUILDERS, TTSFactory
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

    def test_tts_registry_covers_config_choices(self):
        choices = _literal_values(TTSConfig.model_fields["tts_model"].annotation)
        self.assertTrue(choices <= set(_TTS_ENGINE_BUILDERS))

    def test_azure_tts_builder_preserves_argument_mapping(self):
        with patch("open_llm_vtuber.tts.azure_tts.TTSEngine") as engine:
            TTSFactory.get_tts_engine(
                "azure_tts",
                api_key="key",
                region="region",
                voice="voice",
                pitch=0,
                rate=1,
            )

        engine.assert_called_once_with(
            api_key="key",
            region="region",
            voice="voice",
            pitch=0,
            rate=1,
            tailing_silence_ms=0,
        )

    def test_edge_tts_builder_passes_voice_positionally(self):
        with patch("open_llm_vtuber.tts.edge_tts.TTSEngine") as engine:
            TTSFactory.get_tts_engine("edge_tts", voice="voice")

        engine.assert_called_once_with("voice")

    def test_unknown_tts_choice_raises(self):
        with self.assertRaises(ValueError):
            TTSFactory.get_tts_engine("missing")

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
