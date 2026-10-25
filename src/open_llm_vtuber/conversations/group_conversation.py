from typing import Any, Dict, List, Optional, Union
import asyncio
import json
from loguru import logger
from fastapi import WebSocket
import numpy as np

from .conversation_utils import (
    consume_agent_stream,
    create_batch_input,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    should_store_history,
    EMOJI_LIST,
)
from .types import (
    BroadcastFunc,
    GroupConversationState,
    BroadcastContext,
    OutboundChannels,
    WebSocketSend,
)
from ..service_context import ServiceContext
from .tts_manager import TTSTaskManager


async def process_group_conversation(
    client_contexts: Dict[str, ServiceContext],
    client_connections: Dict[str, WebSocket],
    broadcast_func: BroadcastFunc,
    group_members: List[str],
    initiator_client_uid: str,
    group_id: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Process group conversation

    Args:
        client_contexts: Dictionary of client contexts
        client_connections: Dictionary of client WebSocket connections
        broadcast_func: Function to broadcast messages to group
        group_members: List of group member UIDs
        initiator_client_uid: UID of conversation initiator
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags
    """
    # Create TTSTaskManager for each member
    tts_managers = {uid: TTSTaskManager() for uid in group_members}

    try:
        logger.info(f"Group Conversation Chain {session_emoji} started!")

        # Initialize state with group_id
        state = GroupConversationState(
            group_id=group_id,
            session_emoji=session_emoji,
            group_queue=list(group_members),
            memory_index={
                uid: 0 for uid in group_members
            },  # Initialize memory index for each member
        )

        # Initialize group conversation context for each AI
        init_group_conversation_contexts(client_contexts, group_members)

        # Get human name from initiator context
        initiator_context = client_contexts.get(initiator_client_uid)
        human_name = (
            initiator_context.character_config.human_name
            if initiator_context
            else "Human"
        )

        # Process initial input
        input_text = await process_group_input(
            user_input=user_input,
            initiator_context=initiator_context,
            initiator_ws_send=client_connections[initiator_client_uid].send_text,
            broadcast_func=broadcast_func,
            group_members=group_members,
            initiator_client_uid=initiator_client_uid,
        )

        # Check if we should skip storing this input to history
        skip_history = metadata and metadata.get("skip_history", False)

        for member_uid in group_members:
            member_context = client_contexts[member_uid]
            if should_store_history(member_context, skip_history):
                await member_context.store_history_message(
                    role="human",
                    content=input_text,
                    name=human_name,
                )
        if skip_history:
            logger.debug("Skipping storing proactive speak input to group history")

        state.conversation_history = [f"{human_name}: {input_text}"]

        is_first_responder = True
        # Main conversation loop
        while state.group_queue:
            try:
                current_member_uid = state.group_queue.pop(0)

                # Only pass metadata to the first responder
                current_metadata = None
                if is_first_responder:
                    current_metadata = metadata
                    is_first_responder = False

                await handle_group_member_turn(
                    current_member_uid=current_member_uid,
                    state=state,
                    client_contexts=client_contexts,
                    client_connections=client_connections,
                    broadcast_func=broadcast_func,
                    group_members=group_members,
                    images=images,
                    tts_manager=tts_managers[current_member_uid],
                    metadata=current_metadata,
                    skip_history=bool(skip_history),
                )
            except Exception as e:
                logger.error(f"Error in group member turn: {e}")
                await handle_member_error(
                    broadcast_func, group_members, f"Error in conversation: {str(e)}"
                )

    except asyncio.CancelledError:
        logger.info(
            f"🤡👍 Group Conversation {session_emoji} cancelled because interrupted."
        )
        raise
    except Exception as e:
        logger.error(f"Error in group conversation chain: {e}")
        await handle_member_error(
            broadcast_func, group_members, f"Fatal error in conversation: {str(e)}"
        )
        raise
    finally:
        # Cleanup all TTS managers
        for tts_manager in tts_managers.values():
            cleanup_conversation(tts_manager, session_emoji)
        # Clean up
        GroupConversationState.remove_state(state.group_id)


def init_group_conversation_contexts(
    client_contexts: Dict[str, ServiceContext],
    group_members: List[str],
) -> None:
    """Initialize group conversation context for each AI participant"""
    member_contexts = [
        client_contexts[uid] for uid in group_members if uid in client_contexts
    ]
    ai_names = [ctx.character_config.character_name for ctx in member_contexts]

    for context in member_contexts:
        agent = context.agent_engine
        if hasattr(agent, "start_group_conversation"):
            agent.start_group_conversation(
                human_name="Human",
                ai_participants=[
                    name
                    for name in ai_names
                    if name != context.character_config.character_name
                ],
            )
            logger.debug(
                f"Initialized group conversation context for "
                f"{context.character_config.character_name}"
            )


async def process_group_input(
    user_input: Union[str, np.ndarray],
    initiator_context: ServiceContext,
    initiator_ws_send: WebSocketSend,
    broadcast_func: BroadcastFunc,
    group_members: List[str],
    initiator_client_uid: str,
) -> str:
    """Process and broadcast user input to group"""
    input_text = await process_user_input(
        user_input, initiator_context.asr_engine, initiator_ws_send
    )
    await broadcast_transcription(
        broadcast_func, group_members, input_text, initiator_client_uid
    )
    return input_text


async def broadcast_transcription(
    broadcast_func: BroadcastFunc,
    group_members: List[str],
    text: str,
    exclude_uid: str,
) -> None:
    """Broadcast transcription to group members"""
    await broadcast_func(
        group_members,
        {
            "type": "user-input-transcription",
            "text": text,
        },
        exclude_uid,
    )


async def handle_group_member_turn(
    current_member_uid: str,
    state: GroupConversationState,
    client_contexts: Dict[str, ServiceContext],
    client_connections: Dict[str, WebSocket],
    broadcast_func: BroadcastFunc,
    group_members: List[str],
    images: Optional[List[Dict[str, Any]]],
    tts_manager: TTSTaskManager,
    metadata: Optional[Dict[str, Any]] = None,
    skip_history: bool = False,
) -> None:
    """Handle a single group member's conversation turn"""
    # Update current speaker before processing
    state.current_speaker_uid = current_member_uid

    await broadcast_thinking_state(broadcast_func, group_members)

    context = client_contexts[current_member_uid]
    current_ws_send = client_connections[current_member_uid].send_text
    channels = context.channels or OutboundChannels.from_text(current_ws_send)

    new_messages = state.conversation_history[state.memory_index[current_member_uid] :]
    new_context = "\n".join(new_messages) if new_messages else ""

    batch_input = create_batch_input(
        input_text=new_context,
        images=images,
        from_name="Human",
        metadata=metadata,
    )

    logger.info(
        f"AI {context.character_config.character_name} "
        f"(client {current_member_uid}) receiving context:\n{new_context}"
    )

    full_response = await process_member_response(
        context=context,
        batch_input=batch_input,
        channels=channels,
        tts_manager=tts_manager,
        broadcast_func=broadcast_func,
        group_members=group_members,
    )

    if tts_manager.task_list:
        broadcast_ctx = BroadcastContext(
            broadcast_func=broadcast_func,
            group_members=group_members,
            current_client_uid=current_member_uid,
        )

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            channels=channels,
            client_uid=current_member_uid,
            broadcast_ctx=broadcast_ctx,
        )

    if full_response:
        ai_message = f"{context.character_config.character_name}: {full_response}"
        state.conversation_history.append(ai_message)
        logger.info(f"Appended complete response: {ai_message}")

        should_skip_history = skip_history or bool(
            metadata and metadata.get("skip_history", False)
        )
        for member_uid in group_members:
            member_context = client_contexts[member_uid]
            if should_store_history(member_context, should_skip_history):
                await member_context.store_history_message(
                    role="ai",
                    content=full_response,
                    name=context.character_config.character_name,
                    avatar=context.character_config.avatar,
                )

    state.memory_index[current_member_uid] = len(state.conversation_history)
    state.group_queue.append(current_member_uid)

    # Clear speaker after turn completes
    state.current_speaker_uid = None


