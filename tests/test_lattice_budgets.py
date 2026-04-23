"""V7 · layer_budgets — per-layer item-count caps driven by YAML.

Contract:
  - DEFAULT_LAYER_BUDGETS values match the old hardcoded constants
    (otherwise existing fin-core behaviour silently changes when
    this code lands)
  - YAML merge is strict: bad values raise ValueError
  - Clustering respects max_items + min_members
  - MMR respects max_items + max_candidates + mmr_lambda from budget
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent.finance.lattice import spec


pytestmark = pytest.mark.lattice_fast


# ── DEFAULT contract ───────────────────────────────────

def test_default_layer_budgets_match_hard_constants():
    """DEFAULT_LAYER_BUDGETS.calls.* must equal the spec constants.
    If they drift, V6-and-earlier production behaviour silently
    changes."""
    b = spec.DEFAULT_LAYER_BUDGETS
    assert b.calls.max_items == spec.MAX_CALLS == 3
    assert b.calls.max_candidates == spec.MAX_CANDIDATES == 5
    assert b.calls.mmr_lambda == spec.MMR_LAMBDA == 0.7
    # observations uncapped by default (historic behaviour)
    assert b.observations.max_items is None
    # themes / sub_themes: min_members=1 floor
    assert b.themes.min_members == 1
    assert b.sub_themes.min_members == 1


def test_parse_empty_yields_defaults():
    assert spec.parse_layer_budgets(None) == spec.DEFAULT_LAYER_BUDGETS
    assert spec.parse_layer_budgets({}) == spec.DEFAULT_LAYER_BUDGETS


def test_parse_merges_partial_overrides():
    b = spec.parse_layer_budgets({
        "themes": {"max_items": 5},
        "calls": {"mmr_lambda": 0.5},
    })
    # Overridden fields
    assert b.themes.max_items == 5
    assert b.calls.mmr_lambda == 0.5
    # Non-overridden fields keep defaults
    assert b.themes.min_members == 1
    assert b.calls.max_items == spec.MAX_CALLS
    assert b.calls.max_candidates == spec.MAX_CANDIDATES


# ── Parse validation ──────────────────────────────────

@pytest.mark.parametrize("bad_yaml", [
    {"themes": {"max_items": -1}},
    {"sub_themes": {"min_members": -5}},
    {"calls": {"mmr_lambda": 1.5}},         # > 1
    {"calls": {"mmr_lambda": -0.1}},        # < 0
    {"calls": {"max_candidates": 99}},      # > spec.MAX_CANDIDATES (5)
])
def test_parse_rejects_out_of_range_values(bad_yaml):
    with pytest.raises(ValueError):
        spec.parse_layer_budgets(bad_yaml)


# ── Clustering respects layer_budgets ─────────────────

def _make_obs(id_: str, tags, severity="warn"):
    from agent.finance.lattice.observations import Observation
    return Observation(id=id_, kind="test", text=f"t {id_}",
                       tags=tags, severity=severity)


def test_cluster_to_layer_respects_max_items():
    """Given a list of observations where 5 different signatures
    all match something, max_items=2 should emit only the top 2
    by (severity_rank, -member_count)."""
    from agent.finance.lattice import themes
    from agent.finance.lattice.taxonomy import ThemeSignature

    obs = [
        _make_obs("o1", ["risk:earnings"], severity="alert"),
        _make_obs("o2", ["catalyst:earnings"], severity="info"),
        _make_obs("o3", ["risk:drawdown"], severity="warn"),
        _make_obs("o4", ["pnl:large_loss"], severity="warn"),
        _make_obs("o5", ["technical:near_52w_high"], severity="info"),
    ]
    sigs = [
        ThemeSignature(id="t_earn", title="Earnings",
                       any_of=frozenset({"risk:earnings"})),
        ThemeSignature(id="t_cat", title="Catalyst",
                       any_of=frozenset({"catalyst:earnings"})),
        ThemeSignature(id="t_dd", title="Drawdown",
                       any_of=frozenset({"risk:drawdown"})),
        ThemeSignature(id="t_loss", title="Loss",
                       any_of=frozenset({"pnl:large_loss"})),
        ThemeSignature(id="t_high", title="High",
                       any_of=frozenset({"technical:near_52w_high"})),
    ]
    # No budget → all 5 themes
    all_themes = themes._cluster_to_layer(
        obs, sigs, fresh=True, generate_narratives=False, budget=None,
    )
    assert len(all_themes) == 5

    # Budget max_items=2 → top 2 only, sorted by severity
    capped = themes._cluster_to_layer(
        obs, sigs, fresh=True, generate_narratives=False,
        budget=spec.LayerBudget(max_items=2),
    )
    assert len(capped) == 2
    # alert-severity theme must come first
    assert capped[0].severity == "alert"


def test_cluster_to_layer_floors_min_members_via_budget():
    """budget.min_members=3 forces every theme to have ≥3 members,
    even if its own signature said min_members=1."""
    from agent.finance.lattice import themes
    from agent.finance.lattice.taxonomy import ThemeSignature

    obs = [
        _make_obs("o1", ["risk:earnings"]),
        _make_obs("o2", ["risk:earnings"]),
    ]
    sigs = [
        ThemeSignature(id="t", title="T",
                       any_of=frozenset({"risk:earnings"}), min_members=1),
    ]
    # With min_members=1 floor, the theme ships (2 members)
    out_no_floor = themes._cluster_to_layer(
        obs, sigs, fresh=True, generate_narratives=False,
        budget=spec.LayerBudget(min_members=1),
    )
    assert len(out_no_floor) == 1

    # Raise floor to 3 → theme dropped
    out_with_floor = themes._cluster_to_layer(
        obs, sigs, fresh=True, generate_narratives=False,
        budget=spec.LayerBudget(min_members=3),
    )
    assert out_with_floor == []


# ── MMR respects budget ───────────────────────────────

def test_mmr_k_defaults_come_from_spec_when_budget_missing():
    """Regression lock: when called without explicit k, the kwarg
    default is the spec constant. Anyone changing it breaks this."""
    from agent.finance.lattice.calls import select_calls_mmr
    import inspect
    params = inspect.signature(select_calls_mmr).parameters
    assert params["k"].default == spec.MAX_CALLS
    assert params["lambda_"].default == spec.MMR_LAMBDA


# ── YAML loader wires layer_budgets into Taxonomy ─────

def test_yaml_with_layer_budgets_loads_into_taxonomy(tmp_path):
    yaml_body = textwrap.dedent("""
        version: 1
        layer_budgets:
          themes:
            max_items: 2
          calls:
            max_items: 1
            mmr_lambda: 0.3
        dimensions:
          symbol:
            description: "x"
        themes: []
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body)
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy(path=p)
    assert t.layer_budgets.themes.max_items == 2
    assert t.layer_budgets.calls.max_items == 1
    assert t.layer_budgets.calls.mmr_lambda == 0.3
    # Non-overridden fields still inherit defaults
    assert t.layer_budgets.sub_themes.min_members == 1
    assert t.layer_budgets.calls.max_candidates == spec.MAX_CANDIDATES


