import sqlite3
import tempfile
import unittest
from pathlib import Path

from open_llm_vtuber.storage import HistoryNotFoundError, SQLiteHistoryRepository


class ConnectorStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "history.db"
        self.repository = SQLiteHistoryRepository(self.db_path)
        await self.repository.initialize()
        self.alice = await self.repository.resolve_user_identity(
            provider="https://sso.example",
            subject="alice",
            display_name="Alice",
            email="alice@mail.cuc.edu.cn",
        )
        self.bob = await self.repository.resolve_user_identity(
            provider="https://sso.example", subject="bob", display_name="Bob"
        )

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_schema_version_7_is_recorded(self):
        conn = sqlite3.connect(self.db_path)
        try:
            versions = {
                row[0] for row in conn.execute("SELECT version FROM schema_migrations")
            }
        finally:
            conn.close()
        self.assertIn(7, versions)

    async def test_user_profile_lists_login_emails(self):
        profile = await self.repository.get_user_profile(user_id=self.alice)
        self.assertEqual(profile["display_name"], "Alice")
        self.assertEqual(profile["emails"], ["alice@mail.cuc.edu.cn"])

        bob = await self.repository.get_user_profile(user_id=self.bob)
        self.assertEqual(bob["emails"], [])
        self.assertIsNone(await self.repository.get_user_profile(user_id="nobody"))

    async def test_bind_resolve_and_delete_identity(self):
        self.assertIsNone(
            await self.repository.resolve_connector_identity(
                connector_id="qq", external_id="u:1"
            )
        )
        await self.repository.bind_connector_identity(
            connector_id="qq", external_id="u:1", user_id=self.alice, display_name="小A"
        )
        self.assertEqual(
            await self.repository.resolve_connector_identity(
                connector_id="qq", external_id="u:1"
            ),
            self.alice,
        )
        rows = await self.repository.list_connector_identities(user_id=self.alice)
        self.assertEqual(
            [(row["connector_id"], row["external_id"]) for row in rows], [("qq", "u:1")]
        )

        # Another user cannot delete it.
        self.assertFalse(
            await self.repository.delete_connector_identity(
                user_id=self.bob, connector_id="qq", external_id="u:1"
            )
        )
        self.assertTrue(
            await self.repository.delete_connector_identity(
                user_id=self.alice, connector_id="qq", external_id="u:1"
            )
        )
        self.assertIsNone(
            await self.repository.resolve_connector_identity(
                connector_id="qq", external_id="u:1"
            )
        )

    async def test_rebinding_moves_the_account_to_the_new_user(self):
        await self.repository.bind_connector_identity(
            connector_id="qq", external_id="u:1", user_id=self.alice
        )
        await self.repository.bind_connector_identity(
            connector_id="qq", external_id="u:1", user_id=self.bob
        )
        self.assertEqual(
            await self.repository.resolve_connector_identity(
                connector_id="qq", external_id="u:1"
            ),
            self.bob,
        )
        self.assertEqual(
            await self.repository.list_connector_identities(user_id=self.alice), []
        )

    async def test_conversation_mapping_is_scoped_to_the_history_owner(self):
        history = await self.repository.create_history(
            user_id=self.alice, conf_uid="conf"
        )
        await self.repository.set_connector_conversation(
            connector_id="qq",
            chat_key="direct:1",
            user_id=self.alice,
            conf_uid="conf",
            history_uid=history,
        )
        self.assertEqual(
            await self.repository.get_connector_conversation(
                connector_id="qq",
                chat_key="direct:1",
                user_id=self.alice,
                conf_uid="conf",
            ),
            history,
        )
        self.assertIsNone(
            await self.repository.get_connector_conversation(
                connector_id="qq",
                chat_key="direct:1",
                user_id=self.bob,
                conf_uid="conf",
            )
        )
        with self.assertRaises(HistoryNotFoundError):
            await self.repository.set_connector_conversation(
                connector_id="qq",
                chat_key="direct:1",
                user_id=self.bob,
                conf_uid="conf",
                history_uid=history,
            )

    async def test_deleting_the_history_drops_the_mapping(self):
        history = await self.repository.create_history(
            user_id=self.alice, conf_uid="conf"
        )
        await self.repository.set_connector_conversation(
            connector_id="qq",
            chat_key="direct:1",
            user_id=self.alice,
            conf_uid="conf",
            history_uid=history,
        )
        await self.repository.delete_history(
            user_id=self.alice, conf_uid="conf", history_uid=history
        )
        self.assertIsNone(
            await self.repository.get_connector_conversation(
                connector_id="qq",
                chat_key="direct:1",
                user_id=self.alice,
                conf_uid="conf",
            )
        )


if __name__ == "__main__":
    unittest.main()
