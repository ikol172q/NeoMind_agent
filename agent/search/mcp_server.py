# agent/search/mcp_server.py
"""
MCP Web Search Server — expose NeoMind search as an MCP tool.

This module provides a Model Context Protocol (MCP) server that wraps
UniversalSearchEngine and exposes it as a standardized tool for external
agents, IDEs, and other MCP-compatible clients.

Usage:
    # Start the server
    python -m agent.search.mcp_server

    # Or import and use programmatically
    from agent.search.mcp_server import create_mcp_server
    server = create_mcp_server()

Dependencies:
    pip install mcp

Protocol: MCP (Model Context Protocol) — https://modelcontextprotocol.io
"""

import os
import sys
import json
import asyncio
from typing import Any, Dict, Optional

# ── Optional MCP imports ─────────────────────────────────────────────

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    Server = None


def create_mcp_server(domain: str = "general") -> Optional[Any]:
    """Create an MCP server wrapping UniversalSearchEngine.

    Returns None if MCP dependencies are not installed.
    """
    if not HAS_MCP:
        return None

    from .engine import UniversalSearchEngine

    app = Server("neomind-search")
    engine = UniversalSearchEngine(domain=domain)

    @app.list_tools()
    async def list_tools():
        return [
            Tool(
                name="web_search",
                description=(
                    "Search the web using NeoMind's multi-source search engine. "
                    "Aggregates results from DuckDuckGo, Google News, Brave, Serper, "
                    "Tavily, Jina, and more. Results are fused with RRF, "
                    "semantically reranked with FlashRank, and content-extracted."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 10)",
                            "default": 10,
                        },
                        "domain": {
                            "type": "string",
                            "description": "Search domain context: general, finance, tech, news",
                            "enum": ["general", "finance", "tech", "news"],
                            "default": "general",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="search_status",
                description="Get the status of the NeoMind search engine (active sources, intelligence layers).",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="search_metrics",
                description="Get search quality metrics for the current session.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]):
        if name == "web_search":
            query = arguments.get("query", "")
            max_results = arguments.get("max_results", 10)
            req_domain = arguments.get("domain", "general")

            if req_domain != engine.domain:
                engine.set_domain(req_domain)

            result = await engine.search_advanced(
                query=query,
                max_results=max_results,
            )

            if result.error:
                return [TextContent(type="text", text=f"Search error: {result.error}")]

            text = result.format_for_llm(max_items=max_results, include_full_text=True)
            header = (
                f"Found {len(result.items)} results from {len(result.sources_used)} sources"
                f"{' (reranked)' if result.reranked else ''}"
                f"{' (cached)' if result.cached else ''}"
            )
            return [TextContent(type="text", text=f"{header}\n\n{text}")]

        elif name == "search_status":
            return [TextContent(type="text", text=engine.get_status())]

        elif name == "search_metrics":
            report = engine.metrics.format_report()
            return [TextContent(type="text", text=report)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return app


async def run_server():
    """Run the MCP server over stdio."""
    if not HAS_MCP:
        print("Error: MCP not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    server = create_mcp_server()
    if server is None:
        print("Error: Failed to create MCP server.", file=sys.stderr)
        sys.exit(1)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Entry point for `python -m agent.search.mcp_server`."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
