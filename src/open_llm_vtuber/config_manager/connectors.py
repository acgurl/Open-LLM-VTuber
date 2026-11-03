"""Message connector configuration.

Connectors attach the backend to messaging platforms. ``instances`` are the
deployment-managed (global) bots; their users must bind the platform account
to a web account whose login email is in ``binding.allowed_email_domains``
before the bot answers them. Credentials belong in environment variables
(``${QQ_BOT_SECRET}``), never in the repository.
"""

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .i18n import Description, I18nMixin

_CONNECTOR_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")

QQIntent = Literal[
    # @bot messages in public guild channels
    "public_guild_messages",
    # every message in private guild channels (requires the private-bot flag)
    "guild_messages",
    # guild direct messages
    "direct_message",
    # group @bot messages and single (C2C) chats
    "group_and_c2c",
]


class BindingConfig(BaseModel):
    """How platform accounts are tied to web accounts for global bots."""

    allowed_email_domains: list[str] = Field(
        default_factory=lambda: ["cuc.edu.cn"], alias="allowed_email_domains"
    )
    code_ttl_seconds: int = Field(600, alias="code_ttl_seconds", ge=60, le=3600)
    # Shown to unbound users so they know where to get a code. Some platforms
    # drop replies that contain links not registered with them; leave empty
    # to only mention the site name.
    web_url: str = Field("", alias="web_url")

    @field_validator("allowed_email_domains")
    @classmethod
    def check_domains(cls, value: list[str]) -> list[str]:
        domains = []
        for domain in value:
            normalized = domain.strip().lower().lstrip("@").rstrip(".")
            if not _DOMAIN_PATTERN.fullmatch(normalized):
                raise ValueError(f"Invalid email domain: {domain!r}")
            domains.append(normalized)
        return list(dict.fromkeys(domains))


class QQConnectorConfig(BaseModel):
    """QQ official bot (bot.q.qq.com, API v2) over the WebSocket gateway."""

    type: Literal["qq"] = Field("qq", alias="type")
    id: str = Field(..., alias="id")
    enabled: bool = Field(False, alias="enabled")
    name: str = Field("QQ", alias="name")
    app_id: str = Field("", alias="app_id")
    app_secret: str = Field("", alias="app_secret")
    sandbox: bool = Field(False, alias="sandbox")
    # REST calls (token + sending replies) are retried on timeouts, connection
    # errors and 502/503/504. http_retries counts extra attempts after the
    # first; the wait before retry n is retry_backoff_seconds * 2 ** (n - 1).
    request_timeout_seconds: float = Field(8.0, alias="request_timeout_seconds", gt=0)
    http_retries: int = Field(3, alias="http_retries", ge=0, le=10)
    retry_backoff_seconds: float = Field(0.5, alias="retry_backoff_seconds", ge=0)
    intents: list[QQIntent] = Field(
        default_factory=lambda: ["public_guild_messages", "direct_message"],
        alias="intents",
    )
    # Partial character_config deep-merged over the base character in
    # conf.yaml: the bot can have its own name, persona and conf_uid (its
    # histories are kept under that conf_uid). Live2D, ASR and TTS settings
    # are ignored; connector sessions are text-only.
    character: dict[str, Any] = Field(default_factory=dict, alias="character")
    # Replaces system_config.tool_prompts for this bot. None keeps the
    # system prompts except the Live2D expression prompt.
    tool_prompts: dict[str, str] | None = Field(None, alias="tool_prompts")

    @field_validator("id")
    @classmethod
    def check_id(cls, value: str) -> str:
        if not _CONNECTOR_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "connector id must be 1-32 lowercase letters, digits, '-' or '_'"
            )
        return value

    @field_validator("intents")
    @classmethod
    def check_intents(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("QQ connector needs at least one intent")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def check_credentials(self) -> "QQConnectorConfig":
        if self.enabled:
            for name in ("app_id", "app_secret"):
                value = getattr(self, name)
                # An unresolved ${VAR} means the environment variable is unset.
                if not value or "${" in value:
                    raise ValueError(
                        f"connector {self.id}: {name} is required when enabled"
                    )
        return self


class ConnectorsConfig(I18nMixin):
    """Message connector settings."""

    enabled: bool = Field(False, alias="enabled")
    binding: BindingConfig = Field(default_factory=BindingConfig, alias="binding")
    reply_timeout_seconds: int = Field(
        180, alias="reply_timeout_seconds", ge=10, le=900
    )
    max_concurrent_turns: int = Field(4, alias="max_concurrent_turns", ge=1, le=32)
    max_sessions: int = Field(64, alias="max_sessions", ge=1, le=1024)
    session_idle_seconds: int = Field(
        1800, alias="session_idle_seconds", ge=60, le=86400
    )
    max_input_chars: int = Field(2000, alias="max_input_chars", ge=1, le=4000)
    rate_limit_per_minute: int = Field(10, alias="rate_limit_per_minute", ge=1)
    instances: list[QQConnectorConfig] = Field(default_factory=list, alias="instances")

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "enabled": Description(
            en="Start the configured message connectors",
            zh="启动已配置的消息平台连接器",
        ),
        "binding": Description(
            en="Account binding rules for global bots",
            zh="全局机器人的账号绑定规则",
        ),
        "reply_timeout_seconds": Description(
            en="Give up on a reply after this many seconds",
            zh="单轮回复的超时时间（秒）",
        ),
        "max_concurrent_turns": Description(
            en="Connector turns that may run at the same time",
            zh="连接器同时运行的对话轮数上限",
        ),
        "max_sessions": Description(
            en="Connector sessions kept in memory",
            zh="内存中保留的连接器会话上限",
        ),
        "session_idle_seconds": Description(
            en="Close a connector session after this idle time",
            zh="连接器会话空闲多久后释放（秒）",
        ),
        "max_input_chars": Description(
            en="Longest accepted platform message",
            zh="接受的平台消息最大长度",
        ),
        "rate_limit_per_minute": Description(
            en="Messages per platform account per minute",
            zh="每个平台账号每分钟可发送的消息数",
        ),
        "instances": Description(
            en="Deployment-managed bots", zh="部署方管理的全局机器人"
        ),
    }

    @field_validator("instances")
    @classmethod
    def check_unique_ids(
        cls, value: list[QQConnectorConfig]
    ) -> list[QQConnectorConfig]:
        seen: set[str] = set()
        for instance in value:
            if instance.id in seen:
                raise ValueError(f"Duplicate connector id: {instance.id}")
            seen.add(instance.id)
        return value
