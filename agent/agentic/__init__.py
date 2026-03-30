"""NeoMind Canonical Agentic Layer

This is the single source of truth for tool calling, agentic loop,
and tool execution. All frontends (CLI, Telegram, WhatsApp, API)
MUST use this layer — never implement their own tool dispatch.

Architecture:
    Any frontend
        ↓ calls
    AgenticLoop.run(messages, llm_caller)
        ↓ internally
    LLM response → ToolCallParser → ToolRegistry.execute → format result → loop
        ↓ yields
    AgenticEvent (for frontend to render however it wants)

Key classes:
    AgenticLoop   — the core loop (parse → execute → feed back → repeat)
    ToolRegistry  — tool registration and dispatch
    AgenticEvent  — structured events yielded to frontends
"""

from .agentic_loop import AgenticLoop, AgenticEvent, AgenticConfig

__all__ = ["AgenticLoop", "AgenticEvent", "AgenticConfig"]
