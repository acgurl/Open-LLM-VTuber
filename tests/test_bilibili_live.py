import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from open_llm_vtuber.live import bilibili_live
from open_llm_vtuber.live.bilibili_live import BiliBiliLivePlatform


class _FakeLiveClient:
    instances = []

    def __init__(self, room_id, session=None):
        self.room_id = room_id
        self.session = session
        self.stopped = False
        _FakeLiveClient.instances.append(self)

    def set_handler(self, _handler):
        pass

    def start(self):
        pass

    async def join(self):
        pass

    async def stop_and_close(self):
        self.stopped = True


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

    async def test_connects_to_every_configured_room(self):
        _FakeLiveClient.instances.clear()
        platform = BiliBiliLivePlatform.__new__(BiliBiliLivePlatform)
        platform._room_ids = [1, 2]
        platform._sessdata = ""
        platform._session = None
        platform._clients = []
        platform._running = False
        platform._message_handlers = []
        platform._background_tasks = set()
        platform._connected = False
        platform._websocket = None
        platform._init_session = Mock()
        platform.connect = AsyncMock(return_value=True)
        platform.start_receiving = AsyncMock()

        with patch.object(
            bilibili_live,
            "blivedm",
            SimpleNamespace(BLiveClient=_FakeLiveClient),
            create=True,
        ):
            await platform.run()

        self.assertEqual(
            [client.room_id for client in _FakeLiveClient.instances], [1, 2]
        )
        self.assertTrue(all(client.stopped for client in _FakeLiveClient.instances))


if __name__ == "__main__":
    unittest.main()
