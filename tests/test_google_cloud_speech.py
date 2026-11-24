import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

import httpx
import numpy as np
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from open_llm_vtuber.asr.asr_factory import ASRFactory
from open_llm_vtuber.asr.google_cloud_asr import (
    VoiceRecognition as GoogleCloudASR,
    _clean_cjk_spacing,
)
from open_llm_vtuber.config_manager.asr import ASRConfig, GoogleCloudASRConfig
from open_llm_vtuber.config_manager.tts import (
    GoogleCloudTTSConfig,
    TTSConfig,
    VertexTTSConfig,
)
from open_llm_vtuber.speech_models import parse_speech_models
from open_llm_vtuber.tts.google_cloud_tts import TTSEngine as GoogleCloudTTS
from open_llm_vtuber.tts.tts_factory import TTSFactory
from open_llm_vtuber.tts.vertex_tts import TTSEngine as VertexTTS
from open_llm_vtuber.utils.google_auth import (
    GoogleCredentialsError,
    ServiceAccountAuth,
    load_service_account,
)

TOKEN_URI = "https://oauth2.test/token"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()


class _FakeGoogleTransport:
    def __init__(self, replies: list[httpx.Response]) -> None:
        self.replies = replies
        self.token_requests: list[httpx.Request] = []
        self.api_requests: list[httpx.Request] = []
        self.token_reply = httpx.Response(
            200, json={"access_token": "tok-sync-1", "expires_in": 3600}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URI:
            self.token_requests.append(request)
            return self.token_reply
        self.api_requests.append(request)
        return self.replies.pop(0)

    def body(self, index: int = -1) -> dict:
        return json.loads(self.api_requests[index].content)


class GoogleCloudSpeechTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.key_path = Path(self._tmp.name) / "sa.json"
        self.write_key()

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def write_key(self, **overrides) -> None:
        info = {
            "type": "service_account",
            "project_id": "gcp-demo-proj",
            "private_key_id": "kid-1",
            "private_key": _PRIVATE_PEM,
            "client_email": "speech@gcp-demo-proj.iam.gserviceaccount.com",
            "token_uri": TOKEN_URI,
            **overrides,
        }
        self.key_path.write_text(
            json.dumps({k: v for k, v in info.items() if v is not None}),
            encoding="utf-8",
        )

    # ---- config & catalog parsing

    def test_config_validation_and_catalog_parsing(self) -> None:
        tts_cfg = TTSConfig.model_validate(
            {
                "tts_model": "google_cloud_tts",
                "google_cloud_tts": {
                    "credentials_file": str(self.key_path),
                    "voice": "cmn-CN-Chirp3-HD-Leda",
                },
            }
        )
        self.assertIsInstance(tts_cfg.google_cloud_tts, GoogleCloudTTSConfig)
        self.assertEqual(tts_cfg.google_cloud_tts.speaking_rate, 1.0)
        self.assertEqual(tts_cfg.google_cloud_tts.pitch, 0.0)

        asr_cfg = ASRConfig.model_validate(
            {
                "asr_model": "google_cloud_asr",
                "google_cloud_asr": {
                    "credentials_file": str(self.key_path),
                    "language_codes": ["cmn-Hans-CN", "en-US"],
                },
            }
        )
        self.assertIsInstance(asr_cfg.google_cloud_asr, GoogleCloudASRConfig)
        self.assertEqual(asr_cfg.google_cloud_asr.location, "us")
        self.assertEqual(asr_cfg.google_cloud_asr.model, "chirp_3")

        with self.assertRaises(ValidationError):
            GoogleCloudTTSConfig(
                credentials_file=str(self.key_path),
                voice="cmn-CN-Chirp3-HD-Leda",
                speaking_rate=5.0,
            )

        tts_entries = parse_speech_models(
            {
                "tts_models": [
                    {
                        "id": "google-leda",
                        "name": "Google Leda",
                        "provider": "google_cloud_tts",
                        "settings": {
                            "credentials_file": str(self.key_path),
                            "voice": "cmn-CN-Chirp3-HD-Leda",
                        },
                    }
                ]
            },
            "tts",
            "tts_models.yaml",
        )
        self.assertIn("google-leda", tts_entries)

        asr_entries = parse_speech_models(
            {
                "asr_models": [
                    {
                        "id": "google-chirp3",
                        "name": "Google Chirp 3",
                        "provider": "google_cloud_asr",
                        "settings": {
                            "credentials_file": str(self.key_path),
                            "location": "us",
                            "model": "chirp_3",
                            "language_codes": ["auto"],
                        },
                    }
                ]
            },
            "asr",
            "asr_models.yaml",
        )
        self.assertIn("google-chirp3", asr_entries)

    def test_factories_forward_google_cloud_settings(self) -> None:
        with patch("open_llm_vtuber.tts.google_cloud_tts.TTSEngine") as tts_cls:
            TTSFactory.get_tts_engine(
                "google_cloud_tts",
                credentials_file=str(self.key_path),
                voice="cmn-CN-Chirp3-HD-Leda",
                speaking_rate=1.1,
            )
        tts_cls.assert_called_once_with(
            credentials_file=str(self.key_path),
            voice="cmn-CN-Chirp3-HD-Leda",
            language_code=None,
            project_id=None,
            speaking_rate=1.1,
            pitch=0.0,
            model_name=None,
            prompt=None,
        )

        with patch("open_llm_vtuber.asr.google_cloud_asr.VoiceRecognition") as asr_cls:
            ASRFactory.get_asr_system(
                "google_cloud_asr",
                credentials_file=str(self.key_path),
                location="us",
                model="chirp_3",
                language_codes=["cmn-Hans-CN"],
                auto_punctuation=False,
            )
        asr_cls.assert_called_once_with(
            credentials_file=str(self.key_path),
            project_id=None,
            location="us",
            model="chirp_3",
            language_codes=["cmn-Hans-CN"],
            auto_punctuation=False,
        )

    # ---- shared sync auth

    def test_sync_auth_caches_token_sets_quota_project_and_drops_on_401(self) -> None:
        google = _FakeGoogleTransport(
            [
                httpx.Response(200, json={"ok": 1}),
                httpx.Response(401, json={"error": {"message": "expired"}}),
                httpx.Response(200, json={"ok": 2}),
            ]
        )
        info = load_service_account(str(self.key_path))
        auth = ServiceAccountAuth(info, quota_project="quota-proj")
        with httpx.Client(auth=auth, transport=httpx.MockTransport(google)) as client:
            r1 = client.get("https://example.test/one")
            r2 = client.get("https://example.test/two")
            r3 = client.get("https://example.test/three")

        self.assertEqual(
            [r1.status_code, r2.status_code, r3.status_code], [200, 401, 200]
        )
        self.assertEqual(len(google.token_requests), 2)
        for req in google.api_requests:
            self.assertEqual(req.headers["Authorization"], "Bearer tok-sync-1")
            self.assertEqual(req.headers["x-goog-user-project"], "quota-proj")

    # ---- Google Cloud TTS

    def test_tts_language_inference_and_validation(self) -> None:
        google = _FakeGoogleTransport([])
        engine = GoogleCloudTTS(
            credentials_file=str(self.key_path),
            voice="yue-HK-Chirp3-HD-Leda",
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(engine.close)
        self.assertEqual(engine.language_code, "yue-HK")

        explicit = GoogleCloudTTS(
            credentials_file=str(self.key_path),
            voice="Zephyr",
            language_code="cmn-CN",
            model_name="gemini-2.5-flash-tts",
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(explicit.close)
        self.assertEqual(explicit.language_code, "cmn-CN")

        with self.assertRaises(ValueError):
            GoogleCloudTTS(
                credentials_file=str(self.key_path),
                voice="Zephyr",
                transport=httpx.MockTransport(google),
            )

        with self.assertRaises(ValueError):
            GoogleCloudTTS(
                credentials_file=str(self.key_path),
                voice="   ",
                transport=httpx.MockTransport(google),
            )

        self.write_key(project_id=None)
        with self.assertRaises(GoogleCredentialsError):
            GoogleCloudTTS(
                credentials_file=str(self.key_path),
                voice="cmn-CN-Chirp3-HD-Leda",
                transport=httpx.MockTransport(google),
            )

    def test_tts_chirp3_and_gemini_payloads_and_error_cleanup(self) -> None:
        mp3_bytes = b"ID3-fake-mp3-data"
        b64 = base64.b64encode(mp3_bytes).decode("ascii")
        google = _FakeGoogleTransport(
            [
                httpx.Response(200, json={"audioContent": b64}),
                httpx.Response(200, json={"audioContent": b64}),
                httpx.Response(400, json={"error": {"message": "bad voice"}}),
                httpx.Response(200, json={"audioContent": ""}),
            ]
        )
        chirp = GoogleCloudTTS(
            credentials_file=str(self.key_path),
            voice="cmn-CN-Chirp3-HD-Leda",
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(chirp.close)

        # Empty / whitespace text short-circuits without hitting the API.
        self.assertIsNone(chirp.generate_audio("   ", "blank"))
        self.assertEqual(len(google.api_requests), 0)

        out = chirp.generate_audio("你好呀！", "chirp_ok")
        self.assertIsNotNone(out)
        self.assertEqual(Path(out).read_bytes(), mp3_bytes)
        chirp_body = google.body(0)
        self.assertEqual(
            chirp_body,
            {
                "input": {"text": "你好呀！"},
                "voice": {
                    "languageCode": "cmn-CN",
                    "name": "cmn-CN-Chirp3-HD-Leda",
                },
                "audioConfig": {"audioEncoding": "MP3"},
            },
        )
        self.assertEqual(
            google.api_requests[0].headers["x-goog-user-project"], "gcp-demo-proj"
        )

        # Gemini TTS with model_name, prompt, speaking_rate, and pitch.
        gemini = GoogleCloudTTS(
            credentials_file=str(self.key_path),
            voice="Zephyr",
            language_code="cmn-CN",
            model_name="gemini-2.5-flash-tts",
            prompt="用元气可爱的语气",
            speaking_rate=1.15,
            pitch=2.0,
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(gemini.close)
        out_gem = gemini.generate_audio("早安！", "gemini_ok")
        self.assertIsNotNone(out_gem)
        self.assertEqual(
            google.body(1),
            {
                "input": {"text": "早安！", "prompt": "用元气可爱的语气"},
                "voice": {
                    "languageCode": "cmn-CN",
                    "name": "Zephyr",
                    "modelName": "gemini-2.5-flash-tts",
                },
                "audioConfig": {
                    "audioEncoding": "MP3",
                    "speakingRate": 1.15,
                    "pitch": 2.0,
                },
            },
        )

        # API error and empty audioContent return None without leftover files.
        self.assertIsNone(chirp.generate_audio("失败", "bad_status"))
        self.assertFalse(Path("cache/bad_status.mp3").exists())
        self.assertIsNone(chirp.generate_audio("空内容", "empty_audio"))
        self.assertFalse(Path("cache/empty_audio.mp3").exists())

    # ---- Google Cloud ASR

    def test_asr_url_pcm_encoding_cjk_spacing_and_errors(self) -> None:
        self.assertEqual(
            _clean_cjk_spacing("你 好 , 请 问 今 天 天 气 怎 么 样 ?"),
            "你好,请问今天天气怎么样?",
        )
        self.assertEqual(
            _clean_cjk_spacing("Hello world, how are you?"),
            "Hello world, how are you?",
        )
        self.assertEqual(
            _clean_cjk_spacing("我 用 Python 写 代 码 , 很 方 便 !"),
            "我用 Python 写代码,很方便!",
        )

        google = _FakeGoogleTransport(
            [
                httpx.Response(
                    200,
                    json={
                        "results": [
                            {"alternatives": [{"transcript": "你 好 ,"}]},
                            {"alternatives": [{"transcript": "今 天 怎 么 样 ?"}]},
                        ]
                    },
                ),
                httpx.Response(403, json={"error": {"message": "Permission denied"}}),
            ]
        )
        asr = GoogleCloudASR(
            credentials_file=str(self.key_path),
            location="us",
            model="chirp_3",
            language_codes=["auto"],
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(asr.close)
        self.assertEqual(
            asr.url,
            "https://us-speech.googleapis.com/v2/projects/gcp-demo-proj/"
            "locations/us/recognizers/_:recognize",
        )

        global_asr = GoogleCloudASR(
            credentials_file=str(self.key_path),
            project_id="override-proj",
            location="global",
            model="long",
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(global_asr.close)
        self.assertEqual(
            global_asr.url,
            "https://speech.googleapis.com/v2/projects/override-proj/"
            "locations/global/recognizers/_:recognize",
        )

        # Empty array short-circuits.
        self.assertEqual(asr.transcribe_np(np.array([], dtype=np.float32)), "")
        self.assertEqual(len(google.api_requests), 0)

        audio = np.array([0.0, 1.5, -1.5, 0.5], dtype=np.float32)
        text = asr.transcribe_np(audio)
        self.assertEqual(text, "你好,今天怎么样?")

        body = google.body(0)
        self.assertEqual(
            body["config"],
            {
                "explicitDecodingConfig": {
                    "encoding": "LINEAR16",
                    "sampleRateHertz": 16000,
                    "audioChannelCount": 1,
                },
                "languageCodes": ["auto"],
                "model": "chirp_3",
                "features": {"enableAutomaticPunctuation": True},
            },
        )
        decoded_pcm = np.frombuffer(
            base64.b64decode(body["content"]), dtype="<i2"
        ).tolist()
        self.assertEqual(decoded_pcm, [0, 32767, -32767, int(0.5 * 32767)])

        with self.assertRaisesRegex(RuntimeError, "HTTP 403.*Permission denied"):
            asr.transcribe_np(audio)

    # ---- Vertex AI Gemini TTS

    def test_vertex_tts_config_factory_and_catalog(self) -> None:
        cfg = TTSConfig.model_validate(
            {
                "tts_model": "vertex_tts",
                "vertex_tts": {
                    "credentials_file": str(self.key_path),
                    "language_code": "cmn-CN",
                },
            }
        )
        self.assertIsInstance(cfg.vertex_tts, VertexTTSConfig)
        self.assertEqual(cfg.vertex_tts.model, "gemini-3.8-flash-lite-tts")
        self.assertEqual(cfg.vertex_tts.voice, "Leda")
        self.assertEqual(cfg.vertex_tts.location, "global")

        entries = parse_speech_models(
            {
                "tts_models": [
                    {
                        "id": "vertex-leda",
                        "name": "Gemini Leda",
                        "provider": "vertex_tts",
                        "settings": {
                            "credentials_file": str(self.key_path),
                            "model": "gemini-3.8-flash-lite-tts",
                            "voice": "Leda",
                            "location": "global",
                            "language_code": "cmn-CN",
                        },
                    }
                ]
            },
            "tts",
            "tts_models.yaml",
        )
        self.assertIn("vertex-leda", entries)

        with patch("open_llm_vtuber.tts.vertex_tts.TTSEngine") as vtts_cls:
            TTSFactory.get_tts_engine(
                "vertex_tts",
                credentials_file=str(self.key_path),
                model="gemini-3.8-flash-lite-tts",
                voice="Leda",
                location="global",
                language_code="cmn-CN",
            )
        vtts_cls.assert_called_once_with(
            credentials_file=str(self.key_path),
            model="gemini-3.8-flash-lite-tts",
            voice="Leda",
            location="global",
            language_code="cmn-CN",
            project_id=None,
        )

    def test_vertex_tts_riff_l16_payloads_and_error_cleanup(self) -> None:
        riff_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt "
        pcm_bytes = b"\x01\x00\x02\x00\x03\x00\x04\x00"
        google = _FakeGoogleTransport(
            [
                httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "inlineData": {
                                                "mimeType": "audio/wav",
                                                "data": base64.b64encode(
                                                    riff_bytes
                                                ).decode("ascii"),
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "inlineData": {
                                                "mimeType": "audio/l16; rate=24000; channels=1",
                                                "data": base64.b64encode(
                                                    pcm_bytes
                                                ).decode("ascii"),
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                ),
                httpx.Response(400, json={"error": {"message": "bad argument"}}),
            ]
        )

        tts_with_lang = VertexTTS(
            credentials_file=str(self.key_path),
            language_code="cmn-CN",
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(tts_with_lang.close)
        self.assertEqual(
            tts_with_lang.url,
            "https://aiplatform.googleapis.com/v1/projects/gcp-demo-proj/"
            "locations/global/publishers/google/models/"
            "gemini-3.8-flash-lite-tts:generateContent",
        )

        # Blank text short-circuits.
        self.assertIsNone(tts_with_lang.generate_audio("  ", "v_blank"))
        self.assertEqual(len(google.api_requests), 0)

        out_riff = tts_with_lang.generate_audio("你好呀！", "v_riff")
        self.assertIsNotNone(out_riff)
        self.assertEqual(Path(out_riff).read_bytes(), riff_bytes)
        self.assertEqual(
            google.body(0),
            {
                "contents": [{"role": "user", "parts": [{"text": "你好呀！"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Leda"}},
                        "languageCode": "cmn-CN",
                    },
                },
            },
        )

        # Raw L16 PCM wrapped into a valid 24 kHz mono WAV without languageCode.
        tts_plain = VertexTTS(
            credentials_file=str(self.key_path),
            location="us-central1",
            model="gemini-2.5-flash-tts",
            voice="Zephyr",
            transport=httpx.MockTransport(google),
        )
        self.addCleanup(tts_plain.close)
        self.assertIn("us-central1-aiplatform.googleapis.com", tts_plain.url)

        out_pcm = tts_plain.generate_audio("早安！", "v_l16")
        self.assertIsNotNone(out_pcm)
        with wave.open(out_pcm, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 24000)
            self.assertEqual(wf.readframes(wf.getnframes()), pcm_bytes)
        self.assertNotIn(
            "languageCode", google.body(1)["generationConfig"]["speechConfig"]
        )

        # HTTP error leaves no partial file.
        self.assertIsNone(tts_with_lang.generate_audio("失败", "v_err"))
        self.assertFalse(Path("cache/v_err.wav").exists())


if __name__ == "__main__":
    unittest.main()
