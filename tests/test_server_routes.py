import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from open_llm_vtuber.server import WebSocketServer
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class ServerRouteTests(unittest.TestCase):
    def test_registers_health_ws_and_static_mounts(self):
        config = SimpleNamespace(
            system_config=SimpleNamespace(
                enable_proxy=False,
                host="127.0.0.1",
                port=12393,
            )
        )

        previous_cwd = Path.cwd()
        try:
            # Mount directories are resolved relative to the project root.
            import os

            os.chdir(REPO_ROOT)
            server = WebSocketServer(config=config)
        finally:
            os.chdir(previous_cwd)

        paths = {getattr(route, "path", "") for route in server.app.routes}
        names = {getattr(route, "name", "") for route in server.app.routes}
        self.assertIn("/healthz", paths)
        self.assertIn("/client-ws", paths)
        self.assertIn("/auth/login", paths)
        self.assertIn("/auth/callback", paths)
        self.assertIn("/auth/logout", paths)
        self.assertIn("/api/session", paths)
        self.assertIn("/api/mcp/config", paths)
        for name in (
            "cache",
            "live2d-models",
            "backgrounds",
            "avatars",
            "web_tool",
            "frontend",
        ):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
