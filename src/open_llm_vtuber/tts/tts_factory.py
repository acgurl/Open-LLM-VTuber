from typing import Callable, Dict

from .tts_interface import TTSInterface


def _build_azure(kwargs: dict) -> TTSInterface:
    from .azure_tts import TTSEngine as AzureTTSEngine

    return AzureTTSEngine(
        api_key=kwargs.get("api_key"),
        region=kwargs.get("region"),
        voice=kwargs.get("voice"),
        pitch=kwargs.get("pitch"),
        rate=kwargs.get("rate"),
        tailing_silence_ms=kwargs.get("tailing_silence_ms", 0),
    )


def _build_bark(kwargs: dict) -> TTSInterface:
    from .bark_tts import TTSEngine as BarkTTSEngine

    return BarkTTSEngine(kwargs.get("voice"))


def _build_edge(kwargs: dict) -> TTSInterface:
    from .edge_tts import TTSEngine as EdgeTTSEngine

    return EdgeTTSEngine(kwargs.get("voice"))


def _build_pyttsx3(_kwargs: dict) -> TTSInterface:
    from .pyttsx3_tts import TTSEngine as Pyttsx3TTSEngine

    return Pyttsx3TTSEngine()


def _build_cosyvoice(kwargs: dict) -> TTSInterface:
    from .cosyvoice_tts import TTSEngine as CosyvoiceTTSEngine

    return CosyvoiceTTSEngine(
        client_url=kwargs.get("client_url"),
        mode_checkbox_group=kwargs.get("mode_checkbox_group"),
        sft_dropdown=kwargs.get("sft_dropdown"),
        prompt_text=kwargs.get("prompt_text"),
        prompt_wav_upload_url=kwargs.get("prompt_wav_upload_url"),
        prompt_wav_record_url=kwargs.get("prompt_wav_record_url"),
        instruct_text=kwargs.get("instruct_text"),
        seed=kwargs.get("seed"),
        api_name=kwargs.get("api_name"),
    )


def _build_cosyvoice2(kwargs: dict) -> TTSInterface:
    from .cosyvoice2_tts import TTSEngine as Cosyvoice2TTSEngine

    return Cosyvoice2TTSEngine(
        client_url=kwargs.get("client_url"),
        mode_checkbox_group=kwargs.get("mode_checkbox_group"),
        sft_dropdown=kwargs.get("sft_dropdown"),
        prompt_text=kwargs.get("prompt_text"),
        prompt_wav_upload_url=kwargs.get("prompt_wav_upload_url"),
        prompt_wav_record_url=kwargs.get("prompt_wav_record_url"),
        instruct_text=kwargs.get("instruct_text"),
        stream=kwargs.get("stream"),
        seed=kwargs.get("seed"),
        speed=kwargs.get("speed"),
        api_name=kwargs.get("api_name"),
    )


def _build_melo(kwargs: dict) -> TTSInterface:
    from .melo_tts import TTSEngine as MeloTTSEngine

    return MeloTTSEngine(
        speaker=kwargs.get("speaker"),
        language=kwargs.get("language"),
        device=kwargs.get("device"),
        speed=kwargs.get("speed"),
    )


def _build_x_tts(kwargs: dict) -> TTSInterface:
    from .x_tts import TTSEngine as XTTSEngine

    return XTTSEngine(
        api_url=kwargs.get("api_url"),
        speaker_wav=kwargs.get("speaker_wav"),
        language=kwargs.get("language"),
    )


def _build_gpt_sovits(kwargs: dict) -> TTSInterface:
    from .gpt_sovits_tts import TTSEngine as GSVEngine

    return GSVEngine(
        api_url=kwargs.get("api_url"),
        text_lang=kwargs.get("text_lang"),
        ref_audio_path=kwargs.get("ref_audio_path"),
        prompt_lang=kwargs.get("prompt_lang"),
        prompt_text=kwargs.get("prompt_text"),
        text_split_method=kwargs.get("text_split_method"),
        batch_size=kwargs.get("batch_size"),
        media_type=kwargs.get("media_type"),
        streaming_mode=kwargs.get("streaming_mode"),
    )


def _build_siliconflow(kwargs: dict) -> TTSInterface:
    from .siliconflow_tts import SiliconFlowTTS

    return SiliconFlowTTS(
        api_url=kwargs.get("api_url"),
        api_key=kwargs.get("api_key"),
        default_model=kwargs.get("default_model"),
        default_voice=kwargs.get("default_voice"),
        sample_rate=kwargs.get("sample_rate"),
        response_format=kwargs.get("response_format"),
        stream=kwargs.get("stream"),
        speed=kwargs.get("speed"),
        gain=kwargs.get("gain"),
    )


def _build_coqui(kwargs: dict) -> TTSInterface:
    from .coqui_tts import TTSEngine as CoquiTTSEngine

    return CoquiTTSEngine(
        model_name=kwargs.get("model_name"),
        speaker_wav=kwargs.get("speaker_wav"),
        language=kwargs.get("language"),
        device=kwargs.get("device"),
    )


