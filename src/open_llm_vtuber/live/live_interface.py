from abc import ABC, abstractmethod
from typing import Any
from collections.abc import Callable


class LivePlatformInterface(ABC):
    """
    Abstract interface for live streaming platforms.
    This interface defines the methods that any live platform implementation must provide.
    It handles connecting to the VTuber server via proxy, sending messages from the live platform,
    and receiving responses.
    """

    @abstractmethod
    async def connect(self, proxy_url: str) -> bool:
        """
        Connect to the VTuber server via proxy WebSocket.

        Args:
            proxy_url: WebSocket URL for the proxy

        Returns:
            bool: True if connection successful, False otherwise
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from the proxy server.
        """

    @abstractmethod
    async def send_message(self, text: str) -> bool:
        """
        Send a message from the live platform to the VTuber.

        Args:
            text: Message text content

        Returns:
            bool: True if message was sent successfully, False otherwise
        """

    @abstractmethod
    async def register_message_handler(
        self, handler: Callable[[dict[str, Any]], None]
    ) -> None:
        """
        Register a callback function to handle response messages from the VTuber.

        Args:
            handler: Callback function that takes a message dict as parameter
        """

    @abstractmethod
    async def start_receiving(self) -> None:
        """
        Start receiving messages from the proxy server.
        This method should typically be run in a separate task.
        """

    @abstractmethod
    async def run(self) -> None:
        """
        Main entry point to run the live platform client.
        This should handle the complete lifecycle including connection,
        message receiving, and clean disconnection.
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if the client is currently connected to the proxy.

        Returns:
            bool: True if connected, False otherwise
        """

    @abstractmethod
    async def handle_incoming_messages(self, message: dict[str, Any]) -> None:
        """
        Process incoming messages from the VTuber server.

        Args:
            message: The message received from the VTuber
        """
