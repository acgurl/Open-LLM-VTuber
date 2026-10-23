"""Storage configuration for chat history."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class StorageConfig(BaseModel):
    """History storage settings.

    ``backend`` is intentionally limited to the implemented adapters. Adding a
    database backend means implementing ``HistoryRepository``, registering it
    in ``storage.factory``, and extending this literal.
    """

    backend: Literal["sqlite"] = Field("sqlite", alias="backend")
    sqlite_path: str = Field("data/storage/open_llm_vtuber.db", alias="sqlite_path")
    default_user_id: str = Field("local", alias="default_user_id")
    import_legacy_history: bool = Field(True, alias="import_legacy_history")
    legacy_history_dir: str = Field("chat_history", alias="legacy_history_dir")
    legacy_backup_dir: str = Field(
        "data/storage/legacy_history", alias="legacy_backup_dir"
    )

    @field_validator("sqlite_path", "legacy_history_dir", "legacy_backup_dir")
    @classmethod
    def check_non_empty_path(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Storage paths must not be empty")
        return value

    @field_validator("default_user_id")
    @classmethod
    def check_default_user_id(cls, value: str) -> str:
        if not _USER_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "default_user_id must be 1-64 characters of letters, digits, "
                "dot, dash or underscore"
            )
        return value
