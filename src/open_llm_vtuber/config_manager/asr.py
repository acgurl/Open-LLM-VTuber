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


class GoogleCloudASRConfig(I18nMixin):
    """Configuration for Google Cloud Speech-to-Text v2."""

    credentials_file: str = Field(..., alias="credentials_file")
    project_id: str | None = Field(None, alias="project_id")
    location: str = Field("us", alias="location")
    model: str = Field("chirp_3", alias="model")
    language_codes: list[str] = Field(
        default_factory=lambda: ["cmn-Hans-CN"], alias="language_codes"
    )
    auto_punctuation: bool = Field(True, alias="auto_punctuation")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "credentials_file": Description(
            en="Path of the Google Cloud service-account key file (JSON)",
            zh="Google Cloud 服务账号密钥文件（JSON）的路径",
        ),
        "project_id": Description(
            en="Optional Google Cloud project ID (defaults to the key file's project_id)",
            zh="可选 Google Cloud 项目 ID（默认取密钥文件里的 project_id）",
        ),
        "location": Description(
            en="Speech-to-Text v2 location (e.g., us, asia-southeast1, global)",
            zh="Speech-to-Text v2 区域（如 us、asia-southeast1、global）",
        ),
        "model": Description(
            en="Speech-to-Text v2 recognizer model (e.g., chirp_3)",
            zh="Speech-to-Text v2 识别模型（如 chirp_3）",
        ),
        "language_codes": Description(
            en="BCP-47 language codes or ['auto'] for automatic language detection",
            zh="BCP-47 语言代码列表，或填 ['auto'] 自动检测语种",
        ),
        "auto_punctuation": Description(
            en="Enable automatic punctuation in transcription results",
            zh="是否在识别结果中启用自动标点",
        ),
    }


_ASR_CONFIG_FIELDS = {
    "azure_asr": "azure_asr",
    "groq_whisper_asr": "groq_whisper_asr",
    "google_cloud_asr": "google_cloud_asr",
}


class ASRConfig(I18nMixin):
    """Configuration for Automatic Speech Recognition."""

    asr_model: Literal[
        "azure_asr",
        "groq_whisper_asr",
        "google_cloud_asr",
    ] = Field(..., alias="asr_model")
    azure_asr: AzureASRConfig | None = Field(None, alias="azure_asr")
    groq_whisper_asr: GroqWhisperASRConfig | None = Field(
        None, alias="groq_whisper_asr"
    )
    google_cloud_asr: GoogleCloudASRConfig | None = Field(
        None, alias="google_cloud_asr"
    )

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "asr_model": Description(
            en="Speech-to-text model to use", zh="要使用的语音识别模型"
        ),
        "azure_asr": Description(en="Configuration for Azure ASR", zh="Azure ASR 配置"),
        "groq_whisper_asr": Description(
            en="Configuration for Groq Whisper ASR", zh="Groq Whisper ASR 配置"
        ),
        "google_cloud_asr": Description(
            en="Configuration for Google Cloud Speech-to-Text",
            zh="Google Cloud 语音识别配置",
        ),
    }

    @model_validator(mode="after")
    def check_asr_config(self) -> "ASRConfig":
        field_name = _ASR_CONFIG_FIELDS.get(self.asr_model)
        if field_name and getattr(self, field_name) is None:
            raise ValueError(f"Missing configuration for asr_model '{self.asr_model}'")
        return self
