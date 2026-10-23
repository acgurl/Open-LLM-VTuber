import asyncio
import json
from typing import Dict, Optional, Callable

import numpy as np
from fastapi import WebSocket
from loguru import logger

from ..chat_group import ChatGroupManager
from ..service_context import ServiceContext
from ..utils.async_utils import cancel_and_wait
from .group_conversation import process_group_conversation
from .single_conversation import process_single_conversation
from .conversation_utils import EMOJI_LIST
from .types import GroupConversationState, OutboundChannels
from prompts import prompt_loader


MAX_CONCURRENT_CONVERSATIONS = 16


def _active_task_count(tasks: Dict[str, Optional[asyncio.Task]]) -> int:
    return sum(1 for task in tasks.values() if task and not task.done())


async def _reject_if_at_capacity(
    websocket: WebSocket,
    tasks: Dict[str, Optional[asyncio.Task]],
) -> bool:
    if _active_task_count(tasks) < MAX_CONCURRENT_CONVERSATIONS:
        return False

    await websocket.send_text(
        json.dumps(
            {
                "type": "error",
                "message": "Server is busy, please try again shortly",
            }
        )
    )
    return True


async def _cancel_previous_task(
    tasks: Dict[str, Optional[asyncio.Task]], task_key: str
) -> None:
    previous = tasks.get(task_key)
    await cancel_and_wait(
        previous, failure_message=f"Conversation task {task_key} failed"
    )


def _track_task(
    tasks: Dict[str, Optional[asyncio.Task]], task_key: str, task: asyncio.Task
) -> None:
    tasks[task_key] = task

    def _on_done(done_task: asyncio.Task) -> None:
        if not done_task.cancelled():
            error = done_task.exception()
            if error is not None:
                logger.error(
                    f"Conversation task {task_key} raised {type(error).__name__}"
                )
        if tasks.get(task_key) is done_task:
            tasks.pop(task_key, None)

    task.add_done_callback(_on_done)


def _load_proactive_prompt(context: ServiceContext) -> str:
    try:
        prompt_file = context.system_config.tool_prompts.get("proactive_speak_prompt")
        if prompt_file:
            return prompt_loader.load_util(prompt_file)
        logger.warning("Proactive speak prompt not configured, using default")
    except Exception as e:
        logger.error(f"Error loading proactive speak prompt: {e}")
    return "Please say something."


async def _prepare_proactive_speak(
    context: ServiceContext, websocket: WebSocket
) -> tuple[str, dict]:
    user_input = _load_proactive_prompt(context)
    await websocket.send_text(
        json.dumps({"type": "full-text", "text": "AI wants to speak something..."})
    )
    metadata = {
        "proactive_speak": True,
        "skip_memory": True,
        "skip_history": True,
    }
    return user_input, metadata


