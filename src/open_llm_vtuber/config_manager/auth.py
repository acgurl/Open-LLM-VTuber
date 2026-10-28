"""Authentication configuration.

``single`` keeps the historical behaviour where every connection uses
``storage.default_user_id``. ``oidc`` enables the standard OAuth authorization
code flow against an OpenID Connect provider (for example Casdoor).
"""

import os
import re
from typing import ClassVar, Dict, List, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from .i18n import Description, I18nMixin

_COOKIE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class OIDCConfig(BaseModel):
    """OpenID Connect client settings."""

    issuer: str = Field("", alias="issuer")
    client_id: str = Field("", alias="client_id")
    client_secret: str = Field("", alias="client_secret")
    redirect_uri: str = Field("", alias="redirect_uri")
    # Extra registered callbacks for the same client. Login picks the entry
    # whose host matches the request Host, so one deployment can answer on
    # several front-door domains (each keeps its own host-only session cookie).
    redirect_uris: List[str] = Field(default_factory=list, alias="redirect_uris")
    post_logout_redirect_uri: str = Field("", alias="post_logout_redirect_uri")
    scopes: List[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        alias="scopes",
    )
    token_auth_method: Literal["client_secret_post", "client_secret_basic"] = Field(
        "client_secret_post", alias="token_auth_method"
    )
    prompt: str | None = Field(None, alias="prompt")

    @staticmethod
    def _require_http_url(value: str, name: str) -> str:
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{name} must be an absolute HTTP(S) URL")
        return value

    @field_validator("issuer")
    @classmethod
    def check_issuer(cls, value: str) -> str:
        value = cls._require_http_url(value, "OIDC issuer")
        # Discovery is resolved relative to the issuer; a trailing slash is
        # harmless there and would otherwise produce a double slash.
        return value.rstrip("/")

    @field_validator("redirect_uri", "post_logout_redirect_uri")
    @classmethod
    def check_redirect_uri(cls, value: str) -> str:
        # Must match the provider registration byte-for-byte.
        return cls._require_http_url(value, "OIDC redirect URI")

    @field_validator("redirect_uris")
    @classmethod
    def check_redirect_uris(cls, value: List[str]) -> List[str]:
        uris = [
            cls._require_http_url(uri.strip(), "OIDC redirect URI")
            for uri in value
            if uri and uri.strip()
        ]
        return list(dict.fromkeys(uris))

    @model_validator(mode="after")
    def include_primary_redirect_uri(self) -> "OIDCConfig":
        if self.redirect_uri and self.redirect_uri not in self.redirect_uris:
            self.redirect_uris = [self.redirect_uri, *self.redirect_uris]
        return self

    @field_validator("scopes")
    @classmethod
    def check_scopes(cls, value: List[str]) -> List[str]:
        scopes = [scope.strip() for scope in value if scope and scope.strip()]
        if not scopes:
            raise ValueError("OIDC scopes must not be empty")
        if "openid" not in scopes:
            raise ValueError("OIDC scopes must include 'openid'")
        return scopes


class AuthConfig(I18nMixin):
    """Authentication settings for the WebSocket and HTTP entrypoints."""

    mode: Literal["single", "oidc"] = Field("single", alias="mode")
    signing_secret: str = Field(
        default_factory=lambda: os.getenv("VTUBER_AUTH_SECRET", ""),
        alias="signing_secret",
    )
    session_cookie_name: str = Field("vtuber_session", alias="session_cookie_name")
    session_max_age_days: int = Field(7, alias="session_max_age_days")
    state_cookie_name: str = Field("vtuber_oauth_state", alias="state_cookie_name")
    state_max_age_seconds: int = Field(600, alias="state_max_age_seconds")
    cookie_secure: bool = Field(True, alias="cookie_secure")
    max_connections_per_user: int = Field(4, alias="max_connections_per_user")
    archive_local_history: bool = Field(True, alias="archive_local_history")
    archive_dir: str = Field("data/storage/archive", alias="archive_dir")
    oidc: OIDCConfig = Field(default_factory=OIDCConfig, alias="oidc")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "mode": Description(
            en="Authentication mode: single user or OIDC",
            zh="认证模式：单用户或 OIDC",
        ),
        "signing_secret": Description(
            en="Secret used to sign session and OAuth state cookies",
            zh="用于签名会话与 OAuth state Cookie 的密钥",
        ),
        "session_cookie_name": Description(
            en="Session cookie name", zh="会话 Cookie 名称"
        ),
        "session_max_age_days": Description(
            en="Session lifetime in days", zh="会话有效期（天）"
        ),
        "state_cookie_name": Description(
            en="OAuth state cookie name", zh="OAuth state Cookie 名称"
        ),
        "state_max_age_seconds": Description(
            en="OAuth state lifetime in seconds", zh="OAuth state 有效期（秒）"
        ),
        "cookie_secure": Description(
            en="Mark authentication cookies as Secure", zh="认证 Cookie 是否标记 Secure"
        ),
        "max_connections_per_user": Description(
            en="Maximum concurrent WebSocket connections per user",
            zh="每个用户的最大并发 WebSocket 连接数",
        ),
        "archive_local_history": Description(
            en="Export the legacy single-user history before enabling OIDC",
            zh="启用 OIDC 前导出旧的单用户历史",
        ),
        "archive_dir": Description(
            en="Directory for the exported legacy history",
            zh="旧历史归档目录",
        ),
        "oidc": Description(
            en="OpenID Connect provider settings", zh="OpenID Connect 提供商设置"
        ),
    }

    @field_validator("session_cookie_name", "state_cookie_name")
    @classmethod
    def check_cookie_name(cls, value: str) -> str:
        if not _COOKIE_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "Cookie names must be 1-64 characters of letters, digits, "
                "dot, dash or underscore"
            )
        return value

    @field_validator("session_max_age_days")
    @classmethod
    def check_session_lifetime(cls, value: int) -> int:
        if value < 1 or value > 365:
            raise ValueError("session_max_age_days must be between 1 and 365")
        return value

    @field_validator("state_max_age_seconds")
    @classmethod
    def check_state_lifetime(cls, value: int) -> int:
        if value < 30 or value > 3600:
            raise ValueError("state_max_age_seconds must be between 30 and 3600")
        return value

    @field_validator("max_connections_per_user")
    @classmethod
    def check_connection_limit(cls, value: int) -> int:
        if value < 1 or value > 64:
            raise ValueError("max_connections_per_user must be between 1 and 64")
        return value

    @field_validator("archive_dir")
    @classmethod
    def check_archive_dir(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("archive_dir must not be empty")
        return value

    @model_validator(mode="after")
    def check_oidc_settings(self):
        if self.session_cookie_name == self.state_cookie_name:
            raise ValueError(
                "auth.session_cookie_name and auth.state_cookie_name must differ"
            )
        if self.mode != "oidc":
            return self

        if not self.signing_secret or "${" in self.signing_secret:
            raise ValueError(
                "auth.signing_secret is required in OIDC mode; set it in conf.yaml "
                "or export VTUBER_AUTH_SECRET"
            )

        oidc = self.oidc
        missing = [
            name
            for name in ("issuer", "client_id", "client_secret", "redirect_uri")
            if not getattr(oidc, name) or "${" in getattr(oidc, name)
        ]
        if missing:
            raise ValueError(
                "OIDC mode requires the following settings: "
                + ", ".join(f"auth.oidc.{name}" for name in missing)
            )
        return self
