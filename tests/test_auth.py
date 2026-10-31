import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from open_llm_vtuber.auth import (
    AuthManager,
    Identity,
    OIDCError,
    OIDCProvider,
    safe_next_path,
)
from open_llm_vtuber.auth.cookies import SignedCookie
from open_llm_vtuber.chat_group import ChatGroupManager, handle_group_operation
from open_llm_vtuber.config_manager.auth import AuthConfig, OIDCConfig
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.storage import SQLiteHistoryRepository
from open_llm_vtuber.websocket_handler import WebSocketHandler


def oidc_config(**overrides) -> AuthConfig:
    values = {
        "mode": "oidc",
        "signing_secret": "test-secret",
        "cookie_secure": False,
        "oidc": OIDCConfig(
            issuer="https://sso.example.com",
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://testserver/auth/callback",
        ),
    }
    values.update(overrides)
    return AuthConfig(**values)


class SignedCookieTests(unittest.TestCase):
    def test_round_trip_and_tamper_detection(self):
        signer = SignedCookie("secret")
        now = int(time.time())
        token = signer.dumps({"uid": "alice", "iat": now, "exp": now + 60})

        self.assertEqual(signer.loads(token)["uid"], "alice")
        self.assertIsNone(signer.loads(token + "x"))
        self.assertIsNone(SignedCookie("other").loads(token))

    def test_expired_and_too_old_tokens_are_rejected(self):
        signer = SignedCookie("secret")
        now = int(time.time())
        expired = signer.dumps({"uid": "alice", "iat": now - 120, "exp": now - 60})
        old = signer.dumps({"uid": "alice", "iat": now - 20, "exp": now + 60})

        self.assertIsNone(signer.loads(expired))
        self.assertIsNone(signer.loads(old, max_age=10))


class AuthConfigTests(unittest.TestCase):
    def test_default_is_single_user(self):
        config = AuthConfig()
        self.assertEqual(config.mode, "single")
        self.assertEqual(config.session_cookie_name, "vtuber_session")

    def test_oidc_requires_client_settings(self):
        with self.assertRaises(ValueError):
            AuthConfig(mode="oidc")

    def test_valid_oidc_config_normalizes_issuer(self):
        config = oidc_config(
            oidc=OIDCConfig(
                issuer="https://sso.example.com/",
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://testserver/auth/callback",
            )
        )
        self.assertEqual(config.oidc.issuer, "https://sso.example.com")

    def test_safe_next_path_rejects_external_redirects(self):
        self.assertEqual(safe_next_path("//evil.example"), "/")
        self.assertEqual(safe_next_path("https://evil.example"), "/")
        self.assertEqual(safe_next_path("/auth/login"), "/")
        self.assertEqual(safe_next_path("/ok?x=1"), "/ok?x=1")


class AuthManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(Path(self._temp_dir.name) / "auth.db")
        await self.repository.initialize()

        self.manager = AuthManager(oidc_config(), "local")
        self.manager.repository = self.repository
        self.addAsyncCleanup(self._close_manager)
        self.identity = Identity(
            "alice", "Alice", "alice@example.com", "https://sso.example.com"
        )

    async def _close_manager(self):
        await self.manager.close()
        await self.repository.close()
        self._temp_dir.cleanup()

    def test_session_round_trip(self):
        token = self.manager.issue_session(self.identity)
        cookie_name = self.manager.config.session_cookie_name

        self.assertEqual(
            self.manager.resolve_identity({cookie_name: token}),
            Identity("alice", "Alice"),
        )
        self.assertIsNone(self.manager.resolve_identity({}))
        self.assertIsNone(self.manager.resolve_identity({cookie_name: token + "x"}))

    def test_state_round_trip_and_next_sanitizing(self):
        token = self.manager.issue_state(
            state="state-1", nonce="nonce-1", next_path="//evil.example"
        )
        payload = self.manager.verify_state(token, "state-1")

        self.assertEqual(payload["next"], "/")
        self.assertEqual(payload["nonce"], "nonce-1")
        self.assertIsNone(self.manager.verify_state(token, "state-2"))

    async def test_claims_map_to_a_stable_internal_user(self):
        class FakeOIDC:
            async def discovery(self):
                return {"issuer": "https://sso.example.com"}

            async def close(self):
                return None

        await self.manager._oidc.close()
        self.manager._oidc = FakeOIDC()

        first = await self.manager.resolve_claims(
            {"sub": "subject-1", "name": "Alice", "email": "alice@example.com"}
        )
        second = await self.manager.resolve_claims(
            {"sub": "subject-1", "name": "Alice", "email": "alice@example.com"}
        )
        other = await self.manager.resolve_claims({"sub": "subject-2", "name": "Bob"})

        self.assertEqual(first.user_id, second.user_id)
        self.assertNotEqual(first.user_id, other.user_id)
        self.assertEqual(len(first.user_id), 32)


class OIDCTokenValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = OIDCProvider(
            OIDCConfig(
                issuer="https://sso.example.com",
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://testserver/auth/callback",
            )
        )
        self.addAsyncCleanup(self._close_provider)
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self.public_key = self.private_key.public_key()
        self.provider._discovery = {
            "issuer": "https://sso.example.com",
            "authorization_endpoint": "https://sso.example.com/authorize",
            "token_endpoint": "https://sso.example.com/token",
            "jwks_uri": "https://sso.example.com/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        self.provider._jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.public_key)
        )

    async def _close_provider(self):
        await self.provider.close()

    def _token(self, *, nonce="nonce-1", **overrides):
        now = int(time.time())
        payload = {
            "iss": "https://sso.example.com",
            "aud": "client-id",
            "sub": "subject-1",
            "iat": now,
            "exp": now + 60,
            "nonce": nonce,
        }
        payload.update(overrides)
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def test_valid_id_token(self):
        claims = await self.provider.validate_id_token(self._token(), nonce="nonce-1")
        self.assertEqual(claims["sub"], "subject-1")

    async def test_wrong_nonce_is_rejected(self):
        with self.assertRaises(OIDCError):
            await self.provider.validate_id_token(
                self._token(nonce="other"), nonce="nonce-1"
            )

    async def test_wrong_audience_is_rejected(self):
        with self.assertRaises(OIDCError):
            await self.provider.validate_id_token(
                self._token(aud="other-client"), nonce="nonce-1"
            )


class OIDCDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.path == "/.well-known/openid-configuration":
                return httpx.Response(
                    200,
                    json={
                        "issuer": "https://sso.example.com",
                        "authorization_endpoint": "https://sso.example.com/authorize",
                        "token_endpoint": "https://sso.example.com/token",
                        "jwks_uri": "https://sso.example.com/jwks",
                        "userinfo_endpoint": "https://sso.example.com/userinfo",
                        "end_session_endpoint": "https://sso.example.com/logout",
                    },
                )
            if request.url.path == "/token":
                return httpx.Response(
                    200,
                    json={
                        "id_token": "id-token",
                        "access_token": "access-token",
                    },
                )
            if request.url.path == "/userinfo":
                return httpx.Response(200, json={"name": "Alice"})
            return httpx.Response(404)

        self.provider = OIDCProvider(
            OIDCConfig(
                issuer="https://sso.example.com",
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://testserver/auth/callback",
            ),
            transport=httpx.MockTransport(handler),
        )
        self.addAsyncCleanup(self.provider.close)

    async def test_discovery_and_authorization_url(self):
        url = await self.provider.authorization_url(state="state-1", nonce="nonce-1")
        params = parse_qs(urlsplit(url).query)

        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["client_id"], ["client-id"])
        self.assertEqual(params["state"], ["state-1"])
        self.assertEqual(params["nonce"], ["nonce-1"])
        self.assertEqual(params["scope"], ["openid profile email"])

    async def test_token_exchange_posts_client_credentials(self):
        tokens = await self.provider.exchange_code("code-1")

        self.assertEqual(tokens["id_token"], "id-token")
        request = self.requests[-1]
        form = parse_qs(request.content.decode())
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertEqual(form["code"], ["code-1"])
        self.assertEqual(form["client_id"], ["client-id"])
        self.assertEqual(form["client_secret"], ["client-secret"])
        self.assertEqual(form["redirect_uri"], ["http://testserver/auth/callback"])

    async def test_userinfo_uses_bearer_token(self):
        claims = await self.provider.userinfo("access-token")

        self.assertEqual(claims["name"], "Alice")
        self.assertEqual(
            self.requests[-1].headers["authorization"], "Bearer access-token"
        )


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        import json

        self.sent.append(json.loads(data))


class GroupIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_clients_from_different_users_cannot_group(self):
        manager = ChatGroupManager()
        manager.client_group_map = {"owner": "", "guest": ""}
        owner_ws = FakeWebSocket()
        guest_ws = FakeWebSocket()

        async def send_group_update(websocket, client_uid):
            return None

        await handle_group_operation(
            operation="add-client-to-group",
            client_uid="owner",
            target_uid="guest",
            chat_group_manager=manager,
            client_connections={"owner": owner_ws, "guest": guest_ws},
            client_users={"owner": "alice", "guest": "bob"},
            send_group_update=send_group_update,
        )

        self.assertFalse(owner_ws.sent[-1]["success"])
        self.assertIn("different users", owner_ws.sent[-1]["message"])
        self.assertEqual(manager.get_group_members("owner"), [])


class ConnectionLimitTests(unittest.TestCase):
    def test_per_user_connection_reservation(self):
        handler = WebSocketHandler(
            SimpleNamespace(user_id="local"),
            max_connections_per_user=1,
        )

        self.assertTrue(handler.try_reserve_connection("a", "alice"))
        self.assertFalse(handler.try_reserve_connection("b", "alice"))
        self.assertTrue(handler.try_reserve_connection("c", "bob"))

        handler.release_connection_reservation("a")
        self.assertTrue(handler.try_reserve_connection("d", "alice"))


class SessionUserPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_context_receives_the_verified_user_id(self):
        default_context = SimpleNamespace(
            user_id=None,
            history_repository=AsyncMock(),
            config=Mock(),
            system_config=Mock(),
            character_config=Mock(),
            live2d_model=None,
            asr_engine=None,
            tts_engine=None,
            vad_engine=None,
            agent_engine=None,
            translate_engine=None,
            mcp_server_registry=None,
            tool_adapter=None,
        )
        handler = WebSocketHandler(default_context)

        with (
            patch.object(ServiceContext, "load_cache", new=AsyncMock()) as load_cache,
            patch.object(ServiceContext, "init_session_agent", new=AsyncMock()),
        ):
            await handler._init_service_context(
                None, "client", Identity("alice", "Alice")
            )

        default_context.history_repository.ensure_user.assert_awaited_once_with(
            "alice", "Alice"
        )
        kwargs = load_cache.await_args.kwargs
        self.assertEqual(kwargs["user_id"], "alice")
        self.assertIs(kwargs["history_repository"], default_context.history_repository)


if __name__ == "__main__":
    unittest.main()
