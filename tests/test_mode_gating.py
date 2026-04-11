"""Unit tests for ToolDefinition.allowed_modes + ToolRegistry.get_all_tools(mode).

These tests cover the mode-gating foundation committed in eea40a0. They
are the only part of this session's validation that is NOT a real
Telegram/CLI interaction — mode gating is an internal prompt-building
concern, not a user-visible behavior, so unit tests are the appropriate
tool here.

Five tests:
  1. Tool with allowed_modes={"fin"} is visible in fin mode only.
  2. Tool with allowed_modes=None (legacy) is always visible.
  3. Passing mode=None to is_available_in_mode preserves legacy behavior.
  4. ToolRegistry.get_all_tools("fin") filters tools correctly.
  5. ToolRegistry.get_all_tools() with no mode returns every registered tool.
"""

from __future__ import annotations

import pytest

from agent.coding.tool_schema import (
    ToolDefinition,
    ToolParam,
    ParamType,
    PermissionLevel,
)
from agent.coding.tools import ToolRegistry


# ── Helpers ───────────────────────────────────────────────────────────

def _make_tool(name: str, allowed_modes=None) -> ToolDefinition:
    """Build a minimal valid ToolDefinition for testing."""
    return ToolDefinition(
        name=name,
        description=f"test tool {name}",
        parameters=[],
        permission_level=PermissionLevel.READ_ONLY,
        execute=lambda: None,
        allowed_modes=allowed_modes,
    )


# ── Test 1 — mode-specific visibility ─────────────────────────────────

def test_tool_with_fin_mode_only_visible_in_fin():
    """A tool with allowed_modes={'fin'} is visible in fin mode, hidden in others."""
    t = _make_tool("finance_test", allowed_modes={"fin"})
    assert t.is_available_in_mode("fin") is True
    assert t.is_available_in_mode("chat") is False
    assert t.is_available_in_mode("coding") is False
    assert t.is_available_in_mode("nonexistent_mode") is False


# ── Test 2 — legacy tools (no allowed_modes) always visible ───────────

def test_tool_without_allowed_modes_always_visible():
    """Tools without allowed_modes (legacy default) are visible in every mode."""
    t = _make_tool("legacy_tool", allowed_modes=None)
    assert t.is_available_in_mode("fin") is True
    assert t.is_available_in_mode("chat") is True
    assert t.is_available_in_mode("coding") is True
    assert t.is_available_in_mode("any_future_mode") is True


# ── Test 3 — None mode preserves legacy behavior ──────────────────────

def test_none_mode_preserves_legacy_behavior():
    """When caller passes mode=None (doesn't know), don't filter.

    This is crucial for backward compatibility — any old code path that
    calls is_available_in_mode() without a mode argument must still see
    every tool regardless of allowed_modes.
    """
    fin_tool = _make_tool("fin_only", allowed_modes={"fin"})
    legacy_tool = _make_tool("legacy", allowed_modes=None)
    multi_tool = _make_tool("multi", allowed_modes={"fin", "chat"})

    assert fin_tool.is_available_in_mode(None) is True
    assert legacy_tool.is_available_in_mode(None) is True
    assert multi_tool.is_available_in_mode(None) is True


# ── Test 4 — ToolRegistry filters by mode ─────────────────────────────

def test_registry_get_all_tools_filters_by_mode():
    """ToolRegistry.get_all_tools(mode='fin') returns only fin-visible tools.

    Uses a fresh ToolRegistry with a custom set of tools (avoids touching
    the default tool list so tests are deterministic).
    """
    reg = ToolRegistry()
    # Wipe the default tools the __init__ registered and use our own
    reg._tool_definitions = {
        "shared_tool": _make_tool("shared_tool"),  # allowed_modes=None
        "fin_only": _make_tool("fin_only", allowed_modes={"fin"}),
        "chat_only": _make_tool("chat_only", allowed_modes={"chat"}),
        "fin_and_coding": _make_tool(
            "fin_and_coding", allowed_modes={"fin", "coding"}
        ),
    }

    fin_tools = reg.get_all_tools(mode="fin")
    fin_names = {t.name for t in fin_tools}
    assert "shared_tool" in fin_names       # no allowed_modes = always visible
    assert "fin_only" in fin_names          # explicitly in fin
    assert "fin_and_coding" in fin_names    # fin is in the set
    assert "chat_only" not in fin_names     # chat-only excluded from fin

    chat_tools = reg.get_all_tools(mode="chat")
    chat_names = {t.name for t in chat_tools}
    assert "shared_tool" in chat_names
    assert "chat_only" in chat_names
    assert "fin_only" not in chat_names
    assert "fin_and_coding" not in chat_names

    coding_tools = reg.get_all_tools(mode="coding")
    coding_names = {t.name for t in coding_tools}
    assert "shared_tool" in coding_names
    assert "fin_and_coding" in coding_names
    assert "fin_only" not in coding_names
    assert "chat_only" not in coding_names


# ── Test 5 — Default (no mode) returns everything ────────────────────

def test_registry_get_all_tools_none_returns_all():
    """ToolRegistry.get_all_tools() with no mode returns every tool.

    This preserves backward compatibility — existing callers that didn't
    pass a mode should continue to see every tool as before.
    """
    reg = ToolRegistry()
    reg._tool_definitions = {
        "shared_tool": _make_tool("shared_tool"),
        "fin_only": _make_tool("fin_only", allowed_modes={"fin"}),
        "chat_only": _make_tool("chat_only", allowed_modes={"chat"}),
    }

    all_tools = reg.get_all_tools()  # no mode argument
    names = {t.name for t in all_tools}
    assert "shared_tool" in names
    assert "fin_only" in names
    assert "chat_only" in names
    assert len(names) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
