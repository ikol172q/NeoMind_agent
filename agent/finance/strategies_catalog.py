"""Strategies catalog API — serves docs/strategies/strategies.yaml as
JSON, plus per-strategy markdown bodies, for the Strategies tab UI.

The YAML is the single source of truth (Phase 3 subagent output).
The UI reads only through this endpoint — never inlines / duplicates
the catalog. Adding a new strategy means: edit strategies.yaml +
write a new <id>.md, no UI code change needed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["fin-strategies"])

# Resolve relative to the package — agent/finance/strategies_catalog.py
# → repo_root/docs/strategies/strategies.yaml
_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "strategies"
_STRATEGIES_YAML = _STRATEGIES_DIR / "strategies.yaml"


def _load_catalog() -> List[Dict[str, Any]]:
    """Re-read the YAML on every request — file is small (~30k), reads
    are cheap, and editing YAML by hand should reflect immediately
    without a server restart.
    """
    if not _STRATEGIES_YAML.exists():
        return []
    raw = yaml.safe_load(_STRATEGIES_YAML.read_text(encoding="utf-8")) or {}
    return list(raw.get("strategies", []))


@router.get("")
def list_strategies(
    horizon: Optional[str] = Query(None, description="long_term|months|weeks|swing|days|intraday"),
    asset_class: Optional[str] = Query(None),
    feasible_at_10k: Optional[bool] = Query(
        None, description="filter to strategies marked feasible for $10k accounts",
    ),
) -> Dict[str, Any]:
    """Return the strategy catalog, optionally filtered.

    Output shape:
        {
          "count": 35,
          "strategies": [{...}, ...],
          "by_horizon": {"long_term": 10, "months": 3, ...}
        }
    """
    items = _load_catalog()

    if horizon:
        items = [s for s in items if s.get("horizon") == horizon]
    if asset_class:
        items = [s for s in items if s.get("asset_class") == asset_class]
    if feasible_at_10k is not None:
        items = [s for s in items if bool(s.get("feasible_at_10k")) == feasible_at_10k]

    counts: Dict[str, int] = {}
    for s in items:
        h = s.get("horizon", "unknown")
        counts[h] = counts.get(h, 0) + 1

    return {"count": len(items), "strategies": items, "by_horizon": counts}


@router.get("/lattice-fit")
def lattice_fit(project_id: str = Query(..., description="lattice project_id")) -> Dict[str, Any]:
    """For each catalog strategy, score how well it fits today's lattice
    themes — *without* requiring an L3 call. Direct answer to the
    'no calls today, all strategies look like gap' problem.

    Internally: aggregates all L1 obs tags across today's themes, then
    runs the same deterministic scoring function the L3-call matcher
    uses, but at each strategy's natural horizon (so horizon_match
    bonus auto-fires). Returns strategies sorted by score descending.

    The score is the same scale as the L3-call matcher (0-10), and
    score_breakdown is identical — so the UI can render the same
    drill-down explanation as for live call matches.
    """
    try:
        from agent.finance.lattice.calls import build_calls
        from agent.finance.lattice.themes import Theme, ThemeMember
        from agent.finance.lattice.strategy_matcher import match_all_against_themes
    except Exception as exc:
        raise HTTPException(503, f"lattice modules unavailable: {exc}")

    try:
        payload = build_calls(project_id, fresh=False)
    except Exception as exc:
        raise HTTPException(502, f"lattice build failed: {exc}")

    # Re-hydrate Theme objects so the matcher's hasattr() checks work
    themes = [
        Theme(
            id=t["id"],
            title=t.get("title", ""),
            narrative=t.get("narrative", ""),
            narrative_source=t.get("narrative_source", ""),
            members=[ThemeMember(**m) for m in t.get("members", [])],
            tags=t.get("tags", []),
            severity=t.get("severity", "info"),
            cited_numbers=t.get("cited_numbers", []),
        )
        for t in payload.get("themes", [])
    ]

    fit = match_all_against_themes(themes)
    return {
        "project_id":      project_id,
        "themes_count":    len(themes),
        "calls_count":     len(payload.get("calls", [])),
        "strategies_count": len(fit),
        "fit":             fit,
        "explanation": (
            "Score 0-10 per strategy. The same matcher used for L3-call "
            "tagging, run against the aggregate tags of today's themes "
            "(no real L3 call required). High score → strategy aligns "
            "with what today's data is highlighting. Useful when no "
            "high-conviction L3 call has fired yet."
        ),
    }


@router.get("/{strategy_id}")
def get_strategy(strategy_id: str) -> Dict[str, Any]:
    """Return one strategy's YAML row + its full markdown body."""
    items = _load_catalog()
    match = next((s for s in items if s.get("id") == strategy_id), None)
    if match is None:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}")

    md_file = _STRATEGIES_DIR / f"{strategy_id}.md"
    body = md_file.read_text(encoding="utf-8") if md_file.exists() else ""

    return {"strategy": match, "markdown": body}
