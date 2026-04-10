"""Tests for agent.query_engine — QueryEngine, TokenBudget, Compactor, Normalizer.

Tests that all Claude Code-inspired components work correctly:
- TokenBudget tracks usage and triggers warnings/compaction
- MessageNormalizer deduplicates and cleans messages
- ContextCompactor compresses old messages (heuristic + LLM)
- QueryEngine orchestrates the full turn loop
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.query_engine import (
    TokenBudget,
    MessageNormalizer,
    ContextCompactor,
    QueryEngine,
    QueryEvent,
    QueryEventType,
)


# ─── TokenBudget Tests ───────────────────────────────────────────────

class TestTokenBudget:
    def test_initial_state(self):
        budget = TokenBudget(max_context_tokens=100000)
        assert budget.total_input_tokens == 0
        assert budget.total_output_tokens == 0
        assert budget.usage_ratio == 0.0
        assert budget.turn_count == 0

    def test_record_usage(self):
        budget = TokenBudget(max_context_tokens=100000)
        budget.start_turn()
        budget.record_usage(input_tokens=500, output_tokens=200, cost_usd=0.001)
        assert budget.turn_input_tokens == 500
        assert budget.turn_output_tokens == 200
        assert budget.total_input_tokens == 500
        assert budget.total_output_tokens == 200
        assert budget.total_cost_usd == pytest.approx(0.001)

    def test_cumulative_across_turns(self):
        budget = TokenBudget(max_context_tokens=10000)
        budget.start_turn()
        budget.record_usage(input_tokens=1000, output_tokens=500)
        budget.start_turn()
        budget.record_usage(input_tokens=2000, output_tokens=1000)
        assert budget.total_input_tokens == 3000
        assert budget.total_output_tokens == 1500
        assert budget.turn_input_tokens == 2000  # Only current turn
        assert budget.turn_count == 2

    def test_warning_threshold(self):
        budget = TokenBudget(max_context_tokens=10000, warning_threshold=0.6)
        budget.record_usage(input_tokens=3000, output_tokens=3100)
        assert budget.should_warn() is True
        # Second call should not warn again
        assert budget.should_warn() is False

    def test_no_warning_below_threshold(self):
        budget = TokenBudget(max_context_tokens=10000, warning_threshold=0.6)
        budget.record_usage(input_tokens=1000, output_tokens=1000)
        assert budget.should_warn() is False

    def test_compact_threshold(self):
        budget = TokenBudget(max_context_tokens=10000, compact_threshold=0.8)
        budget.record_usage(input_tokens=4000, output_tokens=4100)
        assert budget.should_compact() is True

    def test_after_compact(self):
        budget = TokenBudget(max_context_tokens=10000, compact_threshold=0.8)
        budget.record_usage(input_tokens=5000, output_tokens=4000)
        assert budget.should_compact() is True
        budget.after_compact(tokens_freed=6000)
        assert budget.total_input_tokens == 0  # max(0, 5000 - 6000)
        assert budget.should_compact() is False

    def test_usage_ratio_zero_max(self):
        budget = TokenBudget(max_context_tokens=0)
        assert budget.usage_ratio == 0.0

    def test_summary(self):
        budget = TokenBudget(max_context_tokens=10000)
        budget.start_turn()
        budget.record_usage(input_tokens=100, output_tokens=50, cost_usd=0.0005)
        summary = budget.get_summary()
        assert summary["turn"] == 1
        assert summary["turn_input"] == 100
        assert summary["total_cost_usd"] == pytest.approx(0.0005)
        assert "usage_ratio" in summary


# ─── MessageNormalizer Tests ──────────────────────────────────────────

class TestMessageNormalizer:
    def test_empty_messages(self):
        assert MessageNormalizer.normalize([]) == []

    def test_skip_empty_content(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "world"},
        ]
        result = MessageNormalizer.normalize(messages)
        # Empty assistant skipped, user+user merged if adjacent
        assert all(m["content"] for m in result)

    def test_merge_adjacent_same_role(self):
        messages = [
            {"role": "user", "content": "part 1"},
            {"role": "user", "content": "part 2"},
        ]
        result = MessageNormalizer.normalize(messages)
        assert len(result) == 1
        assert "part 1" in result[0]["content"]
        assert "part 2" in result[0]["content"]

    def test_no_merge_system(self):
        messages = [
            {"role": "system", "content": "sys 1"},
            {"role": "system", "content": "sys 2"},
        ]
        result = MessageNormalizer.normalize(messages)
        assert len(result) == 2

    def test_list_content_flattened(self):
        messages = [
            {"role": "user", "content": [
                {"text": "hello"},
                {"text": "world"},
            ]},
        ]
        result = MessageNormalizer.normalize(messages)
        assert "hello" in result[0]["content"]
        assert "world" in result[0]["content"]

    def test_estimate_tokens(self):
        messages = [
            {"role": "user", "content": "a" * 400},  # ~100 tokens
        ]
        est = MessageNormalizer.estimate_tokens(messages)
        assert 90 <= est <= 120  # rough estimate


# ─── ContextCompactor Tests ──────────────────────────────────────────

class TestContextCompactor:
    def test_heuristic_compact(self):
        compactor = ContextCompactor()
        messages = [
            {"role": "user", "content": f"Message {i} " + "x" * 200}
            for i in range(20)
        ]
        result = compactor._heuristic_compact(messages)
        assert result["role"] == "system"
        assert "Context Summary" in result["content"]

    @pytest.mark.asyncio
    async def test_auto_compact_too_few_messages(self):
        compactor = ContextCompactor()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        new_msgs, freed = await compactor.auto_compact(messages, keep_recent=5)
        assert new_msgs == messages  # Not enough to compact
        assert freed == 0

    @pytest.mark.asyncio
    async def test_auto_compact_with_heuristic(self):
        compactor = ContextCompactor()  # No LLM caller = heuristic
        messages = [
            {"role": "system", "content": "System prompt"},
        ] + [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Msg {i} " + "x" * 100}
            for i in range(20)
        ]
        new_msgs, freed = await compactor.auto_compact(messages, keep_recent=3)
        assert len(new_msgs) < len(messages)
        assert freed > 0
        # System message should be preserved
        assert new_msgs[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_auto_compact_with_llm(self):
        mock_llm = AsyncMock(return_value="Summary of old conversation.")
        compactor = ContextCompactor(llm_caller=mock_llm)
        messages = [
            {"role": "system", "content": "sys"},
        ] + [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Msg {i} data"}
            for i in range(15)
        ]
        new_msgs, freed = await compactor.auto_compact(messages, keep_recent=3)
        assert mock_llm.called
        assert "Summary" in str(new_msgs) or "compacted" in str(new_msgs).lower()

    @pytest.mark.asyncio
    async def test_micro_compact_small_messages_unchanged(self):
        compactor = ContextCompactor()
        messages = [
            {"role": "assistant", "content": "Short response"},
        ]
        result = await compactor.micro_compact(messages)
        assert result == messages

    def test_compress_tool_results(self):
        content = "<tool_result>" + "x" * 10000 + "</tool_result>"
        compressed = ContextCompactor._compress_tool_results(content, max_tokens=100)
        assert len(compressed) < len(content)
        assert "truncated" in compressed


# ─── QueryEngine Tests ────────────────────────────────────────────────

class TestQueryEngine:
    def _mock_config(self):
        mock = MagicMock()
        mock.get.side_effect = lambda k, d=None: {
            "context.max_context_tokens": 100000,
            "context.warning_threshold": 0.6,
            "context.break_threshold": 0.8,
            "compact.keep_recent_turns": 5,
        }.get(k, d)
        mock.mode = "chat"
        return mock

    def test_init_defaults(self):
        config = self._mock_config()
        engine = QueryEngine(config=config)
        assert engine.turn_count == 0
        assert engine.budget.max_context_tokens == 100000

    def test_add_messages(self):
        config = self._mock_config()
        engine = QueryEngine(config=config)
        engine.add_system_message("System")
        engine.add_user_message("Hello")
        engine.add_assistant_message("Hi")
        assert len(engine.messages) == 3
        assert engine.messages[0]["role"] == "system"
        assert engine.messages[1]["role"] == "user"
        assert engine.messages[2]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_run_turn_basic(self):
        """Test a basic turn with no tools."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda k, d=None: d
        mock_config.mode = "chat"

        mock_llm = AsyncMock(return_value={
            "content": "Hello! How can I help?",
            "thinking": "",
            "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        })

        engine = QueryEngine(
            llm_caller=mock_llm,
            config=mock_config,
        )

        events = []
        async for event in engine.run_turn("Hi there"):
            events.append(event)

        event_types = [e.type for e in events]
        assert QueryEventType.TURN_START in event_types
        assert QueryEventType.LLM_STREAM_START in event_types
        assert QueryEventType.LLM_STREAM_END in event_types
        assert QueryEventType.TURN_END in event_types

    def test_get_state(self):
        config = self._mock_config()
        engine = QueryEngine(config=config)
        state = engine.get_state()
        assert "turn_count" in state
        assert "budget" in state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
