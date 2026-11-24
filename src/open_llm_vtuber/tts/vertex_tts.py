"""Vertex AI Gemini TTS engine using service-account authentication."""

import base64
import binascii
from pathlib import Path
import re
from typing import Any
import wave

import httpx
from loguru import logger

from ..utils.google_auth import (
    ServiceAccountAuth,
    google_error_message,
    load_service_account,
    resolve_project_id,
)
from .pooled_tts import PooledTTSEngine

_RATE_RE = re.compile(r"rate=(\d+)", re.IGNORECASE)
_DEFAULT_SAMPLE_RATE = 24000


def _vertex_generate_url(project_id: str, location: str, model: str) -> str:
    loc = location.strip() or "global"
    host = (
        "aiplatform.googleapis.com"
        if loc == "global"
        else f"{loc}-aiplatform.googleapis.com"
    )
    return (
        f"https://{host}/v1/projects/{project_id}/locations/{loc}"
        f"/publishers/google/models/{model}:generateContent"
    )


def _extract_audio_part(payload: Any) -> tuple[bytes, str] | None:
    if not isinstance(payload, dict):
        return None
    candidates = payload.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return None
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    for part in parts:
        if not isinstance(part, dict):
            continue
        inline = part.get("inlineData")
        if not isinstance(inline, dict):
            continue
        data = inline.get("data")
        if not isinstance(data, str) or not data:
            continue
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return None
        mime = str(inline.get("mimeType") or "")
        return raw, mime
    return None


def _sample_rate_from_mime(mime_type: str) -> int:
    match = _RATE_RE.search(mime_type)
    if match:
        rate = int(match.group(1))
        if rate > 0:
            return rate
    return _DEFAULT_SAMPLE_RATE


def _write_wav(output_path: str, audio_bytes: bytes, mime_type: str) -> None:
    if audio_bytes[:4] == b"RIFF":
        Path(output_path).write_bytes(audio_bytes)
        return
    sample_rate = _sample_rate_from_mime(mime_type)
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)


class TTSEngine(PooledTTSEngine):
    """Vertex AI Gemini TTS client backed by a reusable HTTP client pool."""

    file_extension = "wav"

    def __init__(
        self,
        credentials_file: str,
        model: str = "gemini-3.8-flash-lite-tts",
        voice: str = "Leda",
        location: str = "global",
        language_code: str | None = None,
        project_id: str | None = None,
        max_clients: int = 3,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(max_clients=max_clients)
        if not isinstance(model, str) or not model.strip():
            raise ValueError("vertex_tts requires a non-empty model")
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError("vertex_tts requires a non-empty voice")

        self.model = model.strip()
        self.voice = voice.strip()
        self.location = (location or "global").strip() or "global"
        self.language_code = (
            language_code.strip()
            if isinstance(language_code, str) and language_code.strip()
            else None
        )

        info = load_service_account(credentials_file)
        self.project_id = resolve_project_id(info, project_id, credentials_file)
        self.url = _vertex_generate_url(self.project_id, self.location, self.model)
        self._auth = ServiceAccountAuth(info, quota_project=self.project_id)
        self._timeout = float(timeout)
        self._transport = transport

    def _create_client(self) -> httpx.Client:
        return httpx.Client(
            auth=self._auth,
            timeout=self._timeout,
            transport=self._transport,
        )

    def _close_client(self, client: httpx.Client) -> None:
        client.close()

    def _build_payload(self, text: str) -> dict[str, Any]:
        speech_config: dict[str, Any] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}},
        }
        if self.language_code is not None:
            speech_config["languageCode"] = self.language_code
        return {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": speech_config,
            },
        }

    def _synthesize(self, client: httpx.Client, text: str, output_path: str) -> bool:
        if not isinstance(text, str):
            logger.warning("VertexTTS: The text cannot be non-string.")
            return False
        text = text.strip()
        if not text:
            logger.warning("VertexTTS: There is no text to speak.")
            return False

        response = client.post(self.url, json=self._build_payload(text))
        if response.status_code != 200:
            logger.error(
                f"VertexTTS: API error (HTTP {response.status_code}): "
                f"{google_error_message(response.content)}"
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            logger.error("VertexTTS: response was not valid JSON.")
            return False

        extracted = _extract_audio_part(payload)
        if extracted is None or not extracted[0]:
            logger.error("VertexTTS: synthesis completed without audio data.")
            return False

        audio_bytes, mime_type = extracted
        _write_wav(output_path, audio_bytes, mime_type)
        logger.debug(
            f">> VertexTTS synthesized [{self.model}/{self.voice}] for [{text}]"
        )
        return True
