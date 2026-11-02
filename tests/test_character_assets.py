import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from open_llm_vtuber.auth import AuthManager, AuthRedirectMiddleware, Identity
from open_llm_vtuber.config_manager.asset_access import (
    AVATAR_MOUNT,
    LIVE2D_MOUNT,
    CharacterAssetAccess,
)
from open_llm_vtuber.config_manager.auth import AuthConfig, OIDCConfig
from open_llm_vtuber.server import AvatarStaticFiles, CharacterAssetStaticFiles


def write_character(path: Path, **character) -> None:
    lines = ["character_config:"]
    for key, value in character.items():
        lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class AssetFixture:
    """conf.yaml + presets + model_dict + asset files in a temp directory."""

    def __init__(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.characters = self.root / "characters"
        self.characters.mkdir()
        self.conf = self.root / "conf.yaml"
        self.model_dict = self.root / "model_dict.json"

        write_character(self.conf, live2d_model_name="hiyori", avatar="relu.png")
        write_character(
            self.characters / "private.yaml",
            live2d_model_name="yifan",
            avatar="yifan.png",
            allowed_users=["u1", "Alice"],
        )
        write_character(
            self.characters / "shared_private.yaml",
            live2d_model_name="shared",
            allowed_users=["u2"],
        )
        write_character(
            self.characters / "shared_public.yaml", live2d_model_name="shared"
        )
        self.model_dict.write_text(
            json.dumps(
                [
                    {
                        "name": "hiyori",
                        "url": "/live2d-models/hiyori/runtime/h.model3.json",
                    },
                    {
                        "name": "yifan",
                        "url": "/live2d-models/yifan/runtime_v015/yifan.model3.json",
                    },
                    {"name": "shared", "url": "/live2d-models/shared/s.model3.json"},
                ]
            ),
            encoding="utf-8",
        )

        self.live2d = self.root / "live2d-models"
        for rel in (
            "yifan/runtime_v015/yifan.model3.json",
            "hiyori/runtime/h.model3.json",
        ):
            target = self.live2d / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        self.avatars = self.root / "avatars"
        self.avatars.mkdir()
        (self.avatars / "yifan.png").write_bytes(b"png")
        (self.avatars / "relu.png").write_bytes(b"png")

    def access(self, refresh_interval: float = 5.0) -> CharacterAssetAccess:
        return CharacterAssetAccess(
            str(self.characters),
            model_dict_path=str(self.model_dict),
            default_config_path=str(self.conf),
            refresh_interval=refresh_interval,
        )

    def cleanup(self) -> None:
        self._temp.cleanup()


class CharacterAssetAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = AssetFixture()
        self.addCleanup(self.fx.cleanup)

    def test_restricted_preset_assets_are_private(self) -> None:
        access = self.fx.access()
        self.assertTrue(
            access.is_restricted(LIVE2D_MOUNT, "yifan/runtime_v015/yifan.moc3")
        )
        self.assertTrue(access.is_restricted(LIVE2D_MOUNT, "YiFan/runtime_v014/x.png"))
        self.assertTrue(access.is_restricted(AVATAR_MOUNT, "yifan.png"))
        self.assertFalse(access.is_restricted(LIVE2D_MOUNT, "hiyori/runtime/h.moc3"))
        self.assertFalse(access.is_restricted(AVATAR_MOUNT, "relu.png"))
        self.assertFalse(access.is_restricted(LIVE2D_MOUNT, "unknown/a.json"))

    def test_allowlist_matches_id_or_display_name(self) -> None:
        access = self.fx.access()
        path = "yifan/runtime_v015/yifan.moc3"
        self.assertTrue(access.is_allowed(LIVE2D_MOUNT, path, "u1", None))
        self.assertTrue(access.is_allowed(LIVE2D_MOUNT, path, "other", "alice"))
        self.assertFalse(access.is_allowed(LIVE2D_MOUNT, path, "u2", "Bob"))
        self.assertFalse(access.is_allowed(AVATAR_MOUNT, "yifan.png", None, None))

    def test_asset_used_by_a_public_character_stays_public(self) -> None:
        access = self.fx.access()
        self.assertFalse(access.is_restricted(LIVE2D_MOUNT, "shared/s.model3.json"))
        self.assertTrue(
            access.is_allowed(LIVE2D_MOUNT, "shared/s.model3.json", "u9", None)
        )

    def test_malformed_allowlist_denies_everyone(self) -> None:
        write_character(
            self.fx.characters / "private.yaml",
            live2d_model_name="yifan",
            allowed_users={"u1": True},
        )
        access = self.fx.access()
        self.assertTrue(access.is_restricted(LIVE2D_MOUNT, "yifan/a"))
        self.assertFalse(access.is_allowed(LIVE2D_MOUNT, "yifan/a", "u1", "Alice"))

    def test_rules_follow_preset_edits(self) -> None:
        access = self.fx.access(refresh_interval=0)
        self.assertTrue(access.is_restricted(LIVE2D_MOUNT, "yifan/a"))
        preset = self.fx.characters / "private.yaml"
        write_character(preset, live2d_model_name="yifan", avatar="yifan.png")
        stat = preset.stat()
        os.utime(preset, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        self.assertFalse(access.is_restricted(LIVE2D_MOUNT, "yifan/a"))

    def test_missing_model_dict_keeps_models_public(self) -> None:
        self.fx.model_dict.unlink()
        access = self.fx.access()
        self.assertFalse(access.is_restricted(LIVE2D_MOUNT, "yifan/a"))
        self.assertTrue(access.is_restricted(AVATAR_MOUNT, "yifan.png"))


def make_auth() -> AuthManager:
    return AuthManager(
        AuthConfig(
            mode="oidc",
            signing_secret="test-secret",
            cookie_secure=False,
            oidc=OIDCConfig(
                issuer="https://sso.example.com",
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://testserver/auth/callback",
            ),
        ),
        "local",
    )


class CharacterAssetRouteTests(unittest.IsolatedAsyncioTestCase):
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

    def _as(self, user_id: str, name: str | None = None) -> None:
        token = self.auth.issue_session(Identity(user_id, name))
        self.client.cookies.set(self.auth.config.session_cookie_name, token)

    def test_anonymous_gets_404_without_shared_caching(self) -> None:
        for url in (
            "/live2d-models/yifan/runtime_v015/yifan.model3.json",
            "/avatars/yifan.png",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_other_user_gets_404(self) -> None:
        self._as("u2", "Bob")
        response = self.client.get(
            "/live2d-models/yifan/runtime_v015/yifan.model3.json"
        )
        self.assertEqual(response.status_code, 404)

    def test_allowed_user_gets_private_response(self) -> None:
        self._as("u1")
        for url in (
            "/live2d-models/yifan/runtime_v015/yifan.model3.json",
            "/avatars/yifan.png",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "private, no-cache")

    def test_public_assets_keep_shared_cache_policy(self) -> None:
        response = self.client.get("/live2d-models/hiyori/runtime/h.model3.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("public", response.headers["cache-control"])
        response = self.client.get("/avatars/relu.png")
        self.assertEqual(response.status_code, 200)
        self.assertIn("public", response.headers["cache-control"])


if __name__ == "__main__":
    unittest.main()
