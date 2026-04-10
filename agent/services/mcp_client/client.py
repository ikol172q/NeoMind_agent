"""MCP Client for NeoMind Agent.

Connects to MCP servers, discovers tools, and executes them.
Implements the Model Context Protocol client-side using JSON-RPC 2.0.

Usage:
    client = MCPClient()
    result = await client.connect_server("fs", TransportConfig(
        transport_type=TransportType.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    ))
    tools = await client.discover_tools("fs")
    result = await client.call_tool("read_file", {"path": "/tmp/hello.txt"})
    await client.close_all()

Created: 2026-04-02
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.services.mcp_client.transport import (
    BaseTransport,
    TransportConfig,
    create_transport,
)

logger = logging.getLogger(__name__)

# ── JSON-RPC 2.0 helpers ────────────────────────────────────────────


def _jsonrpc_request(method: str, params: Optional[Dict[str, Any]], id: int) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 request envelope."""
    msg: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": id,
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


def _jsonrpc_notification(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a JSON-RPC 2.0 notification (no ``id``)."""
    msg: Dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


# ── Data models ──────────────────────────────────────────────────────


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str


@dataclass
class MCPResource:
    """A resource exposed by an MCP server."""

    uri: str
    name: str
    description: str
    mime_type: Optional[str] = None


@dataclass
class MCPResult:
    """Uniform result wrapper for all MCP operations."""

    success: bool
    content: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── MCP Client ───────────────────────────────────────────────────────


class MCPClient:
    """High-level MCP client that manages multiple server connections.

    Provides tool discovery, resource listing, and tool invocation across
    any number of concurrently connected MCP servers.
    """

    # MCP protocol version this client advertises
    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(self) -> None:
        self._servers: Dict[str, BaseTransport] = {}
        self._server_configs: Dict[str, TransportConfig] = {}
        self._tools: Dict[str, MCPTool] = {}
        self._resources: Dict[str, MCPResource] = {}
        self._request_id: int = 0

    # ── server lifecycle ─────────────────────────────────────────────

    async def connect_server(self, name: str, config: TransportConfig) -> MCPResult:
        """Connect to an MCP server and perform the ``initialize`` handshake.

        If a server with *name* is already connected it will be disconnected
        first so the new connection can take its place.
        """

        # Tear down existing connection with the same name, if any
        if name in self._servers:
            await self.disconnect_server(name)

        transport = create_transport(config)

        try:
            await transport.connect()
        except Exception as exc:
            logger.error("Failed to connect transport for '%s': %s", name, exc)
            return MCPResult(success=False, error=f"Transport connect failed: {exc}")

        self._servers[name] = transport
        self._server_configs[name] = config

        # MCP initialize handshake
        try:
            init_result = await self._send_request(name, "initialize", {
                "protocolVersion": self._PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "NeoMind-Agent",
                    "version": "1.0.0",
                },
            })

            # Send initialized notification (required by MCP spec)
            notification = _jsonrpc_notification("notifications/initialized")
            await transport.send(notification)

            server_info = init_result.get("result", {}).get("serverInfo", {})
            logger.info(
                "MCP server '%s' initialized: %s %s",
                name,
                server_info.get("name", "unknown"),
                server_info.get("version", ""),
            )
            return MCPResult(
                success=True,
                content=init_result.get("result"),
                metadata={"server_name": name},
            )
        except Exception as exc:
            logger.error("MCP initialize handshake failed for '%s': %s", name, exc)
            await self._force_close(name)
            return MCPResult(success=False, error=f"Initialize handshake failed: {exc}")

    async def disconnect_server(self, name: str) -> MCPResult:
        """Gracefully disconnect from a named MCP server."""

        if name not in self._servers:
            return MCPResult(success=False, error=f"Server '{name}' is not connected")

        # Remove tools and resources belonging to this server
        self._tools = {k: v for k, v in self._tools.items() if v.server_name != name}
        self._resources = {k: v for k, v in self._resources.items()}  # resources are keyed by URI

        await self._force_close(name)
        return MCPResult(success=True, metadata={"server_name": name})

    # ── discovery ────────────────────────────────────────────────────

    async def discover_tools(self, server_name: str) -> List[MCPTool]:
        """Query *server_name* for its available tools and cache them."""

        if server_name not in self._servers:
            raise ConnectionError(f"Server '{server_name}' is not connected")

        response = await self._send_request(server_name, "tools/list")
        result = response.get("result", {})
        raw_tools: List[Dict[str, Any]] = result.get("tools", [])

        discovered: List[MCPTool] = []
        for t in raw_tools:
            tool = MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=server_name,
            )
            self._tools[tool.name] = tool
            discovered.append(tool)

        logger.info(
            "Discovered %d tools from '%s': %s",
            len(discovered),
            server_name,
            [t.name for t in discovered],
        )
        return discovered

    async def discover_resources(self, server_name: str) -> List[MCPResource]:
        """Query *server_name* for its available resources and cache them."""

        if server_name not in self._servers:
            raise ConnectionError(f"Server '{server_name}' is not connected")

        response = await self._send_request(server_name, "resources/list")
        result = response.get("result", {})
        raw_resources: List[Dict[str, Any]] = result.get("resources", [])

        discovered: List[MCPResource] = []
        for r in raw_resources:
            resource = MCPResource(
                uri=r.get("uri", ""),
                name=r.get("name", ""),
                description=r.get("description", ""),
                mime_type=r.get("mimeType"),
            )
            self._resources[resource.uri] = resource
            discovered.append(resource)

        logger.info(
            "Discovered %d resources from '%s'",
            len(discovered),
            server_name,
        )
        return discovered

    # ── tool execution ───────────────────────────────────────────────

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> MCPResult:
        """Invoke a previously discovered tool by name.

        Returns an :class:`MCPResult` with the tool's output or error.
        If the server has disconnected, a single reconnection attempt is
        made automatically before failing.
        """

        tool = self._tools.get(tool_name)
        if tool is None:
            return MCPResult(success=False, error=f"Unknown tool: '{tool_name}'")

        server_name = tool.server_name
        transport = self._servers.get(server_name)

        # Attempt reconnection if transport is gone or dead
        if transport is None or not transport.is_connected:
            reconnected = await self._try_reconnect(server_name)
            if not reconnected:
                return MCPResult(
                    success=False,
                    error=f"Server '{server_name}' is disconnected and reconnection failed",
                )

        try:
            response = await self._send_request(server_name, "tools/call", {
                "name": tool_name,
                "arguments": arguments or {},
            })
        except Exception as exc:
            return MCPResult(success=False, error=f"Tool call failed: {exc}")

        # Check for JSON-RPC error
        if "error" in response:
            err = response["error"]
            return MCPResult(
                success=False,
                error=f"[{err.get('code', '?')}] {err.get('message', 'unknown error')}",
                metadata={"raw_error": err},
            )

        result = response.get("result", {})
        content = result.get("content", [])
        is_error = result.get("isError", False)

        return MCPResult(
            success=not is_error,
            content=content,
            error=result.get("error") if is_error else None,
            metadata={"tool": tool_name, "server": server_name},
        )

    # ── resource reading ─────────────────────────────────────────────

    async def read_resource(self, uri: str) -> MCPResult:
        """Read a resource by URI from the server that exposes it."""

        resource = self._resources.get(uri)
        if resource is None:
            return MCPResult(success=False, error=f"Unknown resource URI: '{uri}'")

        # Resources don't track server_name, so search all servers
        for server_name in list(self._servers):
            try:
                response = await self._send_request(server_name, "resources/read", {
                    "uri": uri,
                })
                if "error" not in response:
                    result = response.get("result", {})
                    contents = result.get("contents", [])
                    return MCPResult(
                        success=True,
                        content=contents,
                        metadata={"uri": uri, "server": server_name},
                    )
            except Exception:
                continue

        return MCPResult(success=False, error=f"No server could serve resource: '{uri}'")

    # ── introspection ────────────────────────────────────────────────

    def list_tools(self) -> List[MCPTool]:
        """Return all currently cached tools across every connected server."""
        return list(self._tools.values())

    def list_servers(self) -> Dict[str, bool]:
        """Return a mapping of server name to connection status."""
        return {
            name: transport.is_connected
            for name, transport in self._servers.items()
        }

    # ── cleanup ──────────────────────────────────────────────────────

    async def close_all(self) -> None:
        """Disconnect every server and clear all caches."""

        names = list(self._servers.keys())
        for name in names:
            await self._force_close(name)

        self._tools.clear()
        self._resources.clear()
        logger.info("MCPClient: all servers closed")

    # ── private helpers ──────────────────────────────────────────────

    async def _send_request(
        self,
        server: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC 2.0 request and wait for the matching response.

        Notifications received while waiting are logged and discarded.
        """

        transport = self._servers.get(server)
        if transport is None:
            raise ConnectionError(f"No transport for server '{server}'")

        self._request_id += 1
        req_id = self._request_id

        request = _jsonrpc_request(method, params, req_id)
        await transport.send(request)

        # Read responses until we get the one matching our id.
        # MCP servers may send notifications in between.
        while True:
            response = await transport.receive()

            # Notification (no id) -- log and continue waiting
            if "id" not in response:
                logger.debug("Notification from '%s': %s", server, response.get("method"))
                continue

            if response.get("id") == req_id:
                return response

            # Response for a different id -- log and keep waiting
            logger.warning(
                "Unexpected response id %s (expected %s) from '%s'",
                response.get("id"),
                req_id,
                server,
            )

    async def _try_reconnect(self, server_name: str) -> bool:
        """Attempt to reconnect to a previously configured server."""

        config = self._server_configs.get(server_name)
        if config is None:
            return False

        logger.info("Attempting reconnection to '%s'", server_name)
        result = await self.connect_server(server_name, config)
        if result.success:
            # Re-discover tools so they stay available
            try:
                await self.discover_tools(server_name)
            except Exception as exc:
                logger.warning("Tool re-discovery failed after reconnect: %s", exc)
            return True
        return False

    async def _force_close(self, name: str) -> None:
        """Close a transport and remove it from the registry."""

        transport = self._servers.pop(name, None)
        self._server_configs.pop(name, None)
        if transport is not None:
            try:
                await transport.close()
            except Exception as exc:
                logger.warning("Error closing transport for '%s': %s", name, exc)
