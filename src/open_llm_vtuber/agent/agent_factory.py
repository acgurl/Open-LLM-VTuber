from typing import Any, Callable, Dict, Literal, Optional

from loguru import logger

from .agents.agent_interface import AgentInterface
from .agents.basic_memory_agent import BasicMemoryAgent
from .stateless_llm_factory import LLMFactory as StatelessLLMFactory
from .agents.hume_ai import HumeAIAgent
from .agents.letta_agent import LettaAgent

from ..mcpp.tool_manager import ToolManager
from ..mcpp.tool_executor import ToolExecutor


def _build_basic_memory_agent(
    agent_settings: dict,
    llm_configs: dict,
    system_prompt: str,
    live2d_model,
    tts_preprocessor_config,
    kwargs: dict,
) -> AgentInterface:
    basic_memory_settings: dict = agent_settings.get("basic_memory_agent", {})
    llm_provider: str = basic_memory_settings.get("llm_provider")

    if not llm_provider:
        raise ValueError("LLM provider not specified for basic memory agent")

    if not isinstance(llm_configs, dict):
        raise ValueError("LLM configuration pool is missing")

    llm_config = llm_configs.get(llm_provider)
    if not llm_config:
        raise ValueError(f"Configuration not found for LLM provider: {llm_provider}")
    llm_config = dict(llm_config)
    interrupt_method: Literal["system", "user"] = llm_config.pop(
        "interrupt_method", "user"
    )

    llm = StatelessLLMFactory.create_llm(
        llm_provider=llm_provider, system_prompt=system_prompt, **llm_config
    )

    tool_prompts = kwargs.get("system_config", {}).get("tool_prompts", {})
    tool_manager: Optional[ToolManager] = kwargs.get("tool_manager")
    tool_executor: Optional[ToolExecutor] = kwargs.get("tool_executor")
    mcp_prompt_string: str = kwargs.get("mcp_prompt_string", "")

    return BasicMemoryAgent(
        llm=llm,
        system=system_prompt,
        live2d_model=live2d_model,
        tts_preprocessor_config=tts_preprocessor_config,
        faster_first_response=basic_memory_settings.get("faster_first_response", True),
        segment_method=basic_memory_settings.get("segment_method", "pysbd"),
        use_mcpp=basic_memory_settings.get("use_mcpp", False),
        interrupt_method=interrupt_method,
        tool_prompts=tool_prompts,
        tool_manager=tool_manager,
        tool_executor=tool_executor,
        mcp_prompt_string=mcp_prompt_string,
    )


def _build_hume_ai_agent(
    agent_settings: dict,
    _llm_configs: dict,
    _system_prompt: str,
    _live2d_model,
    _tts_preprocessor_config,
    _kwargs: dict,
) -> AgentInterface:
    settings = agent_settings.get("hume_ai_agent", {})
    return HumeAIAgent(
        api_key=settings.get("api_key"),
        host=settings.get("host", "api.hume.ai"),
        config_id=settings.get("config_id"),
        idle_timeout=settings.get("idle_timeout", 15),
    )


def _build_letta_agent(
    agent_settings: dict,
    _llm_configs: dict,
    _system_prompt: str,
    live2d_model,
    tts_preprocessor_config,
    _kwargs: dict,
) -> AgentInterface:
    settings = agent_settings.get("letta_agent", {})
    return LettaAgent(
        live2d_model=live2d_model,
        id=settings.get("id"),
        tts_preprocessor_config=tts_preprocessor_config,
        faster_first_response=settings.get("faster_first_response"),
        segment_method=settings.get("segment_method"),
        host=settings.get("host"),
        port=settings.get("port"),
    )


AgentBuilder = Callable[
    [dict, dict, str, Any, Any, dict],
    AgentInterface,
]

_AGENT_BUILDERS: Dict[str, AgentBuilder] = {
    "basic_memory_agent": _build_basic_memory_agent,
    "hume_ai_agent": _build_hume_ai_agent,
    "letta_agent": _build_letta_agent,
}


class AgentFactory:
    @staticmethod
    def create_agent(
        conversation_agent_choice: str,
        agent_settings: dict,
        llm_configs: dict,
        system_prompt: str,
        live2d_model=None,
        tts_preprocessor_config=None,
        **kwargs,
    ) -> AgentInterface:
        """Create an agent based on the configuration."""
        logger.info(f"Initializing agent: {conversation_agent_choice}")

        try:
            builder = _AGENT_BUILDERS[conversation_agent_choice]
        except KeyError:
            raise ValueError(
                f"Unsupported agent type: {conversation_agent_choice}"
            ) from None

        return builder(
            agent_settings,
            llm_configs,
            system_prompt,
            live2d_model,
            tts_preprocessor_config,
            kwargs,
        )
