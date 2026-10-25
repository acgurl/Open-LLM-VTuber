import json
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber import service_context as service_context_module
    from open_llm_vtuber.mcpp import tool_adapter as tool_adapter_module
    from open_llm_vtuber.mcpp import user_servers as user_servers_module
    from open_llm_vtuber.mcpp.local_bridge import LocalMCPBridge
    from open_llm_vtuber.mcpp.server_registry import ServerRegistry
    from open_llm_vtuber.mcpp.tool_adapter import ToolAdapter
    from open_llm_vtuber.mcpp.types import MCPServer
    from open_llm_vtuber.mcpp.user_servers import (
        MAX_MCP_RESULT_BYTES,
        build_user_mcp_servers,
        classify_mcp_url,
        local_mcp_config_payload,
        make_exposed_tool_name,
        parse_user_mcp_config,
        split_user_mcp_servers,
        unique_tool_name,
        validate_headers,
        validate_local_tool,
        validate_public_https_url,
        validate_server_name,
    )
    from open_llm_vtuber.message_handler import message_handler
    from open_llm_vtuber.service_context import ServiceContext
    from open_llm_vtuber.storage.sqlite import SQLiteHistoryRepository
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class UserMCPStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = SQLiteHistoryRepository(":memory:")
        await self.repo.initialize()
        await self.repo.ensure_user("alice", "Alice")
        await self.repo.ensure_user("bob", "Bob")

    async def asyncTearDown(self):
        await self.repo.close()

    async def test_crud_is_scoped_to_the_owner(self):
        created = await self.repo.create_user_mcp_server(
            user_id="alice",
            name="my-tools",
            url="https://mcp.example.com/mcp",
            headers={"Authorization": "Bearer a"},
            enabled=False,
        )

        self.assertEqual(created["user_id"], "alice")
        self.assertFalse(created["enabled"])
        self.assertEqual(await self.repo.list_user_mcp_servers(user_id="bob"), [])

        updated = await self.repo.update_user_mcp_server(
            user_id="alice",
            server_id=created["id"],
            name="renamed",
            url="https://mcp.example.com/v2",
            headers={"X-Key": "k"},
            enabled=True,
        )
        self.assertEqual(updated["name"], "renamed")
        self.assertTrue(updated["enabled"])
        self.assertEqual(updated["headers"], {"X-Key": "k"})
        self.assertIsNone(
            await self.repo.update_user_mcp_server(
                user_id="bob",
                server_id=created["id"],
                name="hijack",
                url="https://evil.example.com/mcp",
                headers={},
                enabled=True,
            )
        )

        self.assertFalse(
            await self.repo.delete_user_mcp_server(
                user_id="bob", server_id=created["id"]
            )
        )
        self.assertTrue(
            await self.repo.delete_user_mcp_server(
                user_id="alice", server_id=created["id"]
            )
        )
        self.assertEqual(await self.repo.list_user_mcp_servers(user_id="alice"), [])

    async def test_transport_round_trip(self):
        created = await self.repo.create_user_mcp_server(
            user_id="alice",
            name="sse",
            url="http://127.0.0.1:8788/sse",
            headers={},
            mode="local",
            transport="sse",
        )
        self.assertEqual(created["transport"], "sse")
        self.assertEqual(created["mode"], "local")

        records = await self.repo.replace_user_mcp_servers(
            user_id="alice",
            servers=[
                {
                    "name": "sse",
                    "url": "http://127.0.0.1:8788/sse",
                    "headers": {},
                    "enabled": True,
                    "mode": "local",
                    "transport": "sse",
                }
            ],
        )
        self.assertEqual(records[0]["id"], created["id"])
        self.assertEqual(records[0]["transport"], "sse")

    async def test_duplicate_names_are_rejected(self):
        await self.repo.create_user_mcp_server(
            user_id="alice",
            name="same",
            url="https://a.example.com/mcp",
            headers={},
        )
        with self.assertRaises(ValueError):
            await self.repo.create_user_mcp_server(
                user_id="alice",
                name="same",
                url="https://b.example.com/mcp",
                headers={},
            )

        other = await self.repo.create_user_mcp_server(
            user_id="alice",
            name="other",
            url="https://c.example.com/mcp",
            headers={},
        )
        with self.assertRaises(ValueError):
            await self.repo.update_user_mcp_server(
                user_id="alice",
                server_id=other["id"],
                name="same",
                url="https://c.example.com/mcp",
                headers={},
                enabled=True,
            )


