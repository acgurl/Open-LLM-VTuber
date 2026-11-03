"""Message platform connectors (QQ bot, ...)."""

from .base import Connector, ConnectorCapabilities, InboundMessage
from .binding import BindCodeStore, email_domain_allowed, user_eligible
from .dispatcher import ConnectorDispatcher
from .manager import ConnectorManager, create_connector

__all__ = [
    "BindCodeStore",
    "Connector",
    "ConnectorCapabilities",
    "ConnectorDispatcher",
    "ConnectorManager",
    "InboundMessage",
    "create_connector",
    "email_domain_allowed",
    "user_eligible",
]
