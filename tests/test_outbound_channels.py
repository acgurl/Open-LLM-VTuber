import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.output_types import Actions, DisplayText
    from open_llm_vtuber.conversations import conversation_utils
    from open_llm_vtuber.conversations.types import OutboundChannels
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class _AudioOutput:
    def __init__(self, item):
        self._item = item

    def __aiter__(self):
        async def iterate():
            yield self._item

        return iterate()


class _TTSManager:
    def __init__(self) -> None:
        self.task_list = [asyncio.create_task(asyncio.sleep(0))]

    async def wait_for_delivery(self) -> None:
        pass


class OutboundChannelTests(unittest.IsolatedAsyncioTestCase):
    def make_channels(self):
        text_sent = []
        audio_sent = []

        async def text_send(message: str) -> None:
            text_sent.append(json.loads(message))

        async def audio_send(message: str) -> None:
            audio_sent.append(json.loads(message))

        channels = OutboundChannels(text=text_send, audio=audio_send)
        return channels, text_sent, audio_sent

    async def test_audio_output_uses_audio_channel(self):
        channels, text_sent, audio_sent = self.make_channels()
        output = _AudioOutput(
            ("cache/sentence.wav", DisplayText(text="hi"), "hi", None)
        )

        with patch.object(
            conversation_utils,
            "prepare_audio_payload",
            return_value={"type": "audio"},
        ):
            transcript = await conversation_utils.handle_audio_output(output, channels)

        self.assertEqual(transcript, "hi")
        self.assertEqual(audio_sent, [{"type": "audio"}])
        self.assertEqual(text_sent, [])

    async def test_audio_output_passes_actions_object(self):
        channels, _, audio_sent = self.make_channels()
        actions = Actions(expressions=["happy"])
        output = _AudioOutput(
            ("cache/sentence.wav", DisplayText(text="hi"), "hi", actions)
        )
        seen = {}

        def fake_prepare_audio_payload(**kwargs):
            seen.update(kwargs)
            return {"type": "audio", "actions": kwargs["actions"].to_dict()}

        with patch.object(
            conversation_utils,
            "prepare_audio_payload",
            side_effect=fake_prepare_audio_payload,
        ):
            await conversation_utils.handle_audio_output(output, channels)

        self.assertIsInstance(seen["actions"], Actions)
        self.assertEqual(
            audio_sent,
            [{"type": "audio", "actions": {"expressions": ["happy"]}}],
        )

    async def test_finalize_splits_completion_and_control_messages(self):
        channels, text_sent, audio_sent = self.make_channels()
        manager = _TTSManager()

        with patch.object(
            conversation_utils.message_handler,
            "wait_for_response",
            new=AsyncMock(return_value=True),
        ):
            await conversation_utils.finalize_conversation_turn(
                tts_manager=manager,
                channels=channels,
                client_uid="client",
            )

        self.assertEqual(audio_sent, [{"type": "backend-synth-complete"}])
        self.assertEqual(
            text_sent,
            [
                {"type": "force-new-message"},
                {"type": "control", "text": "conversation-chain-end"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
