import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcp import types

from open_llm_vtuber.mcpp.mcp_client import MCPClient
from open_llm_vtuber.mcpp.server_registry import ServerRegistry


class FakeSession:
    def __init__(self) -> None:
        self.list_tools_calls = 0
        self.call_tool_calls = []

    async def list_tools(self):
        self.list_tools_calls += 1
        return SimpleNamespace(tools=[])

    async def call_tool(self, tool_name, tool_args):
        self.call_tool_calls.append((tool_name, tool_args))
        return SimpleNamespace(isError=False, content=[], meta={})


class TransportSelectionTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, servers: dict) -> MCPClient:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "mcp_servers.json"
        config_path.write_text(json.dumps({"mcp_servers": servers}), encoding="utf-8")
        return MCPClient(ServerRegistry(config_path))

    async def test_http_server_uses_http_session(self):
        client = self.make_client({"remote": {"url": "http://127.0.0.1:8765/mcp"}})
        session = FakeSession()
        http_calls = []

        @asynccontextmanager
        async def fake_http_session(server_name, server, timeout):
            http_calls.append(server_name)
            yield session

        async def fail_stdio(_server_name):
            raise AssertionError("stdio session must not be used for HTTP servers")

        with (
            patch.object(client, "_http_session", fake_http_session),
            patch.object(client, "_ensure_stdio_session", fail_stdio),
        ):
            tools = await client.list_tools("remote")
            await client.call_tool("remote", "ping", {"q": 1})

        self.assertEqual(tools, [])
        self.assertEqual(http_calls, ["remote", "remote"])
        self.assertEqual(session.list_tools_calls, 1)
        self.assertEqual(session.call_tool_calls, [("ping", {"q": 1})])

    async def test_stdio_server_uses_stdio_session(self):
        client = self.make_client({"local": {"command": "python", "args": []}})
        session = FakeSession()
        stdio_calls = []

        async def fake_stdio_session(server_name):
            stdio_calls.append(server_name)
            return session

        def fail_http_session(*_args, **_kwargs):
            raise AssertionError("HTTP session must not be used for stdio servers")

        with (
            patch.object(client, "_http_session", fail_http_session),
            patch.object(client, "_ensure_stdio_session", fake_stdio_session),
        ):
            await client.list_tools("local")
            await client.call_tool("local", "ping", {})

        self.assertEqual(stdio_calls, ["local", "local"])
        self.assertEqual(session.list_tools_calls, 1)
        self.assertEqual(session.call_tool_calls, [("ping", {})])

    async def test_parallel_calls_start_one_stdio_server(self):
        client = self.make_client({"local": {"command": "python", "args": []}})
        session = FakeSession()
        started = []

        async def fake_start(server_name):
            started.append(server_name)
            await asyncio.sleep(0.01)
            client.active_sessions[server_name] = session
            return session

        with patch.object(client, "_start_stdio_session", fake_start):
            await asyncio.gather(
                client.call_tool("local", "a", {}),
                client.call_tool("local", "b", {}),
                client.call_tool("local", "c", {}),
            )

        self.assertEqual(started, ["local"])
        self.assertEqual(len(session.call_tool_calls), 3)


class _ResultSession:
    def __init__(self, result: types.CallToolResult) -> None:
        self.result = result

    async def call_tool(self, tool_name, tool_args):
        return self.result


class CallToolResultMappingTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, result: types.CallToolResult) -> dict:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "mcp_servers.json"
        config_path.write_text(
            json.dumps({"mcp_servers": {"local": {"command": "python", "args": []}}}),
            encoding="utf-8",
        )
        client = MCPClient(ServerRegistry(config_path))
        session = _ResultSession(result)

        async def fake_stdio_session(_server_name):
            return session

        with patch.object(client, "_ensure_stdio_session", fake_stdio_session):
            return await client.call_tool("local", "tool", {})

    async def test_meta_is_returned_as_metadata(self):
        live_view = {"liveViewData": {"url": "https://view"}}
        result = types.CallToolResult.model_validate(
            {"_meta": live_view, "content": [{"type": "text", "text": "ok"}]}
        )

        self.assertEqual((await self._call(result))["metadata"], live_view)

    async def test_error_result_keeps_meta(self):
        result = types.CallToolResult.model_validate(
            {
                "_meta": {"k": "v"},
                "isError": True,
                "content": [{"type": "text", "text": "boom"}],
            }
        )

        mapped = await self._call(result)

        self.assertEqual(mapped["metadata"], {"k": "v"})
        self.assertEqual(mapped["content_items"], [{"type": "error", "text": "boom"}])

    async def test_missing_meta_is_empty_dict(self):
        result = types.CallToolResult(content=[])

        self.assertEqual((await self._call(result))["metadata"], {})

    async def test_resource_contents_are_kept(self):
        result = types.CallToolResult(
            content=[
                types.ResourceLink(
                    type="resource_link",
                    name="doc",
                    uri="https://example.com/doc.pdf",
                    mimeType="application/pdf",
                ),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri="file:///notes.txt", mimeType="text/plain", text="hi"
                    ),
                ),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.BlobResourceContents(
                        uri="file:///a.bin",
                        mimeType="application/octet-stream",
                        blob="AAEC",
                    ),
                ),
            ]
        )

        items = (await self._call(result))["content_items"]

        self.assertEqual(
            items,
            [
                {
                    "type": "resource_link",
                    "mimeType": "application/pdf",
                    "url": "https://example.com/doc.pdf",
                },
                {
                    "type": "resource",
                    "text": "hi",
                    "mimeType": "text/plain",
                    "url": "file:///notes.txt",
                },
                {
                    "type": "resource",
                    "data": "AAEC",
                    "mimeType": "application/octet-stream",
                    "url": "file:///a.bin",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
