import unittest
from unittest import mock

from open_llm_vtuber.mcpp.builtin import deepseek_web as dw


class DeepseekWebTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        dw._calls.clear()

    def test_check_url_rejects_private_and_credentials(self) -> None:
        for bad in (
            "file:///etc/passwd",
            "http://localhost/x",
            "http://127.0.0.1/",
            "http://10.0.0.5/",
            "http://intranet/",
            "https://user:pw@example.com/",
            "",
        ):
            with self.assertRaises(ValueError, msg=bad):
                dw._check_url(bad)
        self.assertEqual(
            dw._check_url("https://www.cuc.edu.cn/a"), "https://www.cuc.edu.cn/a"
        )

    async def test_search_formats_and_clamps(self) -> None:
        payload = {
            "results": [
                {
                    "title": "T",
                    "url": "https://a.cn",
                    "summary": "S" * 2000,
                    "site_name": "A",
                    "date": "2026-06-01T00:00:00+00:00",
                }
            ]
        }
        with mock.patch.object(
            dw, "_post", mock.AsyncMock(return_value=payload)
        ) as post:
            out = await dw.web_search("q", count=99)
        self.assertEqual(post.call_args.args[1]["count"], dw.MAX_RESULTS)
        self.assertFalse(post.call_args.args[1]["need_content"])
        self.assertIn("Untrusted", out)
        self.assertLess(len(out), 1200)
        self.assertIn("2026-06-01", out)

    async def test_search_rejects_long_query_without_spending(self) -> None:
        out = await dw.web_search("x" * 200)
        self.assertTrue(out.startswith("Error"))
        self.assertEqual(len(dw._calls), 0)

    async def test_budget_exhausted(self) -> None:
        with mock.patch.object(
            dw, "_post", mock.AsyncMock(return_value={"results": []})
        ):
            for _ in range(dw.BUDGET_CALLS):
                await dw.web_search("q")
            out = await dw.web_search("q")
        self.assertIn("budget", out)

    async def test_fetch_truncates(self) -> None:
        with mock.patch.object(
            dw,
            "_post",
            mock.AsyncMock(return_value={"title": "t", "content": "x" * 50000}),
        ):
            out = await dw.web_fetch("https://example.com", max_chars=10**6)
        self.assertLess(len(out), dw.MAX_FETCH_CHARS + 400)
        self.assertIn("Truncated", out)

    async def test_missing_key_is_clean_error(self) -> None:
        with mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}):
            out = await dw.web_search("q")
        self.assertEqual(out, "Error: Web search is not configured.")


if __name__ == "__main__":
    unittest.main()
