"""Shared download step for TTS engines that call a self-hosted HTTP server."""

from collections.abc import Callable

from loguru import logger

from .tts_interface import TTSInterface


def fetch_audio_to_file(
    engine: TTSInterface, send_request: Callable[[], object], file_name: str
) -> str | None:
    """Run ``send_request`` and save a 200 response body to ``file_name``.

    Returns the file path, or None on a non-200 status or any failure (the
    partially written file, if any, is removed).
    """
    try:
        response = send_request()
        if response.status_code == 200:
            with open(file_name, "wb") as audio_file:
                audio_file.write(response.content)
            return file_name
        logger.critical(
            f"Error: Failed to generate audio. Status code: {response.status_code}"
        )
        return None
    except Exception as e:
        logger.critical(f"Error: Failed to generate audio. {e}")
        engine.remove_partial_file(file_name)
        return None
