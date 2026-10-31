import unittest
from unittest.mock import AsyncMock, Mock, patch

from open_llm_vtuber import service_context as service_context_module
from open_llm_vtuber.service_context import ServiceContext


class McpInitializationTests(unittest.IsolatedAsyncioTestCase):
    def make_context(self):
        context = ServiceContext()
        context.channels = None
        context.client_uid = "client"
        return context

    async def test_builds_all_components_from_one_tool_fetch(self):
        context = self.make_context()

        with (
            patch.object(service_context_module, "ServerRegistry") as registry,
            patch.object(service_context_module, "ToolAdapter") as tool_adapter,
            patch.object(service_context_module, "ToolManager") as tool_manager,
            patch.object(service_context_module, "MCPClient") as mcp_client,
            patch.object(service_context_module, "ToolExecutor") as tool_executor,
        ):
            tool_adapter.return_value.build_tools = AsyncMock(
                return_value=("prompt", ["openai"], ["claude"], {"raw": {}})
            )
            await context._init_mcp_components(True, ["server"])

        tool_adapter.assert_called_once_with(server_registry=registry.return_value)
        tool_adapter.return_value.build_tools.assert_awaited_once_with(["server"])
        self.assertEqual(context.mcp_prompt, "prompt")
        tool_manager.assert_called_once_with(
            formatted_tools_openai=["openai"],
            formatted_tools_claude=["claude"],
            initial_tools_dict={"raw": {}},
        )
        mcp_client.assert_called_once_with(registry.return_value, None, "client")
        tool_executor.assert_called_once_with(
            mcp_client.return_value, tool_manager.return_value
        )

    async def test_creates_adapter_when_none_is_shared(self):
        context = self.make_context()
        context.tool_adapter = None

        with (
            patch.object(service_context_module, "ServerRegistry") as registry,
            patch.object(service_context_module, "ToolAdapter") as tool_adapter,
            patch.object(service_context_module, "ToolManager"),
            patch.object(service_context_module, "MCPClient") as mcp_client,
            patch.object(service_context_module, "ToolExecutor"),
        ):
            tool_adapter.return_value.build_tools = AsyncMock(
                return_value=("prompt", [], [], {})
            )
            await context._init_mcp_components(True, ["server"])

        tool_adapter.assert_called_once_with(server_registry=registry.return_value)
        self.assertEqual(context.mcp_prompt, "prompt")
        mcp_client.assert_called_once()

    async def test_tool_fetch_failure_still_builds_client_only(self):
        context = self.make_context()

        with (
            patch.object(service_context_module, "ServerRegistry"),
            patch.object(service_context_module, "ToolAdapter") as tool_adapter,
            patch.object(service_context_module, "MCPClient") as mcp_client,
            patch.object(service_context_module, "ToolExecutor") as tool_executor,
        ):
            tool_adapter.return_value.build_tools = AsyncMock(
                side_effect=RuntimeError("boom")
            )
            await context._init_mcp_components(True, ["server"])

        self.assertIsNone(context.tool_manager)
        self.assertEqual(context.mcp_prompt, "[Error constructing MCP tools/prompt]")
        mcp_client.assert_called_once()
        tool_executor.assert_not_called()

    async def test_disabled_mcp_resets_components(self):
        context = self.make_context()
        context.mcp_client = Mock()

        await context._init_mcp_components(False, [])

        self.assertIsNone(context.mcp_client)
        self.assertEqual(context.mcp_prompt, "")


if __name__ == "__main__":
    unittest.main()
