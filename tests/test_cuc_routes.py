import json
import unittest
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_llm_vtuber.auth import AuthRedirectMiddleware
from open_llm_vtuber.config_manager.cuc import CucAuthConfig
from open_llm_vtuber.cuc_routes import init_cuc_auth_routes


class _FakeAuthManager:
    def __init__(self, user_id: str | None) -> None:
        self.enabled = True
        self._user_id = user_id

    def resolve_identity(self, _cookies):
        if self._user_id is None:
            return None
        return SimpleNamespace(user_id=self._user_id, display_name="User")


class CucConfigValidationTests(unittest.TestCase):
    def test_disabled_allows_empty_api_key(self):
        cfg = CucAuthConfig(enabled=False, api_key="")
        self.assertFalse(cfg.enabled)

    def test_enabled_requires_resolved_api_key(self):
        with self.assertRaises(ValueError):
            CucAuthConfig(enabled=True, api_key="")
        with self.assertRaises(ValueError):
            CucAuthConfig(enabled=True, api_key="${CUC_SERVER_KEY}")

    def test_invalid_server_url_and_header_rejected(self):
        with self.assertRaises(ValueError):
            CucAuthConfig(server_url="ftp://127.0.0.1:8787")
        with self.assertRaises(ValueError):
            CucAuthConfig(user_header="Host")
        with self.assertRaises(ValueError):
            CucAuthConfig(user_prefix="bad prefix!")

    def test_trailing_slash_stripped(self):
        cfg = CucAuthConfig(
            enabled=True,
            server_url="http://127.0.0.1:8787/",
            api_key="secret",
        )
        self.assertEqual(cfg.server_url, "http://127.0.0.1:8787")


