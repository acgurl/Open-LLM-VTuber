import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.auth.middleware import IDENTITY_SCOPE_KEY
    from open_llm_vtuber.auth.types import Identity
    from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
    from open_llm_vtuber.server import UserCacheStaticFiles
    from open_llm_vtuber.tts.tts_interface import TTSInterface
    from open_llm_vtuber.utils.audio import new_audio_file_stem
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


class _DummyTTS(TTSInterface):
    def generate_audio(self, text, file_name_no_ext=None):
        return None


class _RecordingEngine:
    def __init__(self) -> None:
        self.received = None

    async def async_generate_audio(self, text, file_name_no_ext=None):
        self.received = file_name_no_ext
        return f"cache/{file_name_no_ext}.mp3"


def _scope(identity=None):
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [],
        "path": "/cache/uid1/audio.mp3",
    }
    if identity is not None:
        scope[IDENTITY_SCOPE_KEY] = identity
    return scope


class CacheIsolationTests(unittest.IsolatedAsyncioTestCase):
    def test_audio_stem_is_scoped_and_sanitized(self):
        scoped = new_audio_file_stem("uid1")
        self.assertTrue(scoped.startswith("uid1/"))
        self.assertEqual(scoped.count("/"), 1)

        sanitized = new_audio_file_stem("../uid")
        self.assertTrue(sanitized.startswith("___uid/"))
        self.assertEqual(sanitized.count("/"), 1)

        self.assertNotIn("/", new_audio_file_stem())

    async def test_tts_manager_scopes_generated_files(self):
        engine = _RecordingEngine()
        manager = TTSTaskManager(cache_scope="uid1")

        path = await manager._generate_audio(engine, "hello")

        self.assertTrue(engine.received.startswith("uid1/"))
        self.assertTrue(path.startswith("cache/uid1/"))

    def test_cache_file_name_creates_user_directory(self):
        tts = _DummyTTS()
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                path = tts.generate_cache_file_name("uid1/audio", "mp3")
                self.assertEqual(
                    os.path.normpath(path),
                    os.path.normpath(os.path.join("cache", "uid1", "audio.mp3")),
                )
                self.assertTrue(os.path.isdir(os.path.join(temp_dir, "cache", "uid1")))
            finally:
                os.chdir(previous)

    async def test_user_cache_files_are_owner_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, "uid1"))
            Path(temp_dir, "uid1", "audio.mp3").write_bytes(b"audio")
            Path(temp_dir, "shared.mp3").write_bytes(b"audio")
            files = UserCacheStaticFiles(directory=temp_dir)

            owner = await files.get_response("uid1/audio.mp3", _scope(Identity("uid1")))
            self.assertEqual(owner.status_code, 200)
            self.assertEqual(owner.headers["cache-control"], "no-store")

            other = await files.get_response("uid1/audio.mp3", _scope(Identity("uid2")))
            self.assertEqual(other.status_code, 404)

            legacy = await files.get_response("shared.mp3", _scope(Identity("uid1")))
            self.assertEqual(legacy.status_code, 404)

            single_mode = await files.get_response("uid1/audio.mp3", _scope())
            self.assertEqual(single_mode.status_code, 200)
