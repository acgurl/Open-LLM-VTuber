import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.mcpp.tool_adapter import ToolAdapter
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ToolAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = ToolAdapter.__new__(ToolAdapter)

    async def test_build_tools_fetches_once_and_returns_raw_tools(self):
        raw_tools = {"server": {"tool": {"description": "d"}}}

        with (
            patch.object(
                self.adapter,
                "get_server_and_tool_info",
                new=AsyncMock(return_value=({}, raw_tools)),
            ) as fetch,
            patch.object(
                self.adapter,
                "construct_mcp_prompt_string",
                return_value="prompt",
            ),
            patch.object(
                self.adapter,
                "format_tools_for_api",
                return_value=(["openai"], ["claude"]),
            ),
        ):
            result = await self.adapter.build_tools(["server"])

        self.assertEqual(result, ("prompt", ["openai"], ["claude"], raw_tools))
        fetch.assert_awaited_once_with(["server"])

    async def test_get_tools_delegates_to_build_tools(self):
        with patch.object(
            self.adapter,
            "build_tools",
            new=AsyncMock(return_value=("prompt", ["openai"], ["claude"], {})),
        ) as build_tools:
            result = await self.adapter.get_tools(["server"])

        self.assertEqual(result, ("prompt", ["openai"], ["claude"]))
        build_tools.assert_awaited_once_with(["server"])


if __name__ == "__main__":
    unittest.main()
