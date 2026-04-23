"""L3 · cross-endpoint coherence (live backend).

Once the backend is live, four endpoints must agree about the
same underlying state:
  - /api/lattice/observations
  - /api/lattice/themes (includes observations)
  - /api/lattice/calls  (includes observations + themes + sub_themes)
  - /api/lattice/graph  (structural view of the above)

If the same observation has two different tag sets depending on
which endpoint returned it, that's a serialisation bug that
would silently mislead the V3 viz. These tests catch it.
"""
from __future__ import annotations

import json
import urllib.request

import pytest


BASE_URL = "http://127.0.0.1:8001/"
PROJECT = "fin-core"

pytestmark = pytest.mark.lattice_slow


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _fetch(path: str, timeout: float = 300) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module", autouse=True)
def _skip_if_no_backend():
    if not _backend_up():
        pytest.skip(f"backend not reachable at {BASE_URL}")


@pytest.fixture(scope="module")
def payloads():
    """Fetch all four endpoints once per module run. /graph builds
    off /calls, so calling them in sequence lets the 60s router
    cache serve /graph cheaply."""
    return {
        "observations": _fetch(f"api/lattice/observations?project_id={PROJECT}"),
        "themes":       _fetch(f"api/lattice/themes?project_id={PROJECT}"),
        "calls":        _fetch(f"api/lattice/calls?project_id={PROJECT}"),
        "graph":        _fetch(f"api/lattice/graph?project_id={PROJECT}"),
    }


# ── Observation-set agreement ──────────────────────────

def test_observations_identical_across_observations_themes_calls(payloads):
    """Same observation ids must appear, with identical tags + text,
    in /observations, /themes, and /calls."""
    obs_from_obs = {o["id"]: o for o in payloads["observations"]["observations"]}
    obs_from_themes = {o["id"]: o for o in payloads["themes"]["observations"]}
    obs_from_calls = {o["id"]: o for o in payloads["calls"]["observations"]}

    assert set(obs_from_obs) == set(obs_from_themes), \
        f"id diff (obs vs themes): {set(obs_from_obs) ^ set(obs_from_themes)}"
    assert set(obs_from_obs) == set(obs_from_calls), \
        f"id diff (obs vs calls): {set(obs_from_obs) ^ set(obs_from_calls)}"

    for oid, o in obs_from_obs.items():
        for other_name, other in (("themes", obs_from_themes), ("calls", obs_from_calls)):
            other_o = other[oid]
            assert o["text"] == other_o["text"], f"{oid} text drift vs {other_name}"
            assert set(o["tags"]) == set(other_o["tags"]), \
                f"{oid} tag drift vs {other_name}: {set(o['tags']) ^ set(other_o['tags'])}"
            assert o["severity"] == other_o["severity"], \
                f"{oid} severity drift vs {other_name}"


# ── Theme / sub_theme agreement between /themes and /calls ──

def test_themes_identical_between_themes_and_calls(payloads):
    t_from_themes = {t["id"]: t for t in payloads["themes"]["themes"]}
    t_from_calls = {t["id"]: t for t in payloads["calls"]["themes"]}
    assert set(t_from_themes) == set(t_from_calls), \
        f"theme id diff: {set(t_from_themes) ^ set(t_from_calls)}"
    for tid, t in t_from_themes.items():
        other = t_from_calls[tid]
        assert t["narrative"] == other["narrative"], f"{tid} narrative drift"
        assert t["narrative_source"] == other["narrative_source"], \
            f"{tid} narrative_source drift"
        assert [m["obs_id"] for m in t["members"]] == \
            [m["obs_id"] for m in other["members"]], f"{tid} member list drift"


def test_sub_themes_identical_between_themes_and_calls(payloads):
    """sub_themes must match exactly between /themes and /calls
    (both should contain them when n=4 is engaged)."""
    st_themes = {s["id"]: s for s in payloads["themes"].get("sub_themes") or []}
    st_calls = {s["id"]: s for s in payloads["calls"].get("sub_themes") or []}
    assert set(st_themes) == set(st_calls), \
        f"sub_theme id diff: {set(st_themes) ^ set(st_calls)}"


# ── Graph ↔ /calls payload counts ──────────────────────

def test_graph_node_counts_match_calls_payload(payloads):
    g = payloads["graph"]
    c = payloads["calls"]
    lc = g["meta"]["layer_counts"]

    expected_l0 = len({o["source"]["widget"] for o in c["observations"]
                       if o.get("source", {}).get("widget")})
    assert lc["L0"] == expected_l0
    assert lc["L1"] == len(c["observations"])
    assert lc["L1.5"] == len(c.get("sub_themes") or [])
    assert lc["L2"] == len(c["themes"])
    assert lc["L3"] == len(c["calls"])


