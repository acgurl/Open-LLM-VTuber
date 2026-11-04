"""QQ official bot connector (bot.q.qq.com, API v2, WebSocket gateway).

The bot connects out to the gateway, so the server needs no public callback
URL. Replies are passive: they quote the inbound ``msg_id``, which the
platform accepts for a few minutes and a few times per message.

Sender ids are namespaced because the platform has two id systems: guild
channels and guild DMs use the user's guild id (``u:``), groups and single
chats use the per-bot openid (``o:``). A binding made in one namespace does
not cover the other.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from loguru import logger
from websockets.asyncio.client import connect as ws_connect

from ..config_manager.connectors import QQConnectorConfig
from .base import Connector, ConnectorCapabilities, InboundHandler, InboundMessage

TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE = "https://api.sgroup.qq.com"
SANDBOX_API_BASE = "https://sandbox.api.sgroup.qq.com"
TOKEN_REFRESH_MARGIN_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 15.0
RETRY_STATUS_CODES = {502, 503, 504}
MAX_FRAME_BYTES = 4 * 1024 * 1024

INTENT_BITS = {
    "guild_messages": 1 << 9,
    "direct_message": 1 << 12,
    "group_and_c2c": 1 << 25,
    "public_guild_messages": 1 << 30,
}

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

_MENTION = re.compile(r"<@!?\w+>")


class QQGatewayError(RuntimeError):
    """The gateway asked us to reconnect or rejected the session."""


class QQAPIError(RuntimeError):
    def __init__(self, status: int, code: Any, message: str) -> None:
        super().__init__(f"HTTP {status}, code {code}: {message}")
        self.status = status
        self.code = code


def intents_value(names: list[str]) -> int:
    value = 0
    for name in names:
        value |= INTENT_BITS[name]
    return value


def _strip_mentions(content: str) -> str:
    return _MENTION.sub("", content or "").strip()


def parse_event(
    connector_id: str, event_type: str, data: dict[str, Any]
) -> InboundMessage | None:
    """Map a gateway dispatch to an InboundMessage, or None to ignore it."""
    if not isinstance(data, dict):
        return None
    message_id = data.get("id")
    author = data.get("author") or {}
    if not isinstance(message_id, str) or not isinstance(author, dict):
        return None
    if author.get("bot"):
        return None
    content = _strip_mentions(str(data.get("content") or ""))

    if event_type in {"AT_MESSAGE_CREATE", "MESSAGE_CREATE"}:
        channel_id, user_id = data.get("channel_id"), author.get("id")
        if not channel_id or not user_id:
            return None
        member = data.get("member") or {}
        return InboundMessage(
            connector_id=connector_id,
            message_id=message_id,
            chat_type="guild",
            chat_id=str(channel_id),
            sender_id=f"u:{user_id}",
            sender_name=member.get("nick") or author.get("username"),
            text=content,
            reply_context={"msg_id": message_id},
        )
    if event_type == "DIRECT_MESSAGE_CREATE":
        guild_id, user_id = data.get("guild_id"), author.get("id")
        if not guild_id or not user_id:
            return None
        return InboundMessage(
            connector_id=connector_id,
            message_id=message_id,
            chat_type="direct",
            chat_id=str(guild_id),
            sender_id=f"u:{user_id}",
            sender_name=author.get("username"),
            text=content,
            reply_context={"msg_id": message_id},
        )
    if event_type == "GROUP_AT_MESSAGE_CREATE":
        group_id, openid = data.get("group_openid"), author.get("member_openid")
        if not group_id or not openid:
            return None
        return InboundMessage(
            connector_id=connector_id,
            message_id=message_id,
            chat_type="group",
            chat_id=str(group_id),
            sender_id=f"o:{openid}",
            text=content,
            reply_context={"msg_id": message_id},
        )
    if event_type == "C2C_MESSAGE_CREATE":
        openid = author.get("user_openid")
        if not openid:
            return None
        return InboundMessage(
            connector_id=connector_id,
            message_id=message_id,
            chat_type="c2c",
            chat_id=str(openid),
            sender_id=f"o:{openid}",
            text=content,
            reply_context={"msg_id": message_id},
        )
    return None


class QQConnector(Connector):
    platform = "qq"
    capabilities = ConnectorCapabilities(
        max_message_chars=1500, max_replies_per_message=4
    )

    def __init__(
        self,
        config: QQConnectorConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        connect: Callable = ws_connect,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(config.id, config.name)
        self.config = config
        self.api_base = SANDBOX_API_BASE if config.sandbox else API_BASE
        self._http = http_client or httpx.AsyncClient(
            timeout=config.request_timeout_seconds
        )
        self._connect = connect
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        # Kept across reconnects so a dropped connection can resume and
        # replay missed events instead of losing them.
        self._session_id: str | None = None
        self._seq: int | None = None

    # ==== auth / REST

    async def _http_request(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        """One REST call, retried on transient network failures."""
        retries = self.config.http_retries
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= retries:
                    raise
                error = f"{type(exc).__name__}: {exc}"
            else:
                # After the last retry the 5xx goes to the caller as an API error.
                if response.status_code not in RETRY_STATUS_CODES or attempt >= retries:
                    return response
                error = f"HTTP {response.status_code}"
            delay = self.config.retry_backoff_seconds * 2**attempt
            attempt += 1
            logger.warning(
                f"Connector {self.connector_id}: {method} {url} failed ({error}); "
                f"retry {attempt}/{retries} in {delay:g}s"
            )
            await asyncio.sleep(delay)

    async def _access_token(self) -> str:
        async with self._token_lock:
            if self._token and self._clock() < self._token_expires_at:
                return self._token
            response = await self._http_request(
                "POST",
                TOKEN_URL,
                json={
                    "appId": self.config.app_id,
                    "clientSecret": self.config.app_secret,
                },
            )
            payload = _json_or_empty(response)
            token = payload.get("access_token")
            if response.status_code >= 400 or not isinstance(token, str):
                raise QQAPIError(
                    response.status_code,
                    payload.get("code"),
                    str(payload.get("message") or "failed to get access token"),
                )
            try:
                expires_in = int(payload.get("expires_in", 7200))
            except (TypeError, ValueError):
                expires_in = 7200
            self._token = token
            self._token_expires_at = self._clock() + max(
                expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 30
            )
            return token

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = await self._access_token()
        response = await self._http_request(
            method,
            f"{self.api_base}{path}",
            json=body,
            headers={
                "Authorization": f"QQBot {token}",
                "X-Union-Appid": self.config.app_id,
            },
        )
        payload = _json_or_empty(response)
        if response.status_code >= 400:
            if response.status_code == 401:
                self._token = None
            raise QQAPIError(
                response.status_code,
                payload.get("code"),
                str(payload.get("message") or response.reason_phrase),
            )
        return payload

    async def send_text(self, message: InboundMessage, text: str, index: int) -> None:
        msg_id = message.reply_context.get("msg_id")
        if message.chat_type == "guild":
            path = f"/channels/{message.chat_id}/messages"
            body: dict[str, Any] = {"content": text, "msg_id": msg_id}
        elif message.chat_type == "direct":
            path = f"/dms/{message.chat_id}/messages"
            body = {"content": text, "msg_id": msg_id}
        elif message.chat_type in {"group", "c2c"}:
            target = "groups" if message.chat_type == "group" else "users"
            path = f"/v2/{target}/{message.chat_id}/messages"
            # Replies to the same msg_id need distinct sequence numbers.
            body = {
                "content": text,
                "msg_type": 0,
                "msg_id": msg_id,
                "msg_seq": index + 1,
            }
        else:
            raise ValueError(f"Unsupported chat type: {message.chat_type}")
        await self._request("POST", path, body)

    # ==== gateway

    async def run(self, on_message: InboundHandler) -> None:
        gateway = await self._request("GET", "/gateway")
        url = gateway.get("url")
        if not isinstance(url, str) or not url.startswith("wss://"):
            raise QQGatewayError("gateway URL missing")

        async with self._connect(
            url, open_timeout=HTTP_TIMEOUT_SECONDS, max_size=MAX_FRAME_BYTES
        ) as websocket:
            hello = await self._receive(websocket)
            if hello.get("op") != OP_HELLO:
                raise QQGatewayError(f"expected HELLO, got op {hello.get('op')}")
            interval = (hello.get("d") or {}).get("heartbeat_interval") or 41250
            await self._identify_or_resume(websocket)
            heartbeat = asyncio.create_task(
                self._heartbeat(websocket, float(interval) / 1000)
            )
            try:
                await self._read_events(websocket, on_message)
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                if self.state == "running":
                    self.state = "connecting"

    async def _identify_or_resume(self, websocket) -> None:
        token = await self._access_token()
        if self._session_id is not None:
            await self._send(
                websocket,
                OP_RESUME,
                {
                    "token": f"QQBot {token}",
                    "session_id": self._session_id,
                    "seq": self._seq or 0,
                },
            )
            return
        await self._send(
            websocket,
            OP_IDENTIFY,
            {
                "token": f"QQBot {token}",
                "intents": intents_value(self.config.intents),
                "shard": [0, 1],
                "properties": {},
            },
        )

    async def _heartbeat(self, websocket, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._send(websocket, OP_HEARTBEAT, self._seq)

    async def _read_events(self, websocket, on_message: InboundHandler) -> None:
        while True:
            frame = await self._receive(websocket)
            op = frame.get("op")
            if isinstance(frame.get("s"), int):
                self._seq = frame["s"]

            if op == OP_DISPATCH:
                await self._dispatch(frame.get("t"), frame.get("d"), on_message)
            elif op == OP_HEARTBEAT:
                await self._send(websocket, OP_HEARTBEAT, self._seq)
            elif op == OP_RECONNECT:
                raise QQGatewayError("gateway requested a reconnect")
            elif op == OP_INVALID_SESSION:
                # The session cannot be resumed; identify again next time.
                self._session_id = None
                self._seq = None
                raise QQGatewayError("gateway invalidated the session")

    async def _dispatch(
        self, event_type: Any, data: Any, on_message: InboundHandler
    ) -> None:
        if event_type == "READY":
            self._session_id = (data or {}).get("session_id")
            self.state = "running"
            self.last_error = None
            logger.info(f"Connector {self.connector_id}: QQ gateway ready")
            return
        if event_type == "RESUMED":
            self.state = "running"
            self.last_error = None
            logger.info(f"Connector {self.connector_id}: QQ session resumed")
            return
        if not isinstance(event_type, str):
            return
        message = parse_event(self.connector_id, event_type, data)
        if message is None:
            logger.debug(f"Connector {self.connector_id}: ignored {event_type}")
            return
        # Content stays out of the log; the type tells which intent delivered it
        # and the sender tail tells accounts apart.
        logger.info(
            f"Connector {self.connector_id}: {event_type} ({message.chat_type}) "
            f"from ...{message.sender_id[-6:]}"
        )
        await on_message(self, message)

    @staticmethod
    async def _receive(websocket) -> dict[str, Any]:
        raw = await websocket.recv()
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise QQGatewayError("invalid gateway frame") from exc
        if not isinstance(frame, dict):
            raise QQGatewayError("invalid gateway frame")
        return frame

    @staticmethod
    async def _send(websocket, op: int, data: Any) -> None:
        await websocket.send(json.dumps({"op": op, "d": data}))

    async def close(self) -> None:
        await self._http.aclose()


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
