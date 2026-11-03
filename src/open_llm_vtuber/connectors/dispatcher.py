"""Route connector messages to per-user agent sessions.

Every message passes the same gate before it reaches the agent: the platform
account must be bound to a web account (``/bind`` with a code from the
logged-in web session), and that account must have logged in with an email in
``binding.allowed_email_domains``. The session then runs with that user's id,
so history, user MCP servers and character ACLs behave as in the browser.
"""

import asyncio
import json
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..auth import Identity
from ..config_manager.connectors import ConnectorsConfig
from ..conversations.conversation_utils import bind_turn_history, run_agent_turn
from ..conversations.types import OutboundChannels
from ..service_context import ServiceContext
from ..session_factory import build_session_context
from . import commands
from .base import Connector, InboundMessage
from .binding import BindCodeStore, user_eligible
from .formatting import clean_reply, live2d_tags, split_reply, strip_markdown

# Messages of one sender in one chat run in order; more than this many
# waiting turns get a "still busy" reply instead of piling up.
MAX_PENDING_PER_CHAT = 2
TURN_SLOT_WAIT_SECONDS = 30.0
RATE_LIMIT_WINDOW_SECONDS = 60.0
SEEN_MESSAGE_LIMIT = 4096
SWEEP_INTERVAL_SECONDS = 60.0
# Binding codes are single use, but one typed in a shared channel can still
# be redeemed by someone faster than its owner.
PRIVATE_CHAT_TYPES = frozenset({"direct", "c2c"})

SessionKey = tuple[str, str, str]
SessionBuilder = Callable[..., Awaitable[ServiceContext]]


@dataclass
class _ConnectorSession:
    user_id: str
    context: ServiceContext
    errors: list[str]
    last_used: float = field(default_factory=time.monotonic)


