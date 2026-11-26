"""Configuration for the CUC campus account binding proxy."""

from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ..mcpp.user_servers import validate_header_name, validate_user_prefix
from .i18n import Description, I18nMixin


class CucAuthConfig(I18nMixin):
    """Settings for proxying CUC campus authentication to cuc-server."""

    enabled: bool = Field(False, alias="enabled")
    server_url: str = Field("http://127.0.0.1:8787", alias="server_url")
    api_key: str = Field("", alias="api_key")
    user_header: str = Field("X-CUC-Profile", alias="user_header")
    user_prefix: str = Field("u_", alias="user_prefix")
    timeout_seconds: float = Field(35.0, alias="timeout_seconds", gt=0, le=120)

    DESCRIPTIONS: ClassVar[dict[str, Description]] = {
        "enabled": Description(
            en="Enable CUC campus account binding endpoints and UI",
            zh="启用传媒大学校园账号绑定接口与设置面板",
        ),
        "server_url": Description(
            en="Base URL of the internal cuc-server HTTP service",
            zh="内部 cuc-server HTTP 服务地址",
        ),
        "api_key": Description(
            en="API key for authenticating with cuc-server",
            zh="访问 cuc-server 的 API 密钥",
        ),
        "user_header": Description(
            en="Header used to forward the authenticated user profile to cuc-server",
            zh="向 cuc-server 传递用户隔离标识的请求头名称",
        ),
        "user_prefix": Description(
            en="Prefix prepended to the formatted user ID in user_header",
            zh="写入 user_header 的用户标识前缀",
        ),
        "timeout_seconds": Description(
            en="HTTP request timeout in seconds when talking to cuc-server",
            zh="请求 cuc-server 的超时时间（秒）",
        ),
    }

    @field_validator("server_url")
    @classmethod
    def check_server_url(cls, value: str) -> str:
        url = (value or "").strip().rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("cuc.server_url must be a valid http or https URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("cuc.server_url must not contain credentials or fragment")
        return url

    @field_validator("user_header")
    @classmethod
    def check_user_header(cls, value: str) -> str:
        return validate_header_name(value)

    @field_validator("user_prefix")
    @classmethod
    def check_user_prefix(cls, value: str) -> str:
        return validate_user_prefix(value)

    @model_validator(mode="after")
    def check_credentials(self) -> "CucAuthConfig":
        if self.enabled:
            # An unresolved ${VAR} means the environment variable is unset.
            if not self.api_key or "${" in self.api_key:
                raise ValueError("cuc.api_key is required when enabled")
        return self
