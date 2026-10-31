from typing import Any
import asyncio
import json
from loguru import logger
import numpy as np

from .conversation_utils import (
    consume_agent_stream,
    create_batch_input,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    should_store_history,
    EMOJI_LIST,
)
from .types import OutboundChannels
from .tts_manager import TTSTaskManager
from ..service_context import ServiceContext


async def process_single_conversation(
    context: ServiceContext,
    channels: OutboundChannels,
    client_uid: str,
    user_input: str | np.ndarray,
    images: list[dict[str, Any]] | None = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: dict[str, Any] | None = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        channels: Text and audio senders for this client
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager(cache_scope=getattr(context, "user_id", None))
    full_response = ""

    try:
        # Bind the whole turn to the history that was active when it started.
        # Opening another history mid-turn must not reroute these writes.
        skip_history = bool(metadata and metadata.get("skip_history", False))
        turn_history_uid = (
            context.history_uid if should_store_history(context, skip_history) else None
        )
        context.turn_history_uid = turn_history_uid
        context.turn_response_persisted = False

        # Send initial signals
        await send_conversation_start_signals(channels.text)
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input
        input_text = await process_user_input(
            user_input, context.asr_engine, channels.text
        )

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        if turn_history_uid:
            await context.store_history_message(
                role="human",
                content=input_text,
                name=context.character_config.human_name,
                history_uid=turn_history_uid,
            )
        elif skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        full_response = await consume_agent_stream(
            context.agent_engine.chat(batch_input),
            context=context,
            channels=channels,
            tts_manager=tts_manager,
            send_text_delta=lambda message: channels.text(json.dumps(message)),
            error_prefix="Error processing agent response",
        )

        # Persist the reply as soon as it is generated. Waiting for playback
        # completion would leave the turn vulnerable to a concurrent history
        # switch (the reply could be written to the wrong history or lost).
        if full_response and turn_history_uid:
            await context.store_history_message(
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
                history_uid=turn_history_uid,
            )
            context.turn_response_persisted = True
            logger.info(f"AI response: {full_response}")

        # finalize_conversation_turn waits for TTS tasks and sends the single
        # backend-synth-complete signal.
        await finalize_conversation_turn(
            tts_manager=tts_manager,
            channels=channels,
            client_uid=client_uid,
        )

        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.error(f"Error in conversation chain: {e}")
        await channels.text(
            json.dumps({"type": "error", "message": f"Conversation error: {e!s}"})
        )
        raise
    finally:
        cleanup_conversation(tts_manager, session_emoji)
