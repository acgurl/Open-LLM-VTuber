from collections.abc import Callable

from .asr_interface import ASRInterface


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


_ASR_BUILDERS: dict[str, Callable[[dict], ASRInterface]] = {
    "azure_asr": _build_azure_asr,
    "groq_whisper_asr": _build_groq_whisper,
}


class ASRFactory:
    @staticmethod
    def get_asr_system(system_name: str, **kwargs) -> ASRInterface:
        try:
            builder = _ASR_BUILDERS[system_name]
        except KeyError:
            raise ValueError(f"Unknown ASR system: {system_name}") from None
        return builder(kwargs)
