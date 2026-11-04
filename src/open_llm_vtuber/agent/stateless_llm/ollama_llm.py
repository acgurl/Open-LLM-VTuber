import atexit
import threading

import requests
from loguru import logger
from .openai_compatible_llm import AsyncLLM

# Preloading can include reading the model from disk.
OLLAMA_CONTROL_TIMEOUT_SECONDS = 120

# (base_url, model) pairs to unload when the process exits. Keys rather than
# instances, so replaced LLMs (e.g. after switch-config) can be collected while
# their model is still unloaded at exit; the exit hook is registered once.
_models_to_unload: set[tuple[str, str]] = set()
_unload_lock = threading.Lock()
_unload_hook_registered = False


def _post_keep_alive_request(
    base_url: str, model: str, keep_alive: float
) -> requests.Response:
    """Load (keep_alive != 0) or unload (0) a model on the Ollama server."""
    return requests.post(
        base_url.replace("/v1", "") + "/api/chat",
        json={"model": model, "keep_alive": keep_alive},
        timeout=OLLAMA_CONTROL_TIMEOUT_SECONDS,
    )


def _unload_model(base_url: str, model: str) -> None:
    logger.info(f"Ollama: Unloading model: {model}")
    # Unloading is a preload request with keep_alive set to 0.
    try:
        logger.debug(_post_keep_alive_request(base_url, model, 0))
    except requests.RequestException as e:
        logger.warning(f"Ollama: failed to unload model: {e}")


def _unload_models_at_exit() -> None:
    with _unload_lock:
        pending = list(_models_to_unload)
        _models_to_unload.clear()
    for base_url, model in pending:
        _unload_model(base_url, model)


def _schedule_unload_at_exit(base_url: str, model: str) -> None:
    global _unload_hook_registered
    with _unload_lock:
        _models_to_unload.add((base_url, model))
        if not _unload_hook_registered:
            atexit.register(_unload_models_at_exit)
            _unload_hook_registered = True


class OllamaLLM(AsyncLLM):
    def __init__(
        self,
        model: str,
        base_url: str,
        llm_api_key: str = "z",
        organization_id: str = "z",
        project_id: str = "z",
        temperature: float = 1.0,
        keep_alive: float = -1,
        unload_at_exit: bool = True,
    ):
        self.keep_alive = keep_alive
        self.unload_at_exit = unload_at_exit
        self.cleaned = False
        super().__init__(
            model=model,
            base_url=base_url,
            llm_api_key=llm_api_key,
            organization_id=organization_id,
            project_id=project_id,
            temperature=temperature,
        )
        # The constructor runs on the WebSocket handling path (e.g.
        # switch-config), so preload in the background instead of blocking the
        # event loop for up to OLLAMA_CONTROL_TIMEOUT_SECONDS.
        threading.Thread(
            target=self._preload, name="ollama-preload", daemon=True
        ).start()
        if unload_at_exit:
            _schedule_unload_at_exit(self.base_url, self.model)

    def _preload(self) -> None:
        try:
            logger.info("Preloading model for Ollama")
            logger.debug(self._post_keep_alive(self.keep_alive))
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to preload model: {e}")
            logger.critical(
                "Fail to connect to Ollama backend. Is Ollama server running? Try running `ollama list` to start the server and try again.\nThe AI will repeat 'Error connecting chat endpoint' until the server is running."
            )
        except Exception as e:
            logger.error(f"Failed to preload model: {e}")

    def cleanup(self):
        """Clean up function to unload the model when exitting"""
        if not self.cleaned and self.unload_at_exit:
            with _unload_lock:
                _models_to_unload.discard((self.base_url, self.model))
            _unload_model(self.base_url, self.model)
            self.cleaned = True

    def _post_keep_alive(self, keep_alive: float) -> requests.Response:
        """Load (keep_alive != 0) or unload (0) the model on the Ollama server."""
        return _post_keep_alive_request(self.base_url, self.model, keep_alive)
