import json
import datetime
from dataclasses import dataclass, field
from loguru import logger
from typing import (
    Dict,
    Any,
    List,
    Literal,
    Union,
    AsyncIterator,
)

from .types import ToolCallObject
from .mcp_client import MCPClient
from .tool_manager import ToolManager
from .user_servers import error_content_items, result_size_exceeded


@dataclass
class ParsedToolCall:
    tool_name: str = ""
    tool_id: str = ""
    tool_input: Any = None
    is_error: bool = False
    result_content: str | dict = ""
    parse_error: bool = False


@dataclass
class ToolRunResult:
    is_error: bool
    text_content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_items: List[Dict[str, Any]] = field(default_factory=list)


class ToolExecutor:
    def __init__(
        self,
        mcp_client: MCPClient | None,
        tool_manager: ToolManager,
        local_bridge=None,
    ):
        self._mcp_client = mcp_client
        self._tool_manager = tool_manager
        self._local_bridge = local_bridge

    def parse_tool_call(
        self, call: Union[Dict[str, Any], ToolCallObject]
    ) -> ParsedToolCall:
        """Parse a tool call from either provider's wire format."""
        tool_name: str = ""
        tool_id: str = ""
        tool_input: Any = None
        is_error: bool = False
        result_content: str | dict = ""
        parse_error: bool = False

        if isinstance(call, ToolCallObject):
            tool_name = call.function.name
            tool_id = call.id
            try:
                tool_input = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to decode OpenAI tool arguments for '{tool_name}'"
                )
                result_content = (
                    f"Error: Invalid arguments format for tool '{tool_name}'."
                )
                is_error = True
                parse_error = True
        elif isinstance(call, dict):
            tool_id = call.get("id")
            tool_name = call.get("name")
            tool_input = call.get("input", call.get("args"))

            if tool_input is None:
                logger.warning(
                    f"Empty input for tool '{tool_name}' (ID: {tool_id}). Using empty object."
                )
                tool_input = {}

            if not tool_id or not tool_name:
                logger.error(f"Invalid Dict tool call structure: {call}")
                result_content = "Error: Invalid tool call structure from LLM."
                is_error = True
                parse_error = True
        else:
            logger.error(f"Unsupported tool call type: {type(call)}")
            result_content = "Error: Unsupported tool call type."
            is_error = True
            parse_error = True

        return ParsedToolCall(
            tool_name=tool_name,
            tool_id=tool_id,
            tool_input=tool_input,
            is_error=is_error,
            result_content=result_content,
            parse_error=parse_error,
        )

    def format_tool_result(
        self,
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
        tool_id: str,
        result_content: str | List[Dict[str, Any]],
        is_error: bool,
    ) -> Dict[str, Any] | None:
        """Format tool result for LLM API."""
        if caller_mode == "Claude":
            # Claude expects content as a list of blocks or a simple string
            # We will return a list if there are multiple items or non-text items
            if isinstance(result_content, list):
                # Already formatted as list of blocks
                content_to_send = result_content
            elif isinstance(result_content, str) and result_content:
                # Simple text result
                content_to_send = result_content
            elif not result_content and is_error:
                # Error case, send error message as string
                content_to_send = "Error occurred during tool execution."
            else:
                # Fallback for empty or unexpected content
                content_to_send = ""

            return {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": content_to_send,
                "is_error": is_error,
            }
        elif caller_mode == "OpenAI":
            # OpenAI expects content as a string
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "content": str(result_content),
            }
        elif caller_mode == "Prompt":
            # Prompt mode also expects a string content for now
            return {
                "tool_id": tool_id,
                "content": str(result_content),
                "is_error": is_error,
            }
        return None

    def process_tool_from_prompt_json(
        self, data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process tool data from JSON in prompt mode."""
        parsed_tools = []
        for item in data:
            server = item.get("mcp_server")
            tool_name = item.get("tool")
            arguments_str = item.get("arguments")
            if all([server, tool_name, arguments_str]):
                try:
                    args_dict = json.loads(arguments_str)
                    parsed_tools.append(
                        {
                            "name": tool_name,
                            "server": server,
                            "args": args_dict,
                            "id": f"prompt_tool_{len(parsed_tools)}",
                        }
                    )
                    logger.info(f"Parsed tool call from prompt JSON: {tool_name}")
                except json.JSONDecodeError:
                    logger.error(
                        "Failed to decode arguments JSON in prompt mode tool call"
                    )
                except Exception as e:
                    logger.error(f"Error processing prompt mode tool dict: {e}")
            else:
                logger.warning("Skipping invalid tool structure in prompt mode JSON")
        return parsed_tools

    @staticmethod
    def _tool_status(
        tool_id: str,
        tool_name: str,
        status: str,
        content: str,
        **extra: Any,
    ) -> Dict[str, Any]:
        update = {
            "type": "tool_call_status",
            "tool_id": tool_id,
            "tool_name": tool_name,
            "status": status,
            "content": content,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
        }
        update.update(extra)
        return update

    @staticmethod
    def _split_image_content(
        caller_mode: str,
        text_content: str,
        content_items: List[Dict[str, Any]],
    ) -> tuple[str, Any]:
        """Return the status text and the LLM-facing content."""
        image_items = [
            item for item in content_items or [] if item.get("type") == "image"
        ]
        if not image_items:
            return text_content, text_content

        status_content = (
            f"{text_content}\n[Tool returned {len(image_items)} image(s)]".strip()
        )
        if caller_mode != "Claude":
            return status_content, status_content

        claude_blocks = []
        if text_content:
            claude_blocks.append({"type": "text", "text": text_content})
        for item in content_items:
            if item.get("type") == "image" and "data" in item and "mimeType" in item:
                claude_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": item["mimeType"],
                            "data": item["data"],
                        },
                    }
                )
        return status_content, claude_blocks if claude_blocks else ""

    def _scoped_status_extra(self, tool_name: str) -> Dict[str, Any]:
        """Mark status events group chat must keep on the owner's socket."""
        tool_info = self._tool_manager.get_tool(tool_name)
        is_scoped_tool = bool(
            tool_info and tool_info.related_server.startswith(("user:", "local:"))
        )
        return {"scoped": True} if is_scoped_tool else {}

    @staticmethod
    def _log_tool_start(parsed: ParsedToolCall, call: Any, is_scoped: bool) -> None:
        # Arguments of user-scoped tools can contain personal data; keep
        # them out of server logs.
        logger.info(
            f"Executing tool: {parsed.tool_name}"
            if is_scoped
            else f"Executing tool: {call}"
        )

    def _report_parse_error(
        self,
        parsed: ParsedToolCall,
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
        scoped_extra: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
        logger.warning(
            f"Skipping tool call due to parsing error: {parsed.result_content}"
        )
        parse_error_id = parsed.tool_id or (
            f"parse_error_{datetime.datetime.now(datetime.timezone.utc).isoformat()}"
        )
        status = self._tool_status(
            parse_error_id,
            parsed.tool_name or "Unknown Tool",
            "error",
            parsed.result_content,
            **scoped_extra,
        )
        formatted = self.format_tool_result(
            caller_mode,
            parse_error_id,
            parsed.result_content,
            True,
        )
        return status, formatted

    @staticmethod
    def _completed_status_extra(
        tool_name: str,
        result: ToolRunResult,
        scoped_extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        extra = dict(scoped_extra)
        if tool_name == "stagehand_navigate" and not result.is_error:
            live_view_data = result.metadata.get("liveViewData", {})
            if live_view_data:
                logger.info(
                    f"Found live view data for stagehand_navigate: {live_view_data}"
                )
                extra["browser_view"] = live_view_data
        return extra

    async def execute_tools(
        self,
        tool_calls: Union[List[Dict[str, Any]], List[ToolCallObject]],
        caller_mode: Literal["Claude", "OpenAI", "Prompt"],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Execute tools and yield status updates."""
        tool_results_for_llm = []

        logger.info(f"Executing {len(tool_calls)} tool(s) for {caller_mode} caller.")
        for call in tool_calls:
            parsed = self.parse_tool_call(call)
            scoped_extra = self._scoped_status_extra(parsed.tool_name)
            self._log_tool_start(parsed, call, bool(scoped_extra))

            if parsed.parse_error:
                status, formatted_result = self._report_parse_error(
                    parsed, caller_mode, scoped_extra
                )
                yield status
                if formatted_result:
                    tool_results_for_llm.append(formatted_result)
                continue

            # Yield 'running' status before execution
            yield self._tool_status(
                parsed.tool_id,
                parsed.tool_name,
                "running",
                f"Input: {json.dumps(parsed.tool_input)}",
                **scoped_extra,
            )

            result = await self.run_single_tool(
                parsed.tool_name, parsed.tool_id, parsed.tool_input
            )
            status_content, llm_formatted_content = self._split_image_content(
                caller_mode, result.text_content, result.content_items
            )

            yield self._tool_status(
                parsed.tool_id,
                parsed.tool_name,
                "error" if result.is_error else "completed",
                (
                    status_content
                    if not result.is_error
                    else f"Error: {result.text_content}"
                ),
                **self._completed_status_extra(parsed.tool_name, result, scoped_extra),
            )

            # Format result for LLM and add to list
            formatted_result = self.format_tool_result(
                caller_mode, parsed.tool_id, llm_formatted_content, result.is_error
            )
            if formatted_result:
                tool_results_for_llm.append(formatted_result)

        logger.info(
            f"Finished executing tools with {len(tool_results_for_llm)} results."
        )
        yield {"type": "final_tool_results", "results": tool_results_for_llm}

    @staticmethod
    def _error_run(message: str) -> ToolRunResult:
        return ToolRunResult(True, message, {}, error_content_items(message))

    async def _call_server_tool(
        self,
        tool_info: Any,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        remote_name = tool_info.remote_name or tool_name
        if tool_info.related_server.startswith("local:"):
            if self._local_bridge is None:
                raise RuntimeError("Local MCP bridge is not available")
            return await self._local_bridge.call_tool(
                server_key=tool_info.related_server,
                tool_name=remote_name,
                tool_args=tool_input,
            )
        if self._mcp_client is None:
            raise RuntimeError("MCP client is not available")
        return await self._mcp_client.call_tool(
            server_name=tool_info.related_server,
            tool_name=remote_name,
            tool_args=tool_input,
        )

    @staticmethod
    def _first_result_text(
        content_items: List[Dict[str, Any]],
    ) -> tuple[bool, str]:
        """Read the first content item the MCP server reported."""
        if content_items and content_items[0].get("type") == "error":
            return True, content_items[0].get(
                "text", "Unknown error from tool execution."
            )
        if content_items and content_items[0].get("type") == "text":
            return False, content_items[0].get("text", "")
        return False, ""

    @staticmethod
    def _log_content_items(tool_name: str, content_items: List[Dict[str, Any]]) -> None:
        logger.info(f"Content items from tool '{tool_name}':")
        for item in content_items:
            item_type = item.get("type", "unknown")
            logger.info(f"  Type: {item_type}")
            for key, value in item.items():
                if key != "type" and key != "data":  # Avoid logging large data
                    log_value = (
                        f"(length: {len(value)})"
                        if isinstance(value, str) and len(value) > 100
                        else value
                    )
                    logger.info(f"    {key}: {log_value}")

    async def run_single_tool(
        self, tool_name: str, tool_id: str, tool_input: Any
    ) -> ToolRunResult:
        """Run a single tool using MCPClient."""
        logger.info(f"Executing tool: {tool_name} (ID: {tool_id})")
        tool_info = self._tool_manager.get_tool(tool_name)
        if tool_input is None:
            tool_input = {}

        if not tool_info:
            logger.error(f"Tool '{tool_name}' not found in ToolManager.")
            return self._error_run(f"Error: Tool '{tool_name}' is not available.")
        if not tool_info.related_server:
            logger.error(f"Tool '{tool_name}' does not have a related server defined.")
            return self._error_run(
                f"Error: Configuration error for tool '{tool_name}'. "
                "No server specified."
            )

        try:
            result_dict = await self._call_server_tool(tool_info, tool_name, tool_input)
            metadata = result_dict.get("metadata", {})
            content_items = result_dict.get("content_items", [])

            is_scoped_tool = tool_info.related_server.startswith(("user:", "local:"))
            if is_scoped_tool and result_size_exceeded(content_items):
                content_items = error_content_items(
                    "Tool result exceeded the size limit"
                )

            is_error, text_content = self._first_result_text(content_items)
            if not is_error:
                logger.info(f"Tool '{tool_name}' executed successfully.")
                if content_items:
                    self._log_content_items(tool_name, content_items)

            return ToolRunResult(is_error, text_content, metadata, content_items)

        except (ValueError, RuntimeError, ConnectionError) as e:
            logger.exception(f"Error executing tool '{tool_name}': {e}")
            return self._error_run(f"Error executing tool '{tool_name}': {e}")
        except Exception as e:
            logger.exception(f"Unexpected error executing tool '{tool_name}': {e}")
            return self._error_run(
                f"Unexpected error executing tool '{tool_name}': {e}"
            )
