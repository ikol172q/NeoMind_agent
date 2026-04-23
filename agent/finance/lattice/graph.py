"""Insight Lattice · graph view (V2).

Pure transformation of the /api/lattice/calls payload into a
self-describing `{nodes, edges}` structure suitable for rendering.

Design contract:
  - This module NEVER recomputes cluster membership or call selection.
    It reads the payload that build_calls() already produced and
    restructures it. Any weight on an edge is either (a) the same
    number stored on the payload's member entry or (b) the breakdown
    that produced that number, recomputed from tags via spec.py's
    reference formula.
  - The recomputed breakdown's `final` MUST equal the payload's
    stored weight. L4 asserts this invariant on every run.
  - Every `provenance.computed_by` value MUST be in
    spec.PROVENANCE_KINDS. Every `layer` in spec.LAYERS. Every
    `kind` in spec.EDGE_KINDS. L1 contract tests pin the enums;
    L4 tests pin the invariants on live data.

Shape of the return value (stable contract):

    {
      "nodes": [
        {
          "id": str,
          "layer": str,              # spec.LAYERS
          "label": str,
          "provenance": {
            "computed_by": str,      # spec.PROVENANCE_KINDS
            "method": str,           # free-form description
            "model": Optional[str],  # only for llm kinds
            "inputs": list[str],     # upstream node ids
          },
          "attrs": {...}             # layer-specific
        }, ...
      ],
      "edges": [
        {
          "source": str,             # node id
          "target": str,             # node id
          "kind": str,               # spec.EDGE_KINDS
          "weight": Optional[float], # membership only
          "computation": {
            "method": str,
            "detail": {...}          # formula inputs + result
          }
        }, ...
      ],
      "meta": {
        "project_id": str,
        "taxonomy_version": int,
        "fetched_at": str,
        "layer_counts": {"L0": N, "L1": N, "L1.5": N, "L2": N, "L3": N},
      }
    }
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent.finance.lattice import spec
from agent.finance.lattice.taxonomy import ThemeSignature, load_taxonomy


# ── L0 widget display names ────────────────────────────

_WIDGET_LABELS: Dict[str, str] = {
    "earnings":  "Earnings calendar",
    "technical": "Price / technical",
    "portfolio": "Portfolio positions",
    "sectors":   "Sector heatmap",
    "sentiment": "Market regime",
    "anomalies": "Anomaly detector",
    "news":      "News feed",
}

_WIDGET_GENERATOR: Dict[str, str] = {
    "earnings":  "gen_earnings_signals",
    "technical": "gen_technical_signals",
    "portfolio": "gen_portfolio_signals",
    "sectors":   "gen_sector_signals",
    "sentiment": "gen_sentiment_signals",
    "anomalies": "gen_anomaly_signals",
    "news":      "gen_news_signals",
}


def _widget_label(widget: str) -> str:
    return _WIDGET_LABELS.get(widget, widget.replace("_", " ").title())


def _widget_generator(widget: str) -> str:
    return _WIDGET_GENERATOR.get(widget, f"gen_{widget}_signals")


# ── membership-edge computation breakdown ──────────────

def _membership_computation(
    obs_tags: set[str],
    sig: ThemeSignature,
    obs_severity: str,
) -> Dict[str, Any]:
    """Build the `computation.detail` payload for a membership edge.
    Every number here is derived via spec.py; the result's `final`
    equals spec.final_membership_weight applied to the same inputs.
    """
    any_matched = sorted(obs_tags & sig.any_of)
    any_of_size = len(sig.any_of)
    jaccard_num = len(any_matched)
    jaccard_den = any_of_size if any_of_size > 0 else 1   # display only
    all_required = sorted(sig.all_of)
    all_satisfied = bool(sig.all_of.issubset(obs_tags)) if sig.all_of else True

    base = spec.base_membership_weight(obs_tags, sig.any_of, sig.all_of)
    bonus = spec.cluster_severity_bonus(obs_severity)
    final = spec.final_membership_weight(
        obs_tags, sig.any_of, sig.all_of, obs_severity,
    )

    return {
        "jaccard_num": jaccard_num,
        "jaccard_den": jaccard_den,
        "any_of_matched": any_matched,
        "any_of_required": sorted(sig.any_of),
        "all_of_required": all_required,
        "all_of_satisfied": all_satisfied,
        "base": base,
        "severity": obs_severity,
        "severity_bonus": bonus,
        "final": final,
    }


# ── builder ────────────────────────────────────────────

def build_graph(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a /api/lattice/calls payload into a graph view.

    The caller is responsible for fetching the payload (via
    build_calls()). This function is a pure transformation — no
    LLM, no network, no cache — and can be called directly in
    tests with a hand-crafted payload.
    """
    observations: List[Dict[str, Any]] = payload.get("observations") or []
    sub_themes: List[Dict[str, Any]] = payload.get("sub_themes") or []
    themes: List[Dict[str, Any]] = payload.get("themes") or []
    calls: List[Dict[str, Any]] = payload.get("calls") or []

    tax = load_taxonomy()
    sig_by_id: Dict[str, ThemeSignature] = {
        s.id: s for s in list(tax.themes) + list(tax.sub_themes)
    }
    obs_by_id: Dict[str, Dict[str, Any]] = {o["id"]: o for o in observations}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # ── L0 nodes: unique widgets referenced by observations ──
    widgets_seen: Dict[str, int] = {}
    for o in observations:
        w = (o.get("source") or {}).get("widget")
        if not w:
            continue
        widgets_seen[w] = widgets_seen.get(w, 0) + 1
    for widget, obs_count in sorted(widgets_seen.items()):
        nodes.append({
            "id": f"widget:{widget}",
            "layer": "L0",
            "label": _widget_label(widget),
            "provenance": {
                "computed_by": "source",
                "method": "external_widget",
                "model": None,
                "inputs": [],
            },
            "attrs": {
                "widget": widget,
                "generator": _widget_generator(widget),
                "obs_count": obs_count,
            },
        })

    # ── L1 nodes + source_emission edges ─────────────────────
    for o in observations:
        widget = (o.get("source") or {}).get("widget")
        nodes.append({
            "id": o["id"],
            "layer": "L1",
            "label": o["text"],
            "provenance": {
                "computed_by": "deterministic",
                "method": "python_generator",
                "model": None,
                "inputs": ([f"widget:{widget}"] if widget else []),
            },
            "attrs": {
                "kind": o["kind"],
                "tags": list(o.get("tags") or []),
                "severity": o["severity"],
                "confidence": o.get("confidence"),
                "numbers": o.get("numbers") or {},
                "source": o.get("source") or {},
            },
        })
        if widget:
            edges.append({
                "source": f"widget:{widget}",
                "target": o["id"],
                "kind": "source_emission",
                "weight": None,
                "computation": {
                    "method": "generator_emission",
                    "detail": {
                        "generator": _widget_generator(widget),
                        "widget": widget,
                        "field": (o.get("source") or {}).get("field"),
                        "symbol": (o.get("source") or {}).get("symbol"),
                    },
                },
            })

    # ── Helper: emit a layer node + its membership edges ─────
    def _emit_cluster_node(item: Dict[str, Any], layer: str,
                           narrative_provenance: str):
        sig = sig_by_id.get(item["id"])
        member_obs_ids = [m["obs_id"] for m in (item.get("members") or [])]
        nodes.append({
            "id": item["id"],
            "layer": layer,
            "label": item["title"],
            "provenance": {
                "computed_by": narrative_provenance,
                "method": "tag_intersection_cluster",
                "model": ("deepseek-chat"
                          if narrative_provenance.startswith("llm") else None),
                "inputs": member_obs_ids,
            },
            "attrs": {
                "title": item["title"],
                "narrative": item.get("narrative"),
                "narrative_source": item.get("narrative_source"),
                "severity": item["severity"],
                "tags": list(item.get("tags") or []),
                "cited_numbers": list(item.get("cited_numbers") or []),
                "member_count": len(member_obs_ids),
            },
        })
        if sig is None:
            return
        for m in item.get("members") or []:
            obs = obs_by_id.get(m["obs_id"])
            if obs is None:
                continue
            comp_detail = _membership_computation(
                set(obs.get("tags") or []), sig, obs["severity"],
            )
            edges.append({
                "source": m["obs_id"],
                "target": item["id"],
                "kind": "membership",
                "weight": m["weight"],
                "computation": {
                    "method": "jaccard+severity_bonus",
                    "detail": comp_detail,
                },
            })

    # ── L1.5 nodes + L1→L1.5 edges ───────────────────────────
    for st in sub_themes:
        # Sub-themes skip LLM narrative by design → deterministic
        _emit_cluster_node(st, "L1.5", "deterministic")

    # ── L2 nodes + L1→L2 edges ───────────────────────────────
    for t in themes:
        narrative_source = t.get("narrative_source", "template_fallback")
        prov = "llm+validator" if narrative_source == "llm" else "deterministic"
        _emit_cluster_node(t, "L2", prov)

    # ── L3 nodes + L2→L3 edges ───────────────────────────────
    for c in calls:
        nodes.append({
            "id": c["id"],
            "layer": "L3",
            "label": c["claim"],
            "provenance": {
                "computed_by": "llm+mmr",
                "method": "toulmin_candidate_then_mmr_select",
                "model": "deepseek-chat",
                "inputs": list(c.get("grounds") or []),
            },
            "attrs": {
                "claim": c["claim"],
                "warrant": c.get("warrant"),
                "qualifier": c.get("qualifier"),
                "rebuttal": c.get("rebuttal"),
                "confidence": c.get("confidence"),
                "time_horizon": c.get("time_horizon"),
                "grounds_count": len(c.get("grounds") or []),
            },
        })
        for ground_theme_id in c.get("grounds") or []:
            edges.append({
                "source": ground_theme_id,
                "target": c["id"],
                "kind": "grounds",
                "weight": None,
                "computation": {
                    "method": "llm_selection+mmr_survived",
                    "detail": {
                        "mmr_lambda": spec.MMR_LAMBDA,
                        "max_candidates": spec.MAX_CANDIDATES,
                        "max_calls": spec.MAX_CALLS,
                        # V4 will add per-candidate MMR scores here
                        # when instrumentation lands. For V2, we only
                        # record structural fact: this theme was
                        # selected as ground.
                    },
                },
            })

    # ── Meta ─────────────────────────────────────────────────
    layer_counts = {layer: 0 for layer in spec.LAYERS}
    for n in nodes:
        layer_counts[n["layer"]] = layer_counts.get(n["layer"], 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "project_id": payload.get("project_id"),
            "taxonomy_version": payload.get("taxonomy_version"),
            "fetched_at": payload.get("fetched_at"),
            "layer_counts": layer_counts,
            "edge_counts": {
                kind: sum(1 for e in edges if e["kind"] == kind)
                for kind in spec.EDGE_KINDS
            },
        },
    }
