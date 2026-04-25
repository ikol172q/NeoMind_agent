"""V9 · runtime layer-budget override — per-process dict + hash.

These tests live at runtime level (no live backend). Pipeline-level
integration tests (that a new override actually changes the themes
output) are already covered by test_lattice_budgets.py — this file
only covers the override mechanism itself.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.lattice_fast


@pytest.fixture(autouse=True)
def _clear_override():
    from agent.finance.lattice import runtime
    runtime.set_budget_override(None)
    yield
    runtime.set_budget_override(None)


def test_no_override_returns_yaml_default():
    from agent.finance.lattice import runtime
    from agent.finance.lattice.taxonomy import load_taxonomy
    assert runtime.get_budget_override() is None
    assert runtime.get_effective_budgets() == load_taxonomy().layer_budgets


def test_partial_override_merges_onto_yaml():
    """Overriding themes.max_items must NOT wipe calls / sub_themes."""
    from agent.finance.lattice import runtime
    from agent.finance.lattice.taxonomy import load_taxonomy
    yaml = load_taxonomy().layer_budgets
    runtime.set_budget_override({"themes": {"max_items": 8}})
    eff = runtime.get_effective_budgets()
    assert eff.themes.max_items == 8
    # calls + sub_themes are untouched
    assert eff.calls == yaml.calls
    assert eff.sub_themes == yaml.sub_themes
    assert eff.observations == yaml.observations


def test_override_can_tune_mmr_lambda():
    from agent.finance.lattice import runtime
    runtime.set_budget_override({"calls": {"mmr_lambda": 0.3}})
    assert abs(runtime.get_effective_budgets().calls.mmr_lambda - 0.3) < 1e-9


def test_override_invalid_raises_valueerror():
    from agent.finance.lattice import runtime
    with pytest.raises(ValueError):
        runtime.set_budget_override({"themes": {"max_items": -1}})
    with pytest.raises(ValueError):
        runtime.set_budget_override({"calls": {"mmr_lambda": 1.5}})
    with pytest.raises(ValueError):
        runtime.set_budget_override({"sub_themes": {"min_members": -1}})


def test_clear_override_with_none_and_empty_dict():
    from agent.finance.lattice import runtime
    from agent.finance.lattice.taxonomy import load_taxonomy
    yaml = load_taxonomy().layer_budgets
    runtime.set_budget_override({"themes": {"max_items": 8}})
    # None clears
    runtime.set_budget_override(None)
    assert runtime.get_effective_budgets() == yaml
    # Empty dict also clears
    runtime.set_budget_override({"themes": {"max_items": 8}})
    runtime.set_budget_override({})
    assert runtime.get_effective_budgets() == yaml


def test_budget_hash_stable_and_distinguishes_overrides():
    from agent.finance.lattice import runtime
    base = runtime.get_effective_budgets()
    h1 = runtime.budget_hash(base)
    h2 = runtime.budget_hash(base)
    assert h1 == h2   # stable
    runtime.set_budget_override({"themes": {"max_items": 7}})
    h3 = runtime.budget_hash(runtime.get_effective_budgets())
    assert h3 != h1   # distinguishes
    # identical override → same hash
    runtime.set_budget_override({"themes": {"max_items": 7}})
    h4 = runtime.budget_hash(runtime.get_effective_budgets())
    assert h4 == h3


def test_override_affects_get_effective_budgets_not_taxonomy():
    """The raw taxonomy YAML must remain untouched by runtime overrides —
    this is what lets 'clear' restore the original state cleanly."""
    from agent.finance.lattice import runtime
    from agent.finance.lattice.taxonomy import load_taxonomy
    yaml_before = load_taxonomy().layer_budgets
    runtime.set_budget_override({"themes": {"max_items": 99}})
    yaml_after = load_taxonomy().layer_budgets
    assert yaml_before == yaml_after
    assert runtime.get_effective_budgets().themes.max_items == 99


def test_override_layer_value_dict_type_required():
    from agent.finance.lattice import runtime
    with pytest.raises(ValueError):
        # layer value must be a dict, not a scalar
        runtime.set_budget_override({"themes": 5})  # type: ignore[arg-type]
