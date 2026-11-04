"""Locking tests for access-control and auth defects (D-ACL1/2, D-AUTH1,
D-CACHE1) and id/verified-email-only allowlists (Q1)."""

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from loguru import logger
from starlette.testclient import TestClient

from open_llm_vtuber.auth import AuthManager, AuthRedirectMiddleware, Identity
from open_llm_vtuber.config_manager.access import (
    is_user_allowed,
    warn_unmatched_allowlist_entries,
)
from open_llm_vtuber.config_manager.asset_access import AVATAR_MOUNT, LIVE2D_MOUNT
from open_llm_vtuber.config_manager.auth import AuthConfig
from open_llm_vtuber.config_manager.utils import scan_config_alts_directory
from open_llm_vtuber.connectors.binding import user_eligible
from open_llm_vtuber.routes import init_webtool_routes
from open_llm_vtuber.server import (
    AvatarStaticFiles,
    CharacterAssetStaticFiles,
    UserCacheStaticFiles,
)
from open_llm_vtuber.storage import SQLiteHistoryRepository

from test_character_assets import AssetFixture, make_auth


class FakeDiscoveryOIDC:
    def __init__(self, userinfo: dict | None = None) -> None:
        self.info = userinfo or {}
        self.claims: dict = {}

    async def discovery(self):
        return {"issuer": "https://sso.example.com"}

    async def exchange_code(self, code: str, *, redirect_uri: str | None = None):
        return {"id_token": "id-token", "access_token": "access-token"}

    async def validate_id_token(self, token: str, *, nonce: str):
        return dict(self.claims)

    async def userinfo(self, access_token: str):
        return dict(self.info)

    async def close(self):
        return None


class _RepositoryAuthCase(unittest.IsolatedAsyncioTestCase):
    """OIDC AuthManager backed by a real SQLite repository."""

    async def asyncSetUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.repository = SQLiteHistoryRepository(self.root / "auth.db")
        await self.repository.initialize()
        self.auth = make_auth()
        self.auth.repository = self.repository
        await self.auth._oidc.close()
        self.oidc = FakeDiscoveryOIDC()
        self.auth._oidc = self.oidc

    async def asyncTearDown(self) -> None:
        await self.auth.close()
        await self.repository.close()
        self._temp.cleanup()


class UnverifiedEmailTests(_RepositoryAuthCase):
    """D-AUTH1: an email the provider marks unverified grants nothing."""

    async def test_unverified_email_is_ignored(self) -> None:
        identity = await self.auth.resolve_claims(
            {"sub": "s1", "email": "eve@cuc.edu.cn", "email_verified": False}
        )

        self.assertIsNone(identity.email)
        self.assertIsNone(identity.display_name)
        profile = await self.repository.get_user_profile(user_id=identity.user_id)
        self.assertEqual(profile["emails"], [])
        self.assertFalse(user_eligible(profile, ["cuc.edu.cn"]))

    async def test_stored_email_is_cleared_once_marked_unverified(self) -> None:
        first = await self.auth.resolve_claims(
            {"sub": "s1", "email": "eve@cuc.edu.cn", "email_verified": True}
        )
        again = await self.auth.resolve_claims(
            {"sub": "s1", "email": "eve@cuc.edu.cn", "email_verified": False}
        )

        self.assertEqual(first.user_id, again.user_id)
        self.assertEqual(await self.auth.verified_emails(first.user_id), ())

    async def test_absent_claim_keeps_email(self) -> None:
        identity = await self.auth.resolve_claims(
            {"sub": "s1", "email": "amy@cuc.edu.cn"}
        )

        self.assertEqual(identity.email, "amy@cuc.edu.cn")
        self.assertEqual(
            await self.auth.verified_emails(identity.user_id), ("amy@cuc.edu.cn",)
        )

    async def test_userinfo_email_keeps_its_own_verification_flag(self) -> None:
        self.oidc.claims = {"sub": "s1", "name": "Eve", "email_verified": True}
        self.oidc.info = {
            "sub": "s1",
            "email": "eve@cuc.edu.cn",
            "email_verified": False,
        }

        identity = await self.auth.authenticate_code("code", nonce="n")

        self.assertIsNone(identity.email)
        self.assertEqual(await self.auth.verified_emails(identity.user_id), ())


