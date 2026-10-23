from abc import ABC, abstractmethod
from typing import AsyncIterator
from loguru import logger

from ..output_types import BaseOutput
from ..input_types import BaseInput


class AgentInterface(ABC):
    """Base interface for all agent implementations"""

    @abstractmethod
    async def chat(self, input_data: BaseInput) -> AsyncIterator[BaseOutput]:
        """
        Chat with the agent asynchronously.

        This function should be implemented by the agent.
        Output type depends on the agent's output_type:
        - SentenceOutput: For text-based responses with display and TTS text
        - AudioOutput: For direct audio output with display text and transcript

        Args:
            input_data: BaseInput - User input data

        Returns:
            AsyncIterator[BaseOutput] - Stream of agent outputs
        """
        logger.critical("Agent: No chat function set.")
        raise ValueError("Agent: No chat function set.")

    def handle_interrupt(self, heard_response: str) -> None:
        """
        Handle user interruption. This function will be called when the agent is interrupted.

        Agents that keep their own conversation state should override this.

        Args:
            heard_response: str - The part of response heard before interruption
        """
        logger.warning(
            "Agent: No interrupt handler set. The agent may not understand "
            "that it was interrupted."
        )

    async def set_memory(
        self,
        messages: list[dict],
        metadata: dict | None = None,
    ) -> None:
        """Load persisted conversation memory for this session.

        Storage is intentionally not accessed here; the session owns the
        user-scoped history and injects the already-authorized messages.
        """
        return None
