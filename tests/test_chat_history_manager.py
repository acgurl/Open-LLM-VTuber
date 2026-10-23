import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.chat_history_manager import (
        create_new_history,
        delete_history,
        get_history,
        get_history_list,
        get_metadata,
        modify_latest_message,
        rename_history_file,
        store_message,
        update_metadata,
    )
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ChatHistoryManagerTests(unittest.TestCase):
    def setUp(self):
        self._original_cwd = os.getcwd()
        self._temp_dir = tempfile.mkdtemp()
        os.chdir(self._temp_dir)

    def tearDown(self):
        os.chdir(self._original_cwd)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_round_trip_store_list_and_delete(self):
        history_uid = create_new_history("conf")

        self.assertEqual(get_history_list("conf"), [])

        store_message("conf", history_uid, "human", "你好", name="Human")
        store_message("conf", history_uid, "ai", "回复", name="AI", avatar="a.png")

        messages = get_history("conf", history_uid)
        self.assertEqual([message["role"] for message in messages], ["human", "ai"])
        self.assertEqual(messages[0]["content"], "你好")
        self.assertEqual(messages[1]["avatar"], "a.png")

        histories = get_history_list("conf")
        self.assertEqual(len(histories), 1)
        self.assertEqual(histories[0]["uid"], history_uid)
        self.assertEqual(histories[0]["latest_message"]["content"], "回复")

        self.assertTrue(delete_history("conf", history_uid))
        self.assertEqual(get_history("conf", history_uid), [])

    def test_listing_does_not_delete_a_new_empty_history(self):
        empty_uid = create_new_history("conf")
        filled_uid = create_new_history("conf")
        store_message("conf", filled_uid, "human", "你好")

        histories = get_history_list("conf")

        self.assertEqual([history["uid"] for history in histories], [filled_uid])
        self.assertTrue(
            os.path.exists(os.path.join("chat_history", "conf", f"{empty_uid}.json"))
        )

    def test_metadata_modify_and_rename(self):
        history_uid = create_new_history("conf")
        store_message("conf", history_uid, "ai", "旧回复")

        self.assertTrue(update_metadata("conf", history_uid, {"title": "会话"}))
        self.assertEqual(get_metadata("conf", history_uid)["title"], "会话")

        self.assertTrue(
            modify_latest_message("conf", history_uid, role="ai", new_content="新回复")
        )
        self.assertEqual(get_history("conf", history_uid)[-1]["content"], "新回复")

        new_uid = "renamed_history"
        self.assertTrue(rename_history_file("conf", history_uid, new_uid))
        self.assertEqual(get_history("conf", history_uid), [])
        self.assertEqual(len(get_history("conf", new_uid)), 1)


if __name__ == "__main__":
    unittest.main()