class AllowlistIdentityTests(unittest.TestCase):
    """Q1: operators are told which entries no longer match anyone."""

    def test_warns_for_entries_that_are_neither_id_nor_email(self) -> None:
        messages: list[str] = []
        sink = logger.add(messages.append, level="WARNING", format="{message}")
        try:
            warn_unmatched_allowlist_entries(
                ["Alice", "3f2a9c04b1de4c7e8a5f6d7c8b9a0e1f", "a@cuc.edu.cn"],
                "characters/private.yaml",
            )
        finally:
            logger.remove(sink)
        self.assertEqual(len(messages), 1)
        self.assertIn("'alice'", messages[0])


class DisplayNameAssetRouteTests(unittest.IsolatedAsyncioTestCase):
    """Q1 on the static mounts: a matching display name is not enough."""

    async def asyncSetUp(self) -> None:
        self.fx = AssetFixture()
        self.auth = make_auth()
        access = self.fx.access()
        app = FastAPI()
        app.add_middleware(AuthRedirectMiddleware, auth=self.auth)
        app.mount(
            "/live2d-models",
            CharacterAssetStaticFiles(
                directory=str(self.fx.live2d),
                mount=LIVE2D_MOUNT,
                asset_access=access,
                auth=self.auth,
            ),
        )
        app.mount(
            "/avatars",
            AvatarStaticFiles(
                directory=str(self.fx.avatars),
                mount=AVATAR_MOUNT,
                asset_access=access,
                auth=self.auth,
            ),
        )
        self.client = TestClient(app, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.auth.close()
        self.fx.cleanup()

    def test_display_name_match_is_denied(self) -> None:
        # private.yaml lists ["u1", "Alice"]; "Alice" is only a display name.
        token = self.auth.issue_session(Identity("u2", "Alice"))
        self.client.cookies.set(self.auth.config.session_cookie_name, token)

        for url in (
            "/live2d-models/yifan/runtime_v015/yifan.model3.json",
            "/avatars/yifan.png",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)


class Live2DInfoAccessTests(unittest.IsolatedAsyncioTestCase):
    """D-ACL1: /live2d-models/info omits folders the caller cannot read."""

    async def asyncSetUp(self) -> None:
        self.fx = AssetFixture()
        for folder in ("yifan", "hiyori"):
            model = self.fx.live2d / folder / f"{folder}.model3.json"
            model.write_text("{}", encoding="utf-8")
        self.original_cwd = os.getcwd()
        os.chdir(self.fx.root)
        self.auth = make_auth()

    async def asyncTearDown(self) -> None:
        os.chdir(self.original_cwd)
        await self.auth.close()
        self.fx.cleanup()

    def client(self, auth: AuthManager) -> TestClient:
        app = FastAPI()
        app.add_middleware(AuthRedirectMiddleware, auth=auth)
        app.include_router(
            init_webtool_routes(
                default_context_cache=None,
                auth=auth,
                asset_access=self.fx.access(),
            )
        )
        return TestClient(app, base_url="http://testserver")

    def names(self, client: TestClient) -> list[str]:
        response = client.get("/live2d-models/info")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["type"], "live2d-models/info")
        self.assertEqual(body["count"], len(body["characters"]))
        return sorted(item["name"] for item in body["characters"])

    def test_anonymous_and_unlisted_users_do_not_see_restricted_folders(self):
        client = self.client(self.auth)
        self.assertEqual(self.names(client), ["hiyori"])

        token = self.auth.issue_session(Identity("u2", "Alice"))
        client.cookies.set(self.auth.config.session_cookie_name, token)
        self.assertEqual(self.names(client), ["hiyori"])

    def test_listed_user_sees_restricted_folder(self):
        client = self.client(self.auth)
        token = self.auth.issue_session(Identity("u1"))
        client.cookies.set(self.auth.config.session_cookie_name, token)
        self.assertEqual(self.names(client), ["hiyori", "yifan"])

    def test_single_user_mode_lists_everything(self):
        self.assertEqual(
            self.names(self.client(AuthManager(AuthConfig(), "local"))),
            ["hiyori", "yifan"],
        )


