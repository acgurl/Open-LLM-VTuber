from typing import Dict, List, Optional, Callable, TypedDict
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import json
import numpy as np
from loguru import logger

from .auth import AuthManager, Identity
from .service_context import ServiceContext
from .chat_group import (
    ChatGroupManager,
    handle_group_operation,
    handle_client_disconnect,
    broadcast_to_group,
)
from .message_handler import message_handler
from .utils.async_utils import cancel_and_wait
from .utils.stream_audio import prepare_audio_payload
from .utils.audio import MAX_AUDIO_SAMPLES
from .config_manager.utils import scan_config_alts_directory, scan_bg_directory
from .storage import HistoryNotFoundError, HistoryRepository
from .mcpp.user_servers import split_user_mcp_servers, validate_server_id
from .conversations.conversation_handler import (
    handle_conversation_trigger,
    handle_group_interrupt,
    handle_individual_interrupt,
)
from .conversations.types import OutboundChannels


MAX_WS_CONNECTIONS = 64
MAX_TEXT_INPUT_CHARS = 4000
MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_DATA_CHARS = 8 * 1024 * 1024
IMAGE_SOURCES = {"camera", "screen", "shared", "clipboard", "upload"}
MAX_LOCAL_MCP_PAYLOAD_CHARS = 256 * 1024


class WSMessage(TypedDict, total=False):
    """Type definition for WebSocket messages"""

    type: str
    action: Optional[str]
    text: Optional[str]
    audio: Optional[List[float]]
    images: Optional[List[str]]
    history_uid: Optional[str]
    file: Optional[str]
    display_text: Optional[dict]


