import threading

import pyttsx3
from loguru import logger

from .tts_interface import TTSInterface


# using https://github.com/thevickypedia/py3-tts because pyttsx3 is unmaintained and not working


class TTSEngine(TTSInterface):
    def __init__(self):
        self.engine = pyttsx3.init()
        self.file_extension = "aiff"
        self.lock = threading.Lock()

    #! This method (pyttsx3) is not thread safe. It will blow if it's called from multiple threads at the same time.
    def generate_audio(self, text, file_name_no_ext=None):
        logger.debug(f"Start Generating {file_name_no_ext}")
        file_name = self.generate_cache_file_name(file_name_no_ext, self.file_extension)

        with self.lock:
            self.engine.save_to_file(text=text, filename=file_name)
            self.engine.runAndWait()
        logger.info(f"Finished Generating {file_name}")
        return file_name
