import os
import json
import re
import asyncio
from urllib.parse import urlsplit
from uuid import uuid4
from fastapi import APIRouter, WebSocket, UploadFile, File, Request, Response
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect
from loguru import logger
from .auth import AuthManager, Identity
from .auth.middleware import IDENTITY_SCOPE_KEY
from .config_manager.asset_access import LIVE2D_MOUNT, CharacterAssetAccess
from .service_context import ServiceContext
from .websocket_handler import WebSocketHandler
from .proxy_handler import ProxyHandler
from .utils.audio import (
    ASR_SAMPLE_RATE,
    MAX_AUDIO_SECONDS,
    decode_pcm_wav,
    new_audio_file_stem,
)


MAX_ASR_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TTS_TEXT_CHARS = 2000
MAX_TTS_SENTENCES = 30
MAX_TTS_CONNECTIONS = 16
MAX_CONCURRENT_ASR = 2
_TTS_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s*")
_TTS_TERMINAL_PUNCTUATION = ".!?。！？"


def _json_error(status_code: int, message: str) -> Response:
    return Response(
        content=json.dumps({"error": message}),
        status_code=status_code,
        media_type="application/json",
    )


def _split_tts_sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in _TTS_SENTENCE_BOUNDARY.split(text)
        if sentence.strip()
    ]


def _with_terminal_punctuation(sentence: str) -> str:
    if sentence[-1] not in _TTS_TERMINAL_PUNCTUATION:
        return sentence + "."
    return sentence


async def _stream_tts_sentences(
    websocket: WebSocket, tts_engine, sentences, *, cache_scope: str | None = None
) -> None:
    for sentence in sentences:
        sentence = _with_terminal_punctuation(sentence)
        # In OIDC mode /cache only serves files under the caller's user id.
        audio_path = await tts_engine.async_generate_audio(
            text=sentence, file_name_no_ext=new_audio_file_stem(cache_scope)
        )
        if not audio_path:
            logger.error("TTS engine returned no audio path")
            await websocket.send_json(
                {"status": "error", "message": "Failed to generate audio"}
            )
            return

        logger.info(f"Generated audio for sentence at: {audio_path}")
        await websocket.send_json(
            {
                "status": "partial",
                "audioPath": audio_path,
                "text": sentence,
            }
        )

    await websocket.send_json({"status": "complete"})


async def _process_tts_request(
    websocket: WebSocket, tts_engine, text: str, *, cache_scope: str | None = None
) -> None:
    if len(text) > MAX_TTS_TEXT_CHARS:
        await websocket.send_json(
            {
                "status": "error",
                "message": f"Text exceeds the {MAX_TTS_TEXT_CHARS}-character limit",
            }
        )
        return

    logger.info(f"Received text for TTS ({len(text)} characters)")

    sentences = _split_tts_sentences(text)
    if len(sentences) > MAX_TTS_SENTENCES:
        await websocket.send_json(
            {
                "status": "error",
                "message": f"Text exceeds the {MAX_TTS_SENTENCES}-sentence limit",
            }
        )
        return

    try:
        await _stream_tts_sentences(
            websocket, tts_engine, sentences, cache_scope=cache_scope
        )
    except Exception:
        logger.exception("Error generating TTS")
        await websocket.send_json(
            {"status": "error", "message": "Failed to generate audio"}
        )


async def _serve_tts_connection(
    websocket: WebSocket, tts_engine, *, cache_scope: str | None = None
) -> None:
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                continue

            await _process_tts_request(
                websocket, tts_engine, text, cache_scope=cache_scope
            )
    except WebSocketDisconnect:
        logger.info("TTS WebSocket client disconnected")
    except Exception:
        logger.exception("Error in TTS WebSocket connection")
        await websocket.close()


def _default_user_id(default_context_cache: ServiceContext) -> str:
    """User id for unauthenticated (single-user) deployments."""
    return getattr(default_context_cache, "user_id", None) or "local"


def _websocket_identity(
    websocket: WebSocket,
    auth: AuthManager | None,
    default_user_id: str,
) -> Identity | None:
    if auth is None:
        return Identity(default_user_id, "Local User")
    return auth.resolve_identity(websocket.cookies)


