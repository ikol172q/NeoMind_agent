"""Context Compactor service — LLM-driven context window compression.

Created: 2026-04-02 (Phase 2 - Coding)
"""

from __future__ import annotations

from .context_compactor import (
    CompactMessage,
    CompactResult,
    ContextCompactor,
    MessageRole,
    PreservePolicy,
)

from .context_collapse import (
    ContextCollapser,
    snip_messages,
)

__all__ = [
    "CompactMessage",
    "CompactResult",
    "ContextCompactor",
    "ContextCollapser",
    "MessageRole",
    "PreservePolicy",
    "snip_messages",
]