class URLValidationTests(unittest.TestCase):
    def test_accepts_public_https(self):
        with patch.object(
            user_servers_module.socket, "getaddrinfo", side_effect=_public_dns
        ):
            self.assertEqual(
                validate_public_https_url("https://mcp.example.com/mcp"),
                "https://mcp.example.com/mcp",
            )

    def test_rejects_private_loopback_and_link_local(self):
        for address in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.2"):
            with self.subTest(address=address):
                with patch.object(
                    user_servers_module.socket,
                    "getaddrinfo",
                    return_value=[
                        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
                    ],
                ):
                    with self.assertRaises(ValueError):
                        validate_public_https_url("https://mcp.example.com/mcp")

    def test_rejects_if_any_resolved_address_is_private(self):
        with patch.object(
            user_servers_module.socket,
            "getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
            ],
        ):
            with self.assertRaises(ValueError):
                validate_public_https_url("https://mcp.example.com/mcp")

    def test_rejects_non_https_credentials_and_local_names(self):
        for url in (
            "http://mcp.example.com/mcp",
            "https://user:pass@mcp.example.com/mcp",
            "https://mcp.example.com/mcp#frag",
            "https://localhost/mcp",
            "https://service.internal/mcp",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_https_url(url)


class URLClassificationTests(unittest.TestCase):
    def test_local_urls_do_not_require_dns(self):
        for url in (
            "http://127.0.0.1:3001/mcp",
            "https://localhost:3001/mcp",
            "http://192.168.1.5:3001/mcp",
            "http://[::1]:3001/mcp",
            "http://my-pc:3001/mcp",
            "http://nas.local:3001/mcp",
        ):
            with self.subTest(url=url):
                self.assertEqual(classify_mcp_url(url), "local")

    def test_public_https_is_remote(self):
        with patch.object(
            user_servers_module.socket, "getaddrinfo", side_effect=_public_dns
        ):
            self.assertEqual(classify_mcp_url("https://mcp.example.com/mcp"), "remote")

    def test_hostname_resolving_private_is_local(self):
        with patch.object(
            user_servers_module.socket,
            "getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))
            ],
        ):
            self.assertEqual(classify_mcp_url("http://mcp.example.com/mcp"), "local")

    def test_public_http_is_rejected(self):
        with patch.object(
            user_servers_module.socket, "getaddrinfo", side_effect=_public_dns
        ):
            with self.assertRaises(ValueError):
                classify_mcp_url("http://mcp.example.com/mcp")

    def test_config_document_is_classified(self):
        with patch.object(
            user_servers_module.socket, "getaddrinfo", side_effect=_public_dns
        ):
            parsed = parse_user_mcp_config(
                {
                    "mcp_servers": {
                        "remote": {
                            "url": "https://mcp.example.com/mcp",
                            "headers": {"Authorization": "Bearer x"},
                        },
                        "local": {
                            "url": "http://127.0.0.1:3001/mcp",
                            "enabled": False,
                        },
                    }
                }
            )
        modes = {entry["name"]: entry["mode"] for entry in parsed}
        self.assertEqual(modes, {"remote": "remote", "local": "local"})
        self.assertFalse(parsed[1]["enabled"])

    def test_config_rejects_stdio_and_unknown_keys(self):
        for config in (
            {"mcp_servers": {"x": {"command": "uvx", "args": ["server"]}}},
            {"mcp_servers": {"x": {"url": "http://127.0.0.1:1/mcp", "cwd": "/"}}},
            {"servers": {}},
            {"mcp_servers": []},
        ):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    parse_user_mcp_config(config)

    def test_standard_mcpservers_and_sse_are_supported(self):
        parsed = parse_user_mcp_config(
            {
                "mcpServers": {
                    "local-sse": {
                        "type": "sse",
                        "url": "http://127.0.0.1:8788/sse?key=k",
                    }
                }
            }
        )
        self.assertEqual(parsed[0]["mode"], "local")
        self.assertEqual(parsed[0]["transport"], "sse")

        with patch.object(
            user_servers_module.socket, "getaddrinfo", side_effect=_public_dns
        ):
            parsed = parse_user_mcp_config(
                {
                    "mcp_servers": {
                        "remote-sse": {
                            "type": "sse",
                            "url": "https://mcp.example.com/sse",
                        }
                    }
                }
            )
        self.assertEqual(parsed[0]["mode"], "remote")
        self.assertEqual(parsed[0]["transport"], "sse")

    def test_stdio_and_conflicting_transports_are_rejected(self):
        for config in (
            {"mcpServers": {"x": {"type": "stdio", "url": "http://127.0.0.1:1/mcp"}}},
            {
                "mcp_servers": {
                    "x": {
                        "type": "sse",
                        "transport": "http",
                        "url": "http://127.0.0.1:1/mcp",
                    }
                }
            },
        ):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    parse_user_mcp_config(config)

    def test_split_and_local_payload(self):
        records = [
            {
                "id": "remote",
                "name": "Remote",
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer r"},
                "enabled": True,
                "mode": "remote",
            },
            {
                "id": "local",
                "name": "Local",
                "url": "http://127.0.0.1:3001/mcp",
                "headers": {"Authorization": "Bearer l"},
                "enabled": True,
                "mode": "local",
            },
            {
                "id": "disabled",
                "name": "Disabled",
                "url": "http://127.0.0.1:3002/mcp",
                "headers": {},
                "enabled": False,
                "mode": "local",
            },
        ]
        remote, local = split_user_mcp_servers(records)
        self.assertEqual([record["id"] for record in remote], ["remote"])
        self.assertEqual([record["id"] for record in local], ["local"])
        payload = local_mcp_config_payload(local)
        self.assertEqual(payload[0]["server_id"], "local")
        self.assertEqual(payload[0]["headers"], {"Authorization": "Bearer l"})


