"""L4 (fast) · graph builder unit tests.

These tests exercise `build_graph()` directly with hand-crafted
payloads — no live backend, no LLM — so every invariant is checked
with deterministic inputs. Live-endpoint coherence is validated
separately in tests/test_lattice_graph_live.py (lattice_slow).

The key L4 invariant:
  For every membership edge in the output, recomputing the weight
  from the raw tags using spec.final_membership_weight produces
  the same float as the edge's `weight` field AND as the
  `computation.detail.final` field. Three-way lock.
"""
from __future__ import annotations

import pytest

from agent.finance.lattice import graph, spec


pytestmark = pytest.mark.lattice_fast


# ── Fixtures: synthetic payload shaped like /api/lattice/calls ──

def _make_payload():
    """Shaped like a real /calls payload. Tag signatures chosen to
    match lattice_taxonomy.yaml's theme_earnings_risk + sub_themes so
    build_graph can look them up in the real taxonomy."""
    obs_1_tags = [
        "symbol:AAPL", "market:US",
        "catalyst:earnings", "risk:earnings", "timescale:short",
    ]
    obs_2_tags = [
        "symbol:NVDA", "market:US",
        "technical:near_52w_high", "direction:up", "timescale:short",
    ]
    return {
        "project_id": "fin-core",
        "taxonomy_version": 1,
        "fetched_at": "2026-04-22T12:00:00Z",
        "observations": [
            {
                "id": "obs_earnings_soon_001",
                "kind": "earnings_soon",
                "text": "AAPL reports in 7d.",
                "tags": obs_1_tags,
                "numbers": {"days_until": 7},
                "source": {"widget": "earnings", "field": "days_until", "symbol": "AAPL"},
                "severity": "warn",
                "confidence": 0.95,
            },
            {
                "id": "obs_near_52w_high_001",
                "kind": "near_52w_high",
                "text": "NVDA at 94th percentile of 20d range.",
                "tags": obs_2_tags,
                "numbers": {"percentile": 94},
                "source": {"widget": "technical", "field": "percentile", "symbol": "NVDA"},
                "severity": "info",
                "confidence": 0.8,
            },
        ],
        "sub_themes": [
            {
                "id": "subtheme_event_risk",
                "title": "Near-term event risk",
                "narrative": "Near-term event risk (1 obs)",
                "narrative_source": "template_fallback",
                "severity": "warn",
                "tags": ["catalyst:earnings", "timescale:short"],
                "cited_numbers": [],
                "members": [{"obs_id": "obs_earnings_soon_001", "weight": 0.567}],
            },
        ],
        "themes": [
            {
                "id": "theme_earnings_risk",
                "title": "Earnings risk",
                "narrative": "AAPL reports in 7 days, elevated IV implied.",
                "narrative_source": "llm",
                "severity": "warn",
                "tags": ["catalyst:earnings", "risk:earnings"],
                "cited_numbers": ["7"],
                "members": [{"obs_id": "obs_earnings_soon_001", "weight": 0.85}],
            },
            {
                "id": "theme_near_highs",
                "title": "Near 52w highs",
                "narrative": "NVDA at 94th percentile.",
                "narrative_source": "llm",
                "severity": "info",
                "tags": ["technical:near_52w_high"],
                "cited_numbers": ["94"],
                "members": [{"obs_id": "obs_near_52w_high_001", "weight": 0.7}],
            },
        ],
        "calls": [
            {
                "id": "call_001",
                "claim": "Hedge AAPL earnings volatility with 30-day puts.",
                "grounds": ["theme_earnings_risk", "theme_near_highs"],
                "warrant": "Elevated IV plus proximity to range top creates asymmetric downside.",
                "qualifier": "Size at ≤1.5% of book; skip if VIX > 25.",
                "rebuttal": "If AAPL pre-announces revenue > 5% above consensus.",
                "confidence": "medium",
                "time_horizon": "weeks",
            },
        ],
    }


# ── Structural invariants ──────────────────────────────

def test_node_count_per_layer_matches_payload():
    p = _make_payload()
    g = graph.build_graph(p)
    counts = g["meta"]["layer_counts"]
    # L0 = unique widgets across obs
    assert counts["L0"] == len({o["source"]["widget"] for o in p["observations"]})
    assert counts["L1"] == len(p["observations"])
    assert counts["L1.5"] == len(p["sub_themes"])
    assert counts["L2"] == len(p["themes"])
    assert counts["L3"] == len(p["calls"])


