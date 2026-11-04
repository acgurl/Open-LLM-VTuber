from gradio_client import Client, handle_file
from ._cosyvoice_base import DEFAULT_PROMPT_WAV_URL, CosyvoiceGradioEngine


class TTSEngine(CosyvoiceGradioEngine):
    engine_label = "cosyvoice2TTS"

    def __init__(
        self,
        client_url="http://127.0.0.1:50000/",
        mode_checkbox_group="预训练音色",
        sft_dropdown="中文女",
        prompt_text="",
        prompt_wav_upload_url=DEFAULT_PROMPT_WAV_URL,
        prompt_wav_record_url=DEFAULT_PROMPT_WAV_URL,
        instruct_text="",
        stream=False,
        seed=0,
        speed=1.0,
        api_name="/generate_audio",
    ):
        self.client = Client(client_url)

        self.mode_checkbox_group = mode_checkbox_group
        self.sft_dropdown = sft_dropdown
        self.prompt_text = prompt_text
        self.prompt_wav_upload = handle_file(prompt_wav_upload_url)
        self.prompt_wav_record = handle_file(prompt_wav_record_url)
        self.instruct_text = instruct_text
        self.stream = stream
        self.seed = seed
        self.speed = speed
        self.api_name = api_name

    def _extra_predict_kwargs(self) -> dict:
        return {"stream": self.stream, "speed": self.speed}