def test_yaml_without_layer_budgets_uses_defaults(tmp_path):
    yaml_body = textwrap.dedent("""
        version: 1
        dimensions:
          symbol:
            description: "x"
        themes: []
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body)
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy(path=p)
    assert t.layer_budgets == spec.DEFAULT_LAYER_BUDGETS


def test_yaml_with_invalid_budgets_logs_and_falls_back(tmp_path, caplog):
    """Bad budget values must not crash — log warning + use defaults."""
    yaml_body = textwrap.dedent("""
        version: 1
        layer_budgets:
          calls:
            mmr_lambda: 99   # out of range
        dimensions:
          symbol:
            description: "x"
        themes: []
    """).strip()
    p = tmp_path / "tax.yaml"
    p.write_text(yaml_body)
    from agent.finance.lattice.taxonomy import load_taxonomy
    import logging
    with caplog.at_level(logging.WARNING):
        t = load_taxonomy(path=p)
    assert t.layer_budgets == spec.DEFAULT_LAYER_BUDGETS
    assert any("layer_budgets" in r.message for r in caplog.records)


# ── Shipped taxonomy: budget block present or defaults ──

def test_shipped_taxonomy_has_valid_layer_budgets():
    from agent.finance.lattice.taxonomy import load_taxonomy
    t = load_taxonomy()
    # Must parse cleanly; either defaults (commented-out) or custom
    b = t.layer_budgets
    assert b.calls.max_items is not None
    assert b.calls.max_candidates is not None
    assert b.calls.mmr_lambda is not None
