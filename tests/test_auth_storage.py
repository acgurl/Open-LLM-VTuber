import json
import tempfile
import unittest
from pathlib import Path

from open_llm_vtuber.storage import (
    SQLiteHistoryRepository,
    UserHistoryStore,
    archive_user_histories,
)


class UserIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(
            Path(self._temp_dir.name) / "history.db"
        )
        await self.repository.initialize()

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_same_external_identity_maps_to_one_internal_user(self):
        first = await self.repository.resolve_user_identity(
            provider="https://sso.example.com",
            subject="subject-1",
            display_name="Alice",
            email="alice@example.com",
        )
        second = await self.repository.resolve_user_identity(
            provider="https://sso.example.com",
            subject="subject-1",
            display_name="Alice",
            email="alice@example.com",
        )
        other = await self.repository.resolve_user_identity(
            provider="https://sso.example.com",
            subject="subject-2",
            display_name="Bob",
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 32)
        self.assertRegex(first, r"^[A-Za-z0-9_.-]{1,64}$")

    async def test_identity_is_scoped_by_provider(self):
        first = await self.repository.resolve_user_identity(
            provider="https://sso-a.example.com", subject="shared-subject"
        )
        second = await self.repository.resolve_user_identity(
            provider="https://sso-b.example.com", subject="shared-subject"
        )

        self.assertNotEqual(first, second)

    async def test_list_conf_uids_only_returns_the_users_characters(self):
        alice = await self.repository.resolve_user_identity(
            provider="https://sso.example.com", subject="alice"
        )
        bob = await self.repository.resolve_user_identity(
            provider="https://sso.example.com", subject="bob"
        )
        alice_store = UserHistoryStore(self.repository, alice)
        bob_store = UserHistoryStore(self.repository, bob)

        alice_uid = await alice_store.create_history("conf-a")
        await alice_store.store_message("conf-a", alice_uid, "human", "hello")
        bob_uid = await bob_store.create_history("conf-b")
        await bob_store.store_message("conf-b", bob_uid, "human", "hi")

        self.assertEqual(
            await self.repository.list_conf_uids(user_id=alice), ["conf-a"]
        )
        self.assertEqual(await self.repository.list_conf_uids(user_id=bob), ["conf-b"])


class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.repository = SQLiteHistoryRepository(self.root / "history.db")
        await self.repository.initialize()
        await self.repository.ensure_user("local", "Local User")
        self.store = UserHistoryStore(self.repository, "local")

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_archive_exports_local_histories_once(self):
        history_uid = await self.store.create_history("conf")
        await self.store.store_message(
            "conf", history_uid, "human", "你好", name="Human"
        )
        await self.store.store_message(
            "conf", history_uid, "ai", "回复", name="AI", avatar="a.png"
        )

        archive_dir = self.root / "archive"
        result = await archive_user_histories(
            self.repository,
            user_id="local",
            archive_dir=archive_dir,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.created)
        self.assertEqual(result.history_count, 1)
        self.assertEqual(result.message_count, 2)

        data = json.loads(result.path.read_text(encoding="utf-8"))
        self.assertEqual(data["user_id"], "local")
        self.assertEqual(data["histories"][0]["history_uid"], history_uid)
        self.assertEqual(
            [message["content"] for message in data["histories"][0]["messages"]],
            ["你好", "回复"],
        )

        again = await archive_user_histories(
            self.repository,
            user_id="local",
            archive_dir=archive_dir,
        )
        self.assertFalse(again.created)
        self.assertEqual(again.history_count, 1)
        self.assertEqual(list(archive_dir.glob("*.json")), [result.path])

    async def test_no_archive_when_user_has_no_histories(self):
        result = await archive_user_histories(
            self.repository,
            user_id="local",
            archive_dir=self.root / "archive",
        )
        self.assertIsNone(result)
        self.assertFalse((self.root / "archive").exists())


if __name__ == "__main__":
    unittest.main()
