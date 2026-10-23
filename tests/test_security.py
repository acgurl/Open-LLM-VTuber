import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from open_llm_vtuber.storage.legacy import (  # noqa: E402
    _get_safe_history_path,
    _sanitize_path_component,
)
from open_llm_vtuber.utils.audio import decode_pcm_wav  # noqa: E402
from open_llm_vtuber.utils.security import (  # noqa: E402
    redact_secrets,
    resolve_existing_file_within,
)


def _wav_bytes(
    samples: np.ndarray | None = None,
    *,
    channels: int = 1,
    sample_width: int = 2,
    sample_rate: int = 16000,
) -> bytes:
    if samples is None:
        samples = np.array([0, 1000, -1000], dtype="<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())
    return buffer.getvalue()


class PathContainmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.base = self.root / "characters"
        self.base.mkdir()
        (self.base / "ok.yaml").write_text("character_config: {}", encoding="utf-8")
        self.sibling = self.root / "characters_evil"
        self.sibling.mkdir()
        (self.sibling / "evil.yaml").write_text("x", encoding="utf-8")
        (self.root / "outside.yaml").write_text("x", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_accepts_file_inside_base(self) -> None:
        resolved = resolve_existing_file_within(
            self.base, "ok.yaml", allowed_suffixes={".yaml"}
        )
        self.assertEqual(resolved, (self.base / "ok.yaml").resolve())

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(ValueError):
            resolve_existing_file_within(
                self.base, "../outside.yaml", allowed_suffixes={".yaml"}
            )

    def test_rejects_sibling_with_shared_prefix(self) -> None:
        with self.assertRaises(ValueError):
            resolve_existing_file_within(
                self.base,
                "../characters_evil/evil.yaml",
                allowed_suffixes={".yaml"},
            )

    def test_rejects_absolute_path(self) -> None:
        with self.assertRaises(ValueError):
            resolve_existing_file_within(
                self.base,
                str((self.base / "ok.yaml").resolve()),
                allowed_suffixes={".yaml"},
            )

    def test_rejects_wrong_suffix(self) -> None:
        (self.base / "payload.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            resolve_existing_file_within(
                self.base, "payload.txt", allowed_suffixes={".yaml"}
            )

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(ValueError):
            resolve_existing_file_within(self.base, "missing.yaml")


class RedactionTests(unittest.TestCase):
    def test_redacts_nested_secret_keys(self) -> None:
        payload = {
            "agent_config": {
                "llm_configs": {
                    "deepseek_llm": {
                        "llm_api_key": "sk-very-secret",
                        "base_url": "https://api.example.com/v1",
                    }
                }
            },
            "asr_config": {"api_key": "groq-secret"},
            "items": [{"password": "hunter2", "name": "visible"}],
        }

        redacted = redact_secrets(payload)
        rendered = repr(redacted)

        self.assertNotIn("sk-very-secret", rendered)
        self.assertNotIn("groq-secret", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertIn("visible", rendered)
        self.assertEqual(
            redacted["agent_config"]["llm_configs"]["deepseek_llm"]["llm_api_key"],
            "***",
        )

    def test_redacts_embedded_url_and_bearer_secrets(self) -> None:
        rendered = repr(
            redact_secrets(
                "GET https://example.com/?token=abc123 Authorization: Bearer xyz.123"
            )
        )
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("xyz.123", rendered)


class HistoryPathTests(unittest.TestCase):
    def test_traversal_is_collapsed_to_a_basename(self) -> None:
        path = _get_safe_history_path("conf", "../../etc/passwd")
        self.assertEqual(Path(path).parent.name, "conf")
        self.assertEqual(Path(path).name, "passwd.json")

    def test_dot_components_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_path_component("..")

    def test_invalid_characters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _sanitize_path_component("bad\x00name")


class WavDecodingTests(unittest.TestCase):
    def test_decodes_normalized_mono_pcm(self) -> None:
        samples = np.array([0, 16384, -16384], dtype="<i2")
        decoded = decode_pcm_wav(_wav_bytes(samples))
        self.assertEqual(decoded.dtype, np.float32)
        np.testing.assert_allclose(decoded, [0.0, 0.5, -0.5], atol=1e-6)

    def test_rejects_malformed_wav(self) -> None:
        with self.assertRaises(ValueError):
            decode_pcm_wav(b"not a wav file")

    def test_rejects_empty_file(self) -> None:
        with self.assertRaises(ValueError):
            decode_pcm_wav(b"")

    def test_rejects_stereo(self) -> None:
        samples = np.zeros(4, dtype="<i2")
        with self.assertRaises(ValueError):
            decode_pcm_wav(_wav_bytes(samples, channels=2))

    def test_rejects_wrong_sample_rate(self) -> None:
        with self.assertRaises(ValueError):
            decode_pcm_wav(_wav_bytes(sample_rate=8000))

    def test_rejects_oversized_audio(self) -> None:
        samples = np.zeros(16000, dtype="<i2")
        with self.assertRaises(ValueError):
            decode_pcm_wav(_wav_bytes(samples), max_seconds=0)


if __name__ == "__main__":
    unittest.main()
