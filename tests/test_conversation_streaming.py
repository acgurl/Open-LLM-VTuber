import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.output_types import (
        Actions,
        DisplayText,
        SentenceOutput,
    )
    from open_llm_vtuber.conversations import (
        conversation_utils,
        group_conversation,
        single_conversation,
    )
    from open_llm_vtuber.conversations.types import OutboundChannels
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class _FakeAgent:
    def __init__(self, items):
        self._items = items

    def chat(self, _batch_input):
        async def stream():
            for item in self._items:
                yield item

        return stream()


def _sentence(text: str) -> SentenceOutput:
    return SentenceOutput(
        display_text=DisplayText(text=text),
        tts_text=text,
        actions=Actions(),
    )


class GroupStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_deltas_tool_status_and_sentences_in_order(self):
        sent = []

        async def broadcast(_members, message, _exclude=None):
            sent.append(message)

        channels = OutboundChannels(text=AsyncMock(), audio=AsyncMock())
        context = SimpleNamespace(
            character_config=SimpleNamespace(character_name="AI", avatar=None),
            agent_engine=_FakeAgent(
                [
                    {"type": "text_delta", "text": "你"},
                    {"type": "tool_call_status", "text": "searching"},
                    _sentence("回答。"),
                ]
            ),
            live2d_model=None,
            tts_engine=None,
            translate_engine=None,
        )

        with patch.object(
            conversation_utils,
            "process_agent_output",
            new=AsyncMock(return_value="回答。"),
        ):
            full_response = await group_conversation.process_member_response(
                context=context,
                batch_input=None,
                channels=channels,
                tts_manager=Mock(),
                broadcast_func=broadcast,
                group_members=["client"],
            )

        self.assertEqual(full_response, "回答。")
        self.assertEqual(
            [message["type"] for message in sent], ["text-delta", "tool_call_status"]
        )
        self.assertEqual(sent[0]["text"], "你")
        self.assertEqual(sent[0]["full_text"], "你")
        self.assertEqual(sent[1]["name"], "AI")
        channels.text.assert_not_awaited()


class StreamErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_error_and_keeps_partial_response(self):
        text_sent = []

        async def text_send(message: str) -> None:
            text_sent.append(json.loads(message))

        async def failing_stream():
            yield {"type": "text_delta", "text": "部分"}
            yield _sentence("部分。")
            raise RuntimeError("boom")

        context = SimpleNamespace(
            character_config=SimpleNamespace(character_name="AI", avatar=None),
            live2d_model=None,
            tts_engine=None,
            translate_engine=None,
        )
        channels = OutboundChannels(text=text_send, audio=AsyncMock())

        with patch.object(
            conversation_utils,
            "process_agent_output",
            new=AsyncMock(return_value="部分。"),
        ):
            full_response = await conversation_utils.consume_agent_stream(
                failing_stream(),
                context=context,
                channels=channels,
                tts_manager=Mock(),
                send_text_delta=lambda message: channels.text(json.dumps(message)),
            )

        self.assertEqual(full_response, "部分。")
        self.assertEqual(text_sent[-1]["type"], "error")
        self.assertIn("boom", text_sent[-1]["message"])
        self.assertEqual(
            [message["type"] for message in text_sent[:-1]], ["text-delta"]
        )


class SingleStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_text_deltas_and_returns_full_response(self):
        text_sent = []

        async def text_send(message: str) -> None:
            text_sent.append(json.loads(message))

        channels = OutboundChannels(text=text_send, audio=AsyncMock())
        context = SimpleNamespace(
            character_config=SimpleNamespace(
                character_name="AI",
                avatar=None,
                human_name="Human",
                conf_uid="conf",
            ),
            agent_engine=_FakeAgent(
                [
                    {"type": "text_delta", "text": "回答"},
                    _sentence("回答。"),
                ]
            ),
            asr_engine=None,
            live2d_model=None,
            tts_engine=None,
            translate_engine=None,
            history_uid=None,
            channels=channels,
        )

        with (
            patch.object(
                conversation_utils,
                "process_agent_output",
                new=AsyncMock(return_value="回答。"),
            ),
            patch.object(
                single_conversation,
                "finalize_conversation_turn",
                new=AsyncMock(),
            ),
            patch.object(single_conversation, "store_message") as store_message,
        ):
            full_response = await single_conversation.process_single_conversation(
                context=context,
                channels=channels,
                client_uid="client",
                user_input="你好",
            )

        self.assertEqual(full_response, "回答。")
        self.assertEqual(
            [message["type"] for message in text_sent],
            ["control", "full-text", "text-delta"],
        )
        self.assertEqual(text_sent[2]["text"], "回答")
        self.assertEqual(text_sent[2]["full_text"], "回答")
        store_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