def test_every_node_id_is_unique():
    g = graph.build_graph(_make_payload())
    ids = [n["id"] for n in g["nodes"]]
    assert len(ids) == len(set(ids))


def test_every_edge_source_and_target_are_real_nodes():
    g = graph.build_graph(_make_payload())
    node_ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["source"] in node_ids, f"phantom source {e['source']}"
        assert e["target"] in node_ids, f"phantom target {e['target']}"


def test_membership_edge_count_equals_sum_of_members():
    p = _make_payload()
    g = graph.build_graph(p)
    expected = (sum(len(s["members"]) for s in p["sub_themes"])
                + sum(len(t["members"]) for t in p["themes"]))
    actual = sum(1 for e in g["edges"] if e["kind"] == "membership")
    assert actual == expected


def test_grounds_edge_count_equals_sum_of_call_grounds():
    p = _make_payload()
    g = graph.build_graph(p)
    expected = sum(len(c["grounds"]) for c in p["calls"])
    actual = sum(1 for e in g["edges"] if e["kind"] == "grounds")
    assert actual == expected


def test_source_emission_edge_per_observation_with_widget():
    p = _make_payload()
    g = graph.build_graph(p)
    expected = sum(1 for o in p["observations"] if (o.get("source") or {}).get("widget"))
    actual = sum(1 for e in g["edges"] if e["kind"] == "source_emission")
    assert actual == expected


# ── Enum invariants (provenance / layer / edge kind) ───

def test_every_layer_is_in_spec_layers():
    g = graph.build_graph(_make_payload())
    for n in g["nodes"]:
        assert n["layer"] in spec.LAYERS, f"node {n['id']} has invalid layer {n['layer']!r}"


def test_every_provenance_is_in_spec_enum():
    g = graph.build_graph(_make_payload())
    for n in g["nodes"]:
        kind = n["provenance"]["computed_by"]
        assert kind in spec.PROVENANCE_KINDS, f"node {n['id']} has invalid provenance {kind!r}"


def test_every_edge_kind_is_in_spec_enum():
    g = graph.build_graph(_make_payload())
    for e in g["edges"]:
        assert e["kind"] in spec.EDGE_KINDS, f"invalid edge kind {e['kind']!r}"


def test_provenance_l1_always_deterministic():
    g = graph.build_graph(_make_payload())
    for n in g["nodes"]:
        if n["layer"] == "L1":
            assert n["provenance"]["computed_by"] == "deterministic"


def test_provenance_l15_always_deterministic():
    g = graph.build_graph(_make_payload())
    for n in g["nodes"]:
        if n["layer"] == "L1.5":
            assert n["provenance"]["computed_by"] == "deterministic"


def test_provenance_l2_matches_narrative_source():
    p = _make_payload()
    g = graph.build_graph(p)
    tmap = {t["id"]: t for t in p["themes"]}
    for n in g["nodes"]:
        if n["layer"] != "L2":
            continue
        want = ("llm+validator"
                if tmap[n["id"]]["narrative_source"] == "llm"
                else "deterministic")
        assert n["provenance"]["computed_by"] == want


def test_provenance_l3_always_llm_plus_mmr():
    g = graph.build_graph(_make_payload())
    l3 = [n for n in g["nodes"] if n["layer"] == "L3"]
    assert l3, "expected at least one L3 node in fixture"
    for n in l3:
        assert n["provenance"]["computed_by"] == "llm+mmr"


# ── The critical L4 invariant: edge weight matches formula recompute ──

def test_every_membership_edge_weight_equals_payload_member_weight():
    """Graph must not invent weights — each one comes directly from
    the payload's member entry."""
    p = _make_payload()
    g = graph.build_graph(p)
    member_weights = {}
    for s in p["sub_themes"] + p["themes"]:
        for m in s["members"]:
            member_weights[(m["obs_id"], s["id"])] = m["weight"]
    for e in g["edges"]:
        if e["kind"] != "membership":
            continue
        expected = member_weights[(e["source"], e["target"])]
        assert e["weight"] == expected, (
            f"edge {e['source']}→{e['target']} weight {e['weight']} "
            f"≠ payload member weight {expected}"
        )


