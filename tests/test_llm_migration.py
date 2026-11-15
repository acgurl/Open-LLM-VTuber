"""Configurations written for removed LLM providers keep loading."""

import copy
import unittest
from pathlib import Path

from pydantic import ValidationError

from open_llm_vtuber.config_manager import read_yaml, validate_config
from open_llm_vtuber.config_manager.agent import AgentConfig
from open_llm_vtuber.config_manager.llm_migration import (
    LEGACY_OPENAI_COMPATIBLE,
    legacy_settings,
    migrate_agent_config,
)
from open_llm_vtuber.config_manager.stateless_llm import (
    OpenAICompatibleConfig,
    StatelessLLMConfigs,
)
from open_llm_vtuber.utils.dicts import deep_merge

# A made-up value: nothing here is a real credential.
FAKE_KEY = "fake-key-for-tests"
TEMPLATE = (
    Path(__file__).resolve().parents[1] / "config_templates" / "conf.default.yaml"
)


def _agent_config(provider, pool):
    return {
        "conversation_agent_choice": "basic_memory_agent",
        "agent_settings": {"basic_memory_agent": {"llm_provider": provider}},
        "llm_configs": pool,
    }


class LegacyProviderTests(unittest.TestCase):
    def test_pool_has_one_provider_per_protocol(self):
        self.assertEqual(
            set(StatelessLLMConfigs.model_fields),
            {
                "openai_compatible_llm",
                "openai_responses_llm",
                "claude_llm",
                "vertex_llm",
            },
        )
        self.assertFalse(
            set(LEGACY_OPENAI_COMPATIBLE) & set(StatelessLLMConfigs.model_fields)
        )

    def test_every_removed_provider_validates_after_mapping(self):
        for provider in LEGACY_OPENAI_COMPATIBLE:
            settings = {"llm_api_key": FAKE_KEY, "model": "m", "base_url": None}
            if provider == "stateless_llm_with_template":
                settings.update(base_url="http://localhost:8080/v1", template="CHATML")
            config = AgentConfig(**_agent_config(provider, {provider: settings}))

            self.assertEqual(
                config.agent_settings.basic_memory_agent.llm_provider,
                "openai_compatible_llm",
                provider,
            )
            self.assertTrue(config.llm_configs.openai_compatible_llm.base_url)

    def test_selected_provider_keeps_its_old_defaults(self):
        config = AgentConfig(
            **_agent_config(
                "deepseek_llm",
                {
                    "deepseek_llm": {
                        "llm_api_key": FAKE_KEY,
                        "model": "deepseek-chat",
                        "temperature": 0.7,
                    }
                },
            )
        )
        section = config.llm_configs.openai_compatible_llm

        self.assertEqual(section.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(section.model, "deepseek-chat")
        self.assertEqual(section.temperature, 0.7)
        self.assertEqual(section.interrupt_method, "user")

    def test_ollama_gets_placeholder_key_and_drops_its_own_settings(self):
        settings = legacy_settings(
            "ollama_llm",
            {
                "base_url": "http://gpu-box:11434/v1",
                "model": "qwen",
                "keep_alive": -1,
                "unload_at_exit": True,
            },
        )

        self.assertEqual(settings["base_url"], "http://gpu-box:11434/v1")
        self.assertEqual(settings["llm_api_key"], "default_api_key")
        self.assertEqual(settings["interrupt_method"], "system")
        self.assertNotIn("keep_alive", settings)
        OpenAICompatibleConfig.model_validate(settings)

    def test_selected_provider_replaces_an_unrelated_compatible_section(self):
        data = _agent_config(
            "deepseek_llm",
            {
                "openai_compatible_llm": {
                    "base_url": "http://127.0.0.1:8080/v1",
                    "llm_api_key": "gateway-key",
                    "model": "gateway-model",
                },
                "deepseek_llm": {"llm_api_key": FAKE_KEY, "model": "deepseek-chat"},
                "groq_llm": {"llm_api_key": "unused", "model": "llama"},
            },
        )

        section = AgentConfig(**data).llm_configs.openai_compatible_llm

        self.assertEqual(section.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(section.llm_api_key, FAKE_KEY)
        self.assertEqual(section.model, "deepseek-chat")

    def test_unselected_removed_sections_are_ignored(self):
        data = _agent_config(
            "openai_compatible_llm",
            {
                "openai_compatible_llm": {
                    "base_url": "http://127.0.0.1:8080/v1",
                    "llm_api_key": FAKE_KEY,
                    "model": "gateway-model",
                },
                # No key at all: would not validate if it were still read.
                "deepseek_llm": {"model": "deepseek-chat"},
            },
        )

        section = AgentConfig(**data).llm_configs.openai_compatible_llm

        self.assertEqual(section.model, "gateway-model")

    def test_validation_does_not_change_the_callers_data(self):
        data = _agent_config(
            "groq_llm", {"groq_llm": {"llm_api_key": FAKE_KEY, "model": "llama"}}
        )
        before = copy.deepcopy(data)

        AgentConfig(**data)
        AgentConfig.model_validate(data)

        self.assertEqual(data, before)

    def test_old_character_file_overrides_a_migrated_conf(self):
        """A character naming ``deepseek_llm`` on top of a renamed conf.yaml."""
        base = _agent_config(
            "openai_compatible_llm",
            {
                "openai_compatible_llm": {
                    "base_url": "https://api.deepseek.com/v1",
                    "llm_api_key": FAKE_KEY,
                    "model": "deepseek-chat",
                }
            },
        )
        character = {
            "agent_settings": {"basic_memory_agent": {"llm_provider": "deepseek_llm"}},
            "llm_configs": {"deepseek_llm": {"model": "deepseek-flash"}},
        }

        section = AgentConfig(
            **deep_merge(base, character)
        ).llm_configs.openai_compatible_llm

        self.assertEqual(section.model, "deepseek-flash")
        self.assertEqual(section.llm_api_key, FAKE_KEY)
        self.assertEqual(section.base_url, "https://api.deepseek.com/v1")

    def test_old_character_file_overrides_an_old_conf(self):
        base = _agent_config(
            "deepseek_llm",
            {"deepseek_llm": {"llm_api_key": FAKE_KEY, "model": "deepseek-chat"}},
        )
        character = {"llm_configs": {"deepseek_llm": {"model": "deepseek-flash"}}}

        section = AgentConfig(
            **deep_merge(base, character)
        ).llm_configs.openai_compatible_llm

        self.assertEqual(section.model, "deepseek-flash")
        self.assertEqual(section.llm_api_key, FAKE_KEY)

    def test_migration_reports_what_it_changed(self):
        data = _agent_config(
            "mistral_llm", {"mistral_llm": {"llm_api_key": FAKE_KEY, "model": "m"}}
        )

        changes = migrate_agent_config(data)

        self.assertIn("llm_provider: mistral_llm -> openai_compatible_llm", changes)
        self.assertNotIn("mistral_llm", data["llm_configs"])
        self.assertEqual(migrate_agent_config(data), [])

    def test_full_config_with_a_removed_provider_loads(self):
        data = read_yaml(str(TEMPLATE))
        agent = data["character_config"]["agent_config"]
        agent["agent_settings"]["basic_memory_agent"]["llm_provider"] = "ollama_llm"
        agent["llm_configs"] = {
            "ollama_llm": {
                "base_url": "http://localhost:11434/v1",
                "model": "qwen2.5:latest",
                "temperature": 1.0,
                "keep_alive": -1,
                "unload_at_exit": True,
            }
        }

        config = validate_config(data).character_config.agent_config

        self.assertEqual(
            config.agent_settings.basic_memory_agent.llm_provider,
            "openai_compatible_llm",
        )
        self.assertEqual(
            config.llm_configs.openai_compatible_llm.model, "qwen2.5:latest"
        )

    def test_unknown_provider_is_still_rejected(self):
        with self.assertRaises(ValidationError):
            AgentConfig(**_agent_config("made_up_llm", {}))


if __name__ == "__main__":
    unittest.main()
