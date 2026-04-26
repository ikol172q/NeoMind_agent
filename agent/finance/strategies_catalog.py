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


@router.get("/widget-coverage")
def widget_coverage() -> Dict[str, Any]:
    """Matrix view: every (strategy, widget) pairing for audit.

    Returns:
        {
          "strategies": [{
              "id": "covered_call_etf",
              "name_en": "...", "name_zh": "...",
              "widgets": [{"id": "options_chain", "status": "planned",
                            "label_en": "...", "label_zh": "..."}, ...],
              "available_count": 1, "planned_count": 2,
          }, ...],
          "summary": {"total_strategies": 36, "fully_available": 2,
                       "has_planned_gaps": 34, ...}
        }

    The cornerstone of Phase 6 Req #5 — the user can audit which
    strategies are actually backed by current lattice widgets and
    which are documented-but-not-implemented gaps.
    """
    try:
        from agent.finance.lattice.widget_registry import get_widget, STATUS_AVAILABLE, STATUS_PLANNED
    except Exception as exc:
        raise HTTPException(503, f"widget_registry unavailable: {exc}")

    items = _load_catalog()
    out_strategies: List[Dict[str, Any]] = []
    fully_available = 0
    has_planned = 0
    has_unresolved = 0

    for s in items:
        widget_ids: List[str] = list(s.get("data_requirement_widgets", []) or [])
        widgets_meta: List[Dict[str, Any]] = []
        avail = 0
        plan = 0
        unresolved: List[str] = []
        for wid in widget_ids:
            w = get_widget(wid)
            if w is None:
                unresolved.append(wid)
                continue
            widgets_meta.append({
                "id": w["id"],
                "status": w["status"],
                "label_en": w.get("label_en"),
                "label_zh": w.get("label_zh"),
                "description": w.get("description"),
            })
            if w["status"] == STATUS_AVAILABLE:
                avail += 1
            elif w["status"] == STATUS_PLANNED:
                plan += 1

        if plan == 0 and unresolved == [] and avail > 0:
            fully_available += 1
        if plan > 0:
            has_planned += 1
        if unresolved:
            has_unresolved += 1

        out_strategies.append({
            "id":             s["id"],
            "name_en":        s.get("name_en"),
            "name_zh":        s.get("name_zh"),
            "horizon":        s.get("horizon"),
            "widgets":        widgets_meta,
            "available_count": avail,
            "planned_count":   plan,
            "unresolved":      unresolved,
            "free_text_requirements": s.get("data_requirements", []),
        })

    return {
        "strategies": out_strategies,
        "summary": {
            "total_strategies":  len(items),
            "fully_available":   fully_available,
            "has_planned_gaps":  has_planned,
            "has_unresolved":    has_unresolved,
        },
        "explanation": (
            "Bidirectional knowledge-graph audit (Phase 6 Step 4). "
            "Each strategy lists its declared widget requirements, with "
            "status per widget. 'available' = lattice currently emits L1 "
            "obs from this widget; 'planned' = referenced by ≥1 strategy "
            "but no generator yet (explicit data gap). UI Strategy card "
            "can render this as ✓/⚠ chips."
        ),
    }


@router.get("/{strategy_id}/widget-status")
def strategy_widget_status(strategy_id: str) -> Dict[str, Any]:
    """Forward map for a single strategy: id → widget statuses."""
    try:
        from agent.finance.lattice.widget_registry import get_widget
    except Exception as exc:
        raise HTTPException(503, f"widget_registry unavailable: {exc}")

    match = next((s for s in _load_catalog() if s.get("id") == strategy_id), None)
    if match is None:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}")

    widget_ids: List[str] = list(match.get("data_requirement_widgets", []) or [])
    widgets_meta = [
        {
            "id":          w["id"] if (w := get_widget(wid)) else wid,
            "status":      (get_widget(wid) or {}).get("status", "unknown"),
            "label_en":    (get_widget(wid) or {}).get("label_en"),
            "label_zh":    (get_widget(wid) or {}).get("label_zh"),
            "description": (get_widget(wid) or {}).get("description"),
        }
        for wid in widget_ids
    ]
    return {
        "strategy_id":              strategy_id,
        "name_en":                  match.get("name_en"),
        "name_zh":                  match.get("name_zh"),
        "free_text_requirements":   match.get("data_requirements", []),
        "widgets":                  widgets_meta,
    }


