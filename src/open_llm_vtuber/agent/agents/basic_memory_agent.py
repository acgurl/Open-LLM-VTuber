from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Literal,
)
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from loguru import logger
from .agent_interface import AgentInterface
from ..output_types import SentenceOutput
from ..stateless_llm.stateless_llm_interface import (
    LLMError,
    LLMToolsUnsupportedError,
    StatelessLLMInterface,
)
from ..transformers import (
    sentence_divider,
    actions_extractor,
    tts_filter,
    display_processor,
)
from ..streaming import make_text_delta
from ...config_manager import TTSPreprocessorConfig
from ..input_types import BatchInput, TextSource
from prompts import prompt_loader
from ...mcpp.tool_manager import ToolManager
from ...mcpp.json_detector import StreamJSONDetector
from ...mcpp.types import ToolCallObject
from ...mcpp.tool_executor import ToolExecutor

# Default for ``basic_memory_agent.max_tool_rounds``: LLM requests per user turn
# in a tool loop. A model that keeps asking for tools (or a server that keeps
# failing) must not loop, and bill, without bound.
DEFAULT_MAX_TOOL_ROUNDS = 10
TOOL_ROUND_LIMIT_NOTICE = "[Stopped: too many consecutive tool calls]"
TOOL_EXECUTOR_MISSING_NOTICE = "[Error: ToolExecutor not configured]"


@dataclass
class _RoundOutcome:
    """What one streamed LLM round produced."""

    text: str = ""
    tool_calls: list[ToolCallObject] = field(default_factory=list)
    # Tool JSON detected in prompt mode.
    prompt_json: list[dict[str, Any]] | None = None
    switched_to_prompt: bool = False
    # The turn ends after this round (LLM error, no executor, no valid tool).
    finished: bool = False


