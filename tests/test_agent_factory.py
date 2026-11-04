import importlib.util
import unittest
from typing import get_args

from loguru import logger
from pydantic import ValidationError

from open_llm_vtuber.agent.agent_factory import AgentFactory
from open_llm_vtuber.config_manager import agent as agent_config_module
from open_llm_vtuber.config_manager.agent import AgentConfig, AgentSettings


class Mem0RemovalTests(unittest.TestCase):
    def test_mem0_is_not_a_selectable_agent(self):
        field = AgentConfig.model_fields["conversation_agent_choice"]

        self.assertNotIn("mem0_agent", get_args(field.annotation))

    def test_factory_rejects_mem0_choice(self):
        with self.assertRaises(ValueError):
            AgentFactory.create_agent(
                conversation_agent_choice="mem0_agent",
                agent_settings={},
                llm_configs={},
                system_prompt="system",
            )


class LettaRemovalTests(unittest.TestCase):
    def test_letta_agent_module_is_gone(self):
        self.assertIsNone(
            importlib.util.find_spec("open_llm_vtuber.agent.agents.letta_agent")
        )

    def test_factory_rejects_letta_choice(self):
        with self.assertRaises(ValueError):
            AgentFactory.create_agent(
                conversation_agent_choice="letta_agent",
                agent_settings={},
                llm_configs={},
                system_prompt="system",
            )

    def test_letta_choice_fails_validation_naming_the_removed_agent(self):
        with self.assertRaises(ValidationError) as raised:
            AgentConfig(
                conversation_agent_choice="letta_agent",
                agent_settings={},
                llm_configs={},
            )

        message = str(raised.exception)
        self.assertIn("letta_agent", message)
        self.assertIn("removed", message)

    def test_leftover_letta_settings_are_ignored_with_one_warning(self):
        agent_config_module._removed_agent_warnings.discard("letta_agent")
        section = {"host": "localhost", "port": 8283, "id": "agent-id"}
        messages = []
        handler_id = logger.add(
            lambda message: messages.append(str(message)), level="WARNING"
        )
        try:
            first = AgentSettings(letta_agent=section)
            AgentSettings(letta_agent=section)
        finally:
            logger.remove(handler_id)

        self.assertNotIn("letta_agent", first.model_dump())
        self.assertEqual(
            len([message for message in messages if "letta_agent" in message]), 1
        )


if __name__ == "__main__":
    unittest.main()
