import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from pydantic import ValidationError

    from open_llm_vtuber.config_manager import read_yaml, validate_config
    from open_llm_vtuber.config_manager.asr import ASRConfig
    from open_llm_vtuber.config_manager.tts import TTSConfig
    from open_llm_vtuber.config_manager.vad import VADConfig
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


TEMPLATE = (
    Path(__file__).resolve().parents[1] / "config_templates" / "conf.default.yaml"
)


class SelectedModelConfigTests(unittest.TestCase):
    def test_tts_requires_config_for_selected_model(self):
        with self.assertRaises(ValidationError) as raised:
            TTSConfig(tts_model="azure_tts")

        self.assertIn("Missing configuration", str(raised.exception))

    def test_asr_requires_config_for_selected_model(self):
        with self.assertRaises(ValidationError) as raised:
            ASRConfig(asr_model="azure_asr")

        self.assertIn("Missing configuration", str(raised.exception))

    def test_vad_requires_config_for_selected_model(self):
        with self.assertRaises(ValidationError) as raised:
            VADConfig(vad_model="silero_vad")

        self.assertIn("Missing configuration", str(raised.exception))

    def test_full_config_rejects_missing_tts_section(self):
        data = read_yaml(str(TEMPLATE))
        data["character_config"]["tts_config"] = {"tts_model": "azure_tts"}

        with self.assertRaises(ValidationError):
            validate_config(data)


class DescriptionKeyTests(unittest.TestCase):
    def test_descriptions_reference_existing_fields(self):
        from open_llm_vtuber.config_manager.i18n import I18nMixin

        def all_subclasses(cls):
            for subclass in cls.__subclasses__():
                yield subclass
                yield from all_subclasses(subclass)

        offenders = []
        for config_class in all_subclasses(I18nMixin):
            unknown = set(config_class.DESCRIPTIONS) - set(config_class.model_fields)
            if unknown:
                offenders.append((config_class.__name__, sorted(unknown)))

        self.assertEqual(offenders, [])


class CharacterNameFallbackTests(unittest.TestCase):
    def test_empty_character_name_falls_back_to_conf_name(self):
        data = read_yaml(str(TEMPLATE))
        data["character_config"]["character_name"] = ""

        config = validate_config(data)

        self.assertEqual(
            config.character_config.character_name,
            config.character_config.conf_name,
        )


if __name__ == "__main__":
    unittest.main()