class ServerNameTests(unittest.TestCase):
    def test_accepts_display_names(self):
        self.assertEqual(validate_server_name("My tools"), "My tools")
        self.assertEqual(validate_server_name("我的工具"), "我的工具")

    def test_rejects_control_characters(self):
        for name in ("bad\nname", "bad\tname", "x" * 65, " padded "):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_server_name(name)


class HeaderValidationTests(unittest.TestCase):
    def test_accepts_auth_headers(self):
        headers = {"Authorization": "Bearer token", "X-Trace": "1"}
        self.assertEqual(validate_headers(headers), headers)

    def test_rejects_hop_by_hop_and_injection(self):
        for headers in (
            {"Host": "evil"},
            {"Cookie": "session=1"},
            {"X-Test": "a\r\nb"},
            {"X-Test": 123},
        ):
            with self.subTest(headers=headers):
                with self.assertRaises(ValueError):
                    validate_headers(headers)

    def test_rejects_too_many_headers(self):
        with self.assertRaises(ValueError):
            validate_headers({f"X-{index}": "v" for index in range(17)})


class LocalToolValidationTests(unittest.TestCase):
    def test_valid_tool_round_trip(self):
        name, description, schema = validate_local_tool(
            {
                "name": "read_file",
                "description": "Read a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        )
        self.assertEqual(name, "read_file")
        self.assertEqual(description, "Read a file")
        self.assertEqual(schema["properties"]["path"]["type"], "string")

    def test_invalid_tools_are_rejected(self):
        for tool in (
            {"name": "bad name", "inputSchema": {"type": "object"}},
            {"name": "ok", "inputSchema": "not-an-object"},
            {"name": "ok", "inputSchema": {"type": "object", "required": "path"}},
            {"name": "ok", "inputSchema": {"type": "object"}, "description": 3},
        ):
            with self.subTest(tool=tool):
                with self.assertRaises(ValueError):
                    validate_local_tool(tool)

    def test_exposed_names_are_safe_and_unique(self):
        first = make_exposed_tool_name("l", "local:one", "read_file")
        second = make_exposed_tool_name("l", "local:two", "read_file")
        self.assertNotEqual(first, second)
        self.assertLessEqual(len(first), 64)
        self.assertRegex(first, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(unique_tool_name(first, {first}), f"{first[:62]}_2")

    def test_build_user_servers_filters_disabled(self):
        servers = build_user_mcp_servers(
            [
                {
                    "id": "one",
                    "name": "One",
                    "url": "https://mcp.example.com/mcp",
                    "headers": {},
                    "enabled": True,
                },
                {
                    "id": "two",
                    "name": "Two",
                    "url": "https://two.example.com/mcp",
                    "headers": {},
                    "enabled": False,
                },
            ]
        )
        self.assertIn("user:one", servers)
        self.assertNotIn("user:two", servers)
        self.assertTrue(servers["user:one"].is_user)
        self.assertEqual(servers["user:one"].display_name, "One")


class LocalMCPBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        message_handler.cleanup_client("client")

    async def _call(self, responder, timeout=0.2, key="local:abc"):
        def send(payload):
            request = json.loads(payload)
            response = responder(request)
            if response is not None:
                message_handler.handle_message("client", response)

        bridge = LocalMCPBridge("client", send, timeout=timeout)
        return await bridge.call_tool(
            server_key=key, tool_name="echo", tool_args={"text": "hello"}
        )

    async def test_returns_text_content(self):
        def responder(request):
            return {
                "type": "local-tool-result",
                "request_id": request["request_id"],
                "server_id": "abc",
                "content_items": [{"type": "text", "text": "ok"}],
            }

        result = await self._call(responder)
        self.assertEqual(result["content_items"], [{"type": "text", "text": "ok"}])

    async def test_error_result(self):
        def responder(request):
            return {
                "type": "local-tool-result",
                "request_id": request["request_id"],
                "server_id": "abc",
                "is_error": True,
                "content_items": [{"type": "error", "text": "boom"}],
            }

        result = await self._call(responder)
        self.assertEqual(result["content_items"][0]["type"], "error")
        self.assertEqual(result["content_items"][0]["text"], "boom")

    async def test_timeout_returns_an_error(self):
        result = await self._call(lambda request: None, timeout=0.05)
        self.assertEqual(result["content_items"][0]["type"], "error")

    async def test_mismatched_server_is_rejected(self):
        def responder(request):
            return {
                "type": "local-tool-result",
                "request_id": request["request_id"],
                "server_id": "other",
                "content_items": [{"type": "text", "text": "ok"}],
            }

        result = await self._call(responder)
        self.assertEqual(result["content_items"][0]["type"], "error")


class LocalToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        message_handler.cleanup_client("client")

    async def test_executor_sends_the_remote_tool_name_to_the_browser(self):
        from open_llm_vtuber.mcpp.tool_executor import ToolExecutor
        from open_llm_vtuber.mcpp.tool_manager import ToolManager
        from open_llm_vtuber.mcpp.types import FormattedTool

        sent_payloads = []

        def send(payload):
            request = json.loads(payload)
            sent_payloads.append(request)
            message_handler.handle_message(
                "client",
                {
                    "type": "local-tool-result",
                    "request_id": request["request_id"],
                    "server_id": "abc",
                    "content_items": [{"type": "text", "text": "ok"}],
                },
            )

        exposed = "l_abc123_echo"
        manager = ToolManager(
            initial_tools_dict={
                exposed: FormattedTool(
                    input_schema={"type": "object", "properties": {}},
                    related_server="local:abc",
                    remote_name="echo",
                )
            }
        )
        bridge = LocalMCPBridge("client", send, timeout=0.2)
        executor = ToolExecutor(None, manager, bridge)

        updates = [
            update
            async for update in executor.execute_tools(
                [{"id": "call-1", "name": exposed, "args": {"text": "hi"}}],
                "OpenAI",
            )
        ]

        self.assertEqual(sent_payloads[0]["tool_name"], "echo")
        self.assertEqual(sent_payloads[0]["arguments"], {"text": "hi"})
        self.assertTrue(all(update.get("scoped") for update in updates[:-1]))
        final = updates[-1]
        self.assertEqual(final["type"], "final_tool_results")
        self.assertIn("ok", str(final["results"]))

    async def test_oversized_local_result_is_rejected_by_the_executor(self):
        from open_llm_vtuber.mcpp.tool_executor import ToolExecutor
        from open_llm_vtuber.mcpp.tool_manager import ToolManager
        from open_llm_vtuber.mcpp.types import FormattedTool

        def send(payload):
            request = json.loads(payload)
            message_handler.handle_message(
                "client",
                {
                    "type": "local-tool-result",
                    "request_id": request["request_id"],
                    "server_id": "abc",
                    "content_items": [
                        {"type": "text", "text": "x" * (MAX_MCP_RESULT_BYTES + 1)}
                    ],
                },
            )

        exposed = "l_abc123_echo"
        manager = ToolManager(
            initial_tools_dict={
                exposed: FormattedTool(
                    input_schema={"type": "object", "properties": {}},
                    related_server="local:abc",
                    remote_name="echo",
                )
            }
        )
        executor = ToolExecutor(
            None, manager, LocalMCPBridge("client", send, timeout=0.2)
        )

        updates = [
            update
            async for update in executor.execute_tools(
                [{"id": "call-1", "name": exposed, "args": {}}],
                "OpenAI",
            )
        ]

        self.assertIn("exceeded the size limit", str(updates[-1]["results"]))


class LocalRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def _context(self):
        context = ServiceContext()
        context.client_uid = "client"
        context.channels = SimpleNamespace(text=lambda payload: None)
        context._local_mcp_config = {
            "local": {
                "id": "local",
                "name": "Local tools",
                "url": "http://127.0.0.1:3001/mcp",
            }
        }
        return context

    async def test_registers_and_unregisters_tools(self):
        context = self._context()
        try:
            exposed = context.register_local_mcp_server(
                server_id="local",
                tools=[
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    }
                ],
            )
            self.assertEqual(len(exposed), 1)
            self.assertTrue(exposed[0].startswith("l_"))
            self.assertTrue(context.mcp_active)
            self.assertIn("Server: Local tools", context.mcp_prompt)
            tool = context.tool_manager.get_tool(exposed[0])
            self.assertEqual(tool.remote_name, "echo")
            self.assertEqual(tool.related_server, "local:local")

            self.assertTrue(context.unregister_local_mcp_server("local"))
            self.assertFalse(context.mcp_active)
            self.assertIsNone(context.tool_manager)
        finally:
            await context.close()

    async def test_existing_tool_name_is_not_shadowed(self):
        context = self._context()
        try:
            candidate = make_exposed_tool_name("l", "local:local", "echo")
            context._base_mcp_tools = {
                candidate: user_servers_module_formatted_tool(candidate)
            }
            exposed = context.register_local_mcp_server(
                server_id="local",
                tools=[{"name": "echo", "inputSchema": {"type": "object"}}],
            )
            self.assertNotEqual(exposed[0], candidate)
            self.assertEqual(
                context.tool_manager.get_tool(candidate).related_server, "global"
            )
        finally:
            await context.close()

    async def test_rejects_without_browser_channel(self):
        context = ServiceContext()
        with self.assertRaises(ValueError):
            context.register_local_mcp_server(server_id="local", tools=[])


def user_servers_module_formatted_tool(name):
    from open_llm_vtuber.mcpp.types import FormattedTool

    return FormattedTool(
        input_schema={"type": "object", "properties": {}},
        related_server="global",
        description="base",
        remote_name=name,
    )


class RegistryMergeTests(unittest.TestCase):
    def test_user_servers_are_added_without_mutating_global(self):
        global_registry = ServerRegistry(
            servers={
                "cuc-kb": MCPServer(name="cuc-kb", url="http://127.0.0.1:8765/mcp")
            }
        )
        user_server = MCPServer(
            name="user:abc",
            url="https://mcp.example.com/mcp",
            is_user=True,
            display_name="Mine",
        )

        merged = global_registry.merged_with({"user:abc": user_server})

        self.assertIn("cuc-kb", merged.servers)
        self.assertIn("user:abc", merged.servers)
        self.assertNotIn("user:abc", global_registry.servers)
        self.assertFalse(merged.get_server("cuc-kb").is_user)

    def test_global_names_cannot_be_overridden(self):
        global_registry = ServerRegistry(
            servers={
                "cuc-kb": MCPServer(name="cuc-kb", url="http://127.0.0.1:8765/mcp")
            }
        )
        merged = global_registry.merged_with(
            {
                "cuc-kb": MCPServer(
                    name="cuc-kb",
                    url="https://evil.example.com/mcp",
                    is_user=True,
                )
            }
        )
        self.assertEqual(merged.get_server("cuc-kb").url, "http://127.0.0.1:8765/mcp")


class ToolNamespaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_tools_are_namespaced_and_global_tools_are_unchanged(self):
        tools = {
            "cuc-kb": [
                UserTool("kb_search", "Search the knowledge base"),
            ],
            "user:abc": [
                UserTool("read_file", "Read a local file"),
            ],
        }

        class FakeClient:
            def __init__(self, registry):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def list_tools(self, server_name):
                return tools[server_name]

        registry = ServerRegistry.from_servers(
            {
                "cuc-kb": MCPServer(name="cuc-kb", url="http://127.0.0.1:8765/mcp"),
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
            prompt, _, _, raw = await adapter.build_tools(["cuc-kb", "user:abc"])

        self.assertIn("kb_search", raw)
        self.assertEqual(raw["kb_search"].related_server, "cuc-kb")
        user_tools = [
            name for name, tool in raw.items() if tool.related_server == "user:abc"
        ]
        self.assertEqual(len(user_tools), 1)
        self.assertTrue(user_tools[0].startswith("u_"))
        self.assertEqual(raw[user_tools[0]].remote_name, "read_file")
        self.assertIn("Server: cuc-kb", prompt)
        self.assertIn("Server: My tools", prompt)

    async def test_user_tool_count_is_capped(self):
        tools = {
            "user:abc": [
                UserTool(f"tool_{index}", "description") for index in range(70)
            ]
        }

        class FakeClient:
            def __init__(self, registry):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def list_tools(self, server_name):
                return tools[server_name]

        registry = ServerRegistry.from_servers(
            {
                "user:abc": MCPServer(
                    name="user:abc",
                    url="https://mcp.example.com/mcp",
                    is_user=True,
                )
            }
        )
        adapter = ToolAdapter(registry)
        with patch.object(tool_adapter_module, "MCPClient", FakeClient):
            _, _, _, raw = await adapter.build_tools(["user:abc"])

        self.assertEqual(len(raw), 64)


class UserServerSessionInitTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_servers_enable_tooling_when_character_disables_mcp(self):
        context = ServiceContext()
        context.channels = None
        context.client_uid = "client"
        context._user_mcp_records = [
            {
                "id": "abc",
                "name": "Mine",
                "url": "https://mcp.example.com/mcp",
                "headers": {},
                "enabled": True,
            }
        ]

        with (
            patch.object(service_context_module, "ServerRegistry") as registry_cls,
            patch.object(service_context_module, "ToolAdapter") as adapter_cls,
            patch.object(service_context_module, "ToolManager"),
            patch.object(service_context_module, "MCPClient"),
            patch.object(service_context_module, "ToolExecutor"),
        ):
            registry_cls.return_value.merged_with.return_value = (
                registry_cls.return_value
            )
            adapter_cls.return_value.build_tools = AsyncMock(
                return_value=("prompt", ["openai"], ["claude"], {"raw": {}})
            )

            await context._init_mcp_components(False, [])

        adapter_cls.assert_called_once_with(server_registry=registry_cls.return_value)
        adapter_cls.return_value.build_tools.assert_awaited_once_with(["user:abc"])
        self.assertTrue(context.mcp_active)


def UserTool(name, description):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )


if __name__ == "__main__":
    unittest.main()