class UnreadablePresetListingTests(unittest.TestCase):
    """D-ACL2: an unparseable preset is not listed unless access is clear."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.alts = self.root / "characters"
        self.alts.mkdir()
        (self.root / "conf.yaml").write_text(
            "character_config:\n  conf_name: Default\n", encoding="utf-8"
        )
        (self.alts / "broken_private.yaml").write_text(
            "character_config:\n  allowed_users: ['u1']\n  conf_name: [unclosed\n",
            encoding="utf-8",
        )
        (self.alts / "broken_public.yaml").write_text(
            "character_config: [unclosed\n", encoding="utf-8"
        )
        self.original_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self.original_cwd)
        self._temp.cleanup()

    def filenames(self, is_allowed=None) -> list[str]:
        return [
            item["filename"]
            for item in scan_config_alts_directory(str(self.alts), is_allowed)
        ]

    def test_filtered_listing_hides_unreadable_preset_with_allowlist(self):
        def allowed(character_config):
            return is_user_allowed(character_config.get("allowed_users"), "u2", None)

        self.assertEqual(self.filenames(allowed), ["conf.yaml", "broken_public.yaml"])

    def test_unfiltered_listing_keeps_every_preset(self):
        self.assertEqual(
            self.filenames(),
            ["conf.yaml", "broken_private.yaml", "broken_public.yaml"],
        )


class FakeCacheTTSEngine:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    async def async_generate_audio(self, text: str, file_name_no_ext: str):
        target = self.cache_dir / f"{file_name_no_ext}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFF")
        return f"cache/{file_name_no_ext}.wav"


class FakeContext:
    def __init__(self, tts_engine) -> None:
        self.tts_engine = tts_engine
        self.asr_engine = None
        self.user_id = None


class TTSCacheScopeTests(unittest.IsolatedAsyncioTestCase):
    """D-CACHE1: /tts-ws audio is fetchable by its owner in OIDC mode."""

    async def asyncSetUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.cache = Path(self._temp.name) / "cache"
        self.cache.mkdir()
        self.auth = make_auth()
        app = FastAPI()
        app.add_middleware(AuthRedirectMiddleware, auth=self.auth)
        app.include_router(
            init_webtool_routes(
                default_context_cache=FakeContext(FakeCacheTTSEngine(self.cache)),
                auth=self.auth,
            )
        )
        app.mount("/cache", UserCacheStaticFiles(directory=str(self.cache)))
        self.client = TestClient(app, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.auth.close()
        self._temp.cleanup()

    def login(self, user_id: str) -> str:
        token = self.auth.issue_session(Identity(user_id))
        self.client.cookies.set(self.auth.config.session_cookie_name, token)
        return f"{self.auth.config.session_cookie_name}={token}"

    def synthesize(self, cookie: str) -> str:
        with self.client.websocket_connect(
            "/tts-ws", headers={"cookie": cookie}
        ) as websocket:
            websocket.send_json({"text": "Hello."})
            partial = websocket.receive_json()
            self.assertEqual(websocket.receive_json(), {"status": "complete"})
        self.assertEqual(partial["status"], "partial")
        return partial["audioPath"]

    def test_owner_can_fetch_generated_audio(self) -> None:
        audio_path = self.synthesize(self.login("u1"))

        self.assertTrue(audio_path.startswith("cache/u1/"))
        response = self.client.get("/" + audio_path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"RIFF")

    def test_other_user_cannot_fetch_generated_audio(self) -> None:
        audio_path = self.synthesize(self.login("u1"))

        self.login("u2")
        self.assertEqual(self.client.get("/" + audio_path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
