import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from open_llm_vtuber.auth import (
        AuthManager,
        AuthRedirectMiddleware,
        init_auth_routes,
    )
    from open_llm_vtuber.config_manager.auth import AuthConfig, OIDCConfig
    from open_llm_vtuber.routes import init_client_ws_route, init_webtool_routes
    from open_llm_vtuber.storage import SQLiteHistoryRepository
    from starlette.websockets import WebSocketDisconnect
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class FakeOIDC:
    def __init__(self) -> None:
        self.claims = {
            "sub": "subject-1",
            "name": "Alice",
            "email": "alice@example.com",
        }

    async def discovery(self):
        return {"issuer": "https://sso.example.com"}

    async def authorization_url(
        self, *, state: str, nonce: str, redirect_uri: str | None = None
    ) -> str:
        self.last_redirect_uri = redirect_uri
        return (
            "https://sso.example.com/authorize"
            f"?state={state}&nonce={nonce}&client_id=client-id"
        )

    async def exchange_code(self, code: str, *, redirect_uri: str | None = None):
        self.last_exchange_redirect_uri = redirect_uri
        return {"id_token": "id-token", "access_token": "access-token"}

    async def validate_id_token(self, token: str, *, nonce: str):
        claims = dict(self.claims)
        claims["nonce"] = nonce
        return claims

    async def userinfo(self, access_token: str):
        return {}

    async def end_session_url(self, *, post_logout_redirect_uri: str):
        return None

    async def close(self):
        return None


def make_config() -> AuthConfig:
    return AuthConfig(
        mode="oidc",
        signing_secret="test-secret",
        cookie_secure=False,
        oidc=OIDCConfig(
            issuer="https://sso.example.com",
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://testserver/auth/callback",
            redirect_uris=[
                "http://testserver/auth/callback",
                "http://ai.testserver/auth/callback",
            ],
        ),
    )


class AuthRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(
            Path(self._temp_dir.name) / "history.db"
        )
        await self.repository.initialize()

        self.auth = AuthManager(make_config(), "local")
        self.auth.repository = self.repository
        await self.auth._oidc.close()
        self.auth._oidc = FakeOIDC()

        self.app = FastAPI()
        self.app.add_middleware(AuthRedirectMiddleware, auth=self.auth)
        self.app.include_router(init_auth_routes(self.auth))

        @self.app.get("/")
        async def index():
            return {"page": "index"}

        @self.app.get("/api/private")
        async def private():
            return {"ok": True}

        @self.app.get("/assets/app.js")
        async def asset():
            return {"asset": True}

        @self.app.get("/cache/audio.mp3")
        async def cached_audio():
            return {"audio": True}

        self.client = TestClient(self.app, base_url="http://testserver")
        self.addAsyncCleanup(self._cleanup)

    async def _cleanup(self):
        await self.auth.close()
        await self.repository.close()
        self._temp_dir.cleanup()

    def _login(self):
        response = self.client.get("/auth/login", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        location = response.headers["location"]
        state = parse_qs(urlsplit(location).query)["state"][0]
        return state

    def test_unauthenticated_browser_is_redirected_and_api_is_401(self):
        response = self.client.get(
            "/", headers={"accept": "text/html"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/auth/login?next=%2F")

        response = self.client.get("/api/private")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["cache-control"], "no-store")

        response = self.client.get("/assets/app.js")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/cache/audio.mp3")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_session_scoped_responses_are_never_cached(self):
        response = self.client.get("/auth/login", follow_redirects=False)
        self.assertEqual(response.headers["cache-control"], "no-store")
        state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]

        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["cache-control"], "no-store")

        response = self.client.get(
            f"/auth/callback?code=code-1&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("vtuber_uid=", response.headers.get("set-cookie", ""))

        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            self.client.cookies.get("vtuber_uid"), response.json()["user_id"]
        )

        response = self.client.get("/auth/logout", follow_redirects=False)
        self.assertEqual(response.headers["cache-control"], "no-store")
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn("vtuber_uid=", set_cookie)
        self.assertIn("Max-Age=0", set_cookie)
        self.assertIsNone(self.client.cookies.get("vtuber_uid"))

    def test_alternate_host_uses_its_own_redirect_uri(self):
        client = TestClient(self.app, base_url="http://ai.testserver")

        response = client.get("/auth/login", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.auth._oidc.last_redirect_uri, "http://ai.testserver/auth/callback"
        )
        state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]

        response = client.get(
            f"/auth/callback?code=code-1&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.auth._oidc.last_exchange_redirect_uri,
            "http://ai.testserver/auth/callback",
        )
        self.assertIn("vtuber_session=", response.headers.get("set-cookie", ""))

    def test_unknown_host_falls_back_to_primary_redirect_uri(self):
        self.assertEqual(
            self.auth.redirect_uri_for("other.example.com"),
            "http://testserver/auth/callback",
        )
        self.assertEqual(
            self.auth.redirect_uri_for(None), "http://testserver/auth/callback"
        )

    def test_session_endpoint_backfills_uid_cookie(self):
        state = self._login()
        self.client.get(
            f"/auth/callback?code=code-1&state={state}",
            follow_redirects=False,
        )
        self.client.cookies.delete("vtuber_uid")

        response = self.client.get("/api/session")

        self.assertEqual(response.status_code, 200)
        self.assertIn("vtuber_uid=", response.headers.get("set-cookie", ""))
        self.assertEqual(
            self.client.cookies.get("vtuber_uid"), response.json()["user_id"]
        )

    def test_login_callback_sets_session_and_logout_clears_it(self):
        state = self._login()

        response = self.client.get(
            f"/auth/callback?code=code-1&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/")
        self.assertIn("vtuber_session=", response.headers.get("set-cookie", ""))

        response = self.client.get("/api/private")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(body["mode"], "oidc")
        self.assertEqual(len(body["user_id"]), 32)

        response = self.client.get("/auth/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/")
        self.assertEqual(self.client.get("/api/private").status_code, 401)

    def test_callback_rejects_invalid_state(self):
        self._login()

        response = self.client.get(
            "/auth/callback?code=code-1&state=tampered",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

    def test_websockets_require_a_session(self):
        context = SimpleNamespace(user_id=None)
        client_app = FastAPI()
        client_app.include_router(
            init_client_ws_route(default_context_cache=context, auth=self.auth)
        )
        client_app.include_router(
            init_webtool_routes(default_context_cache=context, auth=self.auth)
        )
        ws_client = TestClient(client_app)

        with ws_client.websocket_connect("/client-ws") as websocket:
            with self.assertRaises(WebSocketDisconnect) as error:
                websocket.receive_text()
        self.assertEqual(error.exception.code, 4401)

        with ws_client.websocket_connect("/audio-ws?client_uid=missing") as websocket:
            with self.assertRaises(WebSocketDisconnect) as error:
                websocket.receive_text()
        self.assertEqual(error.exception.code, 1008)

        with ws_client.websocket_connect("/tts-ws") as websocket:
            with self.assertRaises(WebSocketDisconnect) as error:
                websocket.receive_text()
        self.assertEqual(error.exception.code, 4401)

        with ws_client.websocket_connect(
            "/client-ws", headers={"origin": "https://evil.example"}
        ) as websocket:
            with self.assertRaises(WebSocketDisconnect) as error:
                websocket.receive_text()
        self.assertEqual(error.exception.code, 1008)

    def test_single_user_mode_keeps_existing_behaviour(self):
        temp_auth = AuthManager(AuthConfig(), "local")
        app = FastAPI()
        app.add_middleware(AuthRedirectMiddleware, auth=temp_auth)
        app.include_router(init_auth_routes(temp_auth))
        app.get("/api/private")(lambda: {"ok": True})
        client = TestClient(app)

        self.assertEqual(client.get("/api/private").status_code, 200)
        session = client.get("/api/session").json()
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user_id"], "local")


if __name__ == "__main__":
    unittest.main()
