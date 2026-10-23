import abc
import numpy as np
import asyncio


class ASRInterface(metaclass=abc.ABCMeta):
    SAMPLE_RATE = 16000
    NUM_CHANNELS = 1
    SAMPLE_WIDTH = 2

    async def async_transcribe_np(self, audio: np.ndarray) -> str:
        """Asynchronously transcribe speech audio in numpy array format.

        By default, this runs the synchronous transcribe_np in a coroutine.
        Subclasses can override this method to provide true async implementation.

        Args:
            audio: The numpy array of the audio data to transcribe.

        Returns:
            str: The transcription result.
        """
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        return await asyncio.to_thread(self.transcribe_np, audio)

    @abc.abstractmethod
    def transcribe_np(self, audio: np.ndarray) -> str:
        """Transcribe speech audio in numpy array format and return the transcription.

        Args:
            audio: The numpy array of the audio data to transcribe.
        """
        raise NotImplementedError
