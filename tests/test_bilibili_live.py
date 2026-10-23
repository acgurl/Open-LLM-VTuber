import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.live.bilibili_live import BiliBiliLivePlatform
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class IncomingMessageHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_awaits_async_handlers(self):
        platform = BiliBiliLivePlatform.__new__(BiliBiliLivePlatform)
        platform._message_handlers = []
        received = []

        async def async_handler(message):
            await asyncio.sleep(0)
            received.append(("async", message))

        def sync_handler(message):
            received.append(("sync", message))

        platform._message_handlers = [async_handler, sync_handler]

        await platform.handle_incoming_messages({"text": "hi"})

        self.assertEqual(
            received,
            [("async", {"text": "hi"}), ("sync", {"text": "hi"})],
        )

    async def test_danmaku_handler_tracks_background_task(self):
        platform = BiliBiliLivePlatform.__new__(BiliBiliLivePlatform)
        platform._background_tasks = set()
        received = []

        async def handle_danmaku(text):
            received.append(text)

        platform._handle_danmaku = handle_danmaku
        handler = BiliBiliLivePlatform.VtuberHandler(platform)

        handler._on_danmaku(
            SimpleNamespace(room_id=1),
            SimpleNamespace(uname="user", msg="hi"),
        )
        await asyncio.sleep(0.01)

        self.assertEqual(received, ["hi"])
        self.assertEqual(platform._background_tasks, set())


if __name__ == "__main__":
    unittest.main()
