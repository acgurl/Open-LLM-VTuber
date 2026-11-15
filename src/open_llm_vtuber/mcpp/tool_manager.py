from loguru import logger
from typing import Any

from .types import FormattedTool


class ToolManager:
    """Holds a session's tools: raw info plus the definitions sent to the LLM."""

    def __init__(
        self,
        formatted_tools: list[dict[str, Any]] | None = None,
        initial_tools_dict: dict[str, FormattedTool] | None = None,
        server_instructions: str = "",
    ) -> None:
        """
        ``formatted_tools`` are the MCP tool definitions offered to the LLM
        (see ``agent/stateless_llm/stateless_llm_interface``); each backend
        places them in its API's own tool field.

        ``server_instructions`` is the system-prompt section built from the
        MCP servers' ``instructions``; the agent appends it while tools are on.
        """
        self.server_instructions: str = server_instructions or ""
        # Raw tool data, for get_tool.
        self.tools: dict[str, FormattedTool] = initial_tools_dict or {}
        self._formatted_tools: list[dict[str, Any]] = formatted_tools or []

        logger.info(f"ToolManager initialized with {len(self._formatted_tools)} tools.")

    def get_tool(self, tool_name: str) -> FormattedTool | None:
        """Get a tool's raw information by its name."""
        tool = self.tools.get(tool_name)
        if isinstance(tool, FormattedTool):
            return tool
        logger.warning(
            f"TM: Raw tool info for '{tool_name}' not found (was initial_tools_dict provided?)."
        )
        return None

    def get_formatted_tools(self) -> list[dict[str, Any]]:
        """The tool definitions offered to the LLM."""
        return self._formatted_tools
