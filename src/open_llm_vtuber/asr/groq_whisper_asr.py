import io
import wave
import numpy as np
from loguru import logger
from groq import Groq
from .asr_interface import ASRInterface


class VoiceRecognition(ASRInterface):
    # sample_rate, n_channels, and sampwidth are defined in asr_interface.py

    def __init__(
        self,
        api_key: str,
        model: str = "distil-whisper-large-v3-en",
        lang: str | None = "en",
    ) -> None:
        logger.info("Initializing Groq ASR...")
        self.client = Groq(api_key=api_key)
        self.lang = (lang or "").strip() or None
        self.model = model

    def transcribe_np(self, audio: np.ndarray) -> str:
        """Transcribe speech audio in numpy array format and return the transcription.

        Args:
            audio: The numpy array of the audio data to transcribe.
        """

        logger.info("Transcribing audio (GroqWhisperASR)...")

        # Turn the audio into an audio file
        # Make sure the audio is in the range [-1, 1]
        audio = np.clip(audio, -1, 1)
        # Convert the audio to 16-bit PCM
        audio_integer = (audio * 32767).astype(np.int16)

        # groq api requires a file-like object for the audio data, so we use a BytesIO object
        audio_buffer = io.BytesIO()

        with wave.open(audio_buffer, "wb") as wf:
            wf.setnchannels(self.NUM_CHANNELS)
            wf.setsampwidth(self.SAMPLE_WIDTH)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(audio_integer.tobytes())

        audio_buffer.seek(0)

        kwargs: dict = {
            "file": ("audio.wav", audio_buffer.read()),
            "model": self.model,
            "response_format": "text",
            "temperature": 0.0,
        }
        if self.lang:
            kwargs["language"] = self.lang
            # 引导 Whisper 输出简体中文，避免短语音误判为繁体或异域语种
            if self.lang.lower().startswith("zh"):
                kwargs["prompt"] = "简体中文。"

        transcription = self.client.audio.transcriptions.create(**kwargs)

        return transcription
