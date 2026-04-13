"""
LLM Service Module — DEPRECATED stub.

The real LLM completion logic lives in agent/services/llm_provider.py
(LLMProvider class with DeepSeek → z.ai → Moonshot → LiteLLM fallback chain).

This file was an early Phase 0 extraction attempt that was never completed.
It is kept as a thin redirect so any future imports don't break.

Created: 2026-04-01 (Phase 0 - Infrastructure Refactoring)
Cleaned: 2026-04-11 (removed malformed code, redirected to real provider)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core import NeoMindAgent


def get_llm_provider():
    """Get the real LLM provider instance.

    Usage:
        from agent.llm_service import get_llm_provider
        provider = get_llm_provider()
        # Use provider.resolve_with_fallback(), etc.
    """
    from agent.services.llm_provider import LLMProvider
    return LLMProvider()
