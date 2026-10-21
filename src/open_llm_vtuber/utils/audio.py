"""Audio input validation helpers."""

import io
import wave

import numpy as np


ASR_SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 120
MAX_AUDIO_SAMPLES = ASR_SAMPLE_RATE * MAX_AUDIO_SECONDS


def decode_pcm_wav(
    contents: bytes,
    *,
    sample_rate: int = ASR_SAMPLE_RATE,
    max_seconds: int = MAX_AUDIO_SECONDS,
) -> np.ndarray:
    """Decode mono 16-bit PCM WAV bytes into normalized float32 samples."""
    if not contents:
        raise ValueError("Empty audio file")

    try:
        with wave.open(io.BytesIO(contents), "rb") as wav_file:
            if wav_file.getnchannels() != 1:
                raise ValueError("Audio must be mono")
            if wav_file.getsampwidth() != 2:
                raise ValueError("Audio must be 16-bit PCM")
            if wav_file.getframerate() != sample_rate:
                raise ValueError(f"Audio must be {sample_rate} Hz")

            frame_count = wav_file.getnframes()
            if frame_count > max_seconds * sample_rate:
                raise ValueError(f"Audio exceeds the {max_seconds}-second limit")
            frames = wav_file.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"Invalid WAV file: {exc}") from exc

    if not frames:
        raise ValueError("Empty audio data")

    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
