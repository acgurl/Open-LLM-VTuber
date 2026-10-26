import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.service_context import ServiceContext
    from open_llm_vtuber.storage import SQLiteHistoryRepository
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class FakeAgent:
    def __init__(self):
        self.messages = None
        self.metadata = None

    async def set_memory(self, messages, metadata=None):
        self.messages = messages
        self.metadata = metadata


class ServiceContextHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(
            Path(self._temp_dir.name) / "history.db"
        )
        await self.repository.initialize()

        self.agent = FakeAgent()
        self.context = ServiceContext()
        self.context.character_config = SimpleNamespace(conf_uid="conf")
        self.context.agent_engine = self.agent
        self.context.set_history_storage(self.repository, "local")

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def test_load_and_store_history_uses_bound_user(self):
        history_uid = await self.context.history.create_history("conf")
        self.context.history_uid = history_uid
        await self.context.store_history_message("human", "你好", name="Human")
        await self.context.store_history_message("ai", "回复", name="AI")

        messages = await self.context.load_history(history_uid)

        self.assertEqual([message["content"] for message in messages], ["你好", "回复"])
        self.assertEqual(self.agent.messages, messages)
        self.assertEqual(self.context.history_uid, history_uid)
        self.assertEqual(self.agent.metadata["role"], "metadata")

    async def test_store_history_message_accepts_an_explicit_history_uid(self):
        old_history = await self.context.history.create_history("conf")
        current_history = await self.context.history.create_history("conf")
        self.context.history_uid = current_history

        await self.context.store_history_message(
            "ai", "旧历史回复", history_uid=old_history
        )

        old_messages = await self.context.history.get_history("conf", old_history)
        current_messages = await self.context.history.get_history(
            "conf", current_history
        )
        self.assertEqual([m["content"] for m in old_messages], ["旧历史回复"])
        self.assertEqual(current_messages, [])

    async def test_load_history_rejects_unknown_id_without_switching(self):
        self.context.history_uid = "current"
        with self.assertRaises(ValueError):
            await self.context.load_history("missing")
        self.assertEqual(self.context.history_uid, "current")

    async def test_metadata_writer_is_scoped_to_current_history(self):
        history_uid = await self.context.history.create_history("conf")
        self.context.history_uid = history_uid

        saved = await self.context.update_history_metadata({"title": "会话"})

        self.assertTrue(saved)
        metadata = await self.context.history.get_metadata("conf", history_uid)
        self.assertEqual(metadata["title"], "会话")


if __name__ == "__main__":
    unittest.main()