async def broadcast_thinking_state(
    broadcast_func: BroadcastFunc, group_members: List[str]
) -> None:
    """Broadcast thinking state to group"""
    await broadcast_func(
        group_members,
        {"type": "control", "text": "conversation-chain-start"},
    )
    await broadcast_func(
        group_members,
        {"type": "full-text", "text": "Thinking..."},
    )


async def handle_member_error(
    broadcast_func: BroadcastFunc,
    group_members: List[str],
    error_message: str,
) -> None:
    """Handle and broadcast member error"""
    await broadcast_func(
        group_members,
        {
            "type": "error",
            "message": error_message,
        },
    )


async def process_member_response(
    context: ServiceContext,
    batch_input: Any,
    channels: OutboundChannels,
    tts_manager: TTSTaskManager,
    broadcast_func: Optional[BroadcastFunc] = None,
    group_members: Optional[List[str]] = None,
) -> str:
    """Process group member's response, handling text/audio and tool status events."""

    async def send_text_delta(message: Dict[str, Any]) -> None:
        if message.get("type") == "tool_call_status" and message.get("scoped"):
            # User/browser-scoped MCP tools may expose personal files or
            # credentials in their input/results; keep them on the owner's
            # socket instead of broadcasting to the group.
            await channels.text(json.dumps(message, ensure_ascii=False))
            return
        if broadcast_func and group_members:
            await broadcast_func(group_members, message)

    return await consume_agent_stream(
        context.agent_engine.chat(batch_input),
        context=context,
        channels=channels,
        tts_manager=tts_manager,
        send_text_delta=send_text_delta,
    )
