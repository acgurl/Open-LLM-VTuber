"""Locking tests for the shared request user-id helper (R3), the /asr auth
path once its in-handler check was dropped, and the shared user-id
pattern (R6)."""

import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from pydantic import ValidationError
from starlette.testclient import TestClient

from open_llm_vtuber.auth import (
    AuthRedirectMiddleware,
    Identity,
    default_user_id,
    request_user_id,
)
from open_llm_vtuber.config_manager.storage import StorageConfig
from open_llm_vtuber.routes import init_webtool_routes
from open_llm_vtuber.storage import DEFAULT_USER_ID, validate_user_id

from test_character_assets import make_auth


def _request(identity=None):
    state = SimpleNamespace()
    if identity is not None:
        state.identity = identity
    return SimpleNamespace(state=state)


class RequestUserIdTests(unittest.TestCase):
    def test_attached_identity_wins(self) -> None:
        request = _request(Identity("u1"))
        context = SimpleNamespace(user_id="ctx")
        self.assertEqual(
            request_user_id(request, SimpleNamespace(enabled=True), context), "u1"
        )

    def test_oidc_without_identity_has_no_user(self) -> None:
        context = SimpleNamespace(user_id="ctx")
        self.assertIsNone(
            request_user_id(_request(), SimpleNamespace(enabled=True), context)
        )

    def test_single_user_falls_back_to_context_then_default(self) -> None:
        disabled = SimpleNamespace(enabled=False)
        self.assertEqual(
            request_user_id(_request(), disabled, SimpleNamespace(user_id="ctx")),
            "ctx",
        )
        self.assertEqual(
            request_user_id(_request(), None, SimpleNamespace(user_id=None)),
            DEFAULT_USER_ID,
        )
        self.assertEqual(default_user_id(None), DEFAULT_USER_ID)
        self.assertEqual(DEFAULT_USER_ID, "local")


class ASRAuthTests(unittest.IsolatedAsyncioTestCase):
    """/asr relies on AuthRedirectMiddleware for authentication."""

    async def asyncSetUp(self) -> None:
        self.auth = make_auth()
        app = FastAPI()
        app.add_middleware(AuthRedirectMiddleware, auth=self.auth)
        app.include_router(
            init_webtool_routes(
                default_context_cache=SimpleNamespace(user_id=None, asr_engine=None),
                auth=self.auth,
            )
        )
        self.client = TestClient(app, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.auth.close()

    def post_empty(self):
        return self.client.post("/asr", files={"file": ("a.wav", b"", "audio/wav")})

    def test_without_session_is_rejected(self) -> None:
        response = self.post_empty()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Authentication required"})

    def test_with_session_reaches_the_handler(self) -> None:
        token = self.auth.issue_session(Identity("u1"))
        self.client.cookies.set(self.auth.config.session_cookie_name, token)
        response = self.post_empty()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Empty audio file"})


class UserIdPatternTests(unittest.TestCase):
    def test_storage_config_and_validator_agree(self) -> None:
        for value in ("local", "a.b-c_1", "x" * 64):
            with self.subTest(value=value):
                self.assertEqual(validate_user_id(value), value)
                self.assertEqual(
                    StorageConfig(default_user_id=value).default_user_id, value
                )
        for value in ("", "a b", "x" * 65, "ü"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_user_id(value)
                with self.assertRaises(ValidationError) as error:
                    StorageConfig(default_user_id=value)
                self.assertIn(
                    "default_user_id must be 1-64 characters of letters, digits, "
                    "dot, dash or underscore",
                    str(error.exception),
                )


if __name__ == "__main__":
    unittest.main()