# ── Phase 6 followup #2: time-aware Strategies ──────────────────
#
# For event-driven strategies (FOMC, quad witching, Russell rebalance,
# earnings season) compute days-until-next-event so the UI can surface
# urgency chips ("fires in 3 days").  Strategies without a deterministic
# calendar trigger (DCA, factor tilts, …) get null — they're always-on.
#
# The event calendars below are deterministic enough to compute without
# external feeds: FOMC has a published schedule, quad witching is the
# 3rd Friday of Mar/Jun/Sep/Dec, Russell reconstitution is late June.
# Per-stock earnings dates are looked up via finance_data_hub if the
# strategy is stock-specific.

import datetime as _dt
from calendar import monthrange as _monthrange


def _third_friday(year: int, month: int) -> _dt.date:
    """Quad-witching falls on the 3rd Friday of Mar/Jun/Sep/Dec."""
    # Find the first Friday
    weekday_of_1st = _dt.date(year, month, 1).weekday()  # Mon=0..Sun=6, Fri=4
    first_friday = 1 + ((4 - weekday_of_1st) % 7)
    return _dt.date(year, month, first_friday + 14)


def _next_quad_witch(today: _dt.date) -> _dt.date:
    """Next quad-witching expiry (3rd Fri of Mar/Jun/Sep/Dec) ≥ today."""
    for y in (today.year, today.year + 1):
        for m in (3, 6, 9, 12):
            d = _third_friday(y, m)
            if d >= today:
                return d
    raise RuntimeError("unreachable")  # always finds one within 12 months


def _next_russell_rebal(today: _dt.date) -> _dt.date:
    """FTSE Russell reconstitution — final rebalance date is the
    last Friday of June (well-known annual schedule)."""
    for y in (today.year, today.year + 1):
        last_day = _monthrange(y, 6)[1]
        last_friday = _dt.date(y, 6, last_day)
        while last_friday.weekday() != 4:  # Fri = 4
            last_friday -= _dt.timedelta(days=1)
        if last_friday >= today:
            return last_friday
    raise RuntimeError("unreachable")


# 2026 FOMC schedule (Fed publishes annually; stale-safe — only the
# *date* matters, not minutes content). Using public schedule.
_FOMC_DATES_2026 = [
    _dt.date(2026, 1, 28),
    _dt.date(2026, 3, 18),
    _dt.date(2026, 4, 29),
    _dt.date(2026, 6, 17),
    _dt.date(2026, 7, 29),
    _dt.date(2026, 9, 16),
    _dt.date(2026, 10, 28),
    _dt.date(2026, 12, 16),
]


def _next_fomc(today: _dt.date) -> Optional[_dt.date]:
    upcoming = [d for d in _FOMC_DATES_2026 if d >= today]
    return upcoming[0] if upcoming else None


def _urgency(days: Optional[int]) -> str:
    if days is None:
        return "none"
    if days <= 3:
        return "imminent"
    if days <= 7:
        return "soon"
    if days <= 21:
        return "upcoming"
    return "distant"


# Strategy id → (event_label_en, event_label_zh, calendar fn)
# Returning None from the fn means "no upcoming event known".
def _earnings_season_window(today: _dt.date) -> Optional[_dt.date]:
    """Earnings 'season' = 4 windows per year, roughly 3 weeks each
    starting the 3rd week of Jan/Apr/Jul/Oct."""
    windows = [
        (1, 14), (4, 14), (7, 14), (10, 14),
    ]
    for y in (today.year, today.year + 1):
        for (m, d) in windows:
            start = _dt.date(y, m, d)
            if start >= today:
                return start
    raise RuntimeError("unreachable")


_TIME_AWARE_RULES: Dict[str, Dict[str, Any]] = {
    "fomc_announcement_fade": {
        "label_en": "Next FOMC",
        "label_zh": "下次 FOMC 议息",
        "fn":       _next_fomc,
    },
    "quad_witching_volatility": {
        "label_en": "Next quad-witching expiry",
        "label_zh": "下次四巫日",
        "fn":       _next_quad_witch,
    },
    "russell_rebalance": {
        "label_en": "Russell reconstitution",
        "label_zh": "罗素再平衡",
        "fn":       _next_russell_rebal,
    },
    "post_earnings_drift": {
        "label_en": "Earnings season opens",
        "label_zh": "财报季开启",
        "fn":       _earnings_season_window,
    },
    "earnings_announcement_drift": {
        "label_en": "Earnings season opens",
        "label_zh": "财报季开启",
        "fn":       _earnings_season_window,
    },
}