def _build_fish(kwargs: dict) -> TTSInterface:
    from .fish_api_tts import TTSEngine as FishAPITTSEngine

    return FishAPITTSEngine(
        api_key=kwargs.get("api_key"),
        reference_id=kwargs.get("reference_id"),
        latency=kwargs.get("latency"),
        base_url=kwargs.get("base_url"),
    )


def _build_minimax(kwargs: dict) -> TTSInterface:
    from .minimax_tts import TTSEngine as MinimaxTTSEngine

    return MinimaxTTSEngine(
        group_id=kwargs.get("group_id"),
        api_key=kwargs.get("api_key"),
        model=kwargs.get("model", "speech-02-turbo"),
        voice_id=kwargs.get("voice_id", "male-qn-qingse"),
        pronunciation_dict=kwargs.get("pronunciation_dict", ""),
    )


def _build_sherpa_onnx(kwargs: dict) -> TTSInterface:
    from .sherpa_onnx_tts import TTSEngine as SherpaOnnxTTSEngine

    return SherpaOnnxTTSEngine(**kwargs)


def _build_openai(kwargs: dict) -> TTSInterface:
    from .openai_tts import TTSEngine as OpenAITTSEngine

    return OpenAITTSEngine(
        model=kwargs.get("model"),
        voice=kwargs.get("voice"),
        api_key=kwargs.get("api_key"),
        base_url=kwargs.get("base_url"),
        file_extension=kwargs.get("file_extension"),
    )


def _build_spark(kwargs: dict) -> TTSInterface:
    from .spark_tts import TTSEngine as SparkTTSEngine

    return SparkTTSEngine(
        api_url=kwargs.get("api_url"),
        prompt_wav_upload=kwargs.get("prompt_wav_upload"),
        api_name=kwargs.get("api_name"),
        gender=kwargs.get("gender"),
        pitch=kwargs.get("pitch"),
        speed=kwargs.get("speed"),
    )


def _build_elevenlabs(kwargs: dict) -> TTSInterface:
    from .elevenlabs_tts import TTSEngine as ElevenLabsTTSEngine

    return ElevenLabsTTSEngine(
        api_key=kwargs.get("api_key"),
        voice_id=kwargs.get("voice_id"),
        model_id=kwargs.get("model_id", "eleven_multilingual_v2"),
        output_format=kwargs.get("output_format", "mp3_44100_128"),
        stability=kwargs.get("stability", 0.5),
        similarity_boost=kwargs.get("similarity_boost", 0.5),
        style=kwargs.get("style", 0.0),
        use_speaker_boost=kwargs.get("use_speaker_boost", True),
    )


def _build_cartesia(kwargs: dict) -> TTSInterface:
    from .cartesia_tts import TTSEngine as CartesiaTTSEngine

    return CartesiaTTSEngine(
        api_key=kwargs.get("api_key"),
        voice_id=kwargs.get("voice_id", "6ccbfb76-1fc6-48f7-b71d-91ac6298247b"),
        model_id=kwargs.get("model_id", "sonic-3"),
        output_format=kwargs.get("output_format", "wav"),
        language=kwargs.get("language", "en"),
        emotion=kwargs.get("emotion", "neutral"),
        volume=kwargs.get("volume", 1.0),
        speed=kwargs.get("speed", 1.0),
    )


def _build_piper(kwargs: dict) -> TTSInterface:
    from .piper_tts import TTSEngine as PiperTTSEngine

    return PiperTTSEngine(
        model_path=kwargs.get("model_path"),
        speaker_id=kwargs.get("speaker_id"),
        length_scale=kwargs.get("length_scale"),
        noise_scale=kwargs.get("noise_scale"),
        noise_w=kwargs.get("noise_w"),
        volume=kwargs.get("volume"),
        normalize_audio=kwargs.get("normalize_audio"),
        use_cuda=kwargs.get("use_cuda"),
    )


_TTS_ENGINE_BUILDERS: Dict[str, Callable[[dict], TTSInterface]] = {
    "azure_tts": _build_azure,
    "bark_tts": _build_bark,
    "edge_tts": _build_edge,
    "pyttsx3_tts": _build_pyttsx3,
    "cosyvoice_tts": _build_cosyvoice,
    "cosyvoice2_tts": _build_cosyvoice2,
    "melo_tts": _build_melo,
    "x_tts": _build_x_tts,
    "gpt_sovits_tts": _build_gpt_sovits,
    "siliconflow_tts": _build_siliconflow,
    "coqui_tts": _build_coqui,
    "fish_api_tts": _build_fish,
    "minimax_tts": _build_minimax,
    "sherpa_onnx_tts": _build_sherpa_onnx,
    "openai_tts": _build_openai,
    "spark_tts": _build_spark,
    "elevenlabs_tts": _build_elevenlabs,
    "cartesia_tts": _build_cartesia,
    "piper_tts": _build_piper,
}


class TTSFactory:
    @staticmethod
    def get_tts_engine(engine_type, **kwargs) -> TTSInterface:
        try:
            builder = _TTS_ENGINE_BUILDERS[engine_type]
        except KeyError:
            raise ValueError(f"Unknown TTS engine type: {engine_type}") from None
        return builder(kwargs)
