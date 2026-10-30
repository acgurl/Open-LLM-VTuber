"""User-bound facade over a HistoryRepository."""

from typing import Literal

from .base import (
    HistoryMessage,
    HistoryRepository,
    ToolCallRecord,
    validate_user_id,
)


class UserHistoryStore:
    """All history operations for one user.

    Runtime code receives this object instead of a raw repository, so it cannot
    accidentally omit the user id and touch another user's data.
    """

    def __init__(self, repository: HistoryRepository, user_id: str) -> None:
        self.repository = repository
        self.user_id = validate_user_id(user_id)

    async def create_history(
        self, conf_uid: str, history_uid: str | None = None
    ) -> str:
        return await self.repository.create_history(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )

    async def history_exists(self, conf_uid: str, history_uid: str) -> bool:
        return await self.repository.history_exists(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )

    async def list_histories(self, conf_uid: str) -> list[dict]:
        return await self.repository.list_histories(
            user_id=self.user_id,
            conf_uid=conf_uid,
        )

    async def get_history(
        self, conf_uid: str, history_uid: str
    ) -> list[HistoryMessage]:
        return await self.repository.get_history(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )

    async def store_message(
        self,
        conf_uid: str,
        history_uid: str,
        role: Literal["human", "ai", "system"],
        content: str,
        name: str | None = None,
        avatar: str | None = None,
    ) -> None:
        if not history_uid:
            return
        await self.repository.store_message(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
            role=role,
            content=content,
            name=name,
            avatar=avatar,
        )

    async def get_metadata(self, conf_uid: str, history_uid: str) -> dict:
        return await self.repository.get_metadata(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )

    async def store_tool_call(
        self,
        conf_uid: str,
        history_uid: str,
        *,
        tool_id: str,
        tool_name: str,
        status: str,
        content: str = "",
        timestamp: str | None = None,
    ) -> None:
        if not history_uid:
            return
        await self.repository.store_tool_call(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
            tool_id=tool_id,
            tool_name=tool_name,
            status=status,
            content=content,
            timestamp=timestamp,
        )

    async def list_tool_calls(
        self, conf_uid: str, history_uid: str
    ) -> list[ToolCallRecord]:
        if not history_uid:
            return []
        return await self.repository.list_tool_calls(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )

    async def update_metadata(
        self, conf_uid: str, history_uid: str, metadata: dict
    ) -> bool:
        if not history_uid:
            return False
        return await self.repository.update_metadata(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
            metadata=metadata,
        )

    async def delete_history(self, conf_uid: str, history_uid: str) -> bool:
        return await self.repository.delete_history(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
        )

    async def modify_latest_message(
        self,
        conf_uid: str,
        history_uid: str,
        role: Literal["human", "ai", "system"],
        new_content: str,
    ) -> bool:
        return await self.repository.modify_latest_message(
            user_id=self.user_id,
            conf_uid=conf_uid,
            history_uid=history_uid,
            role=role,
            new_content=new_content,
        )

    async def rename_history(
        self, conf_uid: str, old_history_uid: str, new_history_uid: str
    ) -> bool:
        return await self.repository.rename_history(
            user_id=self.user_id,
            conf_uid=conf_uid,
            old_history_uid=old_history_uid,
            new_history_uid=new_history_uid,
        )