class BasicMemoryAgent(AgentInterface):
    """Agent with basic chat memory and tool calling support."""

    _system: str = "You are a helpful assistant."
    # The prompt as given to set_system, before the interrupt note is added.
    _base_system: str = _system
    _max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS

    def __init__(
        self,
        llm: StatelessLLMInterface,
        system: str,
        live2d_model,
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        use_mcpp: bool = False,
        interrupt_method: Literal["system", "user"] = "user",
        tool_prompts: dict[str, str] | None = None,
        tool_manager: ToolManager | None = None,
        tool_executor: ToolExecutor | None = None,
        mcp_prompt_string: str = "",
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ):
        """Initialize agent with LLM and configuration."""
        super().__init__()
        self._memory = []
        self._live2d_model = live2d_model
        self._tts_preprocessor_config = tts_preprocessor_config
        self._faster_first_response = faster_first_response
        self._segment_method = segment_method
        self._use_mcpp = use_mcpp
        self._max_tool_rounds = max_tool_rounds
        self.interrupt_method = interrupt_method
        self._tool_prompts = tool_prompts or {}
        self._interrupt_handled = False
        # Tools go through the prompt (JSON in the reply) instead of the API.
        self.prompt_mode_flag = False
        # The current LLM refused native tools; later turns start in prompt
        # mode. Kept on the agent: the LLM client is shared between sessions.
        self._native_tools_refused = False

        self._tool_manager = tool_manager
        self._tool_executor = tool_executor
        self._mcp_prompt_string = mcp_prompt_string
        self._json_detector = StreamJSONDetector()

        self._tools = self._formatted_tools(self._tool_manager)
        logger.debug(f"Agent received {len(self._tools)} tool(s).")

        self._set_llm(llm)
        self.set_system(system if system else self._system)

        # The JSON detector is always created, so only the injected components
        # tell whether tooling was wired up.
        if self._use_mcpp and not all([self._tool_manager, self._tool_executor]):
            logger.warning(
                "use_mcpp is True, but some MCP components are missing in the agent. Tool calling might not work as expected."
            )
        elif not self._use_mcpp and any([self._tool_manager, self._tool_executor]):
            logger.warning(
                "use_mcpp is False, but some MCP components were passed to the agent."
            )

        logger.info("BasicMemoryAgent initialized.")

    @staticmethod
    def _formatted_tools(tool_manager: ToolManager | None) -> list[dict[str, Any]]:
        """The MCP tool definitions; each LLM backend sends them natively."""
        return tool_manager.get_formatted_tools() if tool_manager else []

    def _set_llm(self, llm: StatelessLLMInterface):
        """Set the LLM for chat completion."""
        self._llm = llm
        self.chat = self._chat_function_factory()

    @property
    def llm(self) -> StatelessLLMInterface:
        return self._llm

    def use_llm(
        self,
        llm: StatelessLLMInterface,
        interrupt_method: Literal["system", "user"] = "user",
    ) -> None:
        """Answer with another LLM from the next turn on; memory is kept."""
        if llm is not self._llm:
            self._native_tools_refused = False
        self._set_llm(llm)
        self.prompt_mode_flag = False
        if interrupt_method != self.interrupt_method:
            self.interrupt_method = interrupt_method
            self.set_system(self._base_system)

    def clone_for_session(
        self,
        system: str,
        live2d_model=None,
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        tool_manager: ToolManager | None = None,
        tool_executor: ToolExecutor | None = None,
        mcp_prompt_string: str = "",
        use_mcpp: bool | None = None,
    ) -> "BasicMemoryAgent":
        """Create an agent with independent memory that reuses this agent's LLM client."""
        return BasicMemoryAgent(
            llm=self._llm,
            system=system,
            live2d_model=(
                live2d_model if live2d_model is not None else self._live2d_model
            ),
            tts_preprocessor_config=(
                tts_preprocessor_config
                if tts_preprocessor_config is not None
                else self._tts_preprocessor_config
            ),
            faster_first_response=self._faster_first_response,
            segment_method=self._segment_method,
            use_mcpp=self._use_mcpp if use_mcpp is None else use_mcpp,
            interrupt_method=self.interrupt_method,
            tool_prompts=self._tool_prompts,
            tool_manager=tool_manager,
            tool_executor=tool_executor,
            mcp_prompt_string=mcp_prompt_string,
            max_tool_rounds=self._max_tool_rounds,
        )

    def set_tooling(
        self,
        tool_manager: ToolManager | None,
        tool_executor: ToolExecutor | None,
        mcp_prompt_string: str = "",
        *,
        enabled: bool = True,
    ) -> None:
        """Replace the tool set, e.g. after a browser registered a local MCP."""
        self._tool_manager = tool_manager
        self._tool_executor = tool_executor
        self._mcp_prompt_string = mcp_prompt_string
        self._use_mcpp = enabled
        self._tools = self._formatted_tools(tool_manager)

    def set_system(self, system: str):
        """Set the system prompt."""
        logger.debug(f"Memory Agent: Setting system prompt: '''{system}'''")
        self._base_system = system

        if self.interrupt_method == "user":
            system = f"{system}\n\nIf you received `[interrupted by user]` signal, you were interrupted."

        self._system = system

    def _tool_server_instructions(self) -> str:
        """MCP server instructions, only while this agent offers tools."""
        tool_manager = getattr(self, "_tool_manager", None)
        if not getattr(self, "_use_mcpp", False) or tool_manager is None:
            return ""
        return getattr(tool_manager, "server_instructions", "") or ""

    def _system_with_time(self) -> str:
        """System prompt plus the current Beijing time (fresh on every request)."""
        now = datetime.now(timezone(timedelta(hours=8)))
        weekday = "一二三四五六日"[now.weekday()]
        system = self._system
        instructions = self._tool_server_instructions()
        if instructions:
            system = f"{system}\n\n{instructions}"
        # Stated as public so the confidentiality rules in the security prompt
        # don't make the model deny knowing the time.
        return (
            f"{system}\n\n"
            f"## 当前时间\n"
            f"现在是北京时间 {now:%Y年%m月%d日} 星期{weekday} {now:%H:%M}。\n"
            "这是公开的环境信息，不属于保密内容：用户问日期、时间、星期，"
            "或说“今天/明天/现在”时，直接据此回答，无需调用工具。"
        )

    def _add_message(
        self,
        message: str | list[dict[str, Any]],
        role: str,
    ):
        """Add message to memory."""
        text_content = ""
        if isinstance(message, list):
            for item in message:
                if item.get("type") == "text":
                    text_content += item["text"] + " "
            text_content = text_content.strip()
        elif isinstance(message, str):
            text_content = message
        else:
            logger.warning(
                f"_add_message received unexpected message type: {type(message)}"
            )
            text_content = str(message)

        if not text_content and role == "assistant":
            return

        message_data = {
            "role": role,
            "content": text_content,
        }

        if (
            self._memory
            and self._memory[-1]["role"] == role
            and self._memory[-1]["content"] == text_content
        ):
            return

        self._memory.append(message_data)

    async def set_memory(
        self,
        messages: list[dict],
        metadata: dict | None = None,
    ) -> None:
        """Load memory from already-authorized persisted messages."""
        self._memory = []
        for msg in messages:
            if msg.get("role") == "system":
                continue
            role = "user" if msg.get("role") == "human" else "assistant"
            content = msg.get("content")
            if isinstance(content, str) and content:
                self._memory.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )
            else:
                logger.warning(f"Skipping invalid message from history: {msg}")
        logger.info(f"Loaded {len(self._memory)} messages from history.")

    async def _stream_with_text_deltas(
        self,
        stream: AsyncIterator[str | dict[str, Any]],
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Pass the raw agent stream through while emitting displayable text deltas.

        Prompt-mode replies may be tool JSON, which is not display text.
        """
        async for item in stream:
            if isinstance(item, str):
                if item and not self.prompt_mode_flag:
                    yield make_text_delta(item)
                yield item
            else:
                yield item

    def handle_interrupt(self, heard_response: str) -> None:
        """Handle user interruption."""
        if self._interrupt_handled:
            return

        self._interrupt_handled = True

        if self._memory and self._memory[-1]["role"] == "assistant":
            self._memory[-1]["content"] = heard_response + "..."
        elif heard_response:
            self._memory.append(
                {
                    "role": "assistant",
                    "content": heard_response + "...",
                }
            )

        interrupt_role = "system" if self.interrupt_method == "system" else "user"
        self._memory.append(
            {
                "role": interrupt_role,
                "content": "[Interrupted by user]",
            }
        )
        logger.info(f"Handled interrupt with role '{interrupt_role}'.")

    def _to_text_prompt(self, input_data: BatchInput) -> str:
        """Format input data to text prompt."""
        message_parts = []

        for text_data in input_data.texts:
            if text_data.source == TextSource.INPUT:
                message_parts.append(text_data.content)
            elif text_data.source == TextSource.CLIPBOARD:
                message_parts.append(
                    f"[User shared content from clipboard: {text_data.content}]"
                )

        if input_data.images:
            message_parts.append("\n[User has also provided images]")

        return "\n".join(message_parts).strip()

    def _to_messages(self, input_data: BatchInput) -> list[dict[str, Any]]:
        """Prepare messages for LLM API call."""
        messages = self._memory.copy()
        user_content = []
        text_prompt = self._to_text_prompt(input_data)
        if text_prompt:
            user_content.append({"type": "text", "text": text_prompt})

        if input_data.images:
            image_added = False
            for img_data in input_data.images:
                if isinstance(img_data.data, str) and img_data.data.startswith(
                    "data:image"
                ):
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": img_data.data, "detail": "auto"},
                        }
                    )
                    image_added = True
                else:
                    logger.error(
                        f"Invalid image data format: {type(img_data.data)}. Skipping image."
                    )

            if not image_added and not text_prompt:
                logger.warning(
                    "User input contains images but none could be processed."
                )

        if user_content:
            user_message = {"role": "user", "content": user_content}
            messages.append(user_message)

            skip_memory = False
            if input_data.metadata and input_data.metadata.get("skip_memory", False):
                skip_memory = True

            if not skip_memory:
                self._add_message(
                    text_prompt if text_prompt else "[User provided image(s)]", "user"
                )
        else:
            logger.warning("No content generated for user message.")

        return messages

    async def _drain_tool_executor(
        self,
        tool_executor_iterator: AsyncIterator[dict[str, Any]],
        results: list[dict[str, Any]],
        label: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Forward executor updates and collect the final tool results."""
        try:
            while True:
                update = await anext(tool_executor_iterator)
                if update.get("type") == "final_tool_results":
                    results.extend(update.get("results", []))
                    return
                yield update
        except StopAsyncIteration:
            logger.warning(f"{label} finished without final results marker.")

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCallObject] | list[dict[str, Any]],
        *,
        caller_mode: Literal["Native", "Prompt"],
        results: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Run tools, forwarding progress updates and collecting final results."""
        tool_executor_iterator = self._tool_executor.execute_tools(
            tool_calls=tool_calls,
            caller_mode=caller_mode,
        )
        async for update in self._drain_tool_executor(
            tool_executor_iterator, results, f"{caller_mode} tool executor"
        ):
            yield update

    @staticmethod
    def _tool_results_messages(
        caller_mode: Literal["Native", "Prompt"],
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Shape tool results as the next request's messages."""
        if caller_mode == "Prompt":
            result_strings = [
                res.get("content", "Error: Malformed result") for res in results
            ]
            return [{"role": "user", "content": "\n".join(result_strings)}]
        # Native results already are tool messages.
        return results

    def _missing_tool_executor_notice(self, caller_mode: str) -> str | None:
        """Return the error to show when tools were requested but cannot run."""
        if self._tool_executor:
            return None
        logger.error(
            f"{caller_mode} tool interaction requested but ToolExecutor is not available."
        )
        return TOOL_EXECUTOR_MISSING_NOTICE

    async def _run_tool_round(
        self,
        messages: list[dict[str, Any]],
        *,
        assistant_message: dict[str, Any],
        memory_text: str,
        tool_calls: list[ToolCallObject] | list[dict[str, Any]],
        caller_mode: Literal["Native", "Prompt"],
    ) -> AsyncIterator[dict[str, Any]]:
        """Record the tool-call turn, run the tools and feed the results back.

        Callers check ``_missing_tool_executor_notice`` first, so a turn that
        cannot run its tools leaves ``messages`` and memory untouched.
        """
        messages.append(assistant_message)
        if memory_text:
            self._add_message(memory_text, "assistant")

        results: list[dict[str, Any]] = []
        async for update in self._execute_tool_calls(
            tool_calls,
            caller_mode=caller_mode,
            results=results,
        ):
            yield update

        if results:
            messages.extend(self._tool_results_messages(caller_mode, results))

    def _round_request(
        self, tools: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]] | None]:
        """Return the system prompt and native tools for the next request."""
        system = self._system_with_time()
        if not self.prompt_mode_flag:
            return system, tools
        if not self._mcp_prompt_string:
            logger.warning("Prompt mode active but mcp_prompt_string is empty!")
            return system, None
        return f"{system}\n\n{self._mcp_prompt_string}", None

    def _enter_prompt_mode(self) -> None:
        self.prompt_mode_flag = True
        self._json_detector.reset()

    async def _stream_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        outcome: _RoundOutcome,
    ) -> AsyncIterator[str]:
        """Stream one LLM response into ``outcome``.

        Natively the LLM ends its stream with a list of ``ToolCallObject``; in
        prompt mode the text is scanned for tool JSON instead.
        """
        system_prompt, tools_for_api = self._round_request(tools)
        stream = self._llm.chat_completion(messages, system_prompt, tools=tools_for_api)
        try:
            async for event in stream:
                if isinstance(event, str):
                    outcome.text += event
                    if self.prompt_mode_flag:
                        detected = self._json_detector.process_chunk(event)
                        if detected:
                            outcome.prompt_json = detected
                            break
                    yield event
                elif not self.prompt_mode_flag and isinstance(event, list):
                    outcome.tool_calls = [
                        call for call in event if isinstance(call, ToolCallObject)
                    ]
                    break
        except LLMToolsUnsupportedError as error:
            if self.prompt_mode_flag:
                # No tools were sent, so there is nothing to fall back to.
                outcome.finished = True
                yield str(error)
                return
            logger.warning(
                f"LLM {getattr(self._llm, 'model', '')} has no native tool support. Switching to prompt mode."
            )
            self._native_tools_refused = True
            self._enter_prompt_mode()
            outcome.switched_to_prompt = True
        except LLMError as error:
            # Shown and spoken, but not remembered as something the AI said.
            outcome.finished = True
            yield str(error)

    async def _native_tool_round(
        self, messages: list[dict[str, Any]], outcome: _RoundOutcome
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Run the native tool calls of one round."""
        notice = self._missing_tool_executor_notice("Native")
        if notice:
            outcome.finished = True
            yield notice
            return

        assistant_message = {
            "role": "assistant",
            "content": outcome.text if outcome.text else None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in outcome.tool_calls
            ],
        }
        async for update in self._run_tool_round(
            messages,
            assistant_message=assistant_message,
            memory_text=outcome.text,
            tool_calls=outcome.tool_calls,
            caller_mode="Native",
        ):
            yield update

    async def _prompt_tool_round(
        self, messages: list[dict[str, Any]], outcome: _RoundOutcome
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Run the tool JSON a prompt-mode round produced."""
        logger.info("Processing tools detected via prompt mode JSON.")
        self._json_detector.reset()

        notice = self._missing_tool_executor_notice("Prompt")
        if notice:
            outcome.finished = True
            yield notice
            return

        parsed_tools = self._tool_executor.process_tool_from_prompt_json(
            outcome.prompt_json
        )
        if not parsed_tools:
            # JSON that names no runnable tool is the model's answer, as a
            # native turn without tool calls is; re-sending the same messages
            # would only repeat it up to the round limit.
            logger.warning("Prompt mode JSON contained no valid tool call.")
            self._add_message(outcome.text, "assistant")
            outcome.finished = True
            return

        # Keep the tool-call response in context, as native mode does.
        async for update in self._run_tool_round(
            messages,
            assistant_message={"role": "assistant", "content": outcome.text},
            memory_text=outcome.text,
            tool_calls=parsed_tools,
            caller_mode="Prompt",
        ):
            yield update

    async def _tool_interaction_loop(
        self,
        initial_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Chat with tools: request, run the tools asked for, repeat.

        One loop serves every LLM; each backend converts the messages built
        here to its own protocol.
        """
        messages = initial_messages.copy()

        for _round in range(self._max_tool_rounds):
            outcome = _RoundOutcome()
            async for text in self._stream_round(messages, tools, outcome):
                yield text
            if outcome.finished:
                return
            if outcome.switched_to_prompt:
                continue

            if outcome.prompt_json:
                tool_round = self._prompt_tool_round(messages, outcome)
            elif outcome.tool_calls:
                tool_round = self._native_tool_round(messages, outcome)
            else:
                if outcome.text:
                    self._add_message(outcome.text, "assistant")
                return

            async for item in tool_round:
                yield item
            if outcome.finished:
                return

        logger.warning(f"Tool loop stopped after {self._max_tool_rounds} rounds")
        yield TOOL_ROUND_LIMIT_NOTICE

    def _select_tools(self) -> list[dict[str, Any]] | None:
        """The tools of this turn, or ``None`` for plain chat."""
        if not (self._use_mcpp and self._tool_manager):
            return None
        if not self._tools:
            logger.warning("No tools available, despite MCP being enabled.")
        return self._tools

    async def _simple_chat(
        self, messages: list[dict[str, Any]]
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Stream a completion without tools and remember the reply."""
        logger.info("Starting simple chat completion.")
        token_stream = self._llm.chat_completion(messages, self._system_with_time())
        complete_response = ""
        try:
            async for event in token_stream:
                if isinstance(event, str) and event:
                    yield make_text_delta(event)
                    yield event
                    complete_response += event
        except LLMError as error:
            yield make_text_delta(str(error))
            yield str(error)
        if complete_response:
            self._add_message(complete_response, "assistant")

    def _chat_function_factory(
        self,
    ) -> Callable[[BatchInput], AsyncIterator[SentenceOutput | dict[str, Any]]]:
        """Create the chat pipeline function."""

        @tts_filter(self._tts_preprocessor_config)
        @display_processor()
        @actions_extractor(self._live2d_model)
        @sentence_divider(
            faster_first_response=self._faster_first_response,
            segment_method=self._segment_method,
            valid_tags=["think"],
        )
        async def chat_with_memory(
            input_data: BatchInput,
        ) -> AsyncIterator[str | dict[str, Any]]:
            """Process chat with memory and tools."""
            self.reset_interrupt()
            self.prompt_mode_flag = False

            messages = self._to_messages(input_data)
            tools = self._select_tools()

            if tools is None:
                stream = self._simple_chat(messages)
            else:
                logger.debug(f"Starting tool interaction loop with {len(tools)} tools.")
                if self._native_tools_refused:
                    self._enter_prompt_mode()
                stream = self._stream_with_text_deltas(
                    self._tool_interaction_loop(messages, tools)
                )

            async for output in stream:
                yield output

        return chat_with_memory

    async def chat(
        self,
        input_data: BatchInput,
    ) -> AsyncIterator[SentenceOutput | dict[str, Any]]:
        """Run chat pipeline."""
        chat_func_decorated = self._chat_function_factory()
        async for output in chat_func_decorated(input_data):
            yield output

    def reset_interrupt(self) -> None:
        """Reset interrupt flag."""
        self._interrupt_handled = False

    def start_group_conversation(
        self, human_name: str, ai_participants: list[str]
    ) -> None:
        """Start a group conversation."""
        if not self._tool_prompts:
            logger.warning("Tool prompts dictionary is not set.")
            return

        other_ais = ", ".join(name for name in ai_participants)
        prompt_name = self._tool_prompts.get("group_conversation_prompt", "")

        if not prompt_name:
            logger.warning("No group conversation prompt name found.")
            return

        try:
            group_context = prompt_loader.load_util(prompt_name).format(
                human_name=human_name, other_ais=other_ais
            )
            self._memory.append({"role": "user", "content": group_context})
        except FileNotFoundError:
            logger.error(f"Group conversation prompt file not found: {prompt_name}")
        except KeyError as e:
            logger.error(f"Missing formatting key in group conversation prompt: {e}")
        except Exception as e:
            logger.error(f"Failed to load group conversation prompt: {e}")
