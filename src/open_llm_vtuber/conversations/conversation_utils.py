import asyncio
import re
from typing import Awaitable, Callable, Optional, Union, Any, List, Dict
import numpy as np
import json
from loguru import logger

from ..message_handler import message_handler
from .types import WebSocketSend, BroadcastContext
from .tts_manager import TTSTaskManager
from ..agent.output_types import SentenceOutput, AudioOutput
from ..agent.input_types import BatchInput, TextData, ImageData, TextSource, ImageSource
from ..asr.asr_interface import ASRInterface
from ..live2d_model import Live2dModel
from ..tts.tts_interface import TTSInterface
from ..utils.stream_audio import prepare_audio_payload


PLAYBACK_COMPLETE_TIMEOUT_SECONDS = 120.0


class TextDeltaBuffer:
    """Coalesces streamed text and pushes it to the client at a fixed cadence."""

    def __init__(
        self,
        send: Callable[[Dict[str, Any]], Awaitable[None]],
        character_name: str,
        avatar: Optional[str] = None,
        interval: float = 0.05,
    ) -> None:
        self._send = send
        self._character_name = character_name
        self._avatar = avatar
        self._interval = interval
        self._pending = ""
        self._full_text = ""
        self._last_sent = 0.0
        self._timer: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def push(self, text: str) -> None:
        if not text or self._closed:
            return

        async with self._lock:
            self._pending += text
            self._full_text += text
            now = asyncio.get_running_loop().time()
            if now - self._last_sent >= self._interval:
                await self._flush_locked()
            elif self._timer is None or self._timer.done():
                self._timer = asyncio.create_task(self._flush_after_interval())

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def close(self) -> None:
        async with self._lock:
            await self._flush_locked()
            self._closed = True
            if self._timer and not self._timer.done():
                self._timer.cancel()
            self._timer = None

    def cancel(self) -> None:
        self._closed = True
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    async def _flush_after_interval(self) -> None:
        try:
            await asyncio.sleep(self._interval)
            await self.flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error sending text delta: {e}")

    async def _flush_locked(self) -> None:
        if self._timer and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None

        if not self._pending:
            return

        delta = self._pending
        self._pending = ""
        self._last_sent = asyncio.get_running_loop().time()

        await self._send(
            {
                "type": "text-delta",
                "text": delta,
                "full_text": self._full_text,
                "name": self._character_name,
                "avatar": self._avatar,
            }
        )


