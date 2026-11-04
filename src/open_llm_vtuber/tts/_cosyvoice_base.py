"""Shared Gradio client logic for the CosyVoice and CosyVoice2 engines."""

from loguru import logger

from .tts_interface import TTSInterface

DEFAULT_PROMPT_WAV_URL = (
    "https://github.com/gradio-app/gradio/raw/main/test/test_files/audio_sample.wav"
)


class CosyvoiceGradioEngine(TTSInterface):
    """Calls a CosyVoice Gradio app; subclasses build the client and inputs."""

    engine_label = "cosyvoiceTTS"

    def _extra_predict_kwargs(self) -> dict:
        """Version-specific ``predict`` arguments."""
        return {}

    def generate_audio(self, text, file_name_no_ext=None):
        if file_name_no_ext is not None:
            logger.warning(
                "Warning: customizing the temp file name with file_name_no_ext is "
                f"not supported by {self.engine_label} and will be ignored."
            )

        return self.client.predict(
            tts_text=text,
            mode_checkbox_group=self.mode_checkbox_group,
            sft_dropdown=self.sft_dropdown,
            prompt_text=self.prompt_text,
            prompt_wav_upload=self.prompt_wav_upload,
            prompt_wav_record=self.prompt_wav_record,
            instruct_text=self.instruct_text,
            seed=self.seed,
            api_name=self.api_name,
            **self._extra_predict_kwargs(),
        )