@router.get("/time-aware")
def strategies_time_aware(
    project_id: str = Query(..., description="kept for symmetry; not yet used"),
) -> Dict[str, Any]:
    """For each catalog strategy, compute days-until-next-event so the
    UI can surface urgency chips. Always-on strategies return null.
    """
    today = _dt.date.today()
    entries: List[Dict[str, Any]] = []
    for s in _load_catalog():
        sid = s.get("id")
        rule = _TIME_AWARE_RULES.get(sid)
        if rule is None:
            entries.append({
                "id":           sid,
                "days_until":   None,
                "event_label":  None,
                "event_date":   None,
                "urgency":      "none",
            })
            continue

        next_d: Optional[_dt.date] = rule["fn"](today)
        if next_d is None:
            entries.append({
                "id":          sid,
                "days_until":  None,
                "event_label": rule["label_en"],
                "event_date":  None,
                "urgency":     "none",
            })
            continue

        days = (next_d - today).days
        entries.append({
            "id":           sid,
            "days_until":   days,
            "event_label":  rule["label_en"],
            "event_label_zh": rule["label_zh"],
            "event_date":   next_d.isoformat(),
            "urgency":      _urgency(days),
        })

    return {
        "count":       len(entries),
        "computed_at": _dt.datetime.utcnow().isoformat() + "Z",
        "entries":     entries,
        "explanation": (
            "Days until each strategy's next deterministic calendar trigger. "
            "Always-on strategies (DCA, factor ETFs) return null. UI surfaces "
            "this as 'fires in N days' chips with urgency color."
        ),
    }


# ── L2 / L3 explicit bidirectional ────────────────────────────────
#
# Phase 6 followup: lattice <-> Strategies map for the L2 layer.
#   forward (theme -> strategies):  /api/strategies/by-theme?project_id=&theme_id=
#   reverse (strategy -> themes):   /api/strategies/{strategy_id}/themes-today?project_id=
#
# Both share the project's lattice synthesis so they're always
# consistent with what the trace panel and Strategies card show.

@router.get("/by-theme")
def strategies_by_theme(
    project_id: str = Query(...),
    theme_id: str   = Query(...),
    top_n: int      = Query(8, ge=1, le=30),
) -> Dict[str, Any]:
    """Top catalog strategies fitting an L2 theme. Used by the lattice
    trace panel's L2-node inspector ('Top strategies fitting this
    theme').
    """
    try:
        from agent.finance.lattice.synth import synthesise_lattice
        from agent.finance.lattice.strategy_matcher import (
            match_strategies_against_theme,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"lattice modules unavailable: {exc}")

    bundle = synthesise_lattice(project_id=project_id)
    themes = (bundle or {}).get("themes", [])
    theme = next(
        (t for t in themes
         if (t.id if hasattr(t, "id") else t.get("id")) == theme_id),
        None,
    )
    if theme is None:
        raise HTTPException(404, f"unknown theme {theme_id!r}")

    strategies = match_strategies_against_theme(theme, top_n=top_n)
    title = (
        theme.title if hasattr(theme, "title")
        else (theme.get("title") if isinstance(theme, dict) else None)
    )
    return {
        "theme_id":     theme_id,
        "theme_title":  title,
        "count":        len(strategies),
        "strategies":   strategies,
        "explanation": (
            f"Strategies scored against the L2 theme {theme_id!r} "
            f"({title!r}). Score uses the same matcher as today_fit, "
            f"applied per-theme instead of aggregated."
        ),
    }


@router.get("/{strategy_id}/themes-today")
def themes_matching_strategy_today(
    strategy_id: str,
    project_id: str = Query(...),
) -> Dict[str, Any]:
    """Reverse: which of today's L2 themes score >= 1 against this
    strategy? Used by the Strategies card 'TODAY MATCHING THEMES'
    section to give the user a click-jump path strategy → lattice."""
    try:
        from agent.finance.lattice.synth import synthesise_lattice
        from agent.finance.lattice.strategy_matcher import (
            themes_matching_strategy,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"lattice modules unavailable: {exc}")

    bundle = synthesise_lattice(project_id=project_id)
    themes = (bundle or {}).get("themes", [])
    matches = themes_matching_strategy(strategy_id, themes)
    return {
        "strategy_id":  strategy_id,
        "count":        len(matches),
        "themes":       matches,
        "explanation": (
            f"L2 themes from today's lattice that score >=1 against "
            f"strategy {strategy_id!r}. Click any theme_id to jump "
            f"to the lattice graph focused on that L2 node."
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
