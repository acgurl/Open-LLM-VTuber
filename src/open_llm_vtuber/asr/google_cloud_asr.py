"""Google Cloud Speech-to-Text v2 engine using service-account authentication."""

import base64
import re
from typing import Any

import httpx
import numpy as np
from loguru import logger

from ..utils.google_auth import (
    ServiceAccountAuth,
    google_error_message,
    load_service_account,
    resolve_project_id,
)
from .asr_interface import ASRInterface

_CJK = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_PUNCT = r"，。！？、；：,.!?;:"
# Chirp 3 in `auto` language mode inserts spaces between CJK characters.
_CJK_GAP_RE = re.compile(
    rf"(?<=[{_CJK}])\s+(?=[{_CJK}{_PUNCT}])|(?<=[{_PUNCT}])\s+(?=[{_CJK}])"
)


def _clean_cjk_spacing(text: str) -> str:
    return _CJK_GAP_RE.sub("", text).strip()


def _speech_recognize_url(project_id: str, location: str) -> str:
    loc = location.strip() or "us"
    host = (
        "speech.googleapis.com" if loc == "global" else f"{loc}-speech.googleapis.com"
    )
    return f"https://{host}/v2/projects/{project_id}/locations/{loc}/recognizers/_:recognize"


def _extract_transcript(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        alternatives = result.get("alternatives") or []
        if not alternatives or not isinstance(alternatives[0], dict):
            continue
        transcript = alternatives[0].get("transcript")
        if isinstance(transcript, str) and transcript.strip():
            parts.append(transcript.strip())
    return _clean_cjk_spacing(" ".join(parts))


class VoiceRecognition(ASRInterface):
    """Google Cloud Speech-to-Text v2 client."""

    def __init__(
        self,
        credentials_file: str,
        project_id: str | None = None,
        location: str = "us",
        model: str = "chirp_3",
        language_codes: list[str] | None = None,
        auto_punctuation: bool = True,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        info = load_service_account(credentials_file)
        self.project_id = resolve_project_id(info, project_id, credentials_file)
        self.location = (location or "us").strip() or "us"
        if not isinstance(model, str) or not model.strip():
            raise ValueError("google_cloud_asr requires a non-empty model")
        self.model = model.strip()

        raw_codes = ["cmn-Hans-CN"] if language_codes is None else language_codes
        cleaned_codes = [
            code.strip() for code in raw_codes if isinstance(code, str) and code.strip()
        ]
        if not cleaned_codes:
            raise ValueError("google_cloud_asr requires at least one language_code")
        self.language_codes = cleaned_codes
        self.auto_punctuation = bool(auto_punctuation)
        self.url = _speech_recognize_url(self.project_id, self.location)

        auth = ServiceAccountAuth(info, quota_project=self.project_id)
        self.client = httpx.Client(
            auth=auth, timeout=float(timeout), transport=transport
        )
        logger.info(
            f"Initialized GoogleCloudASR ({self.location}/{self.model}, "
            f"languages={self.language_codes})"
        )

    def _request_body(self, audio: np.ndarray) -> dict[str, Any]:
        pcm_bytes = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        config: dict[str, Any] = {
            "explicitDecodingConfig": {
                "encoding": "LINEAR16",
                "sampleRateHertz": self.SAMPLE_RATE,
                "audioChannelCount": self.NUM_CHANNELS,
            },
            "languageCodes": self.language_codes,
            "model": self.model,
        }
        if self.auto_punctuation:
            config["features"] = {"enableAutomaticPunctuation": True}
        return {
            "config": config,
            "content": base64.b64encode(pcm_bytes).decode("ascii"),
        }

    def transcribe_np(self, audio: np.ndarray) -> str:
        """Transcribe 16 kHz mono float audio via Google Cloud Speech-to-Text v2."""
        if audio.size == 0:
            return ""

        logger.info("Transcribing audio (GoogleCloudASR)...")
        response = self.client.post(self.url, json=self._request_body(audio))
        if response.status_code != 200:
            message = google_error_message(response.content)
            logger.error(
                f"GoogleCloudASR: API error (HTTP {response.status_code}): {message}"
            )
            raise RuntimeError(
                f"Google Cloud ASR error (HTTP {response.status_code}): {message}"
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError("Google Cloud ASR returned invalid JSON") from error

        return _extract_transcript(payload)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.client.close()
