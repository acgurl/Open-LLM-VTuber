# config_manager/asr.py
from pydantic import Field, model_validator
from typing import Literal, ClassVar
from .i18n import I18nMixin, Description


class AzureASRConfig(I18nMixin):
    """Configuration for Azure ASR service."""

    api_key: str = Field(..., alias="api_key")
    region: str = Field(..., alias="region")
    languages: list[str] = Field(["en-US", "zh-CN"], alias="languages")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "api_key": Description(
            en="API key for Azure ASR service", zh="Azure ASR 服务的 API 密钥"
        ),
        "region": Description(
            en="Azure region (e.g., eastus)", zh="Azure 区域（如 eastus)"
        ),
        "languages": Description(
            en="List of languages to detect (e.g., ['en-US', 'zh-CN'])",
            zh="要检测的语言列表（如 ['en-US', 'zh-CN'])",
        ),
    }


class GroqWhisperASRConfig(I18nMixin):
    """Configuration for Groq Whisper ASR."""

    api_key: str = Field(..., alias="api_key")
    model: str = Field("whisper-large-v3-turbo", alias="model")
    lang: str | None = Field(None, alias="lang")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "api_key": Description(
            en="API key for Groq Whisper ASR", zh="Groq Whisper ASR 的 API 密钥"
        ),
        "model": Description(
            en="Name of the Groq Whisper model to use",
            zh="要使用的 Groq Whisper 模型名称",
        ),
        "lang": Description(
            en="Language code (leave empty for auto-detect)",
            zh="语言代码（留空以自动检测）",
        ),
    }


_ASR_CONFIG_FIELDS = {
    "azure_asr": "azure_asr",
    "groq_whisper_asr": "groq_whisper_asr",
}


class ASRConfig(I18nMixin):
    """Configuration for Automatic Speech Recognition."""

    asr_model: Literal[
        "azure_asr",
        "groq_whisper_asr",
    ] = Field(..., alias="asr_model")
    azure_asr: AzureASRConfig | None = Field(None, alias="azure_asr")
    groq_whisper_asr: GroqWhisperASRConfig | None = Field(
        None, alias="groq_whisper_asr"
    )

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "asr_model": Description(
            en="Speech-to-text model to use", zh="要使用的语音识别模型"
        ),
        "azure_asr": Description(en="Configuration for Azure ASR", zh="Azure ASR 配置"),
        "groq_whisper_asr": Description(
            en="Configuration for Groq Whisper ASR", zh="Groq Whisper ASR 配置"
        ),
    }

    @model_validator(mode="after")
    def check_asr_config(self) -> "ASRConfig":
        field_name = _ASR_CONFIG_FIELDS.get(self.asr_model)
        if field_name and getattr(self, field_name) is None:
            raise ValueError(f"Missing configuration for asr_model '{self.asr_model}'")
        return self
