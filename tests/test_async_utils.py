import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.utils.async_utils import cancel_and_wait
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class CancelAndWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancels_running_task(self):
        started = asyncio.Event()

        async def worker():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(worker())
        await started.wait()

        await cancel_and_wait(task, failure_message="worker failed")

        self.assertTrue(task.cancelled())

    async def test_swallows_failure_raised_after_cancel(self):
        started = asyncio.Event()

        async def stubborn_worker():
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise RuntimeError("boom") from None

        task = asyncio.create_task(stubborn_worker())
        await started.wait()

        await cancel_and_wait(task, failure_message="worker failed")

        self.assertTrue(task.done())

    async def test_ignores_missing_or_finished_task(self):
        await cancel_and_wait(None, failure_message="worker failed")

        task = asyncio.create_task(asyncio.sleep(0))
        await task
        await cancel_and_wait(task, failure_message="worker failed")

        self.assertTrue(task.done())


if __name__ == "__main__":
    unittest.main()
