"""Google Cloud Text-to-Speech engine using service-account authentication."""

import base64
import binascii
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from ..utils.google_auth import (
    ServiceAccountAuth,
    google_error_message,
    load_service_account,
    resolve_project_id,
)
from .pooled_tts import PooledTTSEngine

_SYNTHESIZE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"


def _resolve_language_code(voice: str, language_code: str | None) -> str:
    if isinstance(language_code, str) and language_code.strip():
        return language_code.strip()
    parts = [part for part in voice.split("-") if part]
    if len(parts) < 2:
        raise ValueError(
            f"Cannot infer language_code from voice '{voice}'; "
            "set language_code explicitly"
        )
    return f"{parts[0]}-{parts[1]}"


class TTSEngine(PooledTTSEngine):
    """Google Cloud Text-to-Speech client backed by a reusable HTTP client pool."""

    file_extension = "mp3"

    def __init__(
        self,
        credentials_file: str,
        voice: str,
        language_code: str | None = None,
        project_id: str | None = None,
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
        model_name: str | None = None,
        prompt: str | None = None,
        max_clients: int = 3,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(max_clients=max_clients)
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError("google_cloud_tts requires a non-empty voice name")

        self.voice = voice.strip()
        self.language_code = _resolve_language_code(self.voice, language_code)
        info = load_service_account(credentials_file)
        self.project_id = resolve_project_id(info, project_id, credentials_file)
        self._auth = ServiceAccountAuth(info, quota_project=self.project_id)

        self.speaking_rate = float(speaking_rate)
        self.pitch = float(pitch)
        self.model_name = (
            model_name.strip()
            if isinstance(model_name, str) and model_name.strip()
            else None
        )
        self.prompt = (
            prompt.strip() if isinstance(prompt, str) and prompt.strip() else None
        )
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
        input_payload: dict[str, Any] = {"text": text}
        if self.prompt is not None:
            input_payload["prompt"] = self.prompt

        voice_payload: dict[str, Any] = {
            "languageCode": self.language_code,
            "name": self.voice,
        }
        if self.model_name is not None:
            voice_payload["modelName"] = self.model_name

        audio_config: dict[str, Any] = {"audioEncoding": "MP3"}
        if self.speaking_rate != 1.0:
            audio_config["speakingRate"] = self.speaking_rate
        # Chirp 3 HD voices reject non-default pitch parameters; omit when 0.0.
        if self.pitch != 0.0:
            audio_config["pitch"] = self.pitch

        return {
            "input": input_payload,
            "voice": voice_payload,
            "audioConfig": audio_config,
        }

    def _synthesize(self, client: httpx.Client, text: str, output_path: str) -> bool:
        if not isinstance(text, str):
            logger.warning("GoogleCloudTTS: The text cannot be non-string.")
            return False
        text = text.strip()
        if not text:
            logger.warning("GoogleCloudTTS: There is no text to speak.")
            return False

        response = client.post(_SYNTHESIZE_URL, json=self._build_payload(text))
        if response.status_code != 200:
            logger.error(
                f"GoogleCloudTTS: API error (HTTP {response.status_code}): "
                f"{google_error_message(response.content)}"
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            logger.error("GoogleCloudTTS: response was not valid JSON.")
            return False

        audio_content = (
            payload.get("audioContent") if isinstance(payload, dict) else None
        )
        if not isinstance(audio_content, str) or not audio_content:
            logger.error("GoogleCloudTTS: synthesis completed without audioContent.")
            return False

        try:
            audio_bytes = base64.b64decode(audio_content, validate=True)
        except (binascii.Error, ValueError):
            logger.error("GoogleCloudTTS: invalid base64 audioContent.")
            return False

        if not audio_bytes:
            logger.error("GoogleCloudTTS: decoded audioContent is empty.")
            return False

        Path(output_path).write_bytes(audio_bytes)
        logger.debug(f">> GoogleCloudTTS synthesized [{self.voice}] for [{text}]")
        return True
