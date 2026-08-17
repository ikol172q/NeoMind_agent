"""Phase 8 prerequisite — `/cost` has to be right before anything is deleted.

The plan makes this a gate: `budget` is a live `/cost` dependency, so relocating
it is a prerequisite for removing the legacy paths, not an optional harvest.

Checking it turned up something worse than a migration gap. `/cost` reported
`$0.0000` and `0 in / 0 out` after a real turn while the status bar showed
thousands of tokens — and not because the REPL had migrated. The pricing lookup
read `agent_config._config`, an attribute that stopped existing when the config
became a context-scoped proxy, and both call sites wrapped it in a bare
`except`. So every model priced at zero, on **both** paths, silently.
"""

from __future__ import annotations

import pytest

from agent.runtime.llm_stream import UsageChunk
from agent.runtime.usage_accounting import (
    cost_for,
    pricing_for_model,
    pricing_unavailable,
)


class TestPricingLookup:

    def test_the_table_is_reachable(self):
        """The whole failure was that it was not, and nothing said so."""
        assert pricing_unavailable() is False

    def test_a_known_model_has_a_price(self):
        pricing = pricing_for_model("deepseek-v4-flash")
        assert pricing.get("input") and pricing.get("output"), (
            "an empty table here prices every turn at zero"
        )

    def test_an_unknown_model_is_empty_without_raising(self):
        """An unpriced model should still stream."""
        assert pricing_for_model("no-such-model-9000") == {}

    def test_a_broken_table_is_distinguishable_from_an_unpriced_model(self):
        """Both give $0.00. Only one is a bug, and a surface that shows the
        same thing for both leaves nobody able to tell."""
        assert pricing_unavailable() is False
        assert pricing_for_model("no-such-model-9000") == {}


class TestArithmetic:

    def test_cost_is_per_million_tokens(self):
        usage = UsageChunk(
            prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000
        )
        pricing = {"input": 0.14, "output": 0.28}
        assert cost_for(usage, pricing) == pytest.approx(0.42)

    def test_input_and_output_are_priced_separately(self):
        """Output usually costs more; averaging them understates every turn."""
        usage = UsageChunk(prompt_tokens=1_000_000, completion_tokens=0, total_tokens=1_000_000)
        assert cost_for(usage, {"input": 0.14, "output": 0.28}) == pytest.approx(0.14)

    def test_an_unpriced_model_costs_zero_rather_than_raising(self):
        usage = UsageChunk(prompt_tokens=100, completion_tokens=100, total_tokens=200)
        assert cost_for(usage, {}) == 0.0

    def test_a_real_turn_costs_a_real_amount(self):
        """The end-to-end claim: provider-reported usage through the real
        table produces a non-zero number."""
        usage = UsageChunk(prompt_tokens=7_000, completion_tokens=900, total_tokens=7_900)
        cost = cost_for(usage, pricing_for_model("deepseek-v4-flash"))
        assert cost > 0, "this is what /cost was reporting as $0.0000"


class TestTheReplRecordsIt:

    def test_the_session_path_writes_usage_into_the_budget(self):
        """The session path does not go through QueryEngine, which owns the
        budget `/cost` reads — so without this nothing writes it."""
        import sys
        from unittest import mock

        sys.argv = ["x"]
        from cli.neomind_interface import NeoMindInterface

        recorded = {}

        class Budget:
            def record_usage(self, input_tokens, output_tokens, cost_usd):
                recorded.update(
                    input=input_tokens, output=output_tokens, cost=cost_usd
                )

        iface = NeoMindInterface.__new__(NeoMindInterface)
        iface.chat = mock.MagicMock()
        iface.chat.model = "deepseek-v4-flash"
        iface.chat._query_engine = mock.Mock(budget=Budget())

        outcome = mock.Mock(usage={"prompt_tokens": 1_000_000,
                                   "completion_tokens": 1_000_000})
        iface._record_turn_usage(outcome)

        assert recorded["input"] == 1_000_000
        assert recorded["output"] == 1_000_000
        assert recorded["cost"] == pytest.approx(0.42)

    def test_a_turn_with_no_usage_records_nothing(self):
        import sys
        from unittest import mock

        sys.argv = ["x"]
        from cli.neomind_interface import NeoMindInterface

        iface = NeoMindInterface.__new__(NeoMindInterface)
        iface.chat = mock.MagicMock()
        iface.chat._query_engine = mock.Mock(budget=mock.Mock())
        iface._record_turn_usage(mock.Mock(usage={}))
        iface.chat._query_engine.budget.record_usage.assert_not_called()

    def test_a_missing_budget_does_not_break_the_turn(self):
        """The answer is already on screen by the time this runs."""
        import sys
        from unittest import mock

        sys.argv = ["x"]
        from cli.neomind_interface import NeoMindInterface

        iface = NeoMindInterface.__new__(NeoMindInterface)
        iface.chat = mock.MagicMock()
        iface.chat._query_engine = None
        iface._record_turn_usage(mock.Mock(usage={"prompt_tokens": 1}))

    def test_a_failing_budget_does_not_break_the_turn(self):
        import sys
        from unittest import mock

        sys.argv = ["x"]
        from cli.neomind_interface import NeoMindInterface

        class Exploding:
            def record_usage(self, **kw):
                raise RuntimeError("disk full")

        iface = NeoMindInterface.__new__(NeoMindInterface)
        iface.chat = mock.MagicMock()
        iface.chat.model = "deepseek-v4-flash"
        iface.chat.verbose_mode = False
        iface.chat._query_engine = mock.Mock(budget=Exploding())
        iface._record_turn_usage(mock.Mock(usage={"prompt_tokens": 10,
                                                   "completion_tokens": 5}))


class TestNoBareExceptOnPricing:
    """Both call sites swallowed an AttributeError for months. The guard has
    to stay — an accounting failure must not kill a turn — but it must not be
    the reason nobody noticed."""

    @staticmethod
    def _reads_dunder_config(path) -> bool:
        """Parsed, not grepped.

        The first version of this test searched the text and failed on the
        comment explaining the fix — the same mistake as an earlier import
        check that matched a docstring saying "does not import telegram".
        A comment about an attribute is not an access of it.
        """
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_config":
                return True
        return False

    def test_the_legacy_path_no_longer_reads_the_removed_attribute(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        assert not self._reads_dunder_config(
            root / "agent" / "services" / "code_commands.py"
        )

    def test_the_accounting_module_no_longer_reads_it_either(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        assert not self._reads_dunder_config(
            root / "agent" / "runtime" / "usage_accounting.py"
        )
