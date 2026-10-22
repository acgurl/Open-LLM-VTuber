import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.agent.output_types import DisplayText
    from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class _FailingTTSEngine:
    async def async_generate_audio(self, text, file_name_no_ext=None):
        return None

    def remove_file(self, filepath, verbose: bool = True) -> None:
        pass


class PayloadDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_delivery_waits_until_sender_flushes(self):
        manager = TTSTaskManager()
        sent = []

        async def send(message: str) -> None:
            sent.append(json.loads(message))

        manager._sender_task = asyncio.create_task(
            manager._process_payload_queue(send)
        )
        manager._sequence_counter = 1
        await manager._payload_queue.put(
            ({"type": "audio", "audio": "abc"}, 0)
        )

        await manager.wait_for_delivery(timeout=1.0)

        self.assertEqual(sent, [{"type": "audio", "audio": "abc"}])
        manager.clear()
        await asyncio.sleep(0)

    async def test_audio_payloads_use_the_audio_channel(self):
        manager = TTSTaskManager()
        audio_sent = []
        text_sent = []

        async def audio_send(message: str) -> None:
            audio_sent.append(json.loads(message))

        async def text_send(message: str) -> None:
            text_sent.append(json.loads(message))

        await manager.speak(
            tts_text="测试。",
            display_text=DisplayText(text="测试。"),
            actions=None,
            live2d_model=None,
            tts_engine=_FailingTTSEngine(),
            websocket_send=text_send,
            audio_send=audio_send,
        )

        await asyncio.gather(*manager.task_list)
        await manager.wait_for_delivery(timeout=1.0)

        self.assertEqual(len(audio_sent), 1)
        self.assertEqual(audio_sent[0]["type"], "audio")
        self.assertEqual(text_sent, [])
        manager.clear()
        await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
