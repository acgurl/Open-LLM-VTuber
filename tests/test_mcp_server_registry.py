import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from open_llm_vtuber.mcpp.server_registry import ServerRegistry


class ServerRegistryTests(unittest.TestCase):
    def _load(self, servers):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "mcp_servers.json"
            config_path.write_text(
                json.dumps({"mcp_servers": servers}), encoding="utf-8"
            )
            return ServerRegistry(config_path)

    def test_loads_streamable_http_server(self):
        registry = self._load(
            {
                "cuc-kb": {
                    "url": "http://127.0.0.1:8765/mcp",
                    "headers": {"Authorization": "Bearer test-token"},
                }
            }
        )

        server = registry.get_server("cuc-kb")
        self.assertIsNotNone(server)
        self.assertEqual(server.url, "http://127.0.0.1:8765/mcp")
        self.assertEqual(server.headers, {"Authorization": "Bearer test-token"})
        self.assertEqual(server.command, "")

    def test_loads_sse_server(self):
        registry = self._load(
            {
                "cuc-sse": {
                    "url": "http://127.0.0.1:8788/sse",
                    "type": "sse",
                }
            }
        )

        server = registry.get_server("cuc-sse")
        self.assertIsNotNone(server)
        self.assertEqual(server.transport, "sse")

    def test_loads_stdio_server(self):
        registry = self._load(
            {
                "time": {
                    "command": "uvx",
                    "args": ["mcp-server-time"],
                }
            }
        )

        server = registry.get_server("time")
        self.assertIsNotNone(server)
        self.assertIsNone(server.url)
        self.assertEqual(server.command, "uvx")

    def test_ignores_http_server_with_invalid_url(self):
        registry = self._load(
            {
                "bad-scheme": {"url": "ftp://127.0.0.1/mcp"},
                "missing-host": {"url": "http:///mcp"},
            }
        )

        self.assertIsNone(registry.get_server("bad-scheme"))
        self.assertIsNone(registry.get_server("missing-host"))

    def test_ignores_http_server_with_invalid_headers(self):
        registry = self._load(
            {
                "cuc-kb": {
                    "url": "http://127.0.0.1:8765/mcp",
                    "headers": {"Authorization": 123},
                }
            }
        )

        self.assertIsNone(registry.get_server("cuc-kb"))


if __name__ == "__main__":
    unittest.main()
