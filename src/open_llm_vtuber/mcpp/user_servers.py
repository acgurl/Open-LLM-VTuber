"""Validation and construction for user-scoped MCP servers.

Global servers come from the deployment-managed ``mcp_servers.json``. This
module only handles servers a user adds at runtime: they must point at public
HTTPS endpoints (the server must not be able to reach its own internal
services) and their tools are namespaced so they can never shadow a global
tool such as the knowledge-base tools.
"""

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from .types import MCPServer

MAX_USER_MCP_SERVERS = 8
MAX_USER_MCP_TOOLS = 64
MAX_USER_MCP_SCHEMA_BYTES = 256 * 1024
MAX_LOCAL_MCP_SERVERS = 4
MAX_LOCAL_MCP_TOOLS = 64
MAX_TOOL_SCHEMA_BYTES = 64 * 1024
MAX_MCP_RESULT_BYTES = 512 * 1024
USER_MCP_TIMEOUT_SECONDS = 15
USER_MCP_DISCOVERY_TIMEOUT_SECONDS = 10
LOCAL_MCP_TIMEOUT_SECONDS = 30

_HEADER_KEY_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_BLOCKED_HEADERS = {
    "connection",
    "content-length",
    "cookie",
    "host",
    "keep-alive",
    "proxy-authorization",
    "proxy-connection",
    "set-cookie",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localhost",
    ".home.arpa",
)
_LOCAL_HOST_SUFFIXES = (
    ".corp",
    ".home",
    ".home.arpa",
    ".internal",
    ".lan",
    ".local",
    ".localhost",
)
_USER_MCP_ENTRY_KEYS = {"url", "headers", "enabled"}


def validate_server_name(name: Any) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or len(name) > 64
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError(
            "name must be a non-empty string up to 64 characters "
            "without control characters"
        )
    return name


def validate_server_id(server_id: Any) -> str:
    if not isinstance(server_id, str) or not _SERVER_ID_PATTERN.fullmatch(server_id):
        raise ValueError(
            "server_id must be 1-64 characters of letters, digits, dash or underscore"
        )
    return server_id


def validate_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise ValueError("headers must be an object")
    if len(headers) > 16:
        raise ValueError("at most 16 headers are allowed")

    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not _HEADER_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid header name: {key!r}")
        if key.lower() in _BLOCKED_HEADERS:
            raise ValueError(f"header '{key}' is not allowed")
        if (
            not isinstance(value, str)
            or len(value) > 4096
            or any(char in value for char in "\r\n\0")
        ):
            raise ValueError(f"invalid value for header '{key}'")
        cleaned[key] = value
    return cleaned


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return (
        not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or getattr(ip, "is_site_local", False)
        )
        and ip.is_global
    )


def _parse_mcp_url(url: Any):
    if not isinstance(url, str) or not url or url != url.strip() or len(url) > 2048:
        raise ValueError("url must be a non-empty string up to 2048 characters")

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("url must not contain credentials")
    if parsed.fragment:
        raise ValueError("url must not contain a fragment")
    if not parsed.hostname:
        raise ValueError("url must include a host")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("url contains an invalid port") from exc
    return parsed


def _is_local_hostname(host: str) -> bool:
    if (
        host == "localhost"
        or "." not in host
        or any(host.endswith(suffix) for suffix in _LOCAL_HOST_SUFFIXES)
    ):
        return True
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return not _is_public_address(host)


def classify_mcp_url(url: Any) -> str:
    """Return ``local`` (browser connects) or ``remote`` (server connects).

    Local entries may use plain http: the backend never dials them. Remote
    entries must be public HTTPS so the server cannot be used as an SSRF proxy.
    """
    parsed = _parse_mcp_url(url)
    host = parsed.hostname.rstrip(".").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    if _is_local_hostname(host):
        return "local"

    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False

    if not is_ip_literal:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("url host could not be resolved") from exc
        if not infos:
            raise ValueError("url host could not be resolved")
        addresses = {info[4][0] for info in infos}
        if any(not _is_public_address(address) for address in addresses):
            return "local"

    if parsed.scheme != "https":
        raise ValueError("remote MCP url must use https")
    return "remote"


def validate_public_https_url(url: Any) -> str:
    """Reject URLs that could make the server reach its own network.

    DNS is resolved here and again before every MCP connection. Hostname
    allow-listing is not used because users bring their own endpoints.
    """
    parsed = _parse_mcp_url(url)
    if parsed.scheme != "https":
        raise ValueError("url must use https")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or any(
        host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES
    ):
        raise ValueError("url must point at a public host")

    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("url contains an invalid port") from exc

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("url host could not be resolved") from exc
    if not infos:
        raise ValueError("url host could not be resolved")

    addresses = {info[4][0] for info in infos}
    if not all(_is_public_address(address) for address in addresses):
        raise ValueError("url must not resolve to a private or reserved address")

    return url


async def validate_public_https_url_async(url: Any) -> str:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(validate_public_https_url, url),
            timeout=5,
        )
    except asyncio.TimeoutError as exc:
        raise ValueError("url host could not be resolved") from exc


