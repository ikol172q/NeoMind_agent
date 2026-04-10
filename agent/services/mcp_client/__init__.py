"""MCP Client package for NeoMind Agent.

Provides a high-level client for connecting to MCP (Model Context Protocol)
servers, discovering tools/resources, and invoking them over stdio or HTTP
transports using JSON-RPC 2.0.

Created: 2026-04-02
"""

from __future__ import annotations

from agent.services.mcp_client.client import MCPClient, MCPResource, MCPResult, MCPTool
from agent.services.mcp_client.transport import TransportConfig, TransportType

__all__ = [
    "MCPClient",
    "MCPResource",
    "MCPResult",
    "MCPTool",
    "TransportConfig",
    "TransportType",
]