async def handle_conversation_trigger(
    msg_type: str,
    data: dict,
    client_uid: str,
    context: ServiceContext,
    websocket: WebSocket,
    client_contexts: Dict[str, ServiceContext],
    client_connections: Dict[str, WebSocket],
    chat_group_manager: ChatGroupManager,
    received_data_buffers: Dict[str, np.ndarray],
    current_conversation_tasks: Dict[str, Optional[asyncio.Task]],
    broadcast_to_group: Callable,
) -> None:
    """Handle triggers that start a conversation"""
    metadata = None

    if msg_type == "ai-speak-signal":
        user_input, metadata = await _prepare_proactive_speak(context, websocket)
    elif msg_type == "text-input":
        user_input = data.get("text", "")
    else:  # mic-audio-end
        user_input = received_data_buffers[client_uid]
        received_data_buffers[client_uid] = np.array([])

    images = data.get("images")
    session_emoji = np.random.choice(EMOJI_LIST)

    group = chat_group_manager.get_client_group(client_uid)
    if group and len(group.members) > 1:
        # Use group_id as task key for group conversations
        task_key = group.group_id
        if (
            task_key not in current_conversation_tasks
            or current_conversation_tasks[task_key].done()
        ):
            if await _reject_if_at_capacity(websocket, current_conversation_tasks):
                return

            logger.info(f"Starting new group conversation for {task_key}")

            task = asyncio.create_task(
                process_group_conversation(
                    client_contexts=client_contexts,
                    client_connections=client_connections,
                    broadcast_func=broadcast_to_group,
                    group_members=group.members,
                    initiator_client_uid=client_uid,
                    group_id=group.group_id,
                    user_input=user_input,
                    images=images,
                    session_emoji=session_emoji,
                    metadata=metadata,
                )
            )
            _track_task(current_conversation_tasks, task_key, task)
    else:
        # A client may submit another message before the previous stream ends.
        # Cancel the old turn so two tasks cannot mutate the same agent/history.
        await _cancel_previous_task(current_conversation_tasks, client_uid)

        if await _reject_if_at_capacity(websocket, current_conversation_tasks):
            return

        channels = context.channels or OutboundChannels.from_text(websocket.send_text)
        task = asyncio.create_task(
            process_single_conversation(
                context=context,
                channels=channels,
                client_uid=client_uid,
                user_input=user_input,
                images=images,
                session_emoji=session_emoji,
                metadata=metadata,
            )
        )
        _track_task(current_conversation_tasks, client_uid, task)


async def handle_individual_interrupt(
    client_uid: str,
    current_conversation_tasks: Dict[str, Optional[asyncio.Task]],
    context: ServiceContext,
    heard_response: str,
):
    if client_uid in current_conversation_tasks:
        task = current_conversation_tasks[client_uid]
        if task and not task.done():
            task.cancel()
            logger.info("🛑 Conversation task was successfully interrupted")

        try:
            context.agent_engine.handle_interrupt(heard_response)
        except Exception as e:
            logger.error(f"Error handling interrupt: {e}")

        if context.history_uid and heard_response:
            await context.store_history_message(
                role="ai",
                content=heard_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            await context.store_history_message(
                role="system",
                content="[Interrupted by user]",
            )


async def handle_group_interrupt(
    group_id: str,
    heard_response: str,
    current_conversation_tasks: Dict[str, Optional[asyncio.Task]],
    chat_group_manager: ChatGroupManager,
    client_contexts: Dict[str, ServiceContext],
    broadcast_to_group: Callable,
) -> None:
    """Handles interruption for a group conversation"""
    task = current_conversation_tasks.get(group_id)
    if not task or task.done():
        return

    # Get state and speaker info before cancellation
    state = GroupConversationState.get_state(group_id)
    current_speaker_uid = state.current_speaker_uid if state else None

    # Get context from current speaker
    context = None
    group = chat_group_manager.get_group_by_id(group_id)
    if current_speaker_uid:
        context = client_contexts.get(current_speaker_uid)
        logger.info(f"Found current speaker context for {current_speaker_uid}")
    if not context and group and group.members:
        logger.warning(f"No context found for group {group_id}, using first member")
        context = client_contexts.get(next(iter(group.members)))

    # Now cancel the task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info(f"🛑 Group conversation {group_id} cancelled successfully.")

    current_conversation_tasks.pop(group_id, None)
    GroupConversationState.remove_state(group_id)  # Clean up state after we've used it

    # Store messages with speaker info
    if context and group and heard_response:
        for member_uid in group.members:
            if member_uid in client_contexts:
                try:
                    member_ctx = client_contexts[member_uid]
                    member_ctx.agent_engine.handle_interrupt(heard_response)
                    await member_ctx.store_history_message(
                        role="ai",
                        content=heard_response,
                        name=context.character_config.character_name,
                        avatar=context.character_config.avatar,
                    )
                    await member_ctx.store_history_message(
                        role="system",
                        content="[Interrupted by user]",
                    )
                except Exception as e:
                    logger.error(f"Error handling interrupt for {member_uid}: {e}")

    await broadcast_to_group(
        list(group.members),
        {
            "type": "interrupt-signal",
            "text": "conversation-interrupted",
        },
    )
