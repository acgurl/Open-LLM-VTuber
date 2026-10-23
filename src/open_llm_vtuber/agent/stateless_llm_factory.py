from typing import Callable, Dict

from loguru import logger

from .stateless_llm.stateless_llm_interface import StatelessLLMInterface
from .stateless_llm.stateless_llm_with_template import (
    AsyncLLMWithTemplate as StatelessLLMWithTemplate,
)
from .stateless_llm.openai_compatible_llm import AsyncLLM as OpenAICompatibleLLM
from .stateless_llm.ollama_llm import OllamaLLM
from .stateless_llm.claude_llm import AsyncLLM as ClaudeLLM


def _build_openai_compatible(kwargs: dict) -> StatelessLLMInterface:
    return OpenAICompatibleLLM(
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url"),
        llm_api_key=kwargs.get("llm_api_key"),
        organization_id=kwargs.get("organization_id"),
        project_id=kwargs.get("project_id"),
        temperature=kwargs.get("temperature"),
    )


def _build_template(kwargs: dict) -> StatelessLLMInterface:
    return StatelessLLMWithTemplate(
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url"),
        llm_api_key=kwargs.get("llm_api_key"),
        organization_id=kwargs.get("organization_id"),
        template=kwargs.get("template"),
        project_id=kwargs.get("project_id"),
    )


def _build_ollama(kwargs: dict) -> StatelessLLMInterface:
    return OllamaLLM(
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url"),
        llm_api_key=kwargs.get("llm_api_key"),
        organization_id=kwargs.get("organization_id"),
        project_id=kwargs.get("project_id"),
        temperature=kwargs.get("temperature"),
        keep_alive=kwargs.get("keep_alive"),
        unload_at_exit=kwargs.get("unload_at_exit"),
    )


def _build_llama_cpp(kwargs: dict) -> StatelessLLMInterface:
    from .stateless_llm.llama_cpp_llm import LLM as LlamaLLM

    return LlamaLLM(model_path=kwargs.get("model_path"))


def _build_claude(kwargs: dict) -> StatelessLLMInterface:
    return ClaudeLLM(
        system=kwargs.get("system_prompt"),
        base_url=kwargs.get("base_url"),
        model=kwargs.get("model"),
        llm_api_key=kwargs.get("llm_api_key"),
    )


_LLM_BUILDERS: Dict[str, Callable[[dict], StatelessLLMInterface]] = {
    "openai_compatible_llm": _build_openai_compatible,
    "openai_llm": _build_openai_compatible,
    "gemini_llm": _build_openai_compatible,
    "zhipu_llm": _build_openai_compatible,
    "deepseek_llm": _build_openai_compatible,
    "groq_llm": _build_openai_compatible,
    "mistral_llm": _build_openai_compatible,
    "lmstudio_llm": _build_openai_compatible,
    "stateless_llm_with_template": _build_template,
    "ollama_llm": _build_ollama,
    "llama_cpp_llm": _build_llama_cpp,
    "claude_llm": _build_claude,
}


class LLMFactory:
    @staticmethod
    def create_llm(llm_provider, **kwargs) -> StatelessLLMInterface:
        """Create an LLM based on the configuration.

        Args:
            llm_provider: The type of LLM to create
            **kwargs: Additional arguments
        """
        logger.info(f"Initializing LLM: {llm_provider}")
        try:
            builder = _LLM_BUILDERS[llm_provider]
        except KeyError:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}") from None
        return builder(kwargs)
