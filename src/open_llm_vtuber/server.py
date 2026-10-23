"""
Open-LLM-VTuber Server
========================
This module contains the WebSocket server for Open-LLM-VTuber, which handles
the WebSocket connections, serves static files, and manages the web tool.
It uses FastAPI for the server and Starlette for static file serving.
"""

import os
import shutil

from fastapi import FastAPI
from loguru import logger
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

from .auth import AuthManager, AuthRedirectMiddleware, init_auth_routes
from .routes import init_client_ws_route, init_webtool_routes, init_proxy_route
from .service_context import ServiceContext
from .config_manager.auth import AuthConfig
from .config_manager.storage import StorageConfig
from .config_manager.utils import Config
from .storage import (
    HistoryRepository,
    archive_user_histories,
    create_history_repository,
    import_legacy_histories,
)


# Create a custom StaticFiles class that adds CORS headers
class CORSStaticFiles(StarletteStaticFiles):
    """
    Static files handler that adds CORS headers to all responses.
    Needed because Starlette StaticFiles might bypass standard middleware.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)

        # Add CORS headers to all responses
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"

        if path.endswith(".js"):
            response.headers["Content-Type"] = "application/javascript"

        return response


class AvatarStaticFiles(CORSStaticFiles):
    """
    Avatar files handler with security restrictions and CORS headers
    """

    async def get_response(self, path: str, scope):
        allowed_extensions = (".jpg", ".jpeg", ".png", ".gif", ".svg")
        if not any(path.lower().endswith(ext) for ext in allowed_extensions):
            return Response("Forbidden file type", status_code=403)
        response = await super().get_response(path, scope)
        return response


class WebSocketServer:
    """
    API server for Open-LLM-VTuber. This contains the websocket endpoint for the client, hosts the web tool, and serves static files.

    Creates and configures a FastAPI app, registers all routes
    (WebSocket, web tools, proxy) and mounts static assets with CORS.

    Args:
        config (Config): Application configuration containing system settings.
        default_context_cache (ServiceContext, optional):
            Pre‑initialized service context for sessions' service context to reference to.
            **If omitted, `initialize()` method needs to be called to load service context.**

    Notes:
        - If default_context_cache is omitted, call `await initialize()` to load service context cache.
        - Use `clean_cache()` to clear and recreate the local cache directory.
    """

    def __init__(self, config: Config, default_context_cache: ServiceContext = None):
        self.app = FastAPI(title="Open-LLM-VTuber Server")  # Added title for clarity
        self.config = config
        self.default_context_cache = (
            default_context_cache or ServiceContext()
        )  # Use provided context or initialize a new empty one waiting to be loaded
        # It will be populated during the initialize method call
        self.history_repository: HistoryRepository | None = None

        self.storage_config = (
            getattr(config.system_config, "storage", None) or StorageConfig()
        )
        self.auth_config = getattr(config.system_config, "auth", None) or AuthConfig()
        self.auth = AuthManager(self.auth_config, self.storage_config.default_user_id)

        # Authentication cookies are same-origin; wildcard CORS stays
        # credential-less.
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.add_middleware(AuthRedirectMiddleware, auth=self.auth)
        self.app.add_event_handler("shutdown", self.close)

        @self.app.get("/healthz", include_in_schema=False)
        async def healthz():
            ready = self.default_context_cache.character_config is not None
            return JSONResponse(
                {"status": "ok" if ready else "starting"},
                status_code=200 if ready else 503,
            )

        self._include_routes()
        self._mount_static_files()

    def _include_routes(self) -> None:
        self.app.include_router(init_auth_routes(self.auth))
        self.app.include_router(
            init_client_ws_route(
                default_context_cache=self.default_context_cache,
                auth=self.auth,
            ),
        )
        self.app.include_router(
            init_webtool_routes(
                default_context_cache=self.default_context_cache,
                auth=self.auth,
            ),
        )

        system_config = self.config.system_config
        if hasattr(system_config, "enable_proxy") and system_config.enable_proxy:
            if self.auth.enabled:
                logger.warning(
                    "Proxy mode is disabled in OIDC mode; /proxy-ws has no "
                    "user identity"
                )
            else:
                server_url = f"ws://{system_config.host}:{system_config.port}/client-ws"
                self.app.include_router(init_proxy_route(server_url=server_url))

    def _mount_static_files(self) -> None:
        if not os.path.exists("cache"):
            os.makedirs("cache")
        self.app.mount(
            "/cache",
            CORSStaticFiles(directory="cache"),
            name="cache",
        )
        self.app.mount(
            "/live2d-models",
            CORSStaticFiles(directory="live2d-models"),
            name="live2d-models",
        )
        self.app.mount(
            "/bg",
            CORSStaticFiles(directory="backgrounds"),
            name="backgrounds",
        )
        self.app.mount(
            "/avatars",
            AvatarStaticFiles(directory="avatars"),
            name="avatars",
        )
        self.app.mount(
            "/web-tool",
            CORSStaticFiles(directory="web_tool", html=True),
            name="web_tool",
        )
        self.app.mount(
            "/",
            CORSStaticFiles(directory="frontend", html=True),
            name="frontend",
        )

    async def initialize(self):
        """Asynchronously load the service context from config.
        Calling this function is needed if default_context_cache was not provided to the constructor."""
        storage_config = self.storage_config
        repository = create_history_repository(
            backend=storage_config.backend,
            sqlite_path=storage_config.sqlite_path,
        )
        await repository.initialize()
        self.auth.repository = repository

        try:
            if storage_config.import_legacy_history:
                try:
                    await import_legacy_histories(
                        repository,
                        user_id=storage_config.default_user_id,
                        legacy_dir=storage_config.legacy_history_dir,
                        backup_dir=storage_config.legacy_backup_dir,
                    )
                except Exception:
                    logger.exception("Failed to import legacy chat history")

            if self.auth.enabled:
                if self.auth_config.archive_local_history:
                    archive = await archive_user_histories(
                        repository,
                        user_id=storage_config.default_user_id,
                        archive_dir=self.auth_config.archive_dir,
                    )
                    if archive is None:
                        logger.info("No legacy single-user histories to archive")
                # Keep the repository for new sessions, but never bind the
                # local account to a session while OIDC is enabled.
                self.default_context_cache.set_history_storage(repository, None)
            else:
                await repository.ensure_user(
                    storage_config.default_user_id,
                    display_name="Local User",
                )
                self.default_context_cache.set_history_storage(
                    repository,
                    storage_config.default_user_id,
                )

            self.history_repository = repository
            await self.default_context_cache.load_from_config(self.config)
        except Exception:
            await repository.close()
            self.history_repository = None
            self.auth.repository = None
            self.default_context_cache.set_history_storage(None, None)
            raise

    async def close(self):
        """Close shared resources."""
        await self.default_context_cache.close()
        await self.auth.close()
        if self.history_repository is not None:
            await self.history_repository.close()
            self.history_repository = None

    @staticmethod
    def clean_cache():
        """Clean the cache directory by removing and recreating it."""
        cache_dir = "cache"
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            os.makedirs(cache_dir)
