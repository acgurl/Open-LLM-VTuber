import requests
from ._http import fetch_audio_to_file
from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8020/tts_to_audio",
        speaker_wav: str = "female",
        language: str = "en",
    ):
        self.api_url = api_url
        self.speaker_wav = speaker_wav
        self.language = language
        self.file_extension = "wav"

    def generate_audio(self, text, file_name_no_ext=None):
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)

        # Prepare the data for the POST request
        data = {
            "text": text,
            "speaker_wav": self.speaker_wav,
            "language": self.language,
        }

        # Send POST request to the TTS API
        return fetch_audio_to_file(
            self,
            lambda: requests.post(self.api_url, json=data, timeout=120),
            file_name,
        )
