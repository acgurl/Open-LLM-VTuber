import asyncio
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from open_llm_vtuber.mcp_routes import init_user_mcp_routes
    from open_llm_vtuber.service_context import ServiceContext
    from open_llm_vtuber.storage.sqlite import SQLiteHistoryRepository
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


class UserMCPConfigRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = SQLiteHistoryRepository(":memory:")
        asyncio.run(self.repo.initialize())
        asyncio.run(self.repo.ensure_user("local", "Local User"))

        self.context = ServiceContext()
        self.context.user_id = "local"
        self.context.set_history_storage(self.repo, "local")

        self.app = FastAPI()
        self.app.include_router(init_user_mcp_routes(self.context, auth=None))
        self.client = TestClient(self.app)

        self.dns_patch = patch(
            "open_llm_vtuber.mcpp.user_servers.socket.getaddrinfo",
            side_effect=_public_dns,
        )
        self.dns_patch.start()

    def tearDown(self):
        self.dns_patch.stop()
        asyncio.run(self.repo.close())

    def _put(self, config):
        return self.client.put("/api/mcp/config", json={"config": config})

    def test_put_and_get_unified_config(self):
        response = self._put(
            {
                "mcp_servers": {
                    "remote": {
                        "url": "https://mcp.example.com/mcp",
                        "headers": {"Authorization": "Bearer secret"},
                    },
                    "local": {"url": "http://127.0.0.1:3001/mcp"},
                }
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        modes = {server["name"]: server["mode"] for server in data["servers"]}
        self.assertEqual(modes, {"remote": "remote", "local": "local"})
        self.assertEqual(
            data["config"]["mcp_servers"]["remote"]["headers"],
            {"Authorization": "***"},
        )
        self.assertNotIn("headers", data["config"]["mcp_servers"]["local"])
        self.assertNotIn("secret", response.text)

        listing = self.client.get("/api/mcp/config")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["servers"], data["servers"])

    def test_masked_header_round_trip_keeps_secret(self):
        first = self._put(
            {
                "mcp_servers": {
                    "remote": {
                        "url": "https://mcp.example.com/mcp",
                        "headers": {"Authorization": "Bearer secret"},
                    }
                }
            }
        ).json()

        second = self._put(first["config"])
        self.assertEqual(second.status_code, 200, second.text)

        records = asyncio.run(self.repo.list_user_mcp_servers(user_id="local"))
        self.assertEqual(records[0]["headers"], {"Authorization": "Bearer secret"})

    def test_removing_entries_deletes_rows(self):
        self._put(
            {
                "mcp_servers": {
                    "one": {"url": "http://127.0.0.1:3001/mcp"},
                    "two": {"url": "http://127.0.0.1:3002/mcp"},
                }
            }
        )
        response = self._put(
            {"mcp_servers": {"one": {"url": "http://127.0.0.1:3001/mcp"}}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [server["name"] for server in response.json()["servers"]], ["one"]
        )
        self.assertEqual(
            len(asyncio.run(self.repo.list_user_mcp_servers(user_id="local"))), 1
        )

    def test_local_sse_config_round_trip(self):
        response = self._put(
            {
                "mcpServers": {
                    "local-sse": {
                        "type": "sse",
                        "url": "http://127.0.0.1:8788/sse?key=secret",
                    }
                }
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["servers"][0]["mode"], "local")
        self.assertEqual(data["servers"][0]["transport"], "sse")
        self.assertEqual(data["config"]["mcp_servers"]["local-sse"]["type"], "sse")
        self.assertEqual(
            data["config"]["mcp_servers"]["local-sse"]["url"],
            "http://127.0.0.1:8788/sse?key=secret",
        )

    def test_stdio_and_public_http_are_rejected(self):
        for config in (
            {"mcp_servers": {"x": {"command": "uvx", "args": ["server"]}}},
            {"mcp_servers": {"x": {"url": "http://mcp.example.com/mcp"}}},
        ):
            with self.subTest(config=config):
                response = self._put(config)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn("error", response.json())

    def test_limit_is_enforced(self):
        servers = {
            f"local-{index}": {"url": f"http://127.0.0.1:{3000 + index}/mcp"}
            for index in range(9)
        }
        response = self._put({"mcp_servers": servers})
        self.assertEqual(response.status_code, 400)

        five_local = {
            f"local-{index}": {"url": f"http://127.0.0.1:{3000 + index}/mcp"}
            for index in range(5)
        }
        self.assertEqual(self._put({"mcp_servers": five_local}).status_code, 400)

    def test_local_test_endpoint_does_not_dial(self):
        created = self._put(
            {"mcp_servers": {"local": {"url": "http://127.0.0.1:3001/mcp"}}}
        ).json()
        server_id = created["servers"][0]["id"]
        response = self.client.post(
            "/api/mcp/config/test", json={"server_id": server_id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "local", "tools": []})

    def test_test_missing_server(self):
        response = self.client.post(
            "/api/mcp/config/test", json={"server_id": "missing"}
        )
        self.assertEqual(response.status_code, 404)

    def test_oidc_requires_identity(self):
        app = FastAPI()
        app.include_router(
            init_user_mcp_routes(self.context, auth=SimpleNamespace(enabled=True))
        )
        client = TestClient(app)
        self.assertEqual(client.get("/api/mcp/config").status_code, 401)

    def test_missing_storage_returns_503(self):
        context = ServiceContext()
        context.user_id = "local"
        app = FastAPI()
        app.include_router(init_user_mcp_routes(context, auth=None))
        client = TestClient(app)
        self.assertEqual(client.get("/api/mcp/config").status_code, 503)


if __name__ == "__main__":
    unittest.main()
