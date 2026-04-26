"""FastAPI router for the L0 widget registry — exposes the registry
itself + the reverse map (widget → which strategies need it).

Mounted into ``dashboard_server.py``:

    GET /api/lattice/widgets                  list every widget + status
    GET /api/lattice/widgets/{id}             one widget's metadata
    GET /api/lattice/widgets/{id}/strategies  reverse map: strategies needing this widget

The reverse map answers "if I'm looking at widget X in the lattice
graph, what strategies depend on it?" — closing the audit loop the
other direction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml
from fastapi import APIRouter, HTTPException, Query

from agent.finance.lattice.widget_registry import (
    WIDGET_REGISTRY,
    list_widgets,
    get_widget,
    widget_status_summary,
)

router = APIRouter(prefix="/api/lattice/widgets", tags=["fin-lattice-widgets"])

_STRATEGIES_YAML = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs" / "strategies" / "strategies.yaml"
)


def _load_strategies() -> List[Dict[str, Any]]:
    if not _STRATEGIES_YAML.exists():
        return []
    raw = yaml.safe_load(_STRATEGIES_YAML.read_text(encoding="utf-8")) or {}
    return list(raw.get("strategies", []))


@router.get("")
def list_widgets_endpoint(status: str | None = Query(None)) -> Dict[str, Any]:
    """Every widget id known to the lattice. Filter by status if given."""
    items = list_widgets(status)
    return {
        "count":    len(items),
        "widgets":  items,
        "summary":  widget_status_summary(),
        "explanation": (
            "L0 widget controlled vocabulary. 'available' = currently "
            "emitting L1 obs into the lattice; 'planned' = declared by "
            "≥1 catalog strategy but no generator yet (a data gap)."
        ),
    }


@router.get("/{widget_id}")
def get_widget_endpoint(widget_id: str) -> Dict[str, Any]:
    """One widget's metadata. Path supports dotted names like fin_db.wash_sale_detector."""
    w = get_widget(widget_id)
    if w is None:
        raise HTTPException(404, f"unknown widget {widget_id!r}")
    return w


@router.get("/{widget_id}/strategies")
def reverse_widget_to_strategies(widget_id: str) -> Dict[str, Any]:
    """Reverse map: strategies that declare this widget as a data dep."""
    w = get_widget(widget_id)
    if w is None:
        raise HTTPException(404, f"unknown widget {widget_id!r}")

    matches: List[Dict[str, Any]] = []
    for s in _load_strategies():
        widgets = s.get("data_requirement_widgets", []) or []
        if widget_id in widgets:
            matches.append({
                "id":          s.get("id"),
                "name_en":     s.get("name_en"),
                "name_zh":     s.get("name_zh"),
                "horizon":     s.get("horizon"),
                "difficulty":  s.get("difficulty"),
                "feasible_at_10k": s.get("feasible_at_10k"),
            })

    return {
        "widget":       w,
        "strategy_count": len(matches),
        "strategies":   matches,
        "explanation": (
            f"Strategies that declare widget {widget_id!r} as a data "
            f"requirement. {len(matches)} strategies depend on this widget. "
            f"Click any to see its full catalog entry + lattice status."
        ),
    }