class ConnectorDispatcher:
    """Turns inbound platform messages into agent turns and replies."""

    def __init__(
        self,
        default_context_cache: ServiceContext,
        config: ConnectorsConfig,
        bind_codes: BindCodeStore,
        *,
        session_builder: SessionBuilder = build_session_context,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.default_context_cache = default_context_cache
        self.config = config
        self.bind_codes = bind_codes
        self._session_builder = session_builder
        self._clock = clock
        self._sessions: OrderedDict[SessionKey, _ConnectorSession] = OrderedDict()
        self._chat_locks: dict[SessionKey, asyncio.Lock] = {}
        self._pending: dict[SessionKey, int] = {}
        self._turn_slots = asyncio.Semaphore(config.max_concurrent_turns)
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._rate: dict[tuple[str, str], deque[float]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._sweeper: asyncio.Task | None = None
        # Text-only base context per connector (its own character and
        # prompts); sessions are cloned from it. Falls back to the default.
        self.base_contexts: dict[str, ServiceContext] = {}

    @property
    def repository(self):
        return self.default_context_cache.history_repository

    # ==== lifecycle

    def start(self) -> None:
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(self._sweep_forever())

    async def close(self) -> None:
        tasks = [*self._tasks]
        if self._sweeper is not None:
            tasks.append(self._sweeper)
            self._sweeper = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for key in list(self._sessions):
            await self._close_session(key)

    async def join(self) -> None:
        """Wait until every queued message has been handled."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                await self.sweep_idle()
            except Exception:
                logger.exception("Connector session sweep failed")

    async def sweep_idle(self) -> None:
        """Close sessions idle for longer than ``session_idle_seconds``."""
        cutoff = self._clock() - self.config.session_idle_seconds
        for key, session in list(self._sessions.items()):
            if session.last_used < cutoff and not self._busy(key):
                await self._close_session(key)

    # ==== inbound

    async def handle(self, connector: Connector, message: InboundMessage) -> None:
        """Queue ``message``; returns immediately so the connector keeps reading."""
        seen_key = (message.connector_id, message.message_id)
        if seen_key in self._seen:
            return
        self._seen[seen_key] = None
        if len(self._seen) > SEEN_MESSAGE_LIMIT:
            self._seen.popitem(last=False)

        task = asyncio.create_task(self._process(connector, message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _process(self, connector: Connector, message: InboundMessage) -> None:
        key: SessionKey = (message.connector_id, message.chat_key, message.sender_id)
        if self._pending.get(key, 0) >= MAX_PENDING_PER_CHAT:
            await self._reply(connector, message, commands.BUSY_TEXT)
            return

        self._pending[key] = self._pending.get(key, 0) + 1
        lock = self._chat_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                await self._handle_message(connector, message, key)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                f"Connector {message.connector_id}: failed to handle message"
            )
            await self._reply(connector, message, commands.ERROR_TEXT)
        finally:
            self._pending[key] -= 1
            if self._pending[key] <= 0:
                self._pending.pop(key, None)
                if not lock.locked():
                    self._chat_locks.pop(key, None)

    async def _handle_message(
        self, connector: Connector, message: InboundMessage, key: SessionKey
    ) -> None:
        text = message.text.strip()
        if not text:
            return
        repository = self.repository
        if repository is None:
            await self._reply(connector, message, commands.ERROR_TEXT)
            return

        command = commands.parse_command(text)
        if command is not None and command.name == "bind":
            await self._bind(connector, message, command.argument)
            return

        user_id = await repository.resolve_connector_identity(
            connector_id=message.connector_id,
            external_id=message.sender_id,
        )
        if command is not None and command.name == "help":
            await self._reply(
                connector, message, commands.help_text(bound=user_id is not None)
            )
            return
        if user_id is None:
            logger.info(f"{self._bind_tag(message)}: not bound, sent bind hint")
            await self._reply(
                connector,
                message,
                commands.unbound_text(self.config.binding.web_url),
            )
            return

        # Checked on every message, not only at bind time, so narrowing the
        # allowed domains takes effect for existing bindings.
        profile = await repository.get_user_profile(user_id=user_id)
        if not user_eligible(profile, self.config.binding.allowed_email_domains):
            await self._reply(connector, message, commands.INELIGIBLE_TEXT)
            return

        if command is not None:
            await self._run_command(connector, message, key, command, user_id, profile)
            return

        if len(text) > self.config.max_input_chars:
            await self._reply(connector, message, commands.TOO_LONG_TEXT)
            return
        if self._rate_limited(message):
            await self._reply(connector, message, commands.RATE_LIMITED_TEXT)
            return

        try:
            await asyncio.wait_for(
                self._turn_slots.acquire(), timeout=TURN_SLOT_WAIT_SECONDS
            )
        except asyncio.TimeoutError:
            await self._reply(connector, message, commands.SERVER_BUSY_TEXT)
            return
        try:
            session = await self._get_session(key, message, user_id, profile)
            reply = await self._run_turn(session, text)
        finally:
            self._turn_slots.release()
        await self._reply(connector, message, reply)

    # ==== commands

    @staticmethod
    def _bind_tag(message: InboundMessage) -> str:
        return f"Connector {message.connector_id} (...{message.sender_id[-6:]})"

    async def _bind(
        self, connector: Connector, message: InboundMessage, code: str
    ) -> None:
        if message.chat_type not in PRIVATE_CHAT_TYPES:
            logger.info(f"{self._bind_tag(message)}: /bind refused, not a private chat")
            await self._reply(connector, message, "请私聊我发送 /bind 绑定码。")
            return
        if not code:
            await self._reply(connector, message, commands.BIND_USAGE_TEXT)
            return

        attempt_key = f"{message.connector_id}:{message.sender_id}"
        if self.bind_codes.is_locked(attempt_key):
            logger.info(f"{self._bind_tag(message)}: /bind refused, locked")
            await self._reply(connector, message, commands.BIND_LOCKED_TEXT)
            return
        user_id = self.bind_codes.redeem(code, attempt_key)
        if user_id is None:
            locked = self.bind_codes.is_locked(attempt_key)
            logger.info(
                f"{self._bind_tag(message)}: /bind code rejected "
                f"(unknown, expired or already used)"
                f"{'; account now locked' if locked else ''}"
            )
            text = commands.BIND_LOCKED_TEXT if locked else commands.BIND_FAILED_TEXT
            await self._reply(connector, message, text)
            return

        profile = await self.repository.get_user_profile(user_id=user_id)
        if not user_eligible(profile, self.config.binding.allowed_email_domains):
            logger.info(
                f"{self._bind_tag(message)}: /bind refused, web user {user_id} "
                f"has no email in the allowed domains"
            )
            await self._reply(connector, message, commands.INELIGIBLE_TEXT)
            return

        await self.repository.bind_connector_identity(
            connector_id=message.connector_id,
            external_id=message.sender_id,
            user_id=user_id,
            display_name=message.sender_name,
        )
        # Sessions of a previous binding must not keep the old user's memory.
        await self.close_sender_sessions(message.connector_id, message.sender_id)
        logger.info(
            f"{self._bind_tag(message)}: bound a platform account to user {user_id}"
        )
        await self._reply(connector, message, commands.BIND_OK_TEXT)

    async def _run_command(
        self,
        connector: Connector,
        message: InboundMessage,
        key: SessionKey,
        command: commands.Command,
        user_id: str,
        profile: dict | None,
    ) -> None:
        if command.name == "unbind":
            await self.repository.delete_connector_identity(
                user_id=user_id,
                connector_id=message.connector_id,
                external_id=message.sender_id,
            )
            await self.close_sender_sessions(message.connector_id, message.sender_id)
            await self._reply(connector, message, commands.UNBIND_OK_TEXT)
        elif command.name == "whoami":
            name = (profile or {}).get("display_name") or user_id
            await self._reply(connector, message, f"已绑定网页账号：{name}")
        elif command.name == "new":
            session = await self._get_session(key, message, user_id, profile)
            await self._start_new_history(session.context, message)
            await self._reply(connector, message, commands.NEW_CHAT_TEXT)

    # ==== sessions

    def _busy(self, key: SessionKey) -> bool:
        lock = self._chat_locks.get(key)
        return self._pending.get(key, 0) > 0 or (lock is not None and lock.locked())

    async def _get_session(
        self,
        key: SessionKey,
        message: InboundMessage,
        user_id: str,
        profile: dict | None,
    ) -> _ConnectorSession:
        session = self._sessions.get(key)
        if session is not None and session.user_id == user_id:
            self._sessions.move_to_end(key)
            session.last_used = self._clock()
            return session
        if session is not None:
            await self._close_session(key)
        await self._evict_for_new_session()

        errors: list[str] = []
        context = await self._session_builder(
            self.base_contexts.get(message.connector_id, self.default_context_cache),
            channels=_headless_channels(errors),
            client_uid=f"connector-{uuid.uuid4().hex}",
            identity=Identity(
                user_id=user_id,
                display_name=(profile or {}).get("display_name"),
                provider=f"connector:{message.connector_id}",
            ),
            include_local_mcp=False,
        )
        try:
            await self._open_history(context, message)
        except BaseException:
            await context.close()
            raise
        session = _ConnectorSession(user_id, context, errors, self._clock())
        self._sessions[key] = session
        return session

    async def _evict_for_new_session(self) -> None:
        while len(self._sessions) >= self.config.max_sessions:
            idle = [key for key in self._sessions if not self._busy(key)]
            if not idle:
                return
            # OrderedDict keeps least recently used first.
            await self._close_session(idle[0])

    async def _close_session(self, key: SessionKey) -> None:
        session = self._sessions.pop(key, None)
        if session is None:
            return
        try:
            await session.context.close()
        except Exception:
            logger.exception("Failed to close connector session")

    async def close_sender_sessions(self, connector_id: str, sender_id: str) -> None:
        for key in list(self._sessions):
            if key[0] == connector_id and key[2] == sender_id:
                await self._close_session(key)

    async def _open_history(
        self, context: ServiceContext, message: InboundMessage
    ) -> None:
        """Continue the chat's history, or start one for a new chat."""
        history_uid = await self.repository.get_connector_conversation(
            connector_id=message.connector_id,
            chat_key=message.chat_key,
            user_id=context.user_id,
            conf_uid=context.character_config.conf_uid,
        )
        if history_uid:
            try:
                await context.load_history(history_uid)
                return
            except ValueError:
                logger.warning("Connector history mapping is stale; starting anew")
        await self._start_new_history(context, message)

    async def _start_new_history(
        self, context: ServiceContext, message: InboundMessage
    ) -> None:
        conf_uid = context.character_config.conf_uid
        history_uid = await context.history.create_history(conf_uid)
        await self.repository.set_connector_conversation(
            connector_id=message.connector_id,
            chat_key=message.chat_key,
            user_id=context.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )
        if context.history_uid:
            await context.agent_engine.set_memory([], {})
        context.history_uid = history_uid

    # ==== turns

    def _rate_limited(self, message: InboundMessage) -> bool:
        window = self._rate.setdefault(
            (message.connector_id, message.sender_id), deque()
        )
        now = self._clock()
        while window and window[0] <= now - RATE_LIMIT_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= self.config.rate_limit_per_minute:
            return True
        window.append(now)
        return False

    async def _run_turn(self, session: _ConnectorSession, text: str) -> str:
        context = session.context
        session.errors.clear()
        turn_history_uid = bind_turn_history(context, None)
        streamed = _StreamedText()
        try:
            reply = await asyncio.wait_for(
                run_agent_turn(
                    context,
                    channels=context.channels,
                    tts_manager=None,
                    input_text=text,
                    turn_history_uid=turn_history_uid,
                    send_text_delta=streamed.collect,
                ),
                timeout=self.config.reply_timeout_seconds,
            )
        except asyncio.TimeoutError:
            if not context.turn_response_persisted:
                try:
                    context.agent_engine.handle_interrupt("")
                except Exception:
                    logger.exception("Failed to reset agent after timeout")
            return commands.TIMEOUT_TEXT
        finally:
            session.last_used = self._clock()

        # Chat apps show raw text; markup only adds noise.
        # The streamed text keeps the model's line breaks; the sentence-split
        # reply does not, and line breaks carry the structure in plain text.
        raw = streamed.text or reply
        cleaned = strip_markdown(clean_reply(raw, live2d_tags(context.live2d_model)))
        if cleaned:
            return cleaned
        return commands.ERROR_TEXT if session.errors else commands.EMPTY_REPLY_TEXT

    async def _reply(
        self, connector: Connector, message: InboundMessage, text: str
    ) -> None:
        capabilities = connector.capabilities
        parts = split_reply(
            text,
            capabilities.max_message_chars,
            capabilities.max_replies_per_message,
        )
        for index, part in enumerate(parts):
            try:
                await connector.send_text(message, part, index)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    f"Connector {message.connector_id}: reply failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                return


def _headless_channels(errors: list[str]) -> OutboundChannels:
    """Channels for a session without a browser: keep errors, drop the rest."""

    async def send_text(data: str) -> None:
        try:
            payload = json.loads(data)
        except (TypeError, ValueError):
            return
        if isinstance(payload, dict) and payload.get("type") == "error":
            errors.append(str(payload.get("message") or ""))

    async def send_audio(_data: str) -> None:
        return None

    return OutboundChannels(text=send_text, audio=send_audio)


class _StreamedText:
    """Keeps the latest accumulated text of a turn's ``text-delta`` events."""

    def __init__(self) -> None:
        self.text = ""

    async def collect(self, message: dict[str, Any]) -> None:
        if message.get("type") == "text-delta":
            full_text = message.get("full_text")
            if isinstance(full_text, str):
                self.text = full_text
