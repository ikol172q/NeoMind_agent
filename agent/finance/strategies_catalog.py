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
