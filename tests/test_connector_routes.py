import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_llm_vtuber.config_manager.connectors import ConnectorsConfig
from open_llm_vtuber.connector_routes import init_connector_routes
from open_llm_vtuber.connectors import ConnectorManager
from open_llm_vtuber.storage import SQLiteHistoryRepository


class ConnectorRoutesTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(Path(self._temp_dir.name) / "h.db")
        asyncio.run(self.repository.initialize())
        self.student = asyncio.run(
            self.repository.resolve_user_identity(
                provider="https://sso.example",
                subject="s",
                display_name="Student",
                email="s@cuc.edu.cn",
            )
        )
        self.outsider = asyncio.run(
            self.repository.resolve_user_identity(
                provider="https://sso.example", subject="o", email="o@qq.com"
            )
        )
        self.context = SimpleNamespace(
            history_repository=self.repository, user_id=self.student
        )
        self.manager = ConnectorManager(
            self.context,
            ConnectorsConfig(enabled=True),
            factory=lambda _config: None,
        )
        self.app = FastAPI()
        self.app.include_router(
            init_connector_routes(self.context, lambda: self.manager, auth=None)
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        asyncio.run(self.repository.close())
        self._temp_dir.cleanup()

    def test_campus_account_gets_a_redeemable_code(self):
        response = self.client.get("/api/connectors")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["eligible"])

        response = self.client.post("/api/connectors/bind-code")
        self.assertEqual(response.status_code, 200)
        code = response.json()["code"]
        self.assertEqual(self.manager.bind_codes.redeem(code, "qq:u:1"), self.student)

    def test_other_accounts_are_refused_a_code(self):
        self.context.user_id = self.outsider
        self.assertFalse(self.client.get("/api/connectors").json()["eligible"])
        self.assertEqual(self.client.post("/api/connectors/bind-code").status_code, 403)

    def test_bindings_are_listed_and_deleted_by_owner_only(self):
        asyncio.run(
            self.repository.bind_connector_identity(
                connector_id="qq", external_id="u:1", user_id=self.student
            )
        )
        bindings = self.client.get("/api/connectors").json()["bindings"]
        self.assertEqual(
            [(b["connector_id"], b["external_id"]) for b in bindings], [("qq", "u:1")]
        )

        self.context.user_id = self.outsider
        self.assertEqual(
            self.client.delete("/api/connectors/bindings/qq/u:1").status_code, 404
        )
        self.context.user_id = self.student
        self.assertEqual(
            self.client.delete("/api/connectors/bindings/qq/u:1").status_code, 204
        )
        self.assertEqual(self.client.get("/api/connectors").json()["bindings"], [])

    def test_disabled_connectors_return_404(self):
        self.manager = None
        self.assertEqual(self.client.get("/api/connectors").status_code, 404)


if __name__ == "__main__":
    unittest.main()
