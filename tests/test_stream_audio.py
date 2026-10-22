import base64
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from open_llm_vtuber.utils.stream_audio import prepare_audio_payload  # noqa: E402


def _write_tone_wav(path: str, seconds: float = 0.2) -> None:
    sample_rate = 24000
    samples = [
        int(8000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        for index in range(int(sample_rate * seconds))
    ]
    frames = struct.pack("<" + "h" * len(samples), *samples)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)


class AudioPayloadTests(unittest.TestCase):
    def test_wav_payload_is_sent_verbatim_with_mime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "sentence.wav")
            _write_tone_wav(path)

            payload = prepare_audio_payload(audio_path=path)

            with open(path, "rb") as audio_file:
                expected = base64.b64encode(audio_file.read()).decode("utf-8")
            self.assertEqual(payload["audio_mime"], "audio/wav")
            self.assertEqual(payload["audio"], expected)

    def test_silent_payload_has_no_mime(self):
        payload = prepare_audio_payload(audio_path=None)

        self.assertIsNone(payload["audio"])
        self.assertIsNone(payload["audio_mime"])


if __name__ == "__main__":
    unittest.main()
