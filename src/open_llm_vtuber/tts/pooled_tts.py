import abc
import os
import queue
import threading
from typing import Any

from loguru import logger

from .tts_interface import TTSInterface


class PooledTTSEngine(TTSInterface):
    """TTS engine base class backed by a small pool of reusable API clients.

    Many cloud TTS SDKs open a new connection (and TLS handshake) for every
    synthesis call. Keep a bounded pool of clients so consecutive sentences
    reuse warm connections.

    Subclasses implement:
      - _create_client(): create a client/connection object.
      - _synthesize(client, text, output_path) -> bool:
            synthesize text with the client, write the audio file, and return
            True on success. Returning False discards the client.
      - _close_client(client): optional cleanup when a client is discarded.

    Example for an HTTP API:
      class MyHTTPEngine(PooledTTSEngine):
          file_extension = "mp3"

          def _create_client(self):
              return requests.Session()

          def _synthesize(self, client, text, output_path):
              response = client.post(self.url, json={"text": text}, timeout=30)
              response.raise_for_status()
              with open(output_path, "wb") as audio_file:
                  audio_file.write(response.content)
              return True
    """

    file_extension = "mp3"

    def __init__(self, max_clients: int = 3):
        if max_clients < 1:
            raise ValueError("max_clients must be at least 1")
        self.max_clients = max_clients
        self._slots = threading.BoundedSemaphore(max_clients)
        self._idle_clients: queue.LifoQueue = queue.LifoQueue()
        self._closed = False
        self._pool_lock = threading.Lock()

    @abc.abstractmethod
    def _create_client(self) -> Any:
        raise NotImplementedError

    @abc.abstractmethod
    def _synthesize(self, client: Any, text: str, output_path: str) -> bool:
        raise NotImplementedError

    def _close_client(self, client: Any) -> None:
        """Release backend resources. Default is a no-op."""

    def generate_audio(self, text, file_name_no_ext=None):
        output_path = self.generate_cache_file_name(
            file_name_no_ext, self.file_extension
        )
        client = None
        success = False

        try:
            client = self._acquire_client()
            success = bool(self._synthesize(client, text, output_path))
        except Exception as e:
            logger.error(f"{type(self).__name__}: synthesis failed: {e}")
        finally:
            if client is not None:
                self._release_client(client, healthy=success)

        if not success:
            if os.path.exists(output_path):
                os.remove(output_path)
            return None
        return output_path

    def _acquire_client(self) -> Any:
        if self._closed:
            raise RuntimeError(f"{type(self).__name__} is closed")

        self._slots.acquire()
        try:
            if self._closed:
                raise RuntimeError(f"{type(self).__name__} is closed")
            try:
                return self._idle_clients.get_nowait()
            except queue.Empty:
                return self._create_client()
        except Exception:
            self._slots.release()
            raise

    def _release_client(self, client: Any, healthy: bool) -> None:
        if healthy and not self._closed:
            self._idle_clients.put(client)
        else:
            self._close_client_safely(client)
        self._slots.release()

    def _close_client_safely(self, client: Any) -> None:
        try:
            self._close_client(client)
        except Exception as e:
            logger.warning(f"{type(self).__name__}: failed to close client: {e}")

    def close(self) -> None:
        """Discard idle clients; active clients close when they are released."""
        with self._pool_lock:
            if self._closed:
                return
            self._closed = True
            while True:
                try:
                    client = self._idle_clients.get_nowait()
                except queue.Empty:
                    break
                self._close_client_safely(client)