def _websocket_origin_allowed(websocket: WebSocket, auth: AuthManager | None) -> bool:
    """Reject cross-site browser WebSockets in OIDC mode.

    Non-browser clients may omit Origin; the session cookie is still required.
    The frontend is served same-origin, so comparing Origin's host with the
    request Host is sufficient for this deployment.
    """
    if auth is None or not auth.enabled:
        return True
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    default_port = ":443" if parsed.scheme == "https" else ":80"
    origin_host = parsed.netloc.removesuffix(default_port)
    request_host = (websocket.headers.get("host") or "").removesuffix(default_port)
    return origin_host == request_host


async def _reject_websocket(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.accept()
    await websocket.close(code=code, reason=reason)


async def _require_websocket_identity(
    websocket: WebSocket,
    auth: AuthManager | None,
    default_user_id: str,
) -> Identity | None:
    """Reject an unauthenticated or cross-site socket before it is served."""
    if not _websocket_origin_allowed(websocket, auth):
        await _reject_websocket(websocket, 1008, "Origin not allowed")
        return None
    identity = _websocket_identity(websocket, auth, default_user_id)
    if identity is None:
        await _reject_websocket(websocket, 4401, "Authentication required")
        return None
    return identity


def _scan_live2d_models(live2d_dir: str) -> list[dict]:
    """List model folders that contain the matching .model3.json file."""
    supported_extensions = [".png", ".jpg", ".jpeg"]
    valid_characters = []
    for entry in os.scandir(live2d_dir):
        if not entry.is_dir():
            continue
        folder_name = entry.name.replace("\\", "/")
        model3_file = os.path.join(
            live2d_dir, folder_name, f"{folder_name}.model3.json"
        ).replace("\\", "/")
        if not os.path.isfile(model3_file):
            continue

        avatar_file = None
        for ext in supported_extensions:
            avatar_path = os.path.join(live2d_dir, folder_name, f"{folder_name}{ext}")
            if os.path.isfile(avatar_path):
                avatar_file = avatar_path.replace("\\", "/")
                break

        valid_characters.append(
            {
                "name": folder_name,
                "avatar": avatar_file,
                "model_path": model3_file,
            }
        )
    return valid_characters


def init_client_ws_route(
    default_context_cache: ServiceContext,
    auth: AuthManager | None = None,
) -> APIRouter:
    """
    Create and return API routes for handling the `/client-ws` WebSocket connections.

    Args:
        default_context_cache: Default service context cache for new sessions.
        auth: Authentication manager; omitted only by isolated tests.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()
    max_connections_per_user = (
        auth.config.max_connections_per_user if auth is not None else 4
    )
    ws_handler = WebSocketHandler(
        default_context_cache,
        auth_manager=auth,
        max_connections_per_user=max_connections_per_user,
    )

    @router.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for client connections"""
        identity = await _require_websocket_identity(
            websocket, auth, _default_user_id(default_context_cache)
        )
        if identity is None:
            return

        client_uid = str(uuid4())
        per_user_id = identity.user_id if auth is not None and auth.enabled else None

        if not ws_handler.try_reserve_connection(client_uid, per_user_id):
            await _reject_websocket(
                websocket, 1013, "Too many connections for this user"
            )
            return

        try:
            await websocket.accept()

            try:
                await ws_handler.handle_new_connection(websocket, client_uid, identity)
                await ws_handler.handle_websocket_communication(websocket, client_uid)
            except WebSocketDisconnect:
                await ws_handler.handle_disconnect(client_uid)
            except Exception:
                logger.exception(
                    f"Error in WebSocket connection for client {client_uid}"
                )
                await ws_handler.handle_disconnect(client_uid)
                raise
        finally:
            ws_handler.release_connection_reservation(client_uid)

    @router.websocket("/audio-ws")
    async def audio_endpoint(websocket: WebSocket):
        """Secondary WebSocket that carries only audio payloads."""
        identity = _websocket_identity(
            websocket, auth, _default_user_id(default_context_cache)
        )
        client_uid = websocket.query_params.get("client_uid")
        await websocket.accept()
        if (
            not _websocket_origin_allowed(websocket, auth)
            or identity is None
            or not client_uid
            or not ws_handler.has_client(client_uid, identity.user_id)
        ):
            await websocket.close(code=1008, reason="Unknown client")
            return
        await ws_handler.handle_audio_connection(websocket, client_uid)

    return router


def init_proxy_route(server_url: str) -> APIRouter:
    """
    Create and return API routes for handling proxy connections.

    Args:
        server_url: The WebSocket URL of the actual server

    Returns:
        APIRouter: Configured router with proxy WebSocket endpoint
    """
    router = APIRouter()
    proxy_handler = ProxyHandler(server_url)

    @router.websocket("/proxy-ws")
    async def proxy_endpoint(websocket: WebSocket):
        """WebSocket endpoint for proxy connections"""
        try:
            await proxy_handler.handle_client_connection(websocket)
        except Exception as e:
            logger.error(f"Error in proxy connection: {e}")
            raise

    return router


def init_webtool_routes(
    default_context_cache: ServiceContext,
    auth: AuthManager | None = None,
    *,
    asset_access: CharacterAssetAccess | None = None,
) -> APIRouter:
    """
    Create and return API routes for handling web tool interactions.

    Args:
        default_context_cache: Default service context cache for new sessions.
        auth: Authentication manager; omitted only by isolated tests.
        asset_access: Hides restricted Live2D folders from /live2d-models/info.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()
    asr_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ASR)
    tts_slots = asyncio.Semaphore(MAX_TTS_CONNECTIONS)

    @router.get("/web-tool")
    async def web_tool_redirect():
        """Redirect /web-tool to /web-tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/web_tool")
    async def web_tool_redirect_alt():
        """Redirect /web_tool to /web-tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    async def _visible_live2d_models(request: Request, models: list[dict]):
        """Drop folders the static mount would answer 404 to for this caller."""
        if asset_access is None or auth is None or not auth.enabled:
            return models
        identity = request.scope.get(IDENTITY_SCOPE_KEY)
        user_id = getattr(identity, "user_id", None)
        emails = None
        visible = []
        for model in models:
            if asset_access.is_restricted(LIVE2D_MOUNT, model["name"]):
                if user_id is None:
                    continue
                if emails is None:
                    emails = await auth.verified_emails(user_id)
                if not asset_access.is_allowed(
                    LIVE2D_MOUNT, model["name"], user_id, emails
                ):
                    continue
            visible.append(model)
        return visible

    @router.get("/live2d-models/info")
    async def get_live2d_folder_info(request: Request):
        """Get information about available Live2D models"""
        live2d_dir = "live2d-models"
        if not os.path.exists(live2d_dir):
            return JSONResponse(
                {"error": "Live2D models directory not found"}, status_code=404
            )

        valid_characters = await _visible_live2d_models(
            request, _scan_live2d_models(live2d_dir)
        )
        return JSONResponse(
            {
                "type": "live2d-models/info",
                "count": len(valid_characters),
                "characters": valid_characters,
            }
        )

    @router.post("/asr")
    async def transcribe_audio(request: Request, file: UploadFile = File(...)):
        """
        Endpoint for transcribing audio using the ASR engine
        """
        if auth is not None and auth.enabled:
            if auth.resolve_identity(request.cookies) is None:
                return _json_error(401, "Authentication required")
        try:
            contents = await file.read(MAX_ASR_UPLOAD_BYTES + 1)
            logger.info(f"Received audio upload: {len(contents)} bytes")

            if not contents:
                raise ValueError("Empty audio file")
            if len(contents) > MAX_ASR_UPLOAD_BYTES:
                return _json_error(413, "Audio file is too large")

            audio_array = decode_pcm_wav(
                contents,
                sample_rate=ASR_SAMPLE_RATE,
                max_seconds=MAX_AUDIO_SECONDS,
            )

            if asr_semaphore.locked():
                return _json_error(429, "Too many concurrent transcription requests")

            async with asr_semaphore:
                text = await default_context_cache.asr_engine.async_transcribe_np(
                    audio_array
                )
            logger.info(f"Transcription result: {text}")
            return {"text": text}

        except ValueError as e:
            logger.error(f"Audio format error: {e}")
            return _json_error(400, str(e))
        except Exception:
            logger.exception("Error during transcription")
            return _json_error(500, "Internal server error during transcription")

    @router.websocket("/tts-ws")
    async def tts_endpoint(websocket: WebSocket):
        """WebSocket endpoint for TTS generation"""
        identity = await _require_websocket_identity(
            websocket, auth, _default_user_id(default_context_cache)
        )
        if identity is None:
            return

        if tts_slots.locked():
            await _reject_websocket(websocket, 1013, "Server is at capacity")
            return

        await tts_slots.acquire()
        try:
            await websocket.accept()
            logger.info("TTS WebSocket connection established")
            await _serve_tts_connection(
                websocket,
                default_context_cache.tts_engine,
                cache_scope=(
                    identity.user_id if auth is not None and auth.enabled else None
                ),
            )
        finally:
            tts_slots.release()

    return router
