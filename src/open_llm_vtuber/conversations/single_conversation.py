from typing import Any
import asyncio
import json
from loguru import logger
import numpy as np

from .conversation_utils import (
    bind_turn_history,
    run_agent_turn,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    new_session_emoji,
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
    session_emoji: str | None = None,
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
    session_emoji = session_emoji or new_session_emoji()
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager(cache_scope=getattr(context, "user_id", None))
    full_response = ""

    try:
        turn_history_uid = bind_turn_history(context, metadata)

        # Send initial signals
        await send_conversation_start_signals(channels.text)
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input
        input_text = await process_user_input(
            user_input, context.asr_engine, channels.text
        )

        full_response = await run_agent_turn(
            context,
            channels=channels,
            tts_manager=tts_manager,
            input_text=input_text,
            turn_history_uid=turn_history_uid,
            images=images,
            metadata=metadata,
        )

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