def test_graph_edge_counts_match_calls_payload(payloads):
    g = payloads["graph"]
    c = payloads["calls"]
    ec = g["meta"]["edge_counts"]

    # source_emission: one per obs with a widget source
    expected_se = sum(1 for o in c["observations"]
                      if (o.get("source") or {}).get("widget"))
    assert ec["source_emission"] == expected_se

    # membership: sum of members across sub_themes + themes
    expected_mem = (sum(len(s["members"]) for s in (c.get("sub_themes") or []))
                    + sum(len(t["members"]) for t in c["themes"]))
    assert ec["membership"] == expected_mem

    # grounds: sum of call.grounds lengths
    expected_gr = sum(len(call["grounds"]) for call in c["calls"])
    assert ec["grounds"] == expected_gr


def test_graph_every_node_id_exists_in_calls_payload(payloads):
    """Every node in /graph must have a corresponding entry in
    /calls (except L0 widget synthetic nodes)."""
    g = payloads["graph"]
    c = payloads["calls"]
    known_ids = set()
    known_ids.update(o["id"] for o in c["observations"])
    known_ids.update(s["id"] for s in (c.get("sub_themes") or []))
    known_ids.update(t["id"] for t in c["themes"])
    known_ids.update(call["id"] for call in c["calls"])
    for n in g["nodes"]:
        if n["layer"] == "L0":
            # L0 widget nodes are synthetic, not in /calls directly.
            # They're validated to be real widget names via obs.source.
            assert n["id"].startswith("widget:")
            widget = n["id"].removeprefix("widget:")
            obs_widgets = {o["source"]["widget"] for o in c["observations"]
                           if (o.get("source") or {}).get("widget")}
            assert widget in obs_widgets
        else:
            assert n["id"] in known_ids, f"graph node {n['id']} not in /calls"


def test_graph_every_grounds_edge_matches_call_grounds(payloads):
    g = payloads["graph"]
    c = payloads["calls"]
    declared = {(call["id"], tid) for call in c["calls"] for tid in call["grounds"]}
    on_graph = {(e["target"], e["source"]) for e in g["edges"] if e["kind"] == "grounds"}
    assert declared == on_graph, f"diff (declared - graph)={declared - on_graph}, (graph - declared)={on_graph - declared}"


# ── Live L4 recompute: spec formula ↔ graph edges ──────

def test_live_membership_edges_match_spec_recompute(payloads):
    """THE critical invariant on live data. Two levels of strictness:

    1. BIT-EXACT: edge.computation.detail.final must equal what
       spec.final_membership_weight produces from raw tags. No
       tolerance. Any deviation here = graph built a parallel
       implementation of the formula somewhere.
    2. PRECISION-AWARE: edge.weight and payload member.weight are
       rounded (round(x, 3)) by themes.py for display. They must
       equal round(spec_result, 3) exactly.
    """
    from agent.finance.lattice import spec
    from agent.finance.lattice.taxonomy import load_taxonomy

    g = payloads["graph"]
    c = payloads["calls"]
    tax = load_taxonomy()
    sig_by_id = {s.id: s for s in list(tax.themes) + list(tax.sub_themes)}
    obs_by_id = {o["id"]: o for o in c["observations"]}
    member_weights = {}
    for parent in (c.get("sub_themes") or []) + c["themes"]:
        for m in parent["members"]:
            member_weights[(m["obs_id"], parent["id"])] = m["weight"]

    for e in g["edges"]:
        if e["kind"] != "membership":
            continue
        sig = sig_by_id[e["target"]]
        obs = obs_by_id[e["source"]]
        spec_exact = spec.final_membership_weight(
            set(obs["tags"]), sig.any_of, sig.all_of, obs["severity"],
        )
        # Bit-exact: graph's computation.detail.final
        assert e["computation"]["detail"]["final"] == spec_exact, (
            f"edge computation.final {e['computation']['detail']['final']} "
            f"≠ spec recompute {spec_exact} (bit-exact)"
        )
        # Precision-aware: edge.weight rounded to 3dp
        assert e["weight"] == round(spec_exact, 3), (
            f"edge weight {e['weight']} ≠ round(spec, 3) {round(spec_exact, 3)}"
        )
        # Precision-aware: payload member weight matches edge weight
        assert member_weights[(e["source"], e["target"])] == e["weight"], (
            f"payload member weight drift vs edge weight"
        )


def test_live_all_provenance_kinds_in_spec(payloads):
    from agent.finance.lattice import spec
    for n in payloads["graph"]["nodes"]:
        assert n["provenance"]["computed_by"] in spec.PROVENANCE_KINDS


def test_live_all_edge_kinds_in_spec(payloads):
    from agent.finance.lattice import spec
    for e in payloads["graph"]["edges"]:
        assert e["kind"] in spec.EDGE_KINDS


def test_live_all_layers_in_spec(payloads):
    from agent.finance.lattice import spec
    for n in payloads["graph"]["nodes"]:
        assert n["layer"] in spec.LAYERS
