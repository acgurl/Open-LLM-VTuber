import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.agents.agent_interface import AgentInterface
    from open_llm_vtuber.agent.agents.hume_ai import HumeAIAgent
    from open_llm_vtuber.agent.agents.letta_agent import LettaAgent
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class DefaultInterruptTests(unittest.TestCase):
    def test_hume_inherits_default_interrupt_handler(self):
        self.assertIs(HumeAIAgent.handle_interrupt, AgentInterface.handle_interrupt)

    def test_letta_inherits_default_interrupt_handler(self):
        self.assertIs(LettaAgent.handle_interrupt, AgentInterface.handle_interrupt)


if __name__ == "__main__":
    unittest.main()
