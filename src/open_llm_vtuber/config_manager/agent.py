"""
This module contains the pydantic model for the configurations of
different types of agents.
"""

from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any, ClassVar, Literal
from .i18n import I18nMixin, Description
from .stateless_llm import StatelessLLMConfigs

# ======== Configurations for different Agents ========


class BasicMemoryAgentConfig(I18nMixin, BaseModel):
    """Configuration for the basic memory agent."""

    llm_provider: Literal[
        "stateless_llm_with_template",
        "openai_compatible_llm",
        "claude_llm",
        "ollama_llm",
        "lmstudio_llm",
        "openai_llm",
        "gemini_llm",
        "zhipu_llm",
        "deepseek_llm",
        "groq_llm",
        "mistral_llm",
    ] = Field(..., alias="llm_provider")

    faster_first_response: bool | None = Field(True, alias="faster_first_response")
    segment_method: Literal["regex", "pysbd"] = Field("pysbd", alias="segment_method")
    use_mcpp: bool | None = Field(False, alias="use_mcpp")
    mcp_enabled_servers: list[str] | None = Field([], alias="mcp_enabled_servers")
    max_tool_rounds: int = Field(10, ge=1, alias="max_tool_rounds")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "llm_provider": Description(
            en="LLM provider to use for this agent",
            zh="Basic Memory Agent 智能体使用的大语言模型选项",
        ),
        "faster_first_response": Description(
            en="Whether to respond as soon as encountering a comma in the first sentence to reduce latency (default: True)",
            zh="是否在第一句回应时遇上逗号就直接生成音频以减少首句延迟（默认：True）",
        ),
        "segment_method": Description(
            en="Method for segmenting sentences: 'regex' or 'pysbd' (default: 'pysbd')",
            zh="分割句子的方法：'regex' 或 'pysbd'（默认：'pysbd'）",
        ),
        "use_mcpp": Description(
            en="Whether to use MCP (Model Context Protocol) for the agent (default: True)",
            zh="是否使用为智能体启用 MCP (Model Context Protocol) Plus（默认：False）",
        ),
        "mcp_enabled_servers": Description(
            en="List of MCP servers to enable for the agent",
            zh="为智能体启用 MCP 服务器列表",
        ),
        "max_tool_rounds": Description(
            en="Maximum LLM requests per user turn while the model keeps calling tools; the turn stops after that (default: 10)",
            zh="单轮对话中模型连续调用工具时最多请求 LLM 的次数，超过后停止本轮（默认：10）",
        ),
    }


# =================================


class HumeAIConfig(I18nMixin, BaseModel):
    """Configuration for the Hume AI agent."""

    api_key: str = Field(..., alias="api_key")
    host: str = Field("api.hume.ai", alias="host")
    config_id: str | None = Field(None, alias="config_id")
    idle_timeout: int = Field(15, alias="idle_timeout")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "api_key": Description(
            en="API key for Hume AI service", zh="Hume AI 服务的 API 密钥"
        ),
        "host": Description(
            en="Host URL for Hume AI service (default: api.hume.ai)",
            zh="Hume AI 服务的主机地址（默认：api.hume.ai）",
        ),
        "config_id": Description(
            en="Configuration ID for EVI settings", zh="EVI 配置 ID"
        ),
        "idle_timeout": Description(
            en="Idle timeout in seconds before disconnecting (default: 15)",
            zh="空闲超时断开连接的秒数（默认：15）",
        ),
    }


# =================================


# Agents that were removed; their settings sections are still accepted (and
# ignored) so existing conf.yaml files keep loading.
_REMOVED_AGENTS = ("letta_agent",)
_removed_agent_warnings: set[str] = set()


class AgentSettings(I18nMixin, BaseModel):
    """Settings for different types of agents."""

    basic_memory_agent: BasicMemoryAgentConfig | None = Field(
        None, alias="basic_memory_agent"
    )
    hume_ai_agent: HumeAIConfig | None = Field(None, alias="hume_ai_agent")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "basic_memory_agent": Description(
            en="Configuration for basic memory agent", zh="基础记忆代理配置"
        ),
        "hume_ai_agent": Description(
            en="Configuration for Hume AI agent", zh="Hume AI 代理配置"
        ),
    }

    @model_validator(mode="before")
    @classmethod
    def drop_removed_agent_settings(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        removed = [name for name in _REMOVED_AGENTS if name in data]
        if not removed:
            return data
        for name in removed:
            if name not in _removed_agent_warnings:
                _removed_agent_warnings.add(name)
                logger.warning(
                    f"agent_settings.{name} is ignored because that agent was removed. "
                    "Delete this section from conf.yaml."
                )
        return {key: value for key, value in data.items() if key not in removed}


class AgentConfig(I18nMixin, BaseModel):
    """This class contains all of the configurations related to agent."""

    conversation_agent_choice: Literal["basic_memory_agent", "hume_ai_agent"] = Field(
        ..., alias="conversation_agent_choice"
    )
    agent_settings: AgentSettings = Field(..., alias="agent_settings")
    llm_configs: StatelessLLMConfigs = Field(..., alias="llm_configs")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "conversation_agent_choice": Description(
            en="Type of conversation agent to use", zh="要使用的对话代理类型"
        ),
        "agent_settings": Description(
            en="Settings for different agent types", zh="不同代理类型的设置"
        ),
        "llm_configs": Description(
            en="Pool of LLM provider configurations", zh="语言模型提供者配置池"
        ),
    }

    @field_validator("conversation_agent_choice", mode="before")
    @classmethod
    def reject_removed_agent(cls, value: Any) -> Any:
        if value in _REMOVED_AGENTS:
            raise ValueError(
                f"conversation_agent_choice '{value}' was removed; "
                "use 'basic_memory_agent' or 'hume_ai_agent'"
            )
        return value
