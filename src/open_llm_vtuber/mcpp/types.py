from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional, Any


@dataclass
class MCPServer:
    """Class representing a MCP Server

    Args:
        name (str): Name of the server.
        command (str, optional): Command to run a stdio server. Empty for HTTP servers.
        args (list[str], optional): Arguments for the command. Defaults to an empty list.
        env (Optional[dict[str, str]], optional): Environment variables for the command. Defaults to None.
        cwd (Optional[str], optional): Working directory for the command. Defaults to None.
        timeout (Optional[timedelta], optional): Timeout for the command. Defaults to 10 seconds.
        url (Optional[str], optional): Streamable HTTP endpoint for remote servers.
        headers (Optional[dict[str, str]], optional): HTTP headers sent to an HTTP server.
    """

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: Optional[dict[str, str]] = None
    cwd: str | None = None
    timeout: Optional[timedelta] = timedelta(seconds=30)
    description: str = "No description available."
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    # User-added servers are untrusted input: their URL is validated before
    # every connection and their tools are namespaced away from global ones.
    is_user: bool = False
    display_name: Optional[str] = None


@dataclass
class FormattedTool:
    """ "Class representing a formatted tool

    Args:
        input_schema (dict[str, Any]): Input schema for the tool.
        related_server (str): The name of the server that contains the tool.
        generic_schema (Optional[dict[str, Any]], optional): Generic schema for the tool. Defaults to None.
        description (str, optional): Description of the tool, usually from the server's tool definition. Defaults to "No description available.".
        remote_name (Optional[str], optional): Name to send to the MCP server when
            the exposed name was namespaced. Defaults to the exposed name.
    """

    input_schema: dict[str, Any]
    related_server: str
    generic_schema: Optional[dict[str, Any]] = None
    description: str = "No description available."
    remote_name: Optional[str] = None


@dataclass
class ToolCallFunctionObject:
    """Class representing a function object in a tool call

    This class mimics the OpenAI API function object structure for tool calls.

    Args:
        name (str): Name of the function.
        arguments (str): Arguments for the function as a JSON string.
    """

    name: str = ""
    arguments: str = ""


@dataclass
class ToolCallObject:
    """Class representing a tool call object

    This class mimics the OpenAI API ChoiceDeltaToolCall structure.

    Args:
        id (str): Unique identifier for the tool call.
        type (str): Type of the tool call, typically "function".
        index (int): Index of the tool call in the sequence.
        function (ToolCallFunctionObject): Function information for the tool call.
    """

    id: Optional[str] = None
    type: str = "function"
    index: int = 0
    function: ToolCallFunctionObject = field(default_factory=ToolCallFunctionObject)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCallObject":
        """Create a ToolCallObject from a dictionary

        Args:
            data (dict[str, Any]): dictionary containing tool call data.

        Returns:
            ToolCallObject: A new ToolCallObject instance.
        """
        function = ToolCallFunctionObject(
            name=data["function"]["name"], arguments=data["function"]["arguments"]
        )
        return cls(
            id=data["id"], type=data["type"], index=data["index"], function=function
        )
