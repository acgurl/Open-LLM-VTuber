import json
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.mcpp.mcp_client import MCPClient
    from open_llm_vtuber.mcpp.server_registry import ServerRegistry
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class FakeSession:
    def __init__(self) -> None:
        self.list_tools_calls = 0
        self.call_tool_calls = []

    async def list_tools(self):
        self.list_tools_calls += 1
        return SimpleNamespace(tools=[])

    async def call_tool(self, tool_name, tool_args):
        self.call_tool_calls.append((tool_name, tool_args))
        return SimpleNamespace(isError=False, content=[], metadata={})


class TransportSelectionTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, servers: dict) -> MCPClient:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "mcp_servers.json"
        config_path.write_text(
            json.dumps({"mcp_servers": servers}), encoding="utf-8"
        )
        return MCPClient(ServerRegistry(config_path))

    async def test_http_server_uses_http_session(self):
        client = self.make_client(
            {"remote": {"url": "http://127.0.0.1:8765/mcp"}}
        )
        session = FakeSession()
        http_calls = []

        @asynccontextmanager
        async def fake_http_session(server_name, server, timeout):
            http_calls.append(server_name)
            yield session

        async def fail_stdio(_server_name):
            raise AssertionError("stdio session must not be used for HTTP servers")

        with patch.object(client, "_http_session", fake_http_session), patch.object(
            client, "_ensure_stdio_session", fail_stdio
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

        with patch.object(client, "_http_session", fail_http_session), patch.object(
            client, "_ensure_stdio_session", fake_stdio_session
        ):
            await client.list_tools("local")
            await client.call_tool("local", "ping", {})

        self.assertEqual(stdio_calls, ["local", "local"])
        self.assertEqual(session.list_tools_calls, 1)
        self.assertEqual(session.call_tool_calls, [("ping", {})])


if __name__ == "__main__":
    unittest.main()
