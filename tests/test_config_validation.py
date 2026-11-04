import unittest
from pathlib import Path

from pydantic import ValidationError

from open_llm_vtuber.config_manager import read_yaml, validate_config
from open_llm_vtuber.config_manager.agent import BasicMemoryAgentConfig
from open_llm_vtuber.config_manager.asr import ASRConfig
from open_llm_vtuber.config_manager.tts import TTSConfig

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "config_templates" / "conf.default.yaml"
)
ZH_TEMPLATE = TEMPLATE.with_name("conf.ZH.default.yaml")


class SelectedModelConfigTests(unittest.TestCase):
    def test_tts_requires_config_for_selected_model(self):
        with self.assertRaises(ValidationError) as raised:
            TTSConfig(tts_model="azure_tts")

        self.assertIn("Missing configuration", str(raised.exception))

    def test_asr_requires_config_for_selected_model(self):
        with self.assertRaises(ValidationError) as raised:
            ASRConfig(asr_model="azure_asr")

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


class TemplateDefaultsTests(unittest.TestCase):
    def test_templates_keep_use_mcpp_at_the_model_default(self):
        default = BasicMemoryAgentConfig.model_fields["use_mcpp"].default
        for template in (TEMPLATE, ZH_TEMPLATE):
            with self.subTest(template=template.name):
                config = validate_config(read_yaml(str(template)))
                settings = config.character_config.agent_config.agent_settings

                self.assertEqual(settings.basic_memory_agent.use_mcpp, default)

    def test_templates_have_no_removed_agent_sections(self):
        for template in (TEMPLATE, ZH_TEMPLATE):
            with self.subTest(template=template.name):
                data = read_yaml(str(template))
                agent_config = data["character_config"]["agent_config"]

                self.assertNotIn("letta_agent", agent_config["agent_settings"])


if __name__ == "__main__":
    unittest.main()