# Convert class methods to standalone functions
def create_batch_input(
    input_text: str,
    images: Optional[List[Dict[str, Any]]],
    from_name: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> BatchInput:
    """Create batch input for agent processing"""
    return BatchInput(
        texts=[
            TextData(source=TextSource.INPUT, content=input_text, from_name=from_name)
        ],
        images=[
            ImageData(
                source=ImageSource(img["source"]),
                data=img["data"],
                mime_type=img["mime_type"],
            )
            for img in (images or [])
        ]
        if images
        else None,
        metadata=metadata,
    )


async def process_agent_output(
    output: Union[AudioOutput, SentenceOutput],
    character_config: Any,
    live2d_model: Live2dModel,
    tts_engine: TTSInterface,
    websocket_send: WebSocketSend,
    tts_manager: TTSTaskManager,
    translate_engine: Optional[Any] = None,
    streamed: bool = False,
) -> str:
    """Process agent output with character information and optional translation"""
    output.display_text.name = character_config.character_name
    output.display_text.avatar = character_config.avatar

    full_response = ""
    try:
        if isinstance(output, SentenceOutput):
            full_response = await handle_sentence_output(
                output,
                live2d_model,
                tts_engine,
                websocket_send,
                tts_manager,
                translate_engine,
                streamed,
            )
        elif isinstance(output, AudioOutput):
            full_response = await handle_audio_output(output, websocket_send)
        else:
            logger.warning(f"Unknown output type: {type(output)}")
    except Exception as e:
        logger.error(f"Error processing agent output: {e}")
        await websocket_send(
            json.dumps(
                {"type": "error", "message": f"Error processing response: {str(e)}"}
            )
        )

    return full_response


async def handle_sentence_output(
    output: SentenceOutput,
    live2d_model: Live2dModel,
    tts_engine: TTSInterface,
    websocket_send: WebSocketSend,
    tts_manager: TTSTaskManager,
    translate_engine: Optional[Any] = None,
    streamed: bool = False,
) -> str:
    """Handle sentence output type with optional translation support"""
    full_response = ""
    async for display_text, tts_text, actions in output:
        logger.debug(f"🏃 Processing output: '''{tts_text}'''...")

        if translate_engine:
            if len(re.sub(r'[\s.,!?，。！？\'"』」）】\s]+', "", tts_text)):
                tts_text = translate_engine.translate(tts_text)
            logger.info(f"🏃 Text after translation: '''{tts_text}'''...")
        else:
            logger.debug("🚫 No translation engine available. Skipping translation.")

        full_response += display_text.text
        await tts_manager.speak(
            tts_text=tts_text,
            display_text=display_text,
            actions=actions,
            live2d_model=live2d_model,
            tts_engine=tts_engine,
            websocket_send=websocket_send,
            streamed=streamed,
        )
    return full_response


async def handle_audio_output(
    output: AudioOutput,
    websocket_send: WebSocketSend,
) -> str:
    """Process and send AudioOutput directly to the client"""
    full_response = ""
    async for audio_path, display_text, transcript, actions in output:
        full_response += transcript
        audio_payload = await asyncio.to_thread(
            prepare_audio_payload,
            audio_path=audio_path,
            display_text=display_text,
            actions=actions.to_dict() if actions else None,
        )
        await websocket_send(json.dumps(audio_payload))
    return full_response


async def send_conversation_start_signals(websocket_send: WebSocketSend) -> None:
    """Send initial conversation signals"""
    await websocket_send(
        json.dumps(
            {
                "type": "control",
                "text": "conversation-chain-start",
            }
        )
    )
    await websocket_send(json.dumps({"type": "full-text", "text": "Thinking..."}))


async def process_user_input(
    user_input: Union[str, np.ndarray],
    asr_engine: ASRInterface,
    websocket_send: WebSocketSend,
) -> str:
    """Process user input, converting audio to text if needed"""
    if isinstance(user_input, np.ndarray):
        logger.info("Transcribing audio input...")
        input_text = await asr_engine.async_transcribe_np(user_input)
        await websocket_send(
            json.dumps({"type": "user-input-transcription", "text": input_text})
        )
        return input_text
    return user_input


async def finalize_conversation_turn(
    tts_manager: TTSTaskManager,
    websocket_send: WebSocketSend,
    client_uid: str,
    broadcast_ctx: Optional[BroadcastContext] = None,
) -> None:
    """Finalize a conversation turn"""
    if tts_manager.task_list:
        await asyncio.gather(*tts_manager.task_list)
        await websocket_send(json.dumps({"type": "backend-synth-complete"}))

        response = await message_handler.wait_for_response(
            client_uid,
            "frontend-playback-complete",
            timeout=PLAYBACK_COMPLETE_TIMEOUT_SECONDS,
        )

        if not response:
            logger.warning(
                f"No playback completion response from {client_uid} "
                f"within {PLAYBACK_COMPLETE_TIMEOUT_SECONDS:.0f}s"
            )

    await websocket_send(json.dumps({"type": "force-new-message"}))

    if broadcast_ctx and broadcast_ctx.broadcast_func:
        await broadcast_ctx.broadcast_func(
            broadcast_ctx.group_members,
            {"type": "force-new-message"},
            broadcast_ctx.current_client_uid,
        )

    await send_conversation_end_signal(websocket_send, broadcast_ctx)


async def send_conversation_end_signal(
    websocket_send: WebSocketSend,
    broadcast_ctx: Optional[BroadcastContext],
    session_emoji: str = "😊",
) -> None:
    """Send conversation chain end signal"""
    chain_end_msg = {
        "type": "control",
        "text": "conversation-chain-end",
    }

    await websocket_send(json.dumps(chain_end_msg))

    if broadcast_ctx and broadcast_ctx.broadcast_func and broadcast_ctx.group_members:
        await broadcast_ctx.broadcast_func(
            broadcast_ctx.group_members,
            chain_end_msg,
        )

    logger.info(f"😎👍✅ Conversation Chain {session_emoji} completed!")


def cleanup_conversation(tts_manager: TTSTaskManager, session_emoji: str) -> None:
    """Clean up conversation resources"""
    tts_manager.clear()
    logger.debug(f"🧹 Clearing up conversation {session_emoji}.")


EMOJI_LIST = [
    "🐶",
    "🐱",
    "🐭",
    "🐹",
    "🐰",
    "🦊",
    "🐻",
    "🐼",
    "🐨",
    "🐯",
    "🦁",
    "🐮",
    "🐷",
    "🐸",
    "🐵",
    "🐔",
    "🐧",
    "🐦",
    "🐤",
    "🐣",
    "🐥",
    "🦆",
    "🦅",
    "🦉",
    "🦇",
    "🐺",
    "🐗",
    "🐴",
    "🦄",
    "🐝",
    "🌵",
    "🎄",
    "🌲",
    "🌳",
    "🌴",
    "🌱",
    "🌿",
    "☘️",
    "🍀",
    "🍂",
    "🍁",
    "🍄",
    "🌾",
    "💐",
    "🌹",
    "🌸",
    "🌛",
    "🌍",
    "⭐️",
    "🔥",
    "🌈",
    "🌩",
    "⛄️",
    "🎃",
    "🎄",
    "🎉",
    "🎏",
    "🎗",
    "🀄️",
    "🎭",
    "🎨",
    "🧵",
    "🪡",
    "🧶",
    "🥽",
    "🥼",
    "🦺",
    "👔",
    "👕",
    "👜",
    "👑",
]
