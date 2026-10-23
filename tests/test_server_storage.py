import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.config_manager.storage import StorageConfig
    from open_llm_vtuber.server import WebSocketServer
    from open_llm_vtuber.service_context import ServiceContext
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ServerStorageLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_creates_and_closes_shared_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "history.db"
            config = SimpleNamespace(
                system_config=SimpleNamespace(
                    enable_proxy=False,
                    host="127.0.0.1",
                    port=12393,
                    storage=StorageConfig(
                        sqlite_path=str(db_path),
                        import_legacy_history=False,
                    ),
                )
            )

            with patch.object(ServiceContext, "load_from_config", new=AsyncMock()):
                server = WebSocketServer(config=config)
                await server.initialize()

            self.assertTrue(db_path.exists())
            self.assertIsNotNone(server.history_repository)
            self.assertIsNotNone(server.default_context_cache.history)
            self.assertEqual(server.default_context_cache.user_id, "local")

            await server.close()
            self.assertIsNone(server.history_repository)


if __name__ == "__main__":
    unittest.main()
