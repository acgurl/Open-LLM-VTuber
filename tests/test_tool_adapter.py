import unittest
from unittest.mock import AsyncMock, patch

from open_llm_vtuber.mcpp.tool_adapter import ToolAdapter
from open_llm_vtuber.mcpp.types import FormattedTool


class ToolAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = ToolAdapter.__new__(ToolAdapter)

    async def test_build_tools_fetches_once_and_returns_raw_tools(self):
        raw_tools = {"server": {"tool": {"description": "d"}}}

        with (
            patch.object(
                self.adapter,
                "get_server_and_tool_info",
                new=AsyncMock(return_value=({}, raw_tools, {})),
            ) as fetch,
            patch.object(
                self.adapter,
                "construct_mcp_prompt_string",
                return_value="prompt",
            ),
            patch.object(
                self.adapter,
                "format_tools_for_api",
                return_value=["tool"],
            ),
        ):
            result = await self.adapter.build_tools(["server"])

        self.assertEqual(result, ("prompt", ["tool"], raw_tools, ""))
        fetch.assert_awaited_once_with(["server"])

    def test_tools_keep_the_servers_schema(self):
        schema = {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "object",
                    "properties": {"tags": {"type": "array"}},
                    "required": ["tags"],
                },
                "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["filter"],
            "$defs": {"x": {"type": "string"}},
        }
        tools = self.adapter.format_tools_for_api(
            {
                "u_srv_search": FormattedTool(
                    input_schema=schema,
                    related_server="user:abc",
                    description="Search",
                    remote_name="search",
                ),
                "broken": "not a tool",
            }
        )

        self.assertEqual(
            tools,
            [{"name": "u_srv_search", "description": "Search", "input_schema": schema}],
        )
        self.assertIs(tools[0]["input_schema"], schema)


if __name__ == "__main__":
    unittest.main()
