"""V10·A2 · live integrity self-check.

Fast unit tests against crafted payloads — we don't want to hit
live pipelines here. Live-backend smoke lives in the endpoint tests.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.lattice_fast


def _minimal_payload():
    """A small hand-built payload that should pass every check."""
    return {
        "observations": [
            {
                "id": "obs_1",
                "text": "AAPL at 7d from earnings, 0.8% below highs.",
                "numbers": {"days_to_earnings": 7.0},
                "tags": ["symbol:AAPL"],
                "severity": "warn",
                "source": {"widget": "earnings", "generator": "gen_earnings_signals"},
            },
        ],
        "themes": [
            {
                "id": "theme_x",
                "title": "Earnings risk",
                "narrative": "AAPL 7d 后有 earnings (0.8% 波动).",
                "narrative_source": "llm",
                "members": [{"obs_id": "obs_1", "weight": 0.9}],
                "tags": ["catalyst:earnings"],
                "severity": "warn",
                "cited_numbers": ["7"],
            },
        ],
        "calls": [
            {
                "id": "call_1",
                "claim": "Watch AAPL into earnings.",
                "grounds": ["theme_x"],
                "warrant": "Earnings drive short-term variance.",
                "qualifier": "<= 2% of book",
                "rebuttal": "Beat + raise unwinds the risk.",
                "confidence": "medium",
                "time_horizon": "days",
            },
        ],
    }


def _minimal_graph():
    """A hand-built graph with L0→L1→L2→L3 wired up correctly."""
    return {
        "nodes": [
            {"id": "widget:earnings", "layer": "L0", "label": "Earnings", "attrs": {}},
            {"id": "obs_1", "layer": "L1", "label": "obs_1", "attrs": {}},
            {"id": "theme_x", "layer": "L2", "label": "theme_x", "attrs": {}},
            {"id": "call_1", "layer": "L3", "label": "call_1", "attrs": {}},
        ],
        "edges": [
            {
                "source": "widget:earnings", "target": "obs_1",
                "kind": "source_emission", "weight": None,
                "computation": {"method": "generator", "detail": {}},
            },
            {
                "source": "obs_1", "target": "theme_x",
                "kind": "membership", "weight": 0.9,
                "computation": {
                    "method": "jaccard+severity_bonus",
                    "detail": {
                        "any_of_matched": ["catalyst:earnings"],
                        "any_of_required": ["catalyst:earnings"],
                        "all_of_required": [],
                        "all_of_satisfied": True,
                        "base": 1.0,
                        "severity": "warn",
                        "severity_bonus": 0.9,
                        "final": 0.9,
                    },
                },
            },
            {
                "source": "theme_x", "target": "call_1",
                "kind": "grounds", "weight": None,
                "computation": {"method": "ground_similarity", "detail": {}},
            },
        ],
        "meta": {"project_id": "fin-test", "taxonomy_version": 3,
                 "fetched_at": "2026-04-23T00:00:00+00:00",
                 "layer_counts": {"L0": 1, "L1": 1, "L2": 1, "L3": 1},
                 "edge_counts": {"source_emission": 1, "membership": 1, "grounds": 1}},
    }


def test_all_pass_on_clean_fixture():
    from agent.finance.lattice.selfcheck import (
        _check_membership_weights, _check_grounds_real,
        _check_narratives_cite_numbers, _check_observations_have_source,
        _check_l0_widgets_have_downstream,
    )
    payload = _minimal_payload()
    graph = _minimal_graph()
    assert _check_membership_weights(graph)["pass"]
    assert _check_grounds_real(payload)["pass"]
    assert _check_narratives_cite_numbers(payload)["pass"]
    assert _check_observations_have_source(payload)["pass"]
    assert _check_l0_widgets_have_downstream(graph)["pass"]


def test_membership_weight_recompute_catches_drift():
    from agent.finance.lattice.selfcheck import _check_membership_weights
    graph = _minimal_graph()
    # Plant a drift: detail says final=0.9, but base*bonus=1.0*0.5=0.5.
    graph["edges"][1]["computation"]["detail"]["severity_bonus"] = 0.5
    r = _check_membership_weights(graph)
    assert not r["pass"]
    assert "offenders" in r
    assert any("0.5" in o["reason"] for o in r["offenders"])


def test_grounds_catches_phantom_theme_id():
    from agent.finance.lattice.selfcheck import _check_grounds_real
    payload = _minimal_payload()
    payload["calls"][0]["grounds"] = ["theme_x", "theme_PHANTOM"]
    r = _check_grounds_real(payload)
    assert not r["pass"]
    assert r["offenders"][0]["phantom_ground"] == "theme_PHANTOM"


def test_narratives_catch_fabricated_number():
    """Narrative cites '42%' but no member obs text/numbers contain 42."""
    from agent.finance.lattice.selfcheck import _check_narratives_cite_numbers
    payload = _minimal_payload()
    payload["themes"][0]["narrative"] = "AAPL 下跌 42% after earnings miss."
    r = _check_narratives_cite_numbers(payload)
    assert not r["pass"]
    assert r["offenders"][0]["theme"] == "theme_x"


def test_narratives_allow_qualitative_llm_output():
    """Purely-qualitative narratives (no numbers) must pass — there's
    nothing to citation-check against."""
    from agent.finance.lattice.selfcheck import _check_narratives_cite_numbers
    payload = _minimal_payload()
    payload["themes"][0]["narrative"] = "AAPL under pressure into earnings."
    r = _check_narratives_cite_numbers(payload)
    assert r["pass"]


def test_narratives_skip_template_fallback():
    """Template-fallback narratives are deterministic quotes of obs
    text. Excluded from the LLM-citation check by design."""
    from agent.finance.lattice.selfcheck import _check_narratives_cite_numbers
    payload = _minimal_payload()
    payload["themes"][0]["narrative_source"] = "template_fallback"
    payload["themes"][0]["narrative"] = "AAPL 下跌 42% after earnings miss."
    r = _check_narratives_cite_numbers(payload)
    assert r["pass"]


def test_observations_catches_missing_source():
    from agent.finance.lattice.selfcheck import _check_observations_have_source
    payload = _minimal_payload()
    payload["observations"].append({
        "id": "obs_orphan", "text": "x", "tags": [],
        "severity": "info", "source": {},
    })
    r = _check_observations_have_source(payload)
    assert not r["pass"]
    assert r["offenders"][0]["obs"] == "obs_orphan"


def test_l0_widgets_catches_dangling_widget():
    from agent.finance.lattice.selfcheck import _check_l0_widgets_have_downstream
    graph = _minimal_graph()
    graph["nodes"].append({"id": "widget:ghost", "layer": "L0", "label": "Ghost", "attrs": {}})
    r = _check_l0_widgets_have_downstream(graph)
    assert not r["pass"]
    assert r["offenders"][0]["widget"] == "widget:ghost"


def test_run_selfcheck_wraps_checks_with_summary(monkeypatch):
    """run_selfcheck aggregates the individual checks with a summary."""
    from agent.finance.lattice import selfcheck
    payload = _minimal_payload()
    graph = _minimal_graph()
    monkeypatch.setattr(selfcheck, "build_calls", lambda pid, fresh=False: payload)
    monkeypatch.setattr(selfcheck, "build_graph", lambda p: graph)
    r = selfcheck.run_selfcheck("fin-test")
    assert r["project_id"] == "fin-test"
    assert r["all_pass"] is True
    assert r["summary"] == "5/5 pass"
    assert len(r["checks"]) == 5
