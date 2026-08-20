"""Phase 2 gate — `/cost` survives the streaming extraction.

The gate is explicit that asserting the call exists is not enough: it asks for
a real `/cost` value. So these drive the real `TokenBudget` and the real
`/cost` command handler, and read the string a user would see.
"""

from __future__ import annotations

import pytest

from agent.runtime.llm_stream import UsageChunk
from agent.runtime.usage_accounting import (
    UsageRecorderPort,
    cost_for,
    pricing_for_model,
    record_usage_chunk,
)


def make_budget():
    from agent.query_engine import TokenBudget

    return TokenBudget()


PRICING = {"input": 0.27, "output": 1.10}  # per 1M tokens


class TestCostArithmetic:

    def test_cost_is_per_million_tokens(self):
        usage = UsageChunk(prompt_tokens=1_000_000, completion_tokens=0)
        assert cost_for(usage, PRICING) == pytest.approx(0.27)

    def test_input_and_output_are_priced_separately(self):
        usage = UsageChunk(prompt_tokens=500_000, completion_tokens=1_000_000)
        assert cost_for(usage, PRICING) == pytest.approx(0.27 / 2 + 1.10)

    def test_unpriced_model_costs_zero_rather_than_raising(self):
        assert cost_for(UsageChunk(prompt_tokens=999, completion_tokens=999), {}) == 0.0

    def test_missing_pricing_table_is_survivable(self):
        assert cost_for(UsageChunk(prompt_tokens=10), None) == 0.0

    def test_pricing_lookup_never_raises_for_an_unknown_model(self):
        assert pricing_for_model("no-such-model-anywhere") == {}


class TestRecordingIntoTheRealBudget:

    def test_the_real_token_budget_satisfies_the_port(self):
        assert isinstance(make_budget(), UsageRecorderPort)

    def test_provider_counts_land_in_the_budget(self):
        budget = make_budget()
        record_usage_chunk(
            budget, UsageChunk(prompt_tokens=96, completion_tokens=13), PRICING
        )
        summary = budget.get_summary()
        assert summary["total_input"] == 96
        assert summary["total_output"] == 13

    def test_cost_accumulates_across_calls(self):
        budget = make_budget()
        for _ in range(3):
            record_usage_chunk(
                budget, UsageChunk(prompt_tokens=1_000_000, completion_tokens=0), PRICING
            )
        assert budget.get_summary()["total_cost_usd"] == pytest.approx(0.81, abs=1e-6)

    def test_recorded_cost_is_returned(self):
        budget = make_budget()
        cost = record_usage_chunk(
            budget, UsageChunk(prompt_tokens=1_000_000, completion_tokens=1_000_000), PRICING
        )
        assert cost == pytest.approx(1.37)


class TestCostCommandOutput:
    """End to end: a UsageChunk in, the user-visible `/cost` string out."""

    def _cost_text(self, budget):
        from agent.cli_command_system import create_default_registry

        registry = create_default_registry()
        cmd = None
        for attr in ("commands", "_commands"):
            table = getattr(registry, attr, None)
            if isinstance(table, dict) and "cost" in table:
                cmd = table["cost"]
                break
        assert cmd is not None, "the /cost command should be registered"

        class _Engine:
            pass

        engine = _Engine()
        engine.budget = budget
        result = cmd.handler("", agent=None, context={"query_engine": engine})
        return result.text

    def test_cost_reports_the_tokens_the_provider_reported(self):
        budget = make_budget()
        record_usage_chunk(
            budget, UsageChunk(prompt_tokens=96, completion_tokens=13), PRICING
        )
        text = self._cost_text(budget)
        assert "96 in / 13 out" in text, text

    def test_cost_reports_a_real_dollar_figure(self):
        budget = make_budget()
        # 1M in, 1M out at the table above = 0.27 + 1.10
        record_usage_chunk(
            budget, UsageChunk(prompt_tokens=1_000_000, completion_tokens=1_000_000), PRICING
        )
        text = self._cost_text(budget)
        assert "Session cost: $1.3700" in text, text

    def test_cost_without_an_engine_says_so_rather_than_crashing(self):
        from agent.cli_command_system import create_default_registry

        registry = create_default_registry()
        table = getattr(registry, "commands", None) or getattr(registry, "_commands")
        result = table["cost"].handler("", agent=None, context={})
        assert "not available" in result.text.lower()
