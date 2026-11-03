"""Build per-session service contexts from the shared default context.

Browser WebSocket sessions and message-connector sessions start the same way:
clone the default context's configs, share its engines by reference, bind the
verified user, load that user's MCP servers and give the session its own agent
state. Keeping it in one place means both entry points enforce the same
user scoping.
"""

from loguru import logger

from .auth import Identity
from .conversations.types import OutboundChannels
from .mcpp.user_servers import split_user_mcp_servers
from .service_context import ServiceContext
from .storage import HistoryRepository


async def load_user_mcp_servers(
    repository: HistoryRepository | None,
    user_id: str,
) -> tuple[list[dict], list[dict]]:
    """Split this user's enabled MCP rows into remote and browser-local."""
    if repository is None:
        return [], []
    try:
        return split_user_mcp_servers(
            await repository.list_user_mcp_servers(user_id=user_id)
        )
    except Exception:
        logger.exception("Failed to load per-user MCP servers")
        return [], []


async def build_session_context(
    default_context_cache: ServiceContext,
    *,
    channels: OutboundChannels | None,
    client_uid: str,
    identity: Identity,
    include_local_mcp: bool = True,
) -> ServiceContext:
    """Create a session context bound to ``identity``.

    ``include_local_mcp=False`` is for sessions without a browser: local MCP
    servers are reached through the page, so they cannot serve such a session.
    """
    repository = default_context_cache.history_repository
    if repository is not None:
        await repository.ensure_user(identity.user_id, identity.display_name)

    remote_mcp_servers, local_mcp_servers = await load_user_mcp_servers(
        repository, identity.user_id
    )
    if not include_local_mcp:
        local_mcp_servers = []

    session_service_context = ServiceContext()
    await session_service_context.load_cache(
        config=default_context_cache.config.model_copy(deep=True),
        system_config=default_context_cache.system_config.model_copy(deep=True),
        character_config=default_context_cache.character_config.model_copy(deep=True),
        live2d_model=default_context_cache.live2d_model,
        asr_engine=default_context_cache.asr_engine,
        tts_engine=default_context_cache.tts_engine,
        agent_engine=default_context_cache.agent_engine,
        translate_engine=default_context_cache.translate_engine,
        mcp_server_registry=default_context_cache.mcp_server_registry,
        tool_adapter=default_context_cache.tool_adapter,
        channels=channels,
        client_uid=client_uid,
        history_repository=repository,
        user_id=identity.user_id,
        user_display_name=identity.display_name,
        user_mcp_servers=remote_mcp_servers,
        local_mcp_servers=local_mcp_servers,
    )
    # Each session needs its own agent state; the LLM client stays shared.
    await session_service_context.init_session_agent(default_context_cache.agent_engine)
    return session_service_context
