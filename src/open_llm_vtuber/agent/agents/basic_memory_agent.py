from typing import (
    Any,
    Literal,
)
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from loguru import logger
from .agent_interface import AgentInterface
from ..output_types import SentenceOutput
from ..stateless_llm.stateless_llm_interface import StatelessLLMInterface
from ..stateless_llm.claude_llm import AsyncLLM as ClaudeAsyncLLM
from ..stateless_llm.openai_compatible_llm import AsyncLLM as OpenAICompatibleAsyncLLM
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
    tool_calls: list[Any] = field(default_factory=list)
    # Claude assistant content blocks (text and tool_use), in stream order.
    content: list[dict[str, Any]] = field(default_factory=list)
    # Tool JSON detected in prompt mode.
    prompt_json: list[dict[str, Any]] | None = None
    switched_to_prompt: bool = False
    # The turn ends after this round (LLM error, no executor, no valid tool).
    finished: bool = False


class BasicMemoryAgent(AgentInterface):
    """Agent with basic chat memory and tool calling support."""

    _system: str = "You are a helpful assistant."
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
        self.prompt_mode_flag = False

        self._tool_manager = tool_manager
        self._tool_executor = tool_executor
        self._mcp_prompt_string = mcp_prompt_string
        self._json_detector = StreamJSONDetector()

        self._formatted_tools_openai = []
        self._formatted_tools_claude = []
        if self._tool_manager:
            self._formatted_tools_openai = self._tool_manager.get_formatted_tools(
                "OpenAI"
            )
            self._formatted_tools_claude = self._tool_manager.get_formatted_tools(
                "Claude"
            )
            logger.debug(
                f"Agent received pre-formatted tools - OpenAI: {len(self._formatted_tools_openai)}, Claude: {len(self._formatted_tools_claude)}"
            )
        else:
            logger.debug(
                "ToolManager not provided, agent will not have pre-formatted tools."
            )

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

    def _set_llm(self, llm: StatelessLLMInterface):
        """Set the LLM for chat completion."""
        self._llm = llm
        self.chat = self._chat_function_factory()

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
        self._formatted_tools_openai = (
            tool_manager.get_formatted_tools("OpenAI") if tool_manager else []
        )
        self._formatted_tools_claude = (
            tool_manager.get_formatted_tools("Claude") if tool_manager else []
        )

    def set_system(self, system: str):
        """Set the system prompt."""
        logger.debug(f"Memory Agent: Setting system prompt: '''{system}'''")

        if self.interrupt_method == "user":
            system = f"{system}\n\nIf you received `[interrupted by user]` signal, you were interrupted."

        self._system = system

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
        enabled: Callable[[], bool] = lambda: True,
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Pass the raw agent stream through while emitting displayable text deltas."""
        async for item in stream:
            if isinstance(item, str):
                if enabled() and item:
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
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
        label: str,
        results: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Run tools, forwarding progress updates and collecting final results."""
        tool_executor_iterator = self._tool_executor.execute_tools(
            tool_calls=tool_calls,
            caller_mode=caller_mode,
        )
        async for update in self._drain_tool_executor(
            tool_executor_iterator, results, label
        ):
            yield update

    @staticmethod
    def _tool_results_messages(
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Shape tool results as the next request's messages for each mode."""
        if caller_mode == "Claude":
            return [{"role": "user", "content": results}]
        if caller_mode == "Prompt":
            result_strings = [
                res.get("content", "Error: Malformed result") for res in results
            ]
            return [{"role": "user", "content": "\n".join(result_strings)}]
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
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
        label: str,
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
            label=label,
            results=results,
        ):
            yield update

        if results:
            messages.extend(self._tool_results_messages(caller_mode, results))

    async def _stream_claude_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        outcome: _RoundOutcome,
    ) -> AsyncIterator[str]:
        """Stream one Claude response, collecting text and tool_use blocks."""
        stream = self._llm.chat_completion(messages, self._system, tools=tools)
        async for event in stream:
            if event["type"] == "text_delta":
                text = event["text"]
                outcome.text += text
                yield text
                if not outcome.content or outcome.content[-1]["type"] != "text":
                    outcome.content.append({"type": "text", "text": text})
                else:
                    outcome.content[-1]["text"] += text
            elif event["type"] == "tool_use_complete":
                tool_call_data = event["data"]
                logger.info(
                    f"Tool request: {tool_call_data['name']} (ID: {tool_call_data['id']})"
                )
                outcome.tool_calls.append(tool_call_data)
                outcome.content.append(
                    {
                        "type": "tool_use",
                        "id": tool_call_data["id"],
                        "name": tool_call_data["name"],
                        "input": tool_call_data["input"],
                    }
                )
            elif event["type"] == "message_stop":
                break
            elif event["type"] == "error":
                logger.error(f"LLM API Error: {event['message']}")
                outcome.finished = True
                yield f"[Error from LLM: {event['message']}]"
                return

    async def _claude_tool_interaction_loop(
        self,
        initial_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Handle Claude interaction loop with tool support."""
        messages = initial_messages.copy()

        for _round in range(self._max_tool_rounds):
            outcome = _RoundOutcome()
            async for text in self._stream_claude_round(messages, tools, outcome):
                yield text
            if outcome.finished:
                return

            if not outcome.tool_calls:
                if outcome.text:
                    self._add_message(outcome.text, "assistant")
                return

            notice = self._missing_tool_executor_notice("Claude")
            if notice:
                yield notice
                return

            # Whitespace-only text blocks are dropped from the Claude request
            # and the remembered text is stripped; the OpenAI paths keep the
            # raw streamed text. The difference is long-standing and kept.
            assistant_content = [
                block
                for block in outcome.content
                if not (
                    block.get("type") == "text" and not block.get("text", "").strip()
                )
            ]
            memory_text = "".join(
                block["text"] for block in assistant_content if block["type"] == "text"
            ).strip()
            async for update in self._run_tool_round(
                messages,
                assistant_message={"role": "assistant", "content": assistant_content},
                memory_text=memory_text,
                tool_calls=outcome.tool_calls,
                caller_mode="Claude",
                label="Tool executor",
            ):
                yield update

        logger.warning(f"Claude tool loop stopped after {self._max_tool_rounds} rounds")
        yield TOOL_ROUND_LIMIT_NOTICE

    def _openai_round_request(
        self, tools: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]] | None]:
        """Return the system prompt and native tools for the next request."""
        if not self.prompt_mode_flag:
            return self._system, tools
        if not self._mcp_prompt_string:
            logger.warning("Prompt mode active but mcp_prompt_string is empty!")
            return self._system, None
        return f"{self._system}\n\n{self._mcp_prompt_string}", None

    async def _stream_openai_round(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        outcome: _RoundOutcome,
    ) -> AsyncIterator[str]:
        """Stream one OpenAI-compatible response into ``outcome``.

        In prompt mode the text is scanned for tool JSON; natively the LLM
        yields a list of ``ToolCallObject``.
        """
        system_prompt, tools_for_api = self._openai_round_request(tools)
        stream = self._llm.chat_completion(messages, system_prompt, tools=tools_for_api)
        async for event in stream:
            if self.prompt_mode_flag:
                if isinstance(event, str):
                    outcome.text += event
                    detected = self._json_detector.process_chunk(event)
                    if detected:
                        outcome.prompt_json = detected
                        break
                    yield event
            elif event == "__API_NOT_SUPPORT_TOOLS__":
                logger.warning(
                    f"LLM {getattr(self._llm, 'model', '')} has no native tool support. Switching to prompt mode."
                )
                self.prompt_mode_flag = True
                self._json_detector.reset()
                outcome.switched_to_prompt = True
                break
            elif isinstance(event, str):
                outcome.text += event
                yield event
            elif isinstance(event, list) and all(
                isinstance(tc, ToolCallObject) for tc in event
            ):
                outcome.tool_calls = event
                break

    async def _openai_native_tool_round(
        self, messages: list[dict[str, Any]], outcome: _RoundOutcome
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Run the native tool calls of one OpenAI round."""
        notice = self._missing_tool_executor_notice("OpenAI")
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
            caller_mode="OpenAI",
            label="OpenAI tool executor",
        ):
            yield update

    async def _openai_prompt_tool_round(
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
            label="Prompt mode tool executor",
        ):
            yield update

    async def _openai_tool_interaction_loop(
        self,
        initial_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Handle OpenAI interaction with tool support."""
        messages = initial_messages.copy()

        for _round in range(self._max_tool_rounds):
            outcome = _RoundOutcome()
            async for text in self._stream_openai_round(messages, tools, outcome):
                yield text
            if outcome.switched_to_prompt:
                continue

            if outcome.prompt_json:
                tool_round = self._openai_prompt_tool_round(messages, outcome)
            elif outcome.tool_calls:
                tool_round = self._openai_native_tool_round(messages, outcome)
            else:
                if outcome.text:
                    self._add_message(outcome.text, "assistant")
                return

            async for item in tool_round:
                yield item
            if outcome.finished:
                return

        logger.warning(f"OpenAI tool loop stopped after {self._max_tool_rounds} rounds")
        yield TOOL_ROUND_LIMIT_NOTICE

    def _select_tool_mode(
        self,
    ) -> tuple[Literal["Claude", "OpenAI"] | None, list[dict[str, Any]] | None]:
        """Pick the tool loop for the current LLM, or ``None`` for plain chat."""
        if not (self._use_mcpp and self._tool_manager):
            return None, None

        if isinstance(self._llm, ClaudeAsyncLLM):
            tool_mode, tools = "Claude", self._formatted_tools_claude
        elif isinstance(self._llm, OpenAICompatibleAsyncLLM):
            tool_mode, tools = "OpenAI", self._formatted_tools_openai
            # The LLM client remembers a provider that rejected native
            # tools; start in prompt mode so the MCP prompt is injected.
            if not getattr(self._llm, "support_tools", True):
                self.prompt_mode_flag = True
                self._json_detector.reset()
        else:
            logger.warning(
                f"LLM type {type(self._llm)} not explicitly handled for tool mode determination."
            )
            return None, None

        if not tools:
            logger.warning(
                f"No tools available/formatted for '{tool_mode}' mode, despite MCP being enabled."
            )
        return tool_mode, tools

    async def _simple_chat(
        self, messages: list[dict[str, Any]]
    ) -> AsyncIterator[str | dict[str, Any]]:
        """Stream a completion without tools and remember the reply."""
        logger.info("Starting simple chat completion.")
        token_stream = self._llm.chat_completion(messages, self._system)
        complete_response = ""
        async for event in token_stream:
            if isinstance(event, dict) and event.get("type") == "text_delta":
                text_chunk = event.get("text", "")
            elif isinstance(event, str):
                text_chunk = event
            else:
                continue
            if text_chunk:
                yield make_text_delta(text_chunk)
                yield text_chunk
                complete_response += text_chunk
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
            tool_mode, tools = self._select_tool_mode()

            if tool_mode == "Claude":
                logger.debug(
                    f"Starting Claude tool interaction loop with {len(tools)} tools."
                )
                stream = self._stream_with_text_deltas(
                    self._claude_tool_interaction_loop(messages, tools or [])
                )
            elif tool_mode == "OpenAI":
                logger.debug(
                    f"Starting OpenAI tool interaction loop with {len(tools)} tools."
                )
                # Prompt-mode tool JSON is not display text; stream only native turns.
                stream = self._stream_with_text_deltas(
                    self._openai_tool_interaction_loop(messages, tools or []),
                    enabled=lambda: not self.prompt_mode_flag,
                )
            else:
                stream = self._simple_chat(messages)

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
