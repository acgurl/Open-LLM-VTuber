import os
import tempfile
import threading
import time
import unittest

from open_llm_vtuber.tts.pooled_tts import PooledTTSEngine


class FakeClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.closed = False


class FakeEngine(PooledTTSEngine):
    file_extension = "mp3"

    def __init__(self, max_clients=2):
        super().__init__(max_clients=max_clients)
        self.created = 0
        self.fail_next = False
        self._create_lock = threading.Lock()

    def _create_client(self):
        with self._create_lock:
            self.created += 1
            return FakeClient(self.created)

    def _synthesize(self, client, text, output_path):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthesis failed")
        time.sleep(0.02)
        with open(output_path, "wb") as audio_file:
            audio_file.write(b"fake-audio")
        return True

    def _close_client(self, client):
        client.closed = True


class PooledTTSEngineTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_sequential_calls_reuse_one_client(self):
        engine = FakeEngine(max_clients=2)

        first = engine.generate_audio("你好。", "first")
        second = engine.generate_audio("再见。", "second")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(engine.created, 1)

    def test_concurrency_is_bounded_by_pool_size(self):
        engine = FakeEngine(max_clients=2)
        results = []

        def synthesize(index):
            results.append(engine.generate_audio("你好。", f"concurrent_{index}"))

        threads = [threading.Thread(target=synthesize, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 6)
        self.assertTrue(all(result is not None for result in results))
        self.assertLessEqual(engine.created, 2)

    def test_failed_client_is_discarded_and_replaced(self):
        engine = FakeEngine(max_clients=1)
        engine.fail_next = True

        failed = engine.generate_audio("你好。", "failed")
        recovered = engine.generate_audio("你好。", "recovered")

        self.assertIsNone(failed)
        self.assertFalse(os.path.exists("cache/failed.mp3"))
        self.assertIsNotNone(recovered)
        self.assertEqual(engine.created, 2)

    def test_close_releases_idle_clients_and_rejects_new_work(self):
        engine = FakeEngine(max_clients=1)
        engine.generate_audio("你好。", "before_close")

        engine.close()

        self.assertIsNone(engine.generate_audio("再见。", "after_close"))
        self.assertEqual(engine.created, 1)


if __name__ == "__main__":
    unittest.main()
