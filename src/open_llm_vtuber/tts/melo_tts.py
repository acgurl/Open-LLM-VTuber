import os
import sys

from melo.api import TTS

from .tts_interface import TTSInterface

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


class TTSEngine(TTSInterface):
    def __init__(
        self,
        speaker: str = "EN-Default",
        language: str = "EN",
        device: str = "auto",
        speed: float = 1.0,
    ):
        # Speed is adjustable
        self.speed = speed

        # CPU is sufficient for real-time inference.
        # You can set it manually to 'cpu' or 'cuda' or 'cuda:0' or 'mps'

        # English
        self.model = TTS(language=language, device=device)
        self.speaker_id = self.model.hps.data.spk2id[speaker]

        self.temp_audio_file = "temp"
        self.file_extension = "wav"
        self.new_audio_dir = "cache"

        if not os.path.exists(self.new_audio_dir):
            os.makedirs(self.new_audio_dir)

    def generate_audio(self, text, file_name_no_ext=None):
        """
        Generate speech audio file using TTS.
        text: str
            the text to speak
        file_name_no_ext: str
            name of the file without extension


        Returns:
        str: the path to the generated audio file

        """
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)

        def synthesize() -> str:
            self.model.tts_to_file(
                text, self.speaker_id, f"{file_name}", speed=self.speed
            )
            return file_name

        try:
            return synthesize()
        except LookupError:
            import nltk

            nltk.download("averaged_perceptron_tagger_eng")
            try:
                return synthesize()
            except LookupError:
                return None
