import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_llm_vtuber.config_manager.auth import AuthConfig, OIDCConfig
from open_llm_vtuber.config_manager.storage import StorageConfig
from open_llm_vtuber.server import WebSocketServer
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.storage import SQLiteHistoryRepository, UserHistoryStore


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

    async def test_oidc_mode_archives_local_history_and_keeps_it_unbound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "history.db"
            archive_dir = root / "archive"

            repository = SQLiteHistoryRepository(db_path)
            await repository.initialize()
            await repository.ensure_user("local", "Local User")
            store = UserHistoryStore(repository, "local")
            history_uid = await store.create_history("conf")
            await store.store_message("conf", history_uid, "human", "私有历史")
            await repository.close()

            config = SimpleNamespace(
                system_config=SimpleNamespace(
                    enable_proxy=False,
                    host="127.0.0.1",
                    port=12393,
                    storage=StorageConfig(
                        sqlite_path=str(db_path),
                        import_legacy_history=False,
                    ),
                    auth=AuthConfig(
                        mode="oidc",
                        signing_secret="test-secret",
                        cookie_secure=False,
                        archive_local_history=True,
                        archive_dir=str(archive_dir),
                        oidc=OIDCConfig(
                            issuer="https://sso.example.com",
                            client_id="client-id",
                            client_secret="client-secret",
                            redirect_uri="http://testserver/auth/callback",
                        ),
                    ),
                )
            )

            with patch.object(ServiceContext, "load_from_config", new=AsyncMock()):
                server = WebSocketServer(config=config)
                await server.initialize()

            self.assertTrue((archive_dir / "local-history-archive.json").exists())
            self.assertEqual(server.default_context_cache.user_id, None)
            self.assertIsNone(server.default_context_cache.history)
            self.assertIsNotNone(server.default_context_cache.history_repository)
            self.assertIsNotNone(server.auth.repository)

            await server.close()
            self.assertIsNone(server.history_repository)


if __name__ == "__main__":
    unittest.main()
