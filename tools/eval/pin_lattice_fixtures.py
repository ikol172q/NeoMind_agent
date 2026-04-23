#!/usr/bin/env python3
"""Regenerate the lattice drift fixtures under tests/lattice_fixtures/.

Each scenario has a hand-authored input.json containing:
  - `observations`: list of {id, tags, severity, text?, source?}
  - `signatures`: list of {id, title, any_of, all_of, min_members}
    (signatures used in this scenario; NOT the live taxonomy)

This script:
  1. Reads input.json
  2. Computes each (obs_id, sig_id) → final membership weight via
     spec.final_membership_weight (THE reference)
  3. Writes expected_weights.json with the pinned numbers
  4. Builds a synthetic /calls-shaped payload and calls
     graph.build_graph() to produce graph.ref.json

Running this script OVERWRITES the pinned expected values. It is
deliberately a manual step: if any pinned weight changes, the
author must consciously re-run this and explain the change in
the commit message. The drift tests (test_lattice_drift.py) fail
loudly when expected ≠ live until the fixtures are updated.

Usage:
    .venv/bin/python tools/eval/pin_lattice_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.finance.lattice import graph as graph_mod, spec
from agent.finance.lattice.taxonomy import ThemeSignature

FIXTURE_ROOT = ROOT / "tests" / "lattice_fixtures"


def _sig_from_dict(d: dict) -> ThemeSignature:
    return ThemeSignature(
        id=d["id"],
        title=d["title"],
        any_of=frozenset(d.get("any_of") or []),
        all_of=frozenset(d.get("all_of") or []),
        min_members=int(d.get("min_members", 1)),
    )


def _compute_weights(inp: dict) -> dict:
    """Return {(obs_id, sig_id): final_weight_exact} for every
    obs × sig pair where weight > 0."""
    out: dict[str, float] = {}
    for obs in inp["observations"]:
        for sig_d in inp["signatures"]:
            sig = _sig_from_dict(sig_d)
            w = spec.final_membership_weight(
                frozenset(obs["tags"]),
                sig.any_of, sig.all_of,
                obs["severity"],
            )
            if w > 0:
                out[f"{obs['id']}::{sig_d['id']}"] = w
    return out


def _build_synthetic_payload(inp: dict) -> dict:
    """Synthesize a /calls-shaped payload from input.json. sub_themes
    and themes both pull from the same signature list, differentiated
    by prefix (`subtheme_*` → L1.5, `theme_*` → L2). Calls are
    authored directly in input.json if present."""
    # Cluster observations against each signature
    sub_themes = []
    themes = []
    for sig_d in inp["signatures"]:
        sig = _sig_from_dict(sig_d)
        members = []
        for obs in inp["observations"]:
            w = spec.final_membership_weight(
                frozenset(obs["tags"]), sig.any_of, sig.all_of, obs["severity"],
            )
            if w > 0:
                members.append({"obs_id": obs["id"], "weight": round(w, 3)})
        if len(members) < sig.min_members:
            continue
        members.sort(key=lambda m: -m["weight"])
        # Theme severity rollup: worst-member severity
        sev_rank = {obs["id"]: spec.severity_rank(obs["severity"])
                    for obs in inp["observations"]}
        worst = min(members, key=lambda m: sev_rank[m["obs_id"]])
        sev = next(o for o in inp["observations"]
                   if o["id"] == worst["obs_id"])["severity"]
        entry = {
            "id": sig_d["id"], "title": sig_d["title"],
            "narrative": f"{sig_d['title']} ({len(members)} obs)",
            "narrative_source": "template_fallback",
            "severity": sev,
            "tags": sorted(set(list(sig.any_of) + list(sig.all_of))),
            "cited_numbers": [],
            "members": members,
        }
        if sig_d["id"].startswith("subtheme_"):
            sub_themes.append(entry)
        else:
            themes.append(entry)

    return {
        "project_id": inp.get("project_id", "fixture"),
        "taxonomy_version": 1,
        "fetched_at": "FIXED",
        "observations": inp["observations"],
        "sub_themes": sub_themes,
        "themes": themes,
        "calls": inp.get("calls") or [],
    }


def _pin_scenario(path: Path) -> None:
    inp = json.loads((path / "input.json").read_text())

    weights = _compute_weights(inp)
    (path / "expected_weights.json").write_text(
        json.dumps(weights, indent=2, sort_keys=True) + "\n"
    )

    payload = _build_synthetic_payload(inp)

    # Need to monkey-patch taxonomy loader so graph.build_graph can
    # resolve signature lookups. We inject the fixture's signatures
    # as a synthetic taxonomy.
    import agent.finance.lattice.taxonomy as taxmod
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
        # Ensure graph.py picks up the fake
        import importlib
        importlib.reload(graph_mod)
        g = graph_mod.build_graph(payload)
    finally:
        taxmod.load_taxonomy = original_load
        importlib.reload(graph_mod)

    # Sort nodes and edges for stable diffs
    g["nodes"].sort(key=lambda n: (n["layer"], n["id"]))
    g["edges"].sort(key=lambda e: (e["kind"], e["source"], e["target"]))
    (path / "graph.ref.json").write_text(json.dumps(g, indent=2, sort_keys=True) + "\n")

    print(f"pinned {path.name}: {len(weights)} weights, "
          f"{len(g['nodes'])} nodes, {len(g['edges'])} edges")


def main():
    if not FIXTURE_ROOT.exists():
        raise SystemExit(f"missing {FIXTURE_ROOT}")
    for child in sorted(FIXTURE_ROOT.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "input.json").exists():
            print(f"skip {child.name} — no input.json")
            continue
        _pin_scenario(child)


if __name__ == "__main__":
    main()