def validate_local_tool(tool: Any) -> tuple[str, str, dict[str, Any]]:
    """Validate a tool schema registered by a browser-side MCP server."""
    if not isinstance(tool, dict):
        raise ValueError("tool must be an object")

    name = tool.get("name")
    if not isinstance(name, str) or not _TOOL_NAME_PATTERN.fullmatch(name):
        raise ValueError("tool name is invalid")

    description = tool.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str) or len(description) > 4096:
        raise ValueError("tool description is invalid")

    schema = tool.get("inputSchema", tool.get("input_schema"))
    if schema is None:
        schema = {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        raise ValueError("tool inputSchema must be an object")
    if len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) > (
        MAX_TOOL_SCHEMA_BYTES
    ):
        raise ValueError("tool inputSchema is too large")
    if not isinstance(schema.get("properties", {}), dict):
        raise ValueError("tool inputSchema.properties must be an object")
    if not isinstance(schema.get("required", []), list):
        raise ValueError("tool inputSchema.required must be an array")

    return name, description, schema


def make_exposed_tool_name(prefix: str, namespace: str, tool_name: str) -> str:
    """Build a stable, provider-safe name that cannot collide with global tools.

    OpenAI and Claude both cap function names at 64 characters and expect a
    conservative character set. The namespace digest keeps two user servers
    with the same tool name distinct.
    """
    digest = hashlib.sha1(namespace.encode("utf-8")).hexdigest()[:6]
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", tool_name)[:40] or "tool"
    return f"{prefix}_{digest}_{safe_name}"[:64]


def unique_tool_name(candidate: str, taken: set[str]) -> str:
    if candidate not in taken:
        return candidate
    for index in range(2, 1000):
        suffix = f"_{index}"
        trimmed = candidate[: 64 - len(suffix)]
        name = f"{trimmed}{suffix}"
        if name not in taken:
            return name
    raise ValueError("too many tools share the same name")


def user_server_key(server_id: str) -> str:
    return f"user:{server_id}"


def local_server_key(server_id: str) -> str:
    return f"local:{server_id}"


def parse_user_mcp_config(config: Any) -> list[dict]:
    """Validate one user-edited ``mcp_servers`` document.

    The same JSON shape as the deployment ``mcp_servers.json`` is used; the
    backend decides per entry whether it is server-side (remote) or
    browser-side (local). stdio entries are rejected: users must supply an
    HTTP endpoint, and local processes are never started by the server.
    """
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    unknown_top = set(config) - {"mcp_servers"}
    if unknown_top:
        raise ValueError(f"unsupported config keys: {', '.join(sorted(unknown_top))}")
    servers = config.get("mcp_servers")
    if not isinstance(servers, dict):
        raise ValueError("config.mcp_servers must be an object")
    if len(servers) > MAX_USER_MCP_SERVERS:
        raise ValueError(f"At most {MAX_USER_MCP_SERVERS} MCP servers are allowed")

    parsed: list[dict] = []
    for raw_name, entry in servers.items():
        name = validate_server_name(raw_name)
        if not isinstance(entry, dict):
            raise ValueError(f"server '{name}' must be an object")
        unknown = set(entry) - _USER_MCP_ENTRY_KEYS
        if unknown:
            raise ValueError(
                f"server '{name}' has unsupported keys: "
                f"{', '.join(sorted(unknown))}; only url/headers/enabled "
                "are allowed (stdio commands cannot run on the server)"
            )
        url = entry.get("url")
        mode = classify_mcp_url(url)
        headers = validate_headers(entry.get("headers"))
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"server '{name}' enabled must be a boolean")
        parsed.append(
            {
                "name": name,
                "url": url,
                "headers": headers,
                "enabled": enabled,
                "mode": mode,
            }
        )

    local_count = sum(1 for entry in parsed if entry["mode"] == "local")
    if local_count > MAX_LOCAL_MCP_SERVERS:
        raise ValueError(
            f"At most {MAX_LOCAL_MCP_SERVERS} local MCP servers are allowed"
        )
    return parsed


def split_user_mcp_servers(
    records: list[dict] | None,
) -> tuple[list[dict], list[dict]]:
    """Split enabled rows into (remote, local) using the stored mode."""
    remote: list[dict] = []
    local: list[dict] = []
    for record in records or []:
        if not record.get("enabled", True):
            continue
        mode = record.get("mode")
        if mode not in {"local", "remote"}:
            try:
                mode = classify_mcp_url(record.get("url"))
            except ValueError:
                continue
        (local if mode == "local" else remote).append(record)
    return remote, local


def local_mcp_config_payload(records: list[dict] | None) -> list[dict]:
    """Build the browser-facing config for local servers (headers included)."""
    payload: list[dict] = []
    for record in records or []:
        server_id = record.get("id")
        url = record.get("url")
        if not isinstance(server_id, str) or not isinstance(url, str):
            continue
        payload.append(
            {
                "server_id": server_id,
                "name": record.get("name") or server_id,
                "url": url,
                "headers": record.get("headers") or {},
            }
        )
    return payload


def build_user_mcp_servers(records: list[dict] | None) -> dict[str, MCPServer]:
    """Convert remote repository rows into registry entries for one session."""
    servers: dict[str, MCPServer] = {}
    for record in (records or [])[:MAX_USER_MCP_SERVERS]:
        if not record.get("enabled", True):
            continue
        if record.get("mode", "remote") != "remote":
            continue
        server_id = record.get("id")
        url = record.get("url")
        if not isinstance(server_id, str) or not isinstance(url, str):
            continue
        key = user_server_key(server_id)
        servers[key] = MCPServer(
            name=key,
            url=url,
            headers=record.get("headers") or None,
            timeout=timedelta(seconds=USER_MCP_TIMEOUT_SECONDS),
            is_user=True,
            display_name=record.get("name") or key,
        )
    return servers


def content_items_size(content_items: list[dict[str, Any]] | None) -> int:
    total = 0
    for item in content_items or []:
        for key in ("text", "data", "url", "altText"):
            value = item.get(key)
            if isinstance(value, str):
                total += len(value)
    return total
