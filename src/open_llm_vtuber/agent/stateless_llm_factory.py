from collections.abc import Callable

from loguru import logger

from .stateless_llm.claude_llm import ClaudeLLM
from .stateless_llm.openai_compatible_llm import OpenAICompatibleLLM
from .stateless_llm.openai_responses_llm import OpenAIResponsesLLM
from .stateless_llm.stateless_llm_interface import StatelessLLMInterface
from .stateless_llm.vertex_llm import VertexLLM


def _build_openai_compatible(kwargs: dict) -> StatelessLLMInterface:
    return OpenAICompatibleLLM(
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url"),
        llm_api_key=kwargs.get("llm_api_key"),
        organization_id=kwargs.get("organization_id"),
        project_id=kwargs.get("project_id"),
        temperature=kwargs.get("temperature"),
    )


def _build_openai_responses(kwargs: dict) -> StatelessLLMInterface:
    return OpenAIResponsesLLM(
        model=kwargs.get("model"),
        base_url=kwargs.get("base_url") or "https://api.openai.com/v1",
        llm_api_key=kwargs.get("llm_api_key"),
        organization_id=kwargs.get("organization_id"),
        project_id=kwargs.get("project_id"),
        temperature=kwargs.get("temperature"),
        reasoning_effort=kwargs.get("reasoning_effort"),
        max_output_tokens=kwargs.get("max_output_tokens"),
    )


def _build_claude(kwargs: dict) -> StatelessLLMInterface:
    return ClaudeLLM(
        model=kwargs.get("model"),
        llm_api_key=kwargs.get("llm_api_key"),
        base_url=kwargs.get("base_url"),
        max_tokens=kwargs.get("max_tokens") or 16000,
        temperature=kwargs.get("temperature"),
    )


def _build_vertex(kwargs: dict) -> StatelessLLMInterface:
    return VertexLLM(
        model=kwargs.get("model"),
        credentials_file=kwargs.get("credentials_file"),
        project_id=kwargs.get("project_id"),
        location=kwargs.get("location"),
        temperature=kwargs.get("temperature"),
    )


# One builder per wire protocol; the keys are the ``llm_configs`` providers.
_LLM_BUILDERS: dict[str, Callable[[dict], StatelessLLMInterface]] = {
    "openai_compatible_llm": _build_openai_compatible,
    "openai_responses_llm": _build_openai_responses,
    "claude_llm": _build_claude,
    "vertex_llm": _build_vertex,
}


class LLMFactory:
    @staticmethod
    def create_llm(llm_provider, **kwargs) -> StatelessLLMInterface:
        """Create an LLM based on the configuration.

        Args:
            llm_provider: The type of LLM to create
            **kwargs: That provider's settings
        """
        logger.info(f"Initializing LLM: {llm_provider}")
        try:
            builder = _LLM_BUILDERS[llm_provider]
        except KeyError:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}") from None
        return builder(kwargs)
