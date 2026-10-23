import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.proxy_handler import ProxyHandler
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ProxyReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_restarts_heartbeat_after_disconnect(self):
        handler = ProxyHandler("ws://localhost/client-ws")
        handler._running = False
        handler._session = Mock()
        handler._session.ws_connect = AsyncMock(return_value=Mock())
        handler._maintain_connection = AsyncMock()
        handler.forward_server_messages = AsyncMock()

        await handler.connect_to_server()

        self.assertTrue(handler._running)
        self.assertTrue(handler.connected)

        for task in (handler._heartbeat_task, handler.server_task):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *[task for task in (handler._heartbeat_task, handler.server_task) if task],
            return_exceptions=True,
        )


if __name__ == "__main__":
    unittest.main()