class CucRoutesTests(unittest.TestCase):
    def _make_client(
        self,
        *,
        user_id: str | None = "alice",
        auth_enabled: bool = True,
        cuc_enabled: bool = True,
        user_prefix: str = "u_",
        responder=None,
    ):
        recorded: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body_bytes = request.content
            recorded.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "query": dict(request.url.params),
                    "headers": dict(request.headers),
                    "body": json.loads(body_bytes.decode("utf-8"))
                    if body_bytes
                    else None,
                }
            )
            if responder is not None:
                return responder(request)
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        config = CucAuthConfig(
            enabled=cuc_enabled,
            server_url="http://127.0.0.1:8787",
            api_key="srv-secret" if cuc_enabled else "",
            user_header="X-CUC-Profile",
            user_prefix=user_prefix,
        )
        auth = _FakeAuthManager(user_id) if auth_enabled else None
        context = SimpleNamespace(user_id="local")
        app = FastAPI()
        if auth is not None:
            app.add_middleware(AuthRedirectMiddleware, auth=auth)
        app.include_router(
            init_cuc_auth_routes(
                context,
                config,
                auth=auth,
                client_factory=lambda timeout: httpx.AsyncClient(
                    transport=transport, timeout=timeout
                ),
            )
        )
        return TestClient(app), recorded, config

    def test_unauthenticated_returns_401(self):
        client, recorded, _ = self._make_client(user_id=None, auth_enabled=True)
        res = client.get("/api/cuc/auth/status")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(recorded, [])

    def test_disabled_returns_404(self):
        client, recorded, _ = self._make_client(cuc_enabled=False)
        res = client.get("/api/cuc/auth/status")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(recorded, [])

    def test_identity_forwarding_ignores_client_spoofing(self):
        client, recorded, _ = self._make_client(user_id="alice", user_prefix="u_")
        res = client.get(
            "/api/cuc/auth/status?profile=bob",
            headers={"X-CUC-Profile": "bob"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["path"], "/auth/status")
        self.assertEqual(recorded[0]["headers"]["x-api-key"], "srv-secret")
        self.assertEqual(recorded[0]["headers"]["x-cuc-profile"], "u_alice")
        self.assertEqual(recorded[0]["query"], {})

    def test_non_alnum_user_id_hashed_deterministically(self):
        client, recorded, _ = self._make_client(
            user_id="casdoor|user@cuc.edu.cn", user_prefix="u_"
        )
        res = client.get("/api/cuc/auth/status")
        self.assertEqual(res.status_code, 200)
        forwarded = recorded[0]["headers"]["x-cuc-profile"]
        self.assertTrue(forwarded.startswith("u_"))
        self.assertEqual(len(forwarded), 34)

    def test_verify_status_calls_live_status_endpoint(self):
        client, recorded, _ = self._make_client()
        res = client.get("/api/cuc/auth/status?verify=1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(recorded[0]["path"], "/status")

    def test_upstream_401_mapped_to_422(self):
        def responder(_req):
            return httpx.Response(401, json={"error": "统一认证会话已过期"})

        client, _, _ = self._make_client(responder=responder)
        res = client.post("/api/cuc/auth/mail/start")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(
            res.json(),
            {"error": "统一认证会话已过期", "upstream_status": 401},
        )

    def test_upstream_timeout_and_connect_error_mapped(self):
        def timeout_responder(_req):
            raise httpx.ReadTimeout("timed out")

        client, _, _ = self._make_client(responder=timeout_responder)
        self.assertEqual(client.get("/api/cuc/auth/status").status_code, 504)

        def connect_responder(_req):
            raise httpx.ConnectError("connection refused")

        client2, _, _ = self._make_client(responder=connect_responder)
        self.assertEqual(client2.get("/api/cuc/auth/status").status_code, 502)

    def test_invalid_task_id_rejected_with_400(self):
        client, recorded, _ = self._make_client()
        res = client.get("/api/cuc/auth/wechat/bad.id")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(recorded, [])

    def test_wechat_mail_net_opac_flows_and_asset_paths(self):
        def responder(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p == "/auth/login/wechat":
                return httpx.Response(
                    200,
                    json={
                        "taskId": "wt_1",
                        "status": "pending",
                        "qrPath": "/auth/login/wechat/wt_1/qr",
                        "qrMimeType": "image/jpeg",
                        "qrBase64": "AQID",
                    },
                )
            if p == "/auth/login/wechat/wt_1/qr":
                return httpx.Response(
                    200, content=b"QRBYTES", headers={"Content-Type": "image/jpeg"}
                )
            if p == "/auth/login/wechat/wt_1":
                if req.method == "DELETE":
                    return httpx.Response(
                        200, json={"taskId": "wt_1", "status": "cancelled"}
                    )
                return httpx.Response(
                    200, json={"taskId": "wt_1", "status": "confirmed"}
                )
            if p == "/auth/net":
                return httpx.Response(
                    200,
                    json={
                        "taskId": "net_1",
                        "status": "captcha_required",
                        "captchaPath": "/auth/net/net_1/captcha",
                    },
                )
            if p == "/auth/net/net_1/captcha":
                return httpx.Response(
                    200, content=b"CAPBYTES", headers={"Content-Type": "image/png"}
                )
            return httpx.Response(200, json={"ok": True, "path": p})

        client, recorded, _ = self._make_client(responder=responder)

        start_wx = client.post("/api/cuc/auth/wechat/start")
        self.assertEqual(start_wx.status_code, 200)
        self.assertEqual(start_wx.json()["qrPath"], "/api/cuc/auth/wechat/wt_1/qr")

        qr_res = client.get("/api/cuc/auth/wechat/wt_1/qr")
        self.assertEqual(qr_res.status_code, 200)
        self.assertEqual(qr_res.content, b"QRBYTES")
        self.assertEqual(qr_res.headers.get("cache-control"), "no-store")

        poll_res = client.get("/api/cuc/auth/wechat/wt_1?wait=1&timeout=99000")
        self.assertEqual(poll_res.status_code, 200)
        poll_rec = next(r for r in recorded if r["path"] == "/auth/login/wechat/wt_1")
        self.assertEqual(poll_rec["query"], {"wait": "1", "timeout": "25000"})

        self.assertEqual(
            client.delete("/api/cuc/auth/wechat/wt_1").json()["status"], "cancelled"
        )
        self.assertEqual(client.post("/api/cuc/auth/logout").status_code, 200)

        self.assertEqual(client.post("/api/cuc/auth/mail/start").status_code, 200)
        self.assertEqual(
            client.post(
                "/api/cuc/auth/mail/m_1/sms", json={"code": "123456"}
            ).status_code,
            200,
        )
        self.assertEqual(client.post("/api/cuc/auth/mail/logout").status_code, 200)

        net_start = client.post("/api/cuc/auth/net/start")
        self.assertEqual(net_start.status_code, 200)
        self.assertEqual(
            net_start.json()["captchaPath"], "/api/cuc/auth/net/net_1/captcha"
        )
        self.assertEqual(
            client.get("/api/cuc/auth/net/net_1/captcha").content, b"CAPBYTES"
        )
        self.assertEqual(
            client.post(
                "/api/cuc/auth/net/net_1/submit",
                json={"username": "20260001", "password": "pw", "verifyCode": "ab12"},
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post(
                "/api/cuc/auth/net/net_1/sms", json={"smsCode": "654321"}
            ).status_code,
            200,
        )
        self.assertEqual(client.delete("/api/cuc/auth/net/net_1").status_code, 200)
        self.assertEqual(client.post("/api/cuc/auth/net/logout").status_code, 200)

        self.assertEqual(client.post("/api/cuc/auth/opac/auth").status_code, 200)
        self.assertEqual(client.post("/api/cuc/auth/opac/logout").status_code, 200)


if __name__ == "__main__":
    unittest.main()
