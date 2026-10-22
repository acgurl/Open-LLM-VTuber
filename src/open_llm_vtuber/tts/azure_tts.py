import sys
import os
from xml.sax.saxutils import escape, quoteattr

import azure.cognitiveservices.speech as speechsdk
from loguru import logger

from .pooled_tts import PooledTTSEngine

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


class TTSEngine(PooledTTSEngine):
    file_extension = "mp3"

    def __init__(
        self,
        api_key,
        region,
        voice,
        pitch=0,
        rate=1.0,
        tailing_silence_ms=0,
        max_clients=3,
    ):
        """
        Initialize the Azure Text-to-Speech service
        api_key: str
            the Azure API key
        region: str
            the Azure region
        voice: str
            the voice to use
        pitch: int or str
            the pitch adjustment. (percentage, from -100 to 100). Default is 0
        rate: float or str
            the speaking rate. Default is 1.0 (normal speed)
        tailing_silence_ms: int
            silence Azure appends after speech via SSML. Default is 0; the
            service still keeps a small inherent tail.
        max_clients: int
            number of reusable SpeechSynthesizer connections to keep.
        """
        super().__init__(max_clients=max_clients)
        self.speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
        self.speech_config.speech_synthesis_voice_name = voice
        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
        )

        self.voice = voice
        self.pitch = pitch
        self.rate = rate
        self.tailing_silence_ms = max(0, int(tailing_silence_ms))

    def _create_client(self):
        return speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config, audio_config=None
        )

    def _synthesize(self, client, text, output_path):
        if not isinstance(text, str):
            logger.warning("AzureTTS: The text cannot be non-string.")
            logger.warning(f"Received type: {type(text)} and value: {text}")
            return False
        text = text.strip()

        if text == "":
            logger.warning("AzureTTS: There is no text to speak.")
            return False

        result = client.speak_ssml(self._build_ssml(text))
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            self._log_failure(result)
            return False

        audio_data = result.audio_data
        if not audio_data:
            logger.error("AzureTTS: synthesis completed without audio data.")
            return False

        with open(output_path, "wb") as audio_file:
            audio_file.write(audio_data)
        logger.debug(f">> Azure speech synthesized for text [{text}]")
        return True

    def _close_client(self, client):
        client.stop_speaking()

    def _build_ssml(self, text: str) -> str:
        locale = "-".join(self.voice.split("-")[:2])
        return (
            '<speak version="1.0" '
            'xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" '
            f"xml:lang={quoteattr(locale)}>"
            f"<voice name={quoteattr(self.voice)}>"
            f'<mstts:silence type="Tailing" value="{self.tailing_silence_ms}ms"/>'
            f"<prosody pitch={quoteattr(f'{self.pitch}%')} "
            f"rate={quoteattr(str(self.rate))}>"
            f"{escape(text)}"
            "</prosody>"
            "</voice>"
            "</speak>"
        )

    @staticmethod
    def _log_failure(result) -> None:
        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            logger.error(f"Azure speech synthesis canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                if cancellation_details.error_details:
                    logger.error(f"Error details: {cancellation_details.error_details}")
                logger.error("Did you set the Azure speech resource key and region?")
            return
        logger.error(f"Azure speech synthesis failed: {result.reason}")
