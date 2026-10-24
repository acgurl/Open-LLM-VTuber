"""Constructs prompts for servers and tools, formats tool information for OpenAI API."""

import asyncio
import json

from typing import Dict, Optional, List, Tuple, Any
from loguru import logger

from .types import FormattedTool
from .mcp_client import MCPClient
from .server_registry import ServerRegistry
from .user_servers import (
    MAX_TOOL_SCHEMA_BYTES,
    MAX_USER_MCP_SCHEMA_BYTES,
    MAX_USER_MCP_TOOLS,
    USER_MCP_DISCOVERY_TIMEOUT_SECONDS,
    make_exposed_tool_name,
    unique_tool_name,
)


class ToolAdapter:
    """Dynamically fetches tool information from enabled MCP servers and formats it."""

    def __init__(self, server_registry: Optional[ServerRegistry] = None) -> None:
        """Initialize with an ServerRegistry."""
        self.server_registry = server_registry or ServerRegistry()

    async def _fetch_server_tools(self, client: MCPClient, server_name: str):
        if server_name not in self.server_registry.servers:
            logger.warning(
                f"MC: Enabled server '{server_name}' not found in Server Manager. Skipping."
            )
            return None
        if server_name.startswith(("user:", "local:")):
            return await asyncio.wait_for(
                client.list_tools(server_name),
                timeout=USER_MCP_DISCOVERY_TIMEOUT_SECONDS,
            )
        return await client.list_tools(server_name)

    async def get_server_and_tool_info(
        self, enabled_servers: List[str]
    ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, FormattedTool]]:
        """Fetch tool information from specified enabled MCP servers."""
        servers_info: Dict[str, Dict[str, str]] = {}
        formatted_tools: Dict[str, FormattedTool] = {}

        if not enabled_servers:
            logger.warning(
                "MC: No enabled MCP servers specified. Cannot fetch tool info."
            )
            return servers_info, formatted_tools

        logger.debug(f"MC: Fetching tool info for enabled servers: {enabled_servers}")

        # Deployment servers keep the original sequential path (some use stdio
        # transports with task-scoped cleanup). User HTTP servers are fetched
        # concurrently so one slow endpoint cannot multiply the session start
        # time. Results are merged in the configured order so the prompt stays
        # deterministic.
        results: Dict[str, Any] = {}
        async with MCPClient(self.server_registry) as client:
            scoped_servers = [
                name for name in enabled_servers if name.startswith(("user:", "local:"))
            ]
            scoped_set = set(scoped_servers)
            for server_name in enabled_servers:
                if server_name in scoped_set:
                    continue
                try:
                    results[server_name] = await self._fetch_server_tools(
                        client, server_name
                    )
                except Exception as exc:
                    results[server_name] = exc

            scoped_results = await asyncio.gather(
                *(
                    self._fetch_server_tools(client, server_name)
                    for server_name in scoped_servers
                ),
                return_exceptions=True,
            )
            results.update(zip(scoped_servers, scoped_results))

        for server_name in enabled_servers:
            result = results.get(server_name)
            servers_info.setdefault(server_name, {})
            if result is None:
                continue
            if isinstance(result, Exception):
                logger.error(
                    f"MC: Failed to get info for server '{server_name}': {result}"
                )
                continue

            # User and browser-registered servers get a namespace prefix so
            # they can never shadow a global tool. Global names stay exactly
            # as before.
            if server_name.startswith("user:"):
                namespace_prefix = "u"
            elif server_name.startswith("local:"):
                namespace_prefix = "l"
            else:
                namespace_prefix = ""

            tools = result
            logger.debug(f"MC: Found {len(tools)} tools on server '{server_name}'")
            scoped_tool_count = 0
            scoped_schema_bytes = 0
            for tool in tools:
                schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
                description = tool.description
                exposed_name = tool.name
                if namespace_prefix:
                    if scoped_tool_count >= MAX_USER_MCP_TOOLS:
                        logger.warning(
                            f"MC: Server '{server_name}' exceeds "
                            f"{MAX_USER_MCP_TOOLS} tools; extras ignored."
                        )
                        break
                    schema_size = len(
                        json.dumps(schema, ensure_ascii=False).encode("utf-8")
                    )
                    if schema_size > MAX_TOOL_SCHEMA_BYTES:
                        logger.warning(
                            f"MC: Tool '{tool.name}' on '{server_name}' has an "
                            "oversized input schema; ignored."
                        )
                        continue
                    if scoped_schema_bytes + schema_size > MAX_USER_MCP_SCHEMA_BYTES:
                        logger.warning(
                            f"MC: Server '{server_name}' exceeds the total "
                            "schema budget; extras ignored."
                        )
                        break
                    scoped_schema_bytes += schema_size
                    scoped_tool_count += 1
                    description = (description or "")[:4096]
                    candidate = make_exposed_tool_name(
                        namespace_prefix, server_name, tool.name
                    )
                    exposed_name = unique_tool_name(candidate, set(formatted_tools))

                servers_info[server_name][exposed_name] = {}
                tool_info = servers_info[server_name][exposed_name]
                tool_info["description"] = description
                tool_info["parameters"] = schema.get("properties", {})
                tool_info["required"] = schema.get("required", [])

                # Store the tool info in FormattedTool format
                formatted_tools[exposed_name] = FormattedTool(
                    input_schema=schema,
                    related_server=server_name,
                    description=description,
                    # Generic schema will be generated later if needed
                    generic_schema=None,
                    remote_name=tool.name,
                )

        logger.debug(
            f"MC: Finished fetching tool info. Found {len(formatted_tools)} tools across enabled servers."
        )
        return servers_info, formatted_tools

    def construct_mcp_prompt_string(
        self,
        servers_info: Dict[str, Dict[str, str]],
        display_names: Optional[Dict[str, str]] = None,
    ) -> str:
        """Build a single prompt string describing enabled servers and their tools."""
        full_prompt_content = ""
        if not servers_info:
            logger.warning(
                "MC: Cannot construct MCP prompt string, servers_info is empty."
            )
            return full_prompt_content

        logger.debug(
            f"MC: Constructing MCP prompt string for {len(servers_info)} server(s)."
        )

        for server_name, tools in servers_info.items():
            if not tools:  # Skip servers where info couldn't be fetched
                logger.warning(
                    f"MC: No tool info available for server '{server_name}', skipping in prompt."
                )
                continue

            server = self.server_registry.get_server(server_name)
            label = server_name
            if display_names and server_name in display_names:
                label = display_names[server_name]
            elif server is not None and server.is_user and server.display_name:
                label = server.display_name
            prompt_content = f"Server: {label}\n"
            prompt_content += "    Tools:\n"
            for tool_name, tool_info in tools.items():
                prompt_content += f"        {tool_name}:\n"
                # Ensure description is handled correctly (might be None)
                description = tool_info.get("description", "No description available.")
                prompt_content += f"            Description: {description}\n"
                parameters = tool_info.get("parameters", {})
                if parameters:
                    prompt_content += "            Parameters:\n"
                    for param_name, param_info in parameters.items():
                        param_desc = param_info.get("description") or param_info.get(
                            "title", "No description provided."
                        )
                        param_type = param_info.get(
                            "type", "string"
                        )  # Default to string if type missing
                        prompt_content += f"                {param_name}:\n"
                        prompt_content += f"                    Type: {param_type}\n"
                        prompt_content += (
                            f"                    Description: {param_desc}\n"
                        )
                required = tool_info.get("required", [])
                if required:
                    prompt_content += f"            Required: {', '.join(required)}\n"
            full_prompt_content += prompt_content + "\n"  # Add newline between servers

        logger.debug("MC: Finished constructing MCP prompt string.")
        return full_prompt_content.strip()  # Remove trailing newline

    def format_tools_for_api(
        self, formatted_tools_dict: Dict[str, FormattedTool]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Format tools to OpenAI and Claude function-calling compatible schemas."""
        openai_tools = []
        claude_tools = []

        if not formatted_tools_dict:
            logger.warning(
                "MC: Cannot format tools for API, input dictionary is empty."
            )
            return openai_tools, claude_tools

        logger.debug(f"MC: Formatting {len(formatted_tools_dict)} tools for API usage.")

        for tool_name, data_object in formatted_tools_dict.items():
            if not isinstance(data_object, FormattedTool):
                logger.warning(f"MC: Skipping invalid tool format for '{tool_name}'")
                continue

            input_schema = data_object.input_schema
            properties: Dict[str, Dict[str, str]] = input_schema.get("properties", {})
            tool_description = data_object.description or "No description provided."
            required_params = input_schema.get("required", [])

            # Format for OpenAI
            openai_function_params = {
                "type": "object",
                "properties": {},
                "required": required_params,
                "additionalProperties": False,  # Disallow extra properties
            }
            for param_name, param_info in properties.items():
                param_schema = {
                    "type": param_info.get("type", "string"),
                    "description": param_info.get("description")
                    or param_info.get("title", "No description provided."),
                }
                # Add enum if present
                if "enum" in param_info:
                    param_schema["enum"] = param_info["enum"]
                # Handle array type correctly
                if param_schema["type"] == "array" and "items" in param_info:
                    param_schema["items"] = param_info["items"]
                elif param_schema["type"] == "array" and "items" not in param_info:
                    logger.warning(
                        f"MC: Array parameter '{param_name}' in tool '{tool_name}' is missing 'items' definition. Assuming items are strings."
                    )
                    param_schema["items"] = {"type": "string"}  # Default or log warning

                openai_function_params["properties"][param_name] = param_schema

            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": openai_function_params,
                    },
                }
            )

            # Format for Claude
            claude_input_schema = {
                "type": "object",
                "properties": properties,
                "required": required_params,
            }
            claude_tools.append(
                {
                    "name": tool_name,
                    "description": tool_description,
                    "input_schema": claude_input_schema,
                }
            )

        logger.debug(
            f"MC: Finished formatting tools. OpenAI: {len(openai_tools)}, Claude: {len(claude_tools)}."
        )
        return openai_tools, claude_tools

    async def build_tools(
        self, enabled_servers: List[str]
    ) -> Tuple[
        str, List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, FormattedTool]
    ]:
        """Fetch tool info once and return prompt, API schemas, and raw tools."""
        logger.info(
            f"MC: Running dynamic tool construction for servers: {enabled_servers}"
        )
        servers_info, formatted_tools_dict = await self.get_server_and_tool_info(
            enabled_servers
        )
        mcp_prompt_string = self.construct_mcp_prompt_string(servers_info)
        openai_tools, claude_tools = self.format_tools_for_api(formatted_tools_dict)
        logger.info("MC: Dynamic tool construction complete.")
        return mcp_prompt_string, openai_tools, claude_tools, formatted_tools_dict

    async def get_tools(
        self, enabled_servers: List[str]
    ) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Run the dynamic fetching and formatting process."""
        mcp_prompt_string, openai_tools, claude_tools, _ = await self.build_tools(
            enabled_servers
        )
        return mcp_prompt_string, openai_tools, claude_tools
