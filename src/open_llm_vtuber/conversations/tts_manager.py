import asyncio
import json
import time
from typing import List, Optional, Dict
from loguru import logger

from ..agent.output_types import DisplayText, Actions
from ..live2d_model import Live2dModel
from ..tts.tts_interface import TTSInterface
from ..utils.audio import new_audio_file_stem
from ..utils.stream_audio import prepare_audio_payload
from ..utils.text import is_silent_text
from .types import WebSocketSend


TTS_SYNTHESIS_TIMEOUT_SECONDS = 30.0
TTS_DELIVERY_TIMEOUT_SECONDS = 10.0


class TTSTaskManager:
    """Manages TTS tasks and ensures ordered delivery to frontend while allowing parallel TTS generation"""

    def __init__(self) -> None:
        self.task_list: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        # Queue to store ordered payloads
        self._payload_queue: asyncio.Queue[Dict] = asyncio.Queue()
        # Task to handle sending payloads in order
        self._sender_task: Optional[asyncio.Task] = None
        # Counter for maintaining order
        self._sequence_counter = 0
        self._next_sequence_to_send = 0

    async def speak(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        audio_send: WebSocketSend,
        streamed: bool = False,
    ) -> None:
        """
        Queue a TTS task while maintaining order of delivery.

        Args:
            tts_text: Text to synthesize
            display_text: Text to display in UI
            actions: Live2D model actions
            live2d_model: Live2D model instance
            tts_engine: TTS engine instance
            audio_send: Sender for the audio channel
            streamed: Whether the display text was already sent as text deltas
        """
        self._ensure_sender(audio_send)
        current_sequence = self._next_sequence()

        if is_silent_text(tts_text):
            logger.debug("Empty TTS text, sending silent display payload")
            await self._send_silent_payload(
                display_text, actions, current_sequence, streamed
            )
            return

        logger.debug(
            f"🏃Queuing TTS task for: '''{tts_text}''' (by {display_text.name})"
        )

        # Create and queue the TTS task
        task = asyncio.create_task(
            self._process_tts(
                tts_text=tts_text,
                display_text=display_text,
                actions=actions,
                live2d_model=live2d_model,
                tts_engine=tts_engine,
                sequence_number=current_sequence,
                streamed=streamed,
            )
        )
        self.task_list.append(task)

    def _next_sequence(self) -> int:
        sequence = self._sequence_counter
        self._sequence_counter += 1
        return sequence

    def _ensure_sender(self, audio_send: WebSocketSend) -> None:
        if not self._sender_task or self._sender_task.done():
            self._sender_task = asyncio.create_task(
                self._process_payload_queue(audio_send)
            )

    async def _process_payload_queue(self, audio_send: WebSocketSend) -> None:
        """
        Process and send payloads in correct order.
        Runs continuously until all payloads are processed.
        """
        buffered_payloads: Dict[int, Dict] = {}

        while True:
            in_flight = False
            try:
                # Get payload from queue
                payload, sequence_number = await self._payload_queue.get()
                in_flight = True
                buffered_payloads[sequence_number] = payload

                # Send payloads in order
                while self._next_sequence_to_send in buffered_payloads:
                    sequence = self._next_sequence_to_send
                    next_payload = buffered_payloads.pop(sequence)
                    message = json.dumps(next_payload)
                    await audio_send(message)
                    self._next_sequence_to_send += 1
                    logger.info(
                        f"Sent TTS payload #{sequence} "
                        f"({len(message) // 1024} KB) to the client"
                    )

                self._payload_queue.task_done()
                in_flight = False

            except asyncio.CancelledError:
                if in_flight:
                    self._payload_queue.task_done()
                break

    async def _send_silent_payload(
        self,
        display_text: DisplayText,
        actions: Optional[Actions],
        sequence_number: int,
        streamed: bool = False,
    ) -> None:
        """Queue a silent audio payload"""
        audio_payload = prepare_audio_payload(
            audio_path=None,
            display_text=display_text,
            actions=actions,
            streamed=streamed,
        )
        await self._payload_queue.put((audio_payload, sequence_number))

    async def _process_tts(
        self,
        tts_text: str,
        display_text: DisplayText,
        actions: Optional[Actions],
        live2d_model: Live2dModel,
        tts_engine: TTSInterface,
        sequence_number: int,
        streamed: bool = False,
    ) -> None:
        """Process TTS generation and queue the result for ordered delivery"""
        audio_file_path = None
        started_at = time.perf_counter()
        try:
            audio_file_path = await asyncio.wait_for(
                self._generate_audio(tts_engine, tts_text),
                timeout=TTS_SYNTHESIS_TIMEOUT_SECONDS,
            )
            # Decoding/converting audio with pydub is CPU-bound and would block
            # every other connection if done on the event loop.
            payload = await asyncio.to_thread(
                prepare_audio_payload,
                audio_path=audio_file_path,
                display_text=display_text,
                actions=actions,
                streamed=streamed,
            )
            # Queue the payload with its sequence number
            await self._payload_queue.put((payload, sequence_number))
            logger.info(
                f"TTS ready in {time.perf_counter() - started_at:.2f}s "
                f"(seq #{sequence_number}): '''{tts_text[:24]}'''"
            )

        except asyncio.TimeoutError:
            logger.error(
                f"TTS synthesis timed out after {TTS_SYNTHESIS_TIMEOUT_SECONDS:.0f}s "
                f"for '''{tts_text[:24]}'''; sending a silent payload"
            )
            await self._send_silent_payload(
                display_text, actions, sequence_number, streamed
            )

        except Exception as e:
            logger.error(f"Error preparing audio payload: {e}")
            await self._send_silent_payload(
                display_text, actions, sequence_number, streamed
            )

        finally:
            if audio_file_path:
                tts_engine.remove_file(audio_file_path)
                logger.debug("Audio cache file cleaned.")

    async def _generate_audio(self, tts_engine: TTSInterface, text: str) -> str:
        """Generate audio file from text"""
        logger.debug(f"🏃Generating audio for '''{text}'''...")
        return await tts_engine.async_generate_audio(
            text=text,
            file_name_no_ext=new_audio_file_stem(),
        )

    async def wait_for_delivery(
        self, timeout: float = TTS_DELIVERY_TIMEOUT_SECONDS
    ) -> None:
        """Wait until every queued payload has been written to the client."""
        try:
            await asyncio.wait_for(self._payload_queue.join(), timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out waiting for TTS payload delivery "
                f"({self._next_sequence_to_send}/{self._sequence_counter} sent)"
            )

    def clear(self) -> None:
        """Clear all pending tasks and reset state"""
        for task in self.task_list:
            if not task.done():
                task.cancel()
        self.task_list.clear()
        if self._sender_task:
            self._sender_task.cancel()
        self._sequence_counter = 0
        self._next_sequence_to_send = 0
        # Create a new queue to clear any pending items
        self._payload_queue = asyncio.Queue()
