import sys
import unittest
from pathlib import Path
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.agent_factory import AgentFactory
    from open_llm_vtuber.config_manager.agent import AgentConfig
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


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


if __name__ == "__main__":
    unittest.main()
