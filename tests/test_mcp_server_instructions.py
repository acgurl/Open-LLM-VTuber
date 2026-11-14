"""MCP server ``instructions`` must reach the model's system prompt."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
from open_llm_vtuber.mcpp import tool_adapter as tool_adapter_module
from open_llm_vtuber.mcpp.mcp_client import MCPClient
from open_llm_vtuber.mcpp.server_registry import ServerRegistry
from open_llm_vtuber.mcpp.tool_adapter import (
    MAX_USER_SERVER_INSTRUCTIONS_CHARS,
    ToolAdapter,
)
from open_llm_vtuber.mcpp.tool_manager import ToolManager
from open_llm_vtuber.mcpp.types import MCPServer


def _tool(name: str, description: str = "d"):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema={"type": "object", "properties": {}},
    )


class _InitSession:
    def __init__(self, instructions):
        self._instructions = instructions

    async def initialize(self):
        return SimpleNamespace(instructions=self._instructions)


class MCPClientInstructionsTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self) -> MCPClient:
        return MCPClient(ServerRegistry.from_servers({}))

    async def test_records_instructions_from_initialize(self):
        client = self.make_client()
        await client._initialize("kb", _InitSession("  superseded_by 表示已废止  "))
        self.assertEqual(client.get_instructions("kb"), "superseded_by 表示已废止")

    async def test_blank_or_missing_instructions_clear_previous_value(self):
        client = self.make_client()
        await client._initialize("kb", _InitSession("old"))
        await client._initialize("kb", _InitSession(None))
        self.assertEqual(client.get_instructions("kb"), "")
        await client._initialize("kb", _InitSession("   "))
        self.assertEqual(client.get_instructions("kb"), "")


class ToolAdapterInstructionsTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, tools, instructions):
        class FakeClient:
            def __init__(self, registry):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def list_tools(self, server_name):
                return tools[server_name]

            def get_instructions(self, server_name):
                return instructions.get(server_name, "")

        registry = ServerRegistry.from_servers(
            {
                "cuc-kb": MCPServer(name="cuc-kb", url="http://127.0.0.1:8765/mcp"),
                "silent": MCPServer(name="silent", url="http://127.0.0.1:9/mcp"),
                "user:abc": MCPServer(
                    name="user:abc",
                    url="https://mcp.example.com/mcp",
                    is_user=True,
                    display_name="My tools",
                ),
            }
        )
        adapter = ToolAdapter(registry)
        with patch.object(tool_adapter_module, "MCPClient", FakeClient):
            return await adapter.build_tools(list(tools))

    async def test_instructions_section_lists_servers_and_exposed_tool_names(self):
        tools = {
            "cuc-kb": [_tool("kb_search")],
            "silent": [_tool("ping")],
            "user:abc": [_tool("read_file")],
        }
        instructions = {
            "cuc-kb": "newer_version 表示有更新一期",
            "user:abc": "Always pass absolute paths.",
        }
        _, _, _, raw, section = await self.build(tools, instructions)

        user_tool = next(n for n, t in raw.items() if t.related_server == "user:abc")
        self.assertTrue(section.startswith("## 工具服务说明"))
        self.assertIn("### cuc-kb（工具：kb_search）", section)
        self.assertIn("newer_version 表示有更新一期", section)
        self.assertIn(f"### My tools（工具：{user_tool}）", section)
        self.assertIn("用户自行接入的服务", section)
        self.assertIn("Always pass absolute paths.", section)
        self.assertNotIn("silent", section)

    async def test_no_instructions_yields_empty_section(self):
        _, _, _, _, section = await self.build({"cuc-kb": [_tool("kb_search")]}, {})
        self.assertEqual(section, "")

    async def test_server_without_tools_is_omitted(self):
        _, _, _, _, section = await self.build({"cuc-kb": []}, {"cuc-kb": "rules"})
        self.assertEqual(section, "")

    async def test_user_instructions_are_capped(self):
        long_text = "x" * (MAX_USER_SERVER_INSTRUCTIONS_CHARS + 500)
        _, _, _, _, section = await self.build(
            {"user:abc": [_tool("read_file")]}, {"user:abc": long_text}
        )
        self.assertIn("x" * MAX_USER_SERVER_INSTRUCTIONS_CHARS, section)
        self.assertNotIn("x" * (MAX_USER_SERVER_INSTRUCTIONS_CHARS + 1), section)


class AgentSystemPromptTests(unittest.TestCase):
    def make_agent(self, tool_manager, use_mcpp=True):
        agent = BasicMemoryAgent.__new__(BasicMemoryAgent)
        agent._system = "PERSONA"
        agent._tool_manager = tool_manager
        agent._use_mcpp = use_mcpp
        return agent

    def test_instructions_follow_persona_when_tools_enabled(self):
        manager = ToolManager(server_instructions="## 工具服务说明\nRULES")
        system = self.make_agent(manager)._system_with_time()
        self.assertTrue(system.startswith("PERSONA\n\n## 工具服务说明\nRULES"))
        self.assertIn("## 当前时间", system)

    def test_instructions_absent_when_tools_disabled(self):
        manager = ToolManager(server_instructions="RULES")
        self.assertNotIn(
            "RULES", self.make_agent(manager, use_mcpp=False)._system_with_time()
        )
        self.assertNotIn("RULES", self.make_agent(None)._system_with_time())


if __name__ == "__main__":
    unittest.main()
