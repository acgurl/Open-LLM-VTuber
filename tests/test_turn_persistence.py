import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from loguru import logger

from open_llm_vtuber.conversations import conversation_utils, single_conversation
from open_llm_vtuber.conversations.types import OutboundChannels


class _Agent:
    async def chat(self, _batch_input):
        if False:
            yield None


def _context(history_uid="history-a"):
    return SimpleNamespace(
        character_config=SimpleNamespace(
            character_name="AI", avatar="ai.png", human_name="Human"
        ),
        agent_engine=_Agent(),
        asr_engine=None,
        history_uid=history_uid,
        store_history_message=AsyncMock(),
    )


class ChainEndLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_chain_end_log_names_the_turn_emoji(self):
        lines = []
        sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
        self.addCleanup(logger.remove, sink)
        tts_manager = Mock(task_list=[])

        with patch.object(
            single_conversation, "TTSTaskManager", return_value=tts_manager
        ):
            await single_conversation.process_single_conversation(
                context=_context(),
                channels=OutboundChannels.from_text(AsyncMock()),
                client_uid="client",
                user_input="hi",
                session_emoji="🦊",
            )

        completed = [line for line in lines if "completed" in line]
        self.assertEqual(len(completed), 1)
        self.assertIn("Conversation Chain 🦊 completed", completed[0])


class InterruptedReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_heard_part_as_speaker_then_marker(self):
        member = _context()
        speaker = SimpleNamespace(
            character_config=SimpleNamespace(character_name="Other", avatar="o.png")
        )

        await conversation_utils.store_interrupted_reply(
            member, "heard", "history-a", speaker_context=speaker
        )

        self.assertEqual(
            member.store_history_message.await_args_list,
            [
                call(
                    role="ai",
                    content="heard",
                    name="Other",
                    avatar="o.png",
                    history_uid="history-a",
                ),
                call(
                    role="system",
                    content="[Interrupted by user]",
                    history_uid="history-a",
                ),
            ],
        )

    async def test_nothing_heard_or_unbound_stores_nothing(self):
        context = _context()

        await conversation_utils.store_interrupted_reply(context, "", "history-a")
        await conversation_utils.store_interrupted_reply(context, "heard", None)

        context.store_history_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
