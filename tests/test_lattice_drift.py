"""L6 · drift detection — fixture regression + judge baseline.

The single-most-important test in the suite: given a hand-authored
input (tests/lattice_fixtures/scenario_*/input.json), recompute
every membership weight via spec.final_membership_weight and
assert it EXACTLY matches the pinned expected_weights.json.

If anyone changes any of:
  - spec.CLUSTER_SEVERITY_BONUS values
  - spec.base_membership_weight formula shape
  - the clip, the base/bonus multiplication order
  - the all_of hard gate behaviour
... this test reports the diff with precise numeric names — e.g.,
"obs_aapl_earnings_and_high::theme_earnings_risk pinned 0.85,
spec recomputed 0.80 (delta +0.05)" — rather than a vague
"behaviour changed somewhere."

To regenerate fixtures: run tools/eval/pin_lattice_fixtures.py.
The act of modifying expected_weights.json is the author's
conscious acknowledgment that the algorithm has changed.

Judge baseline is run in a separate test marked lattice_drift
(LLM-dependent, nightly only).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from agent.finance.lattice import graph as graph_mod, spec
from agent.finance.lattice.taxonomy import ThemeSignature


FIXTURE_ROOT = Path(__file__).parent / "lattice_fixtures"
SCENARIOS = sorted(p.name for p in FIXTURE_ROOT.iterdir()
                   if (p / "input.json").exists())


pytestmark = pytest.mark.lattice_fast


def _load_scenario(name: str) -> dict:
    path = FIXTURE_ROOT / name
    return {
        "input": json.loads((path / "input.json").read_text()),
        "expected_weights": json.loads((path / "expected_weights.json").read_text()),
        "graph_ref": json.loads((path / "graph.ref.json").read_text()),
    }


def _sig_from_dict(d: dict) -> ThemeSignature:
    return ThemeSignature(
        id=d["id"], title=d["title"],
        any_of=frozenset(d.get("any_of") or []),
        all_of=frozenset(d.get("all_of") or []),
        min_members=int(d.get("min_members", 1)),
    )


# ── Weight regression (THE critical test) ─────────────

@pytest.mark.parametrize("scenario", SCENARIOS)
def test_spec_weights_match_pinned_expected(scenario):
    """For every (obs, sig) pair with non-zero weight in the pinned
    fixture, spec.final_membership_weight must reproduce the exact
    same float. Any delta ≠ 0 = drift.

    Conversely, for pairs NOT in the pinned fixture, the current
    formula must also produce 0 — i.e., the set of non-zero edges
    must match exactly."""
    s = _load_scenario(scenario)
    inp = s["input"]
    expected = s["expected_weights"]

    # Compute live
    live: dict[str, float] = {}
    for obs in inp["observations"]:
        for sig_d in inp["signatures"]:
            sig = _sig_from_dict(sig_d)
            w = spec.final_membership_weight(
                frozenset(obs["tags"]), sig.any_of, sig.all_of, obs["severity"],
            )
            if w > 0:
                live[f"{obs['id']}::{sig_d['id']}"] = w

    # Set equality: same set of non-zero edges
    missing = set(expected) - set(live)
    extra = set(live) - set(expected)
    assert not missing, f"[{scenario}] missing edges vs pinned: {sorted(missing)}"
    assert not extra, f"[{scenario}] extra edges vs pinned: {sorted(extra)}"

    # Value equality: same float, bit-exact
    for key, pinned in expected.items():
        got = live[key]
        assert got == pinned, (
            f"[{scenario}] {key} DRIFT: pinned={pinned}, spec={got}, "
            f"delta={got - pinned:+.6g}. If intentional: re-run "
            f"tools/eval/pin_lattice_fixtures.py."
        )


# ── Graph structure regression ────────────────────────

@pytest.mark.parametrize("scenario", SCENARIOS)
def test_graph_structure_matches_pinned_reference(scenario):
    """build_graph() on the synthetic payload must produce the same
    nodes+edges as the pinned graph.ref.json. Covers:
      - node/edge set equality (no phantoms, no missing)
      - every node's provenance + layer fields
      - every edge's computation.detail bit-exact
    """
    s = _load_scenario(scenario)
    inp = s["input"]
    ref = s["graph_ref"]

    # Rebuild the synthetic payload + graph the same way the pin
    # script does, but inline (so we exercise the production path).
    from tools.eval.pin_lattice_fixtures import _build_synthetic_payload
    payload = _build_synthetic_payload(inp)

    # Inject signatures as the taxonomy (same trick as the pinner)
    import agent.finance.lattice.taxonomy as taxmod
    import importlib
    original_load = taxmod.load_taxonomy
    try:
        sub_sigs = [_sig_from_dict(s) for s in inp["signatures"]
                    if s["id"].startswith("subtheme_")]
        theme_sigs = [_sig_from_dict(s) for s in inp["signatures"]
                      if not s["id"].startswith("subtheme_")]
        fake_tax = taxmod.Taxonomy(
            version=1, dimensions={}, themes=theme_sigs, sub_themes=sub_sigs,
        )
        taxmod.load_taxonomy = lambda *a, **kw: fake_tax
        importlib.reload(graph_mod)
        g = graph_mod.build_graph(payload)
    finally:
        taxmod.load_taxonomy = original_load
        importlib.reload(graph_mod)

    # Sort to match ref
    g["nodes"].sort(key=lambda n: (n["layer"], n["id"]))
    g["edges"].sort(key=lambda e: (e["kind"], e["source"], e["target"]))

    # Layer counts
    assert g["meta"]["layer_counts"] == ref["meta"]["layer_counts"], (
        f"[{scenario}] layer_counts drift: {g['meta']['layer_counts']} vs "
        f"{ref['meta']['layer_counts']}"
    )
    # Edge counts by kind
    assert g["meta"]["edge_counts"] == ref["meta"]["edge_counts"]

    # Node id set
    live_node_ids = {n["id"] for n in g["nodes"]}
    ref_node_ids = {n["id"] for n in ref["nodes"]}
    assert live_node_ids == ref_node_ids, (
        f"[{scenario}] node id diff: missing={ref_node_ids - live_node_ids}, "
        f"extra={live_node_ids - ref_node_ids}"
    )

    # Every node's provenance + layer identical
    ref_by_id = {n["id"]: n for n in ref["nodes"]}
    for n in g["nodes"]:
        r = ref_by_id[n["id"]]
        assert n["layer"] == r["layer"]
        assert n["provenance"]["computed_by"] == r["provenance"]["computed_by"], (
            f"[{scenario}] {n['id']}: provenance drift "
            f"(live={n['provenance']['computed_by']} ref={r['provenance']['computed_by']})"
        )

    # Edge endpoints + kind + computation.detail bit-exact
    live_edge_keys = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}
    ref_edge_keys = {(e["source"], e["target"], e["kind"]) for e in ref["edges"]}
    assert live_edge_keys == ref_edge_keys, (
        f"[{scenario}] edge set diff: "
        f"missing={ref_edge_keys - live_edge_keys}, "
        f"extra={live_edge_keys - ref_edge_keys}"
    )
    ref_edge_by_key = {(e["source"], e["target"], e["kind"]): e for e in ref["edges"]}
    for e in g["edges"]:
        r = ref_edge_by_key[(e["source"], e["target"], e["kind"])]
        if e["kind"] == "membership":
            # Bit-exact computation.detail
            lk = e["computation"]["detail"]
            rk = r["computation"]["detail"]
            for field in ("jaccard_num", "jaccard_den", "any_of_matched",
                          "any_of_required", "all_of_required",
                          "all_of_satisfied", "base", "severity",
                          "severity_bonus", "final"):
                assert lk[field] == rk[field], (
                    f"[{scenario}] edge {e['source']}→{e['target']} "
                    f"detail.{field}: live={lk[field]} ref={rk[field]}"
                )
        # weight (rounded)
        assert e.get("weight") == r.get("weight"), (
            f"[{scenario}] weight drift on {e['source']}→{e['target']}"
        )


# ── Spec-function monotonicity sanity (cheap, always run) ──

def test_spec_severity_rank_order_preserved():
    """alert is more severe than warn is more severe than info.
    If someone flips 0 and 2, theme-severity rollup breaks
    silently. Catch it here."""
    assert spec.severity_rank("alert") < spec.severity_rank("warn")
    assert spec.severity_rank("warn") < spec.severity_rank("info")
    assert spec.severity_rank("info") < spec.severity_rank("unknown")


def test_spec_cluster_severity_bonus_orders_alert_highest():
    """alert gets the biggest weight multiplier."""
    b = spec.CLUSTER_SEVERITY_BONUS
    assert b["alert"] >= b["warn"] >= b["info"]


def test_spec_mmr_lambda_in_reasonable_range():
    """If λ ever goes below 0.3 or above 0.95 without a plan update,
    something is wrong. Bounds are intentionally loose — this test
    exists to catch "accidentally 0 or 1" typos."""
    assert 0.3 <= spec.MMR_LAMBDA <= 0.95


# ── Judge baseline regression (LLM, nightly) ──────────

@pytest.mark.lattice_drift
@pytest.mark.skipif(
    not (Path(__file__).parent / "qa_archive" / "results"
         / "2026-04-21_lattice_l3_judge" / "run3_variance.json").exists(),
    reason="no L3 judge baseline committed",
)
def test_l3_judge_does_not_regress_below_baseline():
    """Load the committed L3 judge baseline and run the judge on
    live data. Fail if any axis drops by more than 0.5 below
    baseline (judge self-consistency typically sits within 0.3
    stdev; 0.5 is the real-signal threshold)."""
    import urllib.request
    # Skip if backend not up
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=3) as r:
            if r.status != 200:
                pytest.skip("backend not reachable")
    except Exception:
        pytest.skip("backend not reachable")

    baseline_path = (Path(__file__).parent / "qa_archive" / "results"
                     / "2026-04-21_lattice_l3_judge" / "run3_variance.json")
    baseline = json.loads(baseline_path.read_text())
    baseline_by_scenario = {s["scenario"]: s for s in baseline["l3_summaries"]}

    from tools.eval.lattice_judge import run
    # Reuse the same scenarios present in the baseline for a direct
    # comparison
    scenario_names = list(baseline_by_scenario.keys())
    current = run(n_samples=3, scenario_names=scenario_names, layer="l3")

    axes = ("claim_actionability", "grounds_traceability", "warrant_validity",
            "qualifier_specificity", "rebuttal_realism")
    drifts: list[str] = []
    for s in current["l3_summaries"]:
        base = baseline_by_scenario.get(s["scenario"])
        if not base:
            continue
        for axis in axes:
            now_val = s.get(f"avg_{axis}")
            base_val = base.get(f"avg_{axis}")
            if now_val is None or base_val is None:
                continue
            if now_val < base_val - 0.5:
                drifts.append(
                    f"{s['scenario']}.{axis}: now={now_val} baseline={base_val} "
                    f"(delta={now_val - base_val:+.2f})"
                )
    assert not drifts, "Judge quality regressed:\n  " + "\n  ".join(drifts)
