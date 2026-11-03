"""Start, supervise and stop the configured connectors."""

import asyncio
import time
from collections.abc import Callable

from loguru import logger

from ..config_manager.connectors import ConnectorsConfig, QQConnectorConfig
from ..service_context import ServiceContext
from ..utils.security import redact_secrets
from .base import Connector
from .binding import BindCodeStore
from .dispatcher import ConnectorDispatcher

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 300.0
# A connection that stayed up this long resets the backoff.
STABLE_RUN_SECONDS = 60.0

ConnectorFactory = Callable[[QQConnectorConfig], Connector]


def create_connector(config: QQConnectorConfig) -> Connector:
    if config.type == "qq":
        from .qq import QQConnector

        return QQConnector(config)
    raise ValueError(f"Unsupported connector type: {config.type}")


class ConnectorManager:
    """Owns the deployment-managed (global) connectors of one server."""

    def __init__(
        self,
        default_context_cache: ServiceContext,
        config: ConnectorsConfig,
        *,
        factory: ConnectorFactory = create_connector,
        dispatcher: ConnectorDispatcher | None = None,
    ) -> None:
        self.config = config
        self.bind_codes = BindCodeStore(config.binding.code_ttl_seconds)
        self.dispatcher = dispatcher or ConnectorDispatcher(
            default_context_cache, config, self.bind_codes
        )
        self._factory = factory
        self.connectors: dict[str, Connector] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    async def start(self) -> None:
        if not self.config.enabled:
            return
        for instance in self.config.instances:
            if not instance.enabled:
                continue
            try:
                connector = self._factory(instance)
            except Exception:
                logger.exception(f"Connector {instance.id}: failed to create")
                continue
            self.connectors[instance.id] = connector
        if not self.connectors:
            logger.info("Connectors are enabled but no instance is enabled")
            return
        self.dispatcher.start()
        for connector_id, connector in self.connectors.items():
            self._tasks[connector_id] = asyncio.create_task(self._supervise(connector))
            logger.info(f"Connector {connector_id} ({connector.platform}) starting")

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for connector in self.connectors.values():
            try:
                await connector.close()
            except Exception:
                logger.exception(f"Connector {connector.connector_id}: close failed")
            connector.state = "stopped"
        await self.dispatcher.close()

    def statuses(self) -> list[dict]:
        return [connector.status() for connector in self.connectors.values()]

    async def _supervise(self, connector: Connector) -> None:
        delay = INITIAL_BACKOFF_SECONDS
        while True:
            started = time.monotonic()
            connector.state = "connecting"
            try:
                await connector.run(self.dispatcher.handle)
                connector.last_error = None
                logger.info(f"Connector {connector.connector_id} disconnected")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                connector.state = "error"
                connector.last_error = redact_secrets(f"{type(exc).__name__}: {exc}")
                logger.warning(
                    f"Connector {connector.connector_id} failed: {connector.last_error}"
                )
            if time.monotonic() - started >= STABLE_RUN_SECONDS:
                delay = INITIAL_BACKOFF_SECONDS
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
