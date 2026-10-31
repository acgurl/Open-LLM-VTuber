import json
import tempfile
import unittest
from pathlib import Path

from open_llm_vtuber.storage import (
    HistoryNotFoundError,
    SQLiteHistoryRepository,
    UserHistoryStore,
    import_legacy_histories,
)


class SQLiteHistoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.repository = SQLiteHistoryRepository(self.root / "history.db")
        await self.repository.initialize()
        await self.repository.ensure_user("alice", "Alice")
        await self.repository.ensure_user("bob", "Bob")
        self.alice = UserHistoryStore(self.repository, "alice")
        self.bob = UserHistoryStore(self.repository, "bob")

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_round_trip_store_list_and_delete(self):
        history_uid = await self.alice.create_history("conf")

        self.assertEqual(await self.alice.list_histories("conf"), [])

        await self.alice.store_message(
            "conf", history_uid, "human", "你好", name="Human"
        )
        await self.alice.store_message(
            "conf", history_uid, "ai", "回复", name="AI", avatar="a.png"
        )

        messages = await self.alice.get_history("conf", history_uid)
        self.assertEqual([message["role"] for message in messages], ["human", "ai"])
        self.assertEqual(messages[0]["content"], "你好")
        self.assertEqual(messages[1]["avatar"], "a.png")

        histories = await self.alice.list_histories("conf")
        self.assertEqual(len(histories), 1)
        self.assertEqual(histories[0]["uid"], history_uid)
        self.assertEqual(histories[0]["latest_message"]["content"], "回复")

        self.assertTrue(await self.alice.delete_history("conf", history_uid))
        self.assertEqual(await self.alice.get_history("conf", history_uid), [])
        self.assertFalse(await self.alice.history_exists("conf", history_uid))

    async def test_listing_excludes_a_new_empty_history(self):
        empty_uid = await self.alice.create_history("conf")
        filled_uid = await self.alice.create_history("conf")
        await self.alice.store_message("conf", filled_uid, "human", "你好")

        histories = await self.alice.list_histories("conf")

        self.assertEqual([history["uid"] for history in histories], [filled_uid])
        self.assertTrue(await self.alice.history_exists("conf", empty_uid))

    async def test_metadata_modify_and_rename(self):
        history_uid = await self.alice.create_history("conf")
        await self.alice.store_message("conf", history_uid, "ai", "旧回复")

        self.assertTrue(
            await self.alice.update_metadata("conf", history_uid, {"title": "会话"})
        )
        metadata = await self.alice.get_metadata("conf", history_uid)
        self.assertEqual(metadata["title"], "会话")
        self.assertEqual(metadata["role"], "metadata")

        self.assertTrue(
            await self.alice.modify_latest_message(
                "conf", history_uid, role="ai", new_content="新回复"
            )
        )
        messages = await self.alice.get_history("conf", history_uid)
        self.assertEqual(messages[-1]["content"], "新回复")

        new_uid = "renamed_history"
        self.assertTrue(await self.alice.rename_history("conf", history_uid, new_uid))
        self.assertEqual(await self.alice.get_history("conf", history_uid), [])
        self.assertEqual(len(await self.alice.get_history("conf", new_uid)), 1)

    async def test_histories_are_isolated_by_user(self):
        history_uid = await self.alice.create_history("conf")
        await self.alice.store_message("conf", history_uid, "human", "alice only")

        self.assertEqual(await self.bob.list_histories("conf"), [])
        self.assertEqual(await self.bob.get_history("conf", history_uid), [])
        self.assertEqual(await self.bob.get_metadata("conf", history_uid), {})
        self.assertFalse(await self.bob.history_exists("conf", history_uid))
        self.assertFalse(await self.bob.delete_history("conf", history_uid))
        self.assertFalse(
            await self.bob.update_metadata("conf", history_uid, {"intruded": True})
        )
        self.assertFalse(
            await self.bob.modify_latest_message(
                "conf", history_uid, role="human", new_content="changed"
            )
        )

        with self.assertRaises(HistoryNotFoundError):
            await self.bob.store_message("conf", history_uid, "human", "intrude")

        messages = await self.alice.get_history("conf", history_uid)
        self.assertEqual([message["content"] for message in messages], ["alice only"])
        self.assertNotIn("intruded", await self.alice.get_metadata("conf", history_uid))

    async def test_store_message_creates_a_missing_history(self):
        history_uid = "missing_history"

        await self.alice.store_message("conf", history_uid, "human", "hello")

        messages = await self.alice.get_history("conf", history_uid)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "hello")

    async def test_tool_calls_follow_their_turn_and_cascade_on_delete(self):
        history_uid = await self.alice.create_history("conf")
        await self.alice.store_message("conf", history_uid, "human", "第一问")
        await self.alice.store_tool_call(
            "conf", history_uid, tool_id="t1", tool_name="kb_search", status="running"
        )
        await self.alice.store_tool_call(
            "conf",
            history_uid,
            tool_id="t1",
            tool_name="kb_search",
            status="completed",
            content='{"ok": true}',
        )
        await self.alice.store_message("conf", history_uid, "ai", "第一答")
        await self.alice.store_message("conf", history_uid, "human", "第二问")
        await self.alice.store_tool_call(
            "conf", history_uid, tool_id="t2", tool_name="card", status="error"
        )

        calls = await self.alice.list_tool_calls("conf", history_uid)
        self.assertEqual([call["tool_id"] for call in calls], ["t1", "t2"])
        self.assertEqual(calls[0]["status"], "completed")
        self.assertEqual(calls[0]["content"], '{"ok": true}')
        self.assertEqual(calls[0]["turn_index"], 0)
        self.assertEqual(calls[1]["turn_index"], 1)
        self.assertEqual(await self.bob.list_tool_calls("conf", history_uid), [])

        self.assertTrue(await self.alice.delete_history("conf", history_uid))
        self.assertEqual(await self.alice.list_tool_calls("conf", history_uid), [])

    async def test_unfinished_tool_call_reads_as_error(self):
        history_uid = await self.alice.create_history("conf")
        await self.alice.store_message("conf", history_uid, "human", "问题")
        await self.alice.store_tool_call(
            "conf", history_uid, tool_id="t1", tool_name="kb_search", status="running"
        )

        calls = await self.alice.list_tool_calls("conf", history_uid)
        self.assertEqual(calls[0]["status"], "error")

    async def test_tool_call_without_history_is_ignored(self):
        await self.alice.store_tool_call(
            "conf", "missing_history", tool_id="t1", tool_name="kb", status="completed"
        )

        self.assertFalse(await self.alice.history_exists("conf", "missing_history"))

    async def test_import_history_preserves_timestamps_and_metadata(self):
        messages = [
            {
                "role": "human",
                "timestamp": "2024-01-01T00:00:00",
                "content": "你好",
            },
            {
                "role": "ai",
                "timestamp": "2024-01-01T00:00:01",
                "content": "回复",
                "name": "AI",
            },
        ]

        imported = await self.repository.import_history(
            user_id="alice",
            conf_uid="conf",
            history_uid="legacy_uid",
            messages=messages,
            metadata={"resume_id": "group-1"},
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:01",
            legacy_path="chat_history/conf/legacy_uid.json",
        )

        self.assertTrue(imported)
        history = await self.alice.get_history("conf", "legacy_uid")
        self.assertEqual(history[0]["timestamp"], "2024-01-01T00:00:00")
        self.assertEqual(history[1]["content"], "回复")
        metadata = await self.alice.get_metadata("conf", "legacy_uid")
        self.assertEqual(metadata["resume_id"], "group-1")
        self.assertEqual(metadata["timestamp"], "2024-01-01T00:00:00")

        duplicate = await self.repository.import_history(
            user_id="alice",
            conf_uid="conf",
            history_uid="legacy_uid",
            messages=messages,
        )
        self.assertFalse(duplicate)


class LegacyImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.repository = SQLiteHistoryRepository(self.root / "history.db")
        await self.repository.initialize()
        await self.repository.ensure_user("local", "Local User")

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_imports_json_and_moves_source_to_backup(self):
        legacy_dir = self.root / "chat_history" / "conf"
        legacy_dir.mkdir(parents=True)
        source = legacy_dir / "legacy_uid.json"
        source.write_text(
            json.dumps(
                [
                    {"role": "metadata", "timestamp": "2024-01-01T00:00:00"},
                    {
                        "role": "human",
                        "timestamp": "2024-01-01T00:00:01",
                        "content": "你好",
                    },
                    {
                        "role": "ai",
                        "timestamp": "2024-01-01T00:00:02",
                        "content": "回复",
                        "name": "AI",
                        "avatar": "a.png",
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = await import_legacy_histories(
            self.repository,
            user_id="local",
            legacy_dir=str(self.root / "chat_history"),
            backup_dir=str(self.root / "backup"),
        )

        self.assertEqual(result.imported, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.failed, 0)
        store = UserHistoryStore(self.repository, "local")
        messages = await store.get_history("conf", "legacy_uid")
        self.assertEqual([message["content"] for message in messages], ["你好", "回复"])
        self.assertEqual(messages[-1]["avatar"], "a.png")
        self.assertFalse(source.exists())
        self.assertTrue((self.root / "backup" / "conf" / "legacy_uid.json").exists())

        second = await import_legacy_histories(
            self.repository,
            user_id="local",
            legacy_dir=str(self.root / "chat_history"),
            backup_dir=str(self.root / "backup"),
        )
        self.assertEqual(second.total, 0)

    async def test_import_is_scoped_to_the_target_user(self):
        legacy_dir = self.root / "chat_history" / "conf"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "other_uid.json").write_text(
            json.dumps(
                [
                    {
                        "role": "human",
                        "timestamp": "2024-01-01T00:00:01",
                        "content": "only local",
                    }
                ]
            ),
            encoding="utf-8",
        )

        await import_legacy_histories(
            self.repository,
            user_id="local",
            legacy_dir=str(self.root / "chat_history"),
            backup_dir=str(self.root / "backup"),
        )

        other = UserHistoryStore(self.repository, "bob")
        self.assertEqual(await other.get_history("conf", "other_uid"), [])


if __name__ == "__main__":
    unittest.main()
