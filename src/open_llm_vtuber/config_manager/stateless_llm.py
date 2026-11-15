"""Settings of the LLM backends, one class per wire protocol."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from .i18n import Description, I18nMixin


class StatelessLLMBaseConfig(I18nMixin):
    """Base configuration for StatelessLLM."""

    # interrupt_method. If the provider supports inserting system prompt anywhere in the chat memory, use "system". Otherwise, use "user".
    interrupt_method: Literal["system", "user"] = Field(
        "user", alias="interrupt_method"
    )
    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "interrupt_method": Description(
            en="""The method to use for prompting the interruption signal.
            If the provider supports inserting system prompt anywhere in the chat memory, use "system".
            Otherwise, use "user". You don't need to change this setting.""",
            zh="""用于表示中断信号的方法(提示词模式)。如果LLM支持在聊天记忆中的任何位置插入系统提示词，请使用“system”。
            否则，请使用“user”。您不需要更改此设置。""",
        ),
    }


_OPENAI_DESCRIPTIONS: dict[str, Description] = {
    "base_url": Description(en="Base URL for the API endpoint", zh="API的URL端点"),
    "llm_api_key": Description(en="API key for authentication", zh="API 认证密钥"),
    "organization_id": Description(
        en="Organization ID for the API (Optional)", zh="组织 ID (可选)"
    ),
    "project_id": Description(
        en="Project ID for the API (Optional)", zh="项目 ID (可选)"
    ),
    "model": Description(en="Name of the LLM model to use", zh="LLM 模型名称"),
}


class OpenAICompatibleConfig(StatelessLLMBaseConfig):
    """OpenAI Chat Completions: OpenAI itself and every compatible endpoint."""

    base_url: str = Field(..., alias="base_url")
    llm_api_key: str = Field(..., alias="llm_api_key")
    model: str = Field(..., alias="model")
    organization_id: str | None = Field(None, alias="organization_id")
    project_id: str | None = Field(None, alias="project_id")
    temperature: float | None = Field(1.0, alias="temperature")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        **StatelessLLMBaseConfig.DESCRIPTIONS,
        **_OPENAI_DESCRIPTIONS,
        "temperature": Description(
            en="What sampling temperature to use, between 0 and 2. "
            "null leaves the API default.",
            zh="使用的采样温度，介于 0 和 2 之间；null 表示使用 API 默认值。",
        ),
    }


class OpenAIResponsesConfig(StatelessLLMBaseConfig):
    """OpenAI Responses API (``/v1/responses``)."""

    base_url: str = Field("https://api.openai.com/v1", alias="base_url")
    llm_api_key: str = Field(..., alias="llm_api_key")
    model: str = Field(..., alias="model")
    organization_id: str | None = Field(None, alias="organization_id")
    project_id: str | None = Field(None, alias="project_id")
    temperature: float | None = Field(None, alias="temperature")
    reasoning_effort: str | None = Field(None, alias="reasoning_effort")
    max_output_tokens: int | None = Field(None, ge=1, alias="max_output_tokens")
    interrupt_method: Literal["system", "user"] = Field(
        "system", alias="interrupt_method"
    )

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        **StatelessLLMBaseConfig.DESCRIPTIONS,
        **_OPENAI_DESCRIPTIONS,
        "temperature": Description(
            en="Sampling temperature, between 0 and 2. Leave null for "
            "reasoning models, which reject it.",
            zh="采样温度，介于 0 和 2 之间。推理模型不接受该参数，请保持 null。",
        ),
        "reasoning_effort": Description(
            en="Reasoning effort of a reasoning model, e.g. low, medium, high "
            "(null: the API default)",
            zh="推理模型的推理强度，例如 low、medium、high（null 为 API 默认）",
        ),
        "max_output_tokens": Description(
            en="Cap on generated tokens, reasoning included (null: no cap)",
            zh="生成 token 上限，含推理 token（null 为不限制）",
        ),
    }


