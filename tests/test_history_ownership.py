"""Locking tests for turn history ownership and switch-config leaks (audit car C4)."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from open_llm_vtuber import service_context as service_context_module
from open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
from open_llm_vtuber.conversations import conversation_handler
from open_llm_vtuber.conversations import conversation_utils
from open_llm_vtuber.conversations import group_conversation
from open_llm_vtuber.conversations.conversation_utils import (
    bind_turn_history,
    consume_agent_stream,
)
from open_llm_vtuber.conversations.tts_manager import TTSTaskManager
from open_llm_vtuber.conversations.types import (
    GroupConversationState,
    OutboundChannels,
)
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.storage import SQLiteHistoryRepository


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def _member(history_uid: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        channels=None,
        user_id=None,
        agent_engine=Mock(),
        history_uid=history_uid,
        character_config=SimpleNamespace(
            character_name="AI", human_name="Human", avatar=""
        ),
        store_history_message=AsyncMock(),
    )


def _stored_uids(context) -> list:
    return [
        call.kwargs.get("history_uid")
        for call in context.store_history_message.await_args_list
    ]


class GroupTurnHistoryTests(unittest.IsolatedAsyncioTestCase):
    """D-GRP4: group writes go to the history bound at the start."""

    def tearDown(self) -> None:
        GroupConversationState.remove_state("group-c4")

    async def run_conversation(self, members: dict, metadata=None) -> None:
        async def switch_history_mid_turn(**_kwargs):
            for context in members.values():
                context.history_uid = "history-b"
            return "hello"

        with (
            patch.object(
                group_conversation,
                "process_group_input",
                new=AsyncMock(side_effect=switch_history_mid_turn),
            ),
            patch.object(group_conversation, "handle_group_member_turn", AsyncMock()),
        ):
            await group_conversation.process_group_conversation(
                client_contexts=members,
                client_connections={uid: FakeWebSocket() for uid in members},
                broadcast_func=AsyncMock(),
                group_members=list(members),
                initiator_client_uid="owner",
                group_id="group-c4",
                user_input="hello",
                metadata=metadata,
            )

    async def test_human_message_goes_to_the_bound_history(self):
        members = {"owner": _member("history-a"), "guest": _member("history-g")}

        await self.run_conversation(members)

        self.assertEqual(_stored_uids(members["owner"]), ["history-a"])
        self.assertEqual(_stored_uids(members["guest"]), ["history-g"])
        # consume_agent_stream reads this for the member's tool calls.
        self.assertEqual(members["owner"].turn_history_uid, "history-a")
        self.assertEqual(members["guest"].turn_history_uid, "history-g")

    async def test_proactive_group_turn_binds_no_history(self):
        members = {"owner": _member("history-a")}

        await self.run_conversation(members, metadata={"skip_history": True})

        members["owner"].store_history_message.assert_not_awaited()
        self.assertIsNone(members["owner"].turn_history_uid)

    async def test_ai_message_goes_to_the_bound_history(self):
        owner = _member("history-b")
        owner.turn_history_uid = "history-a"
        state = GroupConversationState(
            group_id="group-c4",
            conversation_history=["Human: hi"],
            memory_index={"owner": 0},
            group_queue=[],
        )

        with (
            patch.object(
                group_conversation,
                "process_member_response",
                new=AsyncMock(return_value="reply"),
            ),
            patch.object(
                conversation_utils.message_handler,
                "wait_for_response",
                new=AsyncMock(return_value={}),
            ),
        ):
            await group_conversation.handle_group_member_turn(
                current_member_uid="owner",
                state=state,
                client_contexts={"owner": owner},
                client_connections={"owner": FakeWebSocket()},
                broadcast_func=AsyncMock(),
                group_members=["owner"],
                images=None,
                tts_manager=TTSTaskManager(),
            )

        self.assertEqual(_stored_uids(owner), ["history-a"])

    async def run_interrupt(self, member) -> None:
        task = asyncio.create_task(asyncio.Event().wait())
        manager = Mock()
        manager.get_group_by_id.return_value = SimpleNamespace(members={"owner"})
        await conversation_handler.handle_group_interrupt(
            group_id="group-c4",
            heard_response="heard part",
            current_conversation_tasks={"group-c4": task},
            chat_group_manager=manager,
            client_contexts={"owner": member},
            broadcast_to_group=AsyncMock(),
        )

    async def test_group_interrupt_writes_to_the_bound_history(self):
        owner = _member("history-b")
        owner.turn_history_uid = "history-a"

        await self.run_interrupt(owner)

        self.assertEqual(_stored_uids(owner), ["history-a", "history-a"])

    async def test_proactive_group_interrupt_writes_nothing(self):
        owner = _member("history-b")
        owner.turn_history_uid = None

        await self.run_interrupt(owner)

        owner.store_history_message.assert_not_awaited()
        owner.agent_engine.handle_interrupt.assert_called_once_with("heard part")


class SkippedTurnToolCallTests(unittest.IsolatedAsyncioTestCase):
    """D-HIST1: a turn bound to no history stores no tool calls."""

    async def asyncSetUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.repository = SQLiteHistoryRepository(
            Path(self._temp_dir.name) / "history.db"
        )
        await self.repository.initialize()
        self.context = ServiceContext()
        self.context.character_config = SimpleNamespace(
            conf_uid="conf", character_name="AI", avatar=""
        )
        self.context.set_history_storage(self.repository, "local")
        self.context.history_uid = await self.context.history.create_history("conf")

    async def asyncTearDown(self):
        await self.repository.close()
        self._temp_dir.cleanup()

    async def run_tool_turn(self, metadata) -> None:
        async def stream():
            yield {
                "type": "tool_call_status",
                "tool_id": "t1",
                "tool_name": "kb_search",
                "status": "completed",
                "content": "{}",
            }

        bind_turn_history(self.context, metadata)
        await consume_agent_stream(
            stream(),
            context=self.context,
            channels=OutboundChannels.from_text(AsyncMock()),
            tts_manager=None,
            send_text_delta=AsyncMock(),
        )

    async def test_skip_history_turn_stores_no_tool_call(self):
        await self.run_tool_turn({"skip_history": True})

        self.assertEqual(await self.context.get_history_tool_calls(), [])

    async def test_normal_turn_still_stores_the_tool_call(self):
        await self.run_tool_turn(None)

        calls = await self.context.get_history_tool_calls()
        self.assertEqual([call["tool_id"] for call in calls], ["t1"])

    async def test_explicit_none_never_falls_back_to_the_open_history(self):
        stored = await self.context.store_history_tool_call(
            tool_id="t1", tool_name="x", status="completed", history_uid=None
        )
        await self.context.store_history_message("ai", "x", history_uid=None)

        self.assertFalse(stored)
        self.assertEqual(await self.context.get_history_tool_calls(), [])
        self.assertEqual(
            await self.context.history.get_history("conf", self.context.history_uid),
            [],
        )


class SwitchConfigLeakTests(unittest.IsolatedAsyncioTestCase):
    """D-CTX2: rebuilding MCP closes the old client and re-wires the agent."""

    def make_context(self) -> ServiceContext:
        context = ServiceContext()
        context.channels = None
        context.client_uid = "client"
        return context

    async def test_rebuild_closes_the_previous_mcp_client(self):
        context = self.make_context()
        previous = Mock()
        previous.aclose = AsyncMock()
        context.mcp_client = previous

        with (
            patch.object(service_context_module, "ServerRegistry"),
            patch.object(service_context_module, "ToolAdapter") as tool_adapter,
            patch.object(service_context_module, "ToolManager"),
            patch.object(service_context_module, "MCPClient") as mcp_client,
            patch.object(service_context_module, "ToolExecutor"),
        ):
            tool_adapter.return_value.build_tools = AsyncMock(
                return_value=("prompt", [], [], {})
            )
            await context._init_mcp_components(True, ["server"])

        previous.aclose.assert_awaited_once()
        self.assertIs(context.mcp_client, mcp_client.return_value)

    async def test_unchanged_agent_gets_the_rebuilt_tooling(self):
        context = self.make_context()
        agent_config = SimpleNamespace(
            conversation_agent_choice="basic_memory_agent",
            agent_settings=SimpleNamespace(
                basic_memory_agent=SimpleNamespace(use_mcpp=False)
            ),
        )
        context.character_config = SimpleNamespace(
            agent_config=agent_config, persona_prompt="persona"
        )
        agent = Mock(spec=BasicMemoryAgent)
        context.agent_engine = agent
        context.tool_manager = Mock()
        context.tool_executor = Mock()
        context.mcp_prompt = "mcp"
        context.mcp_active = True

        await context.init_agent(agent_config, "persona")

        self.assertIs(context.agent_engine, agent)
        agent.set_tooling.assert_called_once_with(
            context.tool_manager, context.tool_executor, "mcp", enabled=True
        )

    async def test_replaced_agent_is_closed(self):
        context = self.make_context()
        context.system_config = SimpleNamespace(tool_prompts={})
        context.character_config = SimpleNamespace(
            agent_config=Mock(),
            persona_prompt="old",
            avatar="",
            tts_preprocessor_config=None,
        )
        previous = Mock()
        previous.close = AsyncMock()
        context.agent_engine = previous
        replacement = Mock()

        with patch.object(
            service_context_module.AgentFactory,
            "create_agent",
            return_value=replacement,
        ):
            await context.init_agent(Mock(), "new")

        self.assertIs(context.agent_engine, replacement)
        previous.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
