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
from .config_manager import validate_config
from .service_context import ServiceContext, deep_merge
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


LIVE2D_PROMPT = "live2d_expression_prompt"


async def build_connector_base_context(
    default_context_cache: ServiceContext,
    *,
    character: dict,
    tool_prompts: dict[str, str] | None,
) -> ServiceContext:
    """Create the shared, text-only base context of one connector.

    ``character`` is a partial character_config merged over the default
    character; ``tool_prompts`` replaces the system tool prompts (None keeps
    them minus the Live2D expression prompt). Sessions of the connector are
    then cloned from this context with ``build_session_context``.
    """
    system_config = default_context_cache.system_config
    if tool_prompts is None:
        tool_prompts = {
            name: path
            for name, path in system_config.tool_prompts.items()
            if name != LIVE2D_PROMPT
        }
    character_data = deep_merge(
        default_context_cache.character_config.model_dump(by_alias=True),
        character or {},
    )
    config = validate_config(
        {
            "system_config": {
                **system_config.model_dump(by_alias=True),
                "tool_prompts": dict(tool_prompts),
            },
            "character_config": character_data,
        }
    )

    context = ServiceContext()
    # The repository is shared; the base context itself is never bound to a
    # user and never stores history.
    context.set_history_storage(default_context_cache.history_repository, None)
    await context.load_headless(config)
    return context


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
    user_emails: tuple[str, ...] = ()
    if repository is not None:
        await repository.ensure_user(identity.user_id, identity.display_name)
        profile = await repository.get_user_profile(user_id=identity.user_id)
        if isinstance(profile, dict):
            user_emails = tuple(profile.get("emails") or ())

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
        user_emails=user_emails,
    )
    # Each session needs its own agent state; the LLM client stays shared.
    await session_service_context.init_session_agent(default_context_cache.agent_engine)
    return session_service_context