def test_every_membership_computation_final_matches_spec_recompute():
    """THE invariant. Given the edge's recorded tags + signature,
    spec.final_membership_weight MUST produce the same float that's
    stored on computation.detail.final. If anyone ever hand-writes
    a weight on a graph edge, this fails. If the formula changes
    without production code being updated, this fails."""
    from agent.finance.lattice.taxonomy import load_taxonomy

    p = _make_payload()
    g = graph.build_graph(p)
    tax = load_taxonomy()
    sig_by_id = {s.id: s for s in list(tax.themes) + list(tax.sub_themes)}
    obs_by_id = {o["id"]: o for o in p["observations"]}

    for e in g["edges"]:
        if e["kind"] != "membership":
            continue
        sig = sig_by_id[e["target"]]
        obs = obs_by_id[e["source"]]
        expected = spec.final_membership_weight(
            set(obs["tags"]), sig.any_of, sig.all_of, obs["severity"],
        )
        got = e["computation"]["detail"]["final"]
        assert got == expected, (
            f"edge {e['source']}→{e['target']}: "
            f"computation.detail.final={got} ≠ spec recompute {expected}"
        )


def test_membership_computation_detail_has_all_fields():
    g = graph.build_graph(_make_payload())
    required = {"jaccard_num", "jaccard_den", "any_of_matched",
                "any_of_required", "all_of_required", "all_of_satisfied",
                "base", "severity", "severity_bonus", "final"}
    for e in g["edges"]:
        if e["kind"] != "membership":
            continue
        assert required.issubset(e["computation"]["detail"].keys()), (
            f"edge missing fields: {required - set(e['computation']['detail'].keys())}"
        )


def test_grounds_edge_points_from_theme_to_call():
    """Direction invariant: source must be an L2 node, target an L3 node."""
    g = graph.build_graph(_make_payload())
    layer = {n["id"]: n["layer"] for n in g["nodes"]}
    for e in g["edges"]:
        if e["kind"] != "grounds":
            continue
        assert layer[e["source"]] == "L2"
        assert layer[e["target"]] == "L3"


def test_source_emission_points_from_l0_to_l1():
    g = graph.build_graph(_make_payload())
    layer = {n["id"]: n["layer"] for n in g["nodes"]}
    for e in g["edges"]:
        if e["kind"] != "source_emission":
            continue
        assert layer[e["source"]] == "L0"
        assert layer[e["target"]] == "L1"


def test_membership_points_from_l1_to_l15_or_l2():
    g = graph.build_graph(_make_payload())
    layer = {n["id"]: n["layer"] for n in g["nodes"]}
    for e in g["edges"]:
        if e["kind"] != "membership":
            continue
        assert layer[e["source"]] == "L1"
        assert layer[e["target"]] in ("L1.5", "L2")


# ── Edge cases ─────────────────────────────────────────

def test_empty_payload_produces_empty_graph():
    g = graph.build_graph({"observations": [], "sub_themes": [], "themes": [], "calls": []})
    assert g["nodes"] == []
    assert g["edges"] == []
    assert g["meta"]["layer_counts"] == {"L0": 0, "L1": 0, "L1.5": 0, "L2": 0, "L3": 0}


def test_payload_with_no_sub_themes_still_builds():
    p = _make_payload()
    p["sub_themes"] = []
    g = graph.build_graph(p)
    assert g["meta"]["layer_counts"]["L1.5"] == 0
    assert g["meta"]["layer_counts"]["L2"] == len(p["themes"])


def test_payload_with_no_calls_still_builds():
    p = _make_payload()
    p["calls"] = []
    g = graph.build_graph(p)
    assert g["meta"]["layer_counts"]["L3"] == 0
    assert sum(1 for e in g["edges"] if e["kind"] == "grounds") == 0


def test_observation_without_widget_source_skips_l0_edge():
    p = _make_payload()
    p["observations"][0]["source"] = None
    g = graph.build_graph(p)
    # No source_emission edge for that obs
    edges_from_orphan = [e for e in g["edges"]
                         if e["kind"] == "source_emission"
                         and e["target"] == p["observations"][0]["id"]]
    assert edges_from_orphan == []


# ── Meta counters truth ────────────────────────────────

def test_meta_edge_counts_match_actual_edges():
    g = graph.build_graph(_make_payload())
    for kind, count in g["meta"]["edge_counts"].items():
        actual = sum(1 for e in g["edges"] if e["kind"] == kind)
        assert actual == count, f"meta counted {count} {kind} but {actual} exist"


def test_meta_layer_counts_match_actual_nodes():
    g = graph.build_graph(_make_payload())
    for layer, count in g["meta"]["layer_counts"].items():
        actual = sum(1 for n in g["nodes"] if n["layer"] == layer)
        assert actual == count, f"meta counted {count} {layer} but {actual} exist"