class ClaudeConfig(StatelessLLMBaseConfig):
    """Claude through Anthropic's Messages API."""

    base_url: str = Field("https://api.anthropic.com", alias="base_url")
    llm_api_key: str = Field(..., alias="llm_api_key")
    model: str = Field(..., alias="model")
    max_tokens: int = Field(16000, ge=1, alias="max_tokens")
    temperature: float | None = Field(None, alias="temperature")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        **StatelessLLMBaseConfig.DESCRIPTIONS,
        "base_url": Description(
            en="Base URL for Claude API", zh="Claude API 的API端点"
        ),
        "llm_api_key": Description(en="API key for authentication", zh="API 认证密钥"),
        "model": Description(
            en="Name of the Claude model to use", zh="要使用的 Claude 模型名称"
        ),
        "max_tokens": Description(
            en="Maximum number of tokens in one response",
            zh="单次回复的最大 token 数",
        ),
        "temperature": Description(
            en="Sampling temperature, between 0 and 1. Leave null: current "
            "Claude models reject the parameter.",
            zh="采样温度，介于 0 和 1 之间。当前 Claude 模型不接受该参数，请保持 null。",
        ),
    }


class VertexConfig(StatelessLLMBaseConfig):
    """Configuration for Vertex AI (native API, service-account key file)."""

    credentials_file: str = Field(..., alias="credentials_file")
    model: str = Field(..., alias="model")
    project_id: str | None = Field(None, alias="project_id")
    location: str = Field("global", alias="location")
    temperature: float = Field(1.0, alias="temperature")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        **StatelessLLMBaseConfig.DESCRIPTIONS,
        "credentials_file": Description(
            en="Path of the Google Cloud service-account key file (JSON)",
            zh="Google Cloud 服务账号密钥文件（JSON）的路径",
        ),
        "model": Description(
            en="Name of the model to use, e.g. gemini-3-flash-preview",
            zh="要使用的模型名称，例如 gemini-3-flash-preview",
        ),
        "project_id": Description(
            en="Google Cloud project (defaults to the one in the key file)",
            zh="Google Cloud 项目 ID（默认取密钥文件里的项目）",
        ),
        "location": Description(
            en="Vertex AI location, e.g. global or us-central1",
            zh="Vertex AI 区域，例如 global 或 us-central1",
        ),
        "temperature": Description(
            en="What sampling temperature to use, between 0 and 2.",
            zh="使用的采样温度，介于 0 和 2 之间。",
        ),
    }


class StatelessLLMConfigs(I18nMixin, BaseModel):
    """Pool of LLM provider configurations, one entry per wire protocol.

    Providers that only differed by their default URL (``deepseek_llm``,
    ``ollama_llm``, ...) were folded into ``openai_compatible_llm``; see
    ``llm_migration`` for how existing files keep loading.
    """

    openai_compatible_llm: OpenAICompatibleConfig | None = Field(
        None, alias="openai_compatible_llm"
    )
    openai_responses_llm: OpenAIResponsesConfig | None = Field(
        None, alias="openai_responses_llm"
    )
    claude_llm: ClaudeConfig | None = Field(None, alias="claude_llm")
    vertex_llm: VertexConfig | None = Field(None, alias="vertex_llm")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "openai_compatible_llm": Description(
            en="OpenAI Chat Completions API: OpenAI and every compatible "
            "endpoint (DeepSeek, Ollama, LM Studio, Gemini, Zhipu, Groq, ...)",
            zh="OpenAI Chat Completions 协议：OpenAI 及所有兼容端点"
            "（DeepSeek、Ollama、LM Studio、Gemini、智谱、Groq 等）",
        ),
        "openai_responses_llm": Description(
            en="OpenAI Responses API (/v1/responses)",
            zh="OpenAI Responses 协议（/v1/responses）",
        ),
        "claude_llm": Description(
            en="Claude through Anthropic's Messages API",
            zh="Claude（Anthropic Messages 原生协议）",
        ),
        "vertex_llm": Description(
            en="Configuration for Vertex AI (service-account key file)",
            zh="Vertex AI 配置（使用服务账号密钥文件）",
        ),
    }
