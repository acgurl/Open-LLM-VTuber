from typing import Callable, Dict

from .asr_interface import ASRInterface


def _build_faster_whisper(kwargs: dict) -> ASRInterface:
    from .faster_whisper_asr import VoiceRecognition as FasterWhisperASR

    return FasterWhisperASR(
        model_path=kwargs.get("model_path"),
        download_root=kwargs.get("download_root"),
        language=kwargs.get("language"),
        device=kwargs.get("device"),
        compute_type=kwargs.get("compute_type"),
        prompt=kwargs.get("prompt"),
    )


def _build_whisper_cpp(kwargs: dict) -> ASRInterface:
    from .whisper_cpp_asr import VoiceRecognition as WhisperCPPASR

    return WhisperCPPASR(**kwargs)


def _build_whisper(kwargs: dict) -> ASRInterface:
    from .openai_whisper_asr import VoiceRecognition as WhisperASR

    return WhisperASR(**kwargs)


def _build_fun_asr(kwargs: dict) -> ASRInterface:
    from .fun_asr import VoiceRecognition as FunASR

    return FunASR(
        model_name=kwargs.get("model_name"),
        vad_model=kwargs.get("vad_model"),
        punc_model=kwargs.get("punc_model"),
        ncpu=kwargs.get("ncpu"),
        hub=kwargs.get("hub"),
        device=kwargs.get("device"),
        language=kwargs.get("language"),
        use_itn=kwargs.get("use_itn"),
    )


def _build_azure_asr(kwargs: dict) -> ASRInterface:
    from .azure_asr import VoiceRecognition as AzureASR

    return AzureASR(
        subscription_key=kwargs.get("api_key"),
        region=kwargs.get("region"),
        languages=kwargs.get("languages", ["en-US", "zh-CN"]),
    )


def _build_groq_whisper(kwargs: dict) -> ASRInterface:
    from .groq_whisper_asr import VoiceRecognition as GroqWhisperASR

    return GroqWhisperASR(
        api_key=kwargs.get("api_key"),
        model=kwargs.get("model"),
        lang=kwargs.get("lang"),
    )


def _build_sherpa_onnx(kwargs: dict) -> ASRInterface:
    from .sherpa_onnx_asr import VoiceRecognition as SherpaOnnxASR

    return SherpaOnnxASR(**kwargs)


_ASR_BUILDERS: Dict[str, Callable[[dict], ASRInterface]] = {
    "faster_whisper": _build_faster_whisper,
    "whisper_cpp": _build_whisper_cpp,
    "whisper": _build_whisper,
    "fun_asr": _build_fun_asr,
    "azure_asr": _build_azure_asr,
    "groq_whisper_asr": _build_groq_whisper,
    "sherpa_onnx_asr": _build_sherpa_onnx,
}


class ASRFactory:
    @staticmethod
    def get_asr_system(system_name: str, **kwargs) -> ASRInterface:
        try:
            builder = _ASR_BUILDERS[system_name]
        except KeyError:
            raise ValueError(f"Unknown ASR system: {system_name}") from None
        return builder(kwargs)
