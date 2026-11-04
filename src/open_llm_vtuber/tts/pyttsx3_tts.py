import threading

import pyttsx3
from loguru import logger

from .tts_interface import TTSInterface


# Offline system TTS via the `pyttsx3` package (SAPI5 / NSSpeechSynthesizer / eSpeak).


class TTSEngine(TTSInterface):
    def __init__(self):
        self.engine = pyttsx3.init()
        self.file_extension = "aiff"
        self.lock = threading.Lock()

    #! This method (pyttsx3) is not thread safe. It will blow if it's called from multiple threads at the same time.
    def generate_audio(self, text, file_name_no_ext=None):
        logger.debug(f"Start Generating {file_name_no_ext}")
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)

        try:
            with self.lock:
                self.engine.save_to_file(text=text, filename=file_name)
                self.engine.runAndWait()
        except Exception as e:
            logger.critical(f"Error: pyttsx3 unable to generate audio: {e}")
            self.remove_partial_file(file_name)
            return None
        logger.info(f"Finished Generating {file_name}")
        return file_name
