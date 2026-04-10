"""Tests for agent.prompt_composer — DynamicPromptComposer.

Tests the Claude Code SYSTEM_PROMPT_DYNAMIC_BOUNDARY pattern:
- Static sections are cached and ordered by priority
- Dynamic sections are rebuilt per-turn
- Tool sections auto-generated from registry
- Budget info injected when approaching limits
"""

import pytest
from unittest.mock import MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.prompt_composer import (
    DynamicPromptComposer,
    PromptSection,
    PROMPT_DYNAMIC_BOUNDARY,
    _split_prompt_sections,
)


class TestPromptSection:
    def test_basic(self):
        s = PromptSection("test", "content", cacheable=True, priority=10)
        assert s.name == "test"
        assert s.cacheable is True
        assert s.priority == 10
        assert "test" in repr(s)


class TestDynamicPromptComposer:
    def test_static_sections(self):
        composer = DynamicPromptComposer()
        composer.set_static("identity", "You are NeoMind.", priority=0)
        composer.set_static("rules", "Be helpful.", priority=10)
        result = composer.compose()
        assert "You are NeoMind" in result
        assert "Be helpful" in result
        # Identity should come before rules (lower priority = earlier)
        assert result.index("NeoMind") < result.index("Be helpful")

    def test_dynamic_boundary_present(self):
        composer = DynamicPromptComposer()
        composer.set_static("test", "Static part")
        result = composer.compose()
        assert "DYNAMIC CONTEXT" in result

    def test_static_caching(self):
        composer = DynamicPromptComposer()
        composer.set_static("a", "Content A")
        # First call builds cache
        r1 = composer._get_cached_static()
        assert composer._cache_dirty is False
        # Second call uses cache
        r2 = composer._get_cached_static()
        assert r1 == r2

    def test_cache_invalidation(self):
        composer = DynamicPromptComposer()
        composer.set_static("a", "V1")
        r1 = composer._get_cached_static()
        composer.set_static("a", "V2")
        assert composer._cache_dirty is True
        r2 = composer._get_cached_static()
        assert r2 != r1
        assert "V2" in r2

    def test_remove_static(self):
        composer = DynamicPromptComposer()
        composer.set_static("a", "Section A")
        composer.set_static("b", "Section B")
        composer.remove_static("a")
        result = composer.compose()
        assert "Section A" not in result
        assert "Section B" in result

    def test_dynamic_providers(self):
        composer = DynamicPromptComposer()
        composer.set_static("base", "Base prompt")

        def my_provider(mode=None, tool_registry=None, budget=None):
            return PromptSection("dynamic_test", f"Mode is {mode}", cacheable=False, priority=30)

        composer.add_dynamic_provider(my_provider)
        result = composer.compose(mode="coding")
        assert "Mode is coding" in result

    def test_dynamic_provider_returns_none(self):
        composer = DynamicPromptComposer()
        composer.add_dynamic_provider(lambda **kw: None)
        result = composer.compose()
        assert result is not None  # Should not crash

    def test_dynamic_provider_error_handled(self):
        composer = DynamicPromptComposer()

        def bad_provider(**kw):
            raise ValueError("Provider error")

        composer.add_dynamic_provider(bad_provider)
        result = composer.compose()  # Should not raise
        assert result is not None

    def test_extra_context(self):
        composer = DynamicPromptComposer()
        result = composer.compose(extra_context={"workspace": "/home/user/project"})
        assert "/home/user/project" in result

    def test_budget_info_injected_when_high(self):
        composer = DynamicPromptComposer()
        mock_budget = MagicMock()
        mock_budget.usage_ratio = 0.75
        mock_budget.max_context_tokens = 100000
        result = composer.compose(budget=mock_budget)
        assert "Budget" in result or "75%" in result

    def test_budget_info_not_injected_when_low(self):
        composer = DynamicPromptComposer()
        mock_budget = MagicMock()
        mock_budget.usage_ratio = 0.3
        mock_budget.max_context_tokens = 100000
        result = composer.compose(budget=mock_budget)
        assert "Approaching limit" not in result

    def test_tool_section_from_registry(self):
        composer = DynamicPromptComposer()
        # Mock tool registry
        mock_registry = MagicMock()
        mock_tool = MagicMock()
        mock_tool.to_prompt_schema.return_value = "**Bash**: Execute commands"
        mock_registry.get_all_definitions.return_value = [mock_tool]

        result = composer.compose(tool_registry=mock_registry)
        assert "TOOL SYSTEM" in result or "Bash" in result


class TestSplitPromptSections:
    def test_no_headers(self):
        sections = _split_prompt_sections("Just a plain prompt.")
        assert len(sections) == 1
        assert sections[0][0] == "identity"

    def test_with_headers(self):
        prompt = (
            "Preamble text\n\n"
            "═══ IDENTITY ═══\n\n"
            "You are NeoMind.\n\n"
            "═══ RULES ═══\n\n"
            "Be helpful."
        )
        sections = _split_prompt_sections(prompt)
        names = [s[0] for s in sections]
        assert "preamble" in names
        assert "identity" in names
        assert "rules" in names

    def test_empty_string(self):
        sections = _split_prompt_sections("")
        assert len(sections) == 1


class TestFromConfig:
    def test_from_config_basic(self):
        mock_config = MagicMock()
        mock_config.system_prompt = "You are NeoMind.\n═══ RULES ═══\nBe good."
        composer = DynamicPromptComposer.from_config(mock_config)
        result = composer.compose()
        assert "NeoMind" in result

    def test_from_config_no_prompt(self):
        mock_config = MagicMock()
        mock_config.system_prompt = None
        composer = DynamicPromptComposer.from_config(mock_config)
        result = composer.compose()
        # Should work without crashing
        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