class WebSocketHandler:
    """Handles WebSocket connections and message routing"""

    def __init__(
        self,
        default_context_cache: ServiceContext,
        auth_manager: AuthManager | None = None,
        max_connections_per_user: int = 4,
    ):
        """Initialize the WebSocket handler with default context"""
        self.default_context_cache = default_context_cache
        self.auth_manager = auth_manager
        self.max_connections_per_user = max_connections_per_user
        self.client_connections: Dict[str, WebSocket] = {}
        # Audio gets its own socket so large TTS payloads cannot block text deltas.
        self.client_audio_connections: Dict[str, WebSocket] = {}
        self.client_contexts: Dict[str, ServiceContext] = {}
        self.client_users: Dict[str, str] = {}
        # Slots are reserved before the expensive per-session initialization so a
        # burst of connections cannot spawn unbounded MCP processes.
        self._pending_connections: set[str] = set()
        self._pending_user_ids: Dict[str, str] = {}
        self.chat_group_manager = ChatGroupManager()
        self.current_conversation_tasks: Dict[str, Optional[asyncio.Task]] = {}
        self.received_data_buffers: Dict[str, np.ndarray] = {}

        # Message handlers mapping
        self._message_handlers = self._init_message_handlers()

    def _init_message_handlers(self) -> Dict[str, Callable]:
        """Initialize message type to handler mapping"""
        return {
            "add-client-to-group": self._handle_group_operation,
            "remove-client-from-group": self._handle_group_operation,
            "request-group-info": self._handle_group_info,
            "fetch-history-list": self._handle_history_list_request,
            "fetch-and-set-history": self._handle_fetch_history,
            "create-new-history": self._handle_create_history,
            "delete-history": self._handle_delete_history,
            "interrupt-signal": self._handle_interrupt,
            "mic-audio-data": self._handle_audio_data,
            "mic-audio-end": self._handle_conversation_trigger,
            "raw-audio-data": self._handle_raw_audio_data,
            "text-input": self._handle_conversation_trigger,
            "ai-speak-signal": self._handle_conversation_trigger,
            "fetch-configs": self._handle_fetch_configs,
            "switch-config": self._handle_config_switch,
            "fetch-backgrounds": self._handle_fetch_backgrounds,
            "audio-play-start": self._handle_audio_play_start,
            "request-init-config": self._handle_init_config_request,
            "heartbeat": self._handle_heartbeat,
            "register-local-mcp": self._handle_register_local_mcp,
            "unregister-local-mcp": self._handle_unregister_local_mcp,
            # Resolved by message_handler before routing; kept out of the
            # unknown-message warning path.
            "local-tool-result": self._handle_local_tool_result,
        }

    def try_reserve_connection(
        self, client_uid: str, user_id: str | None = None
    ) -> bool:
        """Reserve a connection slot before session initialization starts."""
        if (
            len(self.client_connections) + len(self._pending_connections)
            >= MAX_WS_CONNECTIONS
        ):
            return False

        if user_id is not None:
            active = sum(1 for value in self.client_users.values() if value == user_id)
            pending = sum(
                1 for value in self._pending_user_ids.values() if value == user_id
            )
            if active + pending >= self.max_connections_per_user:
                return False

        self._pending_connections.add(client_uid)
        if user_id is not None:
            self._pending_user_ids[client_uid] = user_id
        return True

    def release_connection_reservation(self, client_uid: str) -> None:
        self._pending_connections.discard(client_uid)
        self._pending_user_ids.pop(client_uid, None)

    def has_client(self, client_uid: str, user_id: str | None = None) -> bool:
        if client_uid not in self.client_connections:
            return False
        if user_id is None:
            return True
        return self.client_users.get(client_uid) == user_id

    @staticmethod
    def _install_serialized_send(websocket: WebSocket) -> None:
        """Serialize frames; TTS and conversation tasks send concurrently."""
        send_lock = asyncio.Lock()
        raw_send_text = websocket.send_text

        async def serialized_send_text(data: str) -> None:
            async with send_lock:
                await raw_send_text(data)

        websocket.send_text = serialized_send_text

    async def handle_new_connection(
        self,
        websocket: WebSocket,
        client_uid: str,
        identity: Identity | None = None,
    ) -> None:
        """
        Handle new WebSocket connection setup

        Args:
            websocket: The WebSocket connection
            client_uid: Unique identifier for the client
            identity: Server-verified identity; defaults to the local user

        Raises:
            Exception: If initialization fails
        """
        if identity is None:
            if self.auth_manager is not None and self.auth_manager.enabled:
                raise ValueError("Authentication required")
            local_user_id = getattr(self.default_context_cache, "user_id", None)
            if not isinstance(local_user_id, str) or not local_user_id:
                local_user_id = "local"
            identity = Identity(local_user_id, "Local User")
        try:
            self._install_serialized_send(websocket)

            async def send_audio(data: str) -> None:
                audio_websocket = self.client_audio_connections.get(client_uid)
                if audio_websocket is not None:
                    try:
                        await audio_websocket.send_text(data)
                        return
                    except Exception as e:
                        logger.warning(
                            f"Audio WebSocket send failed for client {client_uid}: {e}; "
                            "falling back to the main connection"
                        )
                        self.client_audio_connections.pop(client_uid, None)
                await websocket.send_text(data)

            channels = OutboundChannels(text=websocket.send_text, audio=send_audio)
            session_service_context = await self._init_service_context(
                channels, client_uid, identity
            )

            await self._store_client_data(
                websocket, client_uid, session_service_context
            )

            await self._send_initial_messages(
                websocket, client_uid, session_service_context
            )

            logger.info(f"Connection established for client {client_uid}")

        except Exception as e:
            logger.error(
                f"Failed to initialize connection for client {client_uid}: {e}"
            )
            await self._cleanup_failed_connection(client_uid)
            raise

    async def handle_audio_connection(
        self, websocket: WebSocket, client_uid: str
    ) -> None:
        """Attach a secondary socket that only carries audio payloads."""
        self._install_serialized_send(websocket)

        previous = self.client_audio_connections.get(client_uid)
        self.client_audio_connections[client_uid] = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=1000)
            except Exception:
                pass

        logger.info(f"Audio channel connected for client {client_uid}")
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning(f"Audio WebSocket error for client {client_uid}: {e}")
        finally:
            if self.client_audio_connections.get(client_uid) is websocket:
                self.client_audio_connections.pop(client_uid, None)
            logger.info(f"Audio channel disconnected for client {client_uid}")

    async def _close_audio_connection(self, client_uid: str) -> None:
        websocket = self.client_audio_connections.pop(client_uid, None)
        if websocket is None:
            return
        try:
            await websocket.close(code=1000)
        except Exception:
            pass

    async def _store_client_data(
        self,
        websocket: WebSocket,
        client_uid: str,
        session_service_context: ServiceContext,
    ):
        """Store client data and initialize group status"""
        # The reservation only protects the expensive initialization window.
        self._pending_connections.discard(client_uid)
        self._pending_user_ids.pop(client_uid, None)
        self.client_connections[client_uid] = websocket
        self.client_contexts[client_uid] = session_service_context
        self.client_users[client_uid] = session_service_context.user_id
        self.received_data_buffers[client_uid] = np.array([])

        self.chat_group_manager.client_group_map[client_uid] = ""
        await self.send_group_update(websocket, client_uid)

    async def _send_initial_messages(
        self,
        websocket: WebSocket,
        client_uid: str,
        session_service_context: ServiceContext,
    ):
        """Send initial connection messages to the client"""
        await websocket.send_text(
            json.dumps({"type": "full-text", "text": "Connection established"})
        )

        await websocket.send_text(
            json.dumps(session_service_context.model_conf_payload(client_uid))
        )

        # The backend decides which user MCP entries are local; the browser
        # connects to those and registers their tools over WebSocket.
        await websocket.send_text(
            json.dumps(
                {
                    "type": "local-mcp-config",
                    "servers": session_service_context.get_local_mcp_config(),
                },
                ensure_ascii=False,
            )
        )

        # Send initial group status
        await self.send_group_update(websocket, client_uid)

    async def _load_user_mcp_servers(
        self,
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

    async def _init_service_context(
        self,
        channels: OutboundChannels,
        client_uid: str,
        identity: Identity,
    ) -> ServiceContext:
        """Initialize service context for a new session by cloning the default context"""
        repository = self.default_context_cache.history_repository
        if repository is not None:
            await repository.ensure_user(identity.user_id, identity.display_name)

        remote_mcp_servers, local_mcp_servers = await self._load_user_mcp_servers(
            repository, identity.user_id
        )

        session_service_context = ServiceContext()
        await session_service_context.load_cache(
            config=self.default_context_cache.config.model_copy(deep=True),
            system_config=self.default_context_cache.system_config.model_copy(
                deep=True
            ),
            character_config=self.default_context_cache.character_config.model_copy(
                deep=True
            ),
            live2d_model=self.default_context_cache.live2d_model,
            asr_engine=self.default_context_cache.asr_engine,
            tts_engine=self.default_context_cache.tts_engine,
            vad_engine=self.default_context_cache.vad_engine,
            agent_engine=self.default_context_cache.agent_engine,
            translate_engine=self.default_context_cache.translate_engine,
            mcp_server_registry=self.default_context_cache.mcp_server_registry,
            tool_adapter=self.default_context_cache.tool_adapter,
            channels=channels,
            client_uid=client_uid,
            history_repository=self.default_context_cache.history_repository,
            user_id=identity.user_id,
            user_display_name=identity.display_name,
            user_mcp_servers=remote_mcp_servers,
            local_mcp_servers=local_mcp_servers,
        )
        # Each connection needs its own agent state; the LLM client stays shared.
        await session_service_context.init_session_agent(
            self.default_context_cache.agent_engine
        )
        return session_service_context

    async def handle_websocket_communication(
        self, websocket: WebSocket, client_uid: str
    ) -> None:
        """
        Handle ongoing WebSocket communication

        Args:
            websocket: The WebSocket connection
            client_uid: Unique identifier for the client
        """
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    message_handler.handle_message(client_uid, data)
                    await self._route_message(websocket, client_uid, data)
                except WebSocketDisconnect:
                    raise
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    continue
                except Exception:
                    logger.exception("Error processing message")
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "Invalid request"})
                    )
                    continue

        except WebSocketDisconnect:
            logger.info(f"Client {client_uid} disconnected")
            raise
        except Exception as e:
            logger.error(f"Fatal error in WebSocket communication: {e}")
            raise

    async def _route_message(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """
        Route incoming message to appropriate handler

        Args:
            websocket: The WebSocket connection
            client_uid: Client identifier
            data: Message data
        """
        msg_type = data.get("type")
        if not msg_type:
            logger.warning("Message received without type")
            return

        handler = self._message_handlers.get(msg_type)
        if handler:
            await handler(websocket, client_uid, data)
        else:
            if msg_type != "frontend-playback-complete":
                logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_group_operation(
        self, websocket: WebSocket, client_uid: str, data: dict
    ) -> None:
        """Handle group-related operations"""
        operation = data.get("type")
        target_uid = data.get(
            "invitee_uid" if operation == "add-client-to-group" else "target_uid"
        )

        await handle_group_operation(
            operation=operation,
            client_uid=client_uid,
            target_uid=target_uid,
            chat_group_manager=self.chat_group_manager,
            client_connections=self.client_connections,
            client_users=self.client_users,
            send_group_update=self.send_group_update,
        )

    async def handle_disconnect(self, client_uid: str) -> None:
        """Handle client disconnection"""
        group = self.chat_group_manager.get_client_group(client_uid)
        if group:
            await handle_group_interrupt(
                group_id=group.group_id,
                heard_response="",
                current_conversation_tasks=self.current_conversation_tasks,
                chat_group_manager=self.chat_group_manager,
                client_contexts=self.client_contexts,
                broadcast_to_group=self.broadcast_to_group,
            )

        await handle_client_disconnect(
            client_uid=client_uid,
            chat_group_manager=self.chat_group_manager,
            client_connections=self.client_connections,
            send_group_update=self.send_group_update,
        )

        await self._release_client(
            client_uid, "Conversation task failed during disconnect"
        )

        logger.info(f"Client {client_uid} disconnected")
        message_handler.cleanup_client(client_uid)

    async def _release_client(self, client_uid: str, failure_message: str) -> None:
        """Drop the client's sockets, task, and context."""
        await self._close_audio_connection(client_uid)
        self.client_connections.pop(client_uid, None)
        context = self.client_contexts.pop(client_uid, None)
        self.client_users.pop(client_uid, None)
        self.received_data_buffers.pop(client_uid, None)
        await self._cancel_conversation_task(client_uid, failure_message)

        # Closing the context releases resources such as the MCP client.
        if context:
            await context.close()

    async def _cancel_conversation_task(
        self, client_uid: str, failure_message: str
    ) -> None:
        task = self.current_conversation_tasks.pop(client_uid, None)
        await cancel_and_wait(task, failure_message=failure_message)

    async def _cleanup_failed_connection(self, client_uid: str) -> None:
        """Clean up failed connection data"""
        self.chat_group_manager.client_group_map.pop(client_uid, None)
        await self._release_client(
            client_uid, "Conversation task failed during connection cleanup"
        )
        message_handler.cleanup_client(client_uid)

    async def broadcast_to_group(
        self, group_members: list[str], message: dict, exclude_uid: str = None
    ) -> None:
        """Broadcasts a message to group members"""
        await broadcast_to_group(
            group_members=group_members,
            message=message,
            client_connections=self.client_connections,
            exclude_uid=exclude_uid,
        )

    async def send_group_update(self, websocket: WebSocket, client_uid: str):
        """Sends group information to a client"""
        group = self.chat_group_manager.get_client_group(client_uid)
        if group:
            current_members = self.chat_group_manager.get_group_members(client_uid)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "group-update",
                        "members": current_members,
                        "is_owner": group.owner_uid == client_uid,
                    }
                )
            )
        else:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "group-update",
                        "members": [],
                        "is_owner": False,
                    }
                )
            )

    async def _handle_interrupt(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle conversation interruption"""
        heard_response = data.get("text", "")
        context = self.client_contexts[client_uid]
        group = self.chat_group_manager.get_client_group(client_uid)

        if group and len(group.members) > 1:
            await handle_group_interrupt(
                group_id=group.group_id,
                heard_response=heard_response,
                current_conversation_tasks=self.current_conversation_tasks,
                chat_group_manager=self.chat_group_manager,
                client_contexts=self.client_contexts,
                broadcast_to_group=self.broadcast_to_group,
            )
        else:
            await handle_individual_interrupt(
                client_uid=client_uid,
                current_conversation_tasks=self.current_conversation_tasks,
                context=context,
                heard_response=heard_response,
            )

    async def _handle_history_list_request(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle request for chat history list"""
        context = self.client_contexts[client_uid]
        try:
            histories = (
                await context.history.list_histories(context.character_config.conf_uid)
                if context.history is not None
                else []
            )
        except Exception:
            logger.exception("Failed to list chat histories")
            histories = []
        await websocket.send_text(
            json.dumps({"type": "history-list", "histories": histories})
        )

    async def _handle_fetch_history(
        self, websocket: WebSocket, client_uid: str, data: dict
    ):
        """Handle fetching and setting specific chat history"""
        history_uid = data.get("history_uid")
        if not history_uid:
            return

        context = self.client_contexts[client_uid]
        messages = []
        created_uid: str | None = None
        if context.history is not None:
            try:
                messages = await context.load_history(history_uid)
            except (HistoryNotFoundError, ValueError):
                # The client reconnected with a stale history (deleted, or from
                # another character). Start a fresh one so the next turn is
                # stored instead of silently dropped.
                logger.info(
                    f"History {history_uid} unavailable for client {client_uid}; "
                    "creating a new one"
                )
                try:
                    created_uid = await context.history.create_history(
                        context.character_config.conf_uid
                    )
                    await context.load_history(created_uid)
                except Exception:
                    logger.exception("Failed to create replacement history")
                    created_uid = None
            except Exception:
                logger.exception("Failed to load chat history")
                messages = []

        tool_calls = []
        load_tool_calls = getattr(context, "get_history_tool_calls", None)
        if context.history is not None and load_tool_calls is not None:
            try:
                tool_calls = await load_tool_calls(created_uid or history_uid)
            except Exception:
                logger.exception("Failed to load tool calls for history")

        await websocket.send_text(
            json.dumps(
                {
                    "type": "history-data",
                    "messages": [msg for msg in messages if msg["role"] != "system"],
                    "tool_calls": tool_calls,
                }
            )
        )
        if created_uid:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "new-history-created",
                        "history_uid": created_uid,
                    }
                )
            )

    async def _handle_create_history(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle creation of new chat history"""
        context = self.client_contexts[client_uid]
        if context.history is None:
            logger.warning("History storage is not configured")
            return

        history_uid = await context.history.create_history(
            context.character_config.conf_uid
        )
        try:
            await context.load_history(history_uid)
        except Exception:
            logger.exception("Failed to reset memory for a new history")
        await websocket.send_text(
            json.dumps(
                {
                    "type": "new-history-created",
                    "history_uid": history_uid,
                }
            )
        )

    async def _handle_delete_history(
        self, websocket: WebSocket, client_uid: str, data: dict
    ):
        """Handle deletion of chat history"""
        history_uid = data.get("history_uid")
        if not history_uid:
            return

        context = self.client_contexts[client_uid]
        success = (
            await context.history.delete_history(
                context.character_config.conf_uid,
                history_uid,
            )
            if context.history is not None
            else False
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "history-deleted",
                    "success": success,
                    "history_uid": history_uid,
                }
            )
        )
        if success and history_uid == context.history_uid:
            context.history_uid = None

    async def _handle_audio_data(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle incoming audio data"""
        audio_data = data.get("audio", [])
        if not isinstance(audio_data, (list, tuple)) or not audio_data:
            return

        if len(audio_data) > MAX_AUDIO_SAMPLES:
            await self._reject_oversized_audio(websocket, client_uid)
            return

        buffer = self.received_data_buffers.get(client_uid)
        if buffer is None:
            return
        if len(buffer) + len(audio_data) > MAX_AUDIO_SAMPLES:
            await self._reject_oversized_audio(websocket, client_uid)
            return

        self.received_data_buffers[client_uid] = np.append(
            buffer,
            np.array(audio_data, dtype=np.float32),
        )

    async def _reject_oversized_audio(
        self, websocket: WebSocket, client_uid: str
    ) -> None:
        self.received_data_buffers[client_uid] = np.array([])
        logger.warning(f"Audio input from {client_uid} exceeded the size limit")
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "message": "Audio input is too long; the recording was discarded",
                }
            )
        )

    async def _handle_raw_audio_data(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle incoming raw audio data for VAD processing"""
        context = self.client_contexts[client_uid]
        if context.vad_engine is None:
            return

        chunk = data.get("audio", [])
        if chunk:
            for audio_bytes in context.vad_engine.detect_speech(chunk):
                if audio_bytes == b"<|PAUSE|>":
                    await websocket.send_text(
                        json.dumps({"type": "control", "text": "interrupt"})
                    )
                elif audio_bytes == b"<|RESUME|>":
                    pass
                elif len(audio_bytes) > 1024:
                    # Detected audio activity (voice)
                    buffer = self.received_data_buffers.get(client_uid)
                    if buffer is None:
                        return
                    if len(buffer) + len(audio_bytes) // 2 > MAX_AUDIO_SAMPLES:
                        await self._reject_oversized_audio(websocket, client_uid)
                        return
                    self.received_data_buffers[client_uid] = np.append(
                        buffer,
                        # VAD yields int16 PCM bytes; ASR engines and the
                        # mic-audio-data path both expect [-1, 1] floats.
                        np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                        / 32768.0,
                    )
                    await websocket.send_text(
                        json.dumps({"type": "control", "text": "mic-audio-end"})
                    )

    def _validate_conversation_input(
        self, msg_type: str, data: WSMessage
    ) -> Optional[str]:
        if msg_type == "text-input":
            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                return "Text input must be a non-empty string"
            if len(text) > MAX_TEXT_INPUT_CHARS:
                return f"Text input exceeds {MAX_TEXT_INPUT_CHARS} characters"

        images = data.get("images")
        if images is not None:
            if not isinstance(images, list) or len(images) > MAX_IMAGES_PER_MESSAGE:
                return f"At most {MAX_IMAGES_PER_MESSAGE} images are allowed"
            for image in images:
                if not isinstance(image, dict):
                    return "Invalid image payload"
                source = image.get("source")
                mime_type = image.get("mime_type")
                image_data = image.get("data")
                if source not in IMAGE_SOURCES:
                    return "Invalid image source"
                if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
                    return "Invalid image type"
                if not isinstance(image_data, str):
                    return "Invalid image data"
                if len(image_data) > MAX_IMAGE_DATA_CHARS:
                    return "Image is too large"

        return None

    async def _handle_conversation_trigger(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle triggers that start a conversation"""
        error = self._validate_conversation_input(data.get("type", ""), data)
        if error:
            await websocket.send_text(json.dumps({"type": "error", "message": error}))
            return

        await handle_conversation_trigger(
            msg_type=data.get("type", ""),
            data=data,
            client_uid=client_uid,
            context=self.client_contexts[client_uid],
            websocket=websocket,
            client_contexts=self.client_contexts,
            client_connections=self.client_connections,
            chat_group_manager=self.chat_group_manager,
            received_data_buffers=self.received_data_buffers,
            current_conversation_tasks=self.current_conversation_tasks,
            broadcast_to_group=self.broadcast_to_group,
        )

    async def _handle_fetch_configs(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle fetching available configurations"""
        context = self.client_contexts[client_uid]
        config_files = scan_config_alts_directory(
            context.system_config.config_alts_dir,
            is_allowed=context.character_allowed,
        )
        await websocket.send_text(
            json.dumps({"type": "config-files", "configs": config_files})
        )

    async def _handle_config_switch(
        self, websocket: WebSocket, client_uid: str, data: dict
    ):
        """Handle switching to a different configuration"""
        config_file_name = data.get("file")
        if config_file_name:
            context = self.client_contexts[client_uid]
            await context.handle_config_switch(websocket, config_file_name)

    async def _handle_fetch_backgrounds(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle fetching available background images"""
        bg_files = scan_bg_directory()
        await websocket.send_text(
            json.dumps({"type": "background-files", "files": bg_files})
        )

    async def _handle_audio_play_start(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """
        Handle audio playback start notification
        """
        group_members = self.chat_group_manager.get_group_members(client_uid)
        if len(group_members) > 1:
            display_text = data.get("display_text")
            if display_text:
                silent_payload = prepare_audio_payload(
                    audio_path=None,
                    display_text=display_text,
                    actions=None,
                    forwarded=True,
                )
                await self.broadcast_to_group(
                    group_members, silent_payload, exclude_uid=client_uid
                )

    async def _handle_group_info(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle group info request"""
        await self.send_group_update(websocket, client_uid)

    async def _handle_init_config_request(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle request for initialization configuration"""
        context = self.client_contexts.get(client_uid)
        if not context:
            context = self.default_context_cache

        await websocket.send_text(json.dumps(context.model_conf_payload(client_uid)))

    async def _send_local_mcp_error(
        self, websocket: WebSocket, server_id, message: str
    ) -> None:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "local-mcp-error",
                    "server_id": server_id if isinstance(server_id, str) else "",
                    "message": message,
                },
                ensure_ascii=False,
            )
        )

    async def _handle_register_local_mcp(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Register tool schemas from an MCP server running in the browser."""
        context = self.client_contexts.get(client_uid)
        if context is None:
            return

        raw_server_id = data.get("server_id")
        try:
            server_id = validate_server_id(raw_server_id)
            title = data.get("name")
            name = title if isinstance(title, str) else server_id
            tools = data.get("tools")
            if not isinstance(tools, list):
                raise ValueError("tools must be a list")
            if len(json.dumps(data, ensure_ascii=False)) > MAX_LOCAL_MCP_PAYLOAD_CHARS:
                raise ValueError("Local MCP registration payload is too large")
            exposed_tools = context.register_local_mcp_server(
                server_id=server_id,
                tools=tools,
            )
        except Exception as exc:
            if isinstance(exc, ValueError):
                message = str(exc)
            else:
                logger.exception("Failed to register local MCP tools")
                message = "Failed to register local MCP server"
            logger.warning(
                f"Local MCP registration failed for client {client_uid}: {message}"
            )
            await self._send_local_mcp_error(websocket, raw_server_id, message)
            return

        await websocket.send_text(
            json.dumps(
                {
                    "type": "local-mcp-registered",
                    "server_id": server_id,
                    "server_name": name,
                    "tools": exposed_tools,
                },
                ensure_ascii=False,
            )
        )
        logger.info(
            f"Local MCP server '{server_id}' registered "
            f"{len(exposed_tools)} tool(s) for client {client_uid}"
        )

    async def _handle_unregister_local_mcp(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        context = self.client_contexts.get(client_uid)
        if context is None:
            return
        try:
            server_id = validate_server_id(data.get("server_id"))
        except ValueError as exc:
            await self._send_local_mcp_error(websocket, data.get("server_id"), str(exc))
            return

        removed = context.unregister_local_mcp_server(server_id)
        await websocket.send_text(
            json.dumps(
                {
                    "type": "local-mcp-unregistered",
                    "server_id": server_id,
                    "success": removed,
                },
                ensure_ascii=False,
            )
        )

    async def _handle_local_tool_result(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        # message_handler.wait_for_response already consumed the payload.
        return

    async def _handle_heartbeat(
        self, websocket: WebSocket, client_uid: str, data: WSMessage
    ) -> None:
        """Handle heartbeat messages from clients"""
        try:
            await websocket.send_text(json.dumps({"type": "heartbeat-ack"}))
        except Exception as e:
            logger.error(f"Error sending heartbeat acknowledgment: {e}")
