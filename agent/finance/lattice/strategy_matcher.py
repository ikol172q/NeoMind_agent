"""Deterministic matcher: L3 call → strategies.yaml entry.

Given a freshly-generated L3 ``Call`` and the L2 themes it grounds in,
pick the best-fit ``strategy_id`` from
``docs/strategies/strategies.yaml`` (Phase 3 catalog). Returns None if
no strategy clears a minimum score.

Why deterministic instead of LLM-suggested?
  - LLM prompt changes risk regressions in the existing 128 lattice
    tests + the production call-generation behaviour.
  - The 35 strategies have stable structured metadata (horizon,
    asset_class, defined_risk, pdt_relevant, tax_treatment) — a small
    scoring function gives stable, explainable matches.
  - "Why does this call cite strategy X?" is auditable: the score
    breakdown is trivially logged.

Scoring (max ~10 per strategy):
  +3 horizon agrees (time_horizon mapped to strategy.horizon)
  +2 every overlapping tag in member_tags ∩ strategy_implied_tags
  +2 if any options-related tag and strategy.asset_class == 'options'
  +2 if 'risk:earnings' in member_tags and 'earnings' in strategy.id
  +1 if 'risk:wash_sale' / pdt_breach / compliance:* in member_tags
     and strategy.tax_treatment.wash_sale_risk != 'low'
  −2 if call horizon is short and strategy.feasible_at_10k is False
  −5 if pdt_relevant strategy and call horizon is intraday but the
     user's account is <$25k (V1 hardcodes this as TRUE — match-time
     account-equity threshold not yet plumbed)

Threshold: top score must be ≥ 3 to assign. Avoids noisy single-tag
matches that don't actually fit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

logger = logging.getLogger(__name__)


# Map L3 Call.time_horizon → strategy.horizon. Lattice uses
# {intraday, days, weeks, quarter}; catalog uses {long_term, months,
# weeks, swing, days, intraday}.
HORIZON_MAP: Dict[str, str] = {
    "intraday": "intraday",
    "days":     "days",
    "weeks":    "weeks",
    "quarter":  "months",   # "quarter" ≈ multi-month view
    "long":     "long_term",
}

_STRATEGIES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "docs" / "strategies"
)
_STRATEGIES_YAML = _STRATEGIES_DIR / "strategies.yaml"

_PDT_AWARE_HORIZON = {"intraday", "days"}

# Conservative default: assume the user is on a sub-$25k account
# (per the user's stated $10k starting capital) so PDT-relevant
# strategies under day-trading horizons get penalised. Future plumbing
# can read this from a runtime account config.
_ASSUMED_ACCOUNT_UNDER_25K = True


def _load_strategies() -> List[Dict[str, Any]]:
    if not _STRATEGIES_YAML.exists():
        return []
    try:
        raw = yaml.safe_load(_STRATEGIES_YAML.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("strategies.yaml parse error: %s", exc)
        return []
    return list(raw.get("strategies", []))


def _collect_member_tags(
    grounds: Sequence[str],
    themes_by_id: Dict[str, Any],
) -> List[str]:
    """Return all member observations' tags for the themes a call grounds in.

    ``themes_by_id`` is keyed by theme_id and each value is the theme
    dict (with .members list of {obs_id, tags?}). The shape may vary —
    we read members defensively.
    """
    out: List[str] = []
    for tid in grounds:
        theme = themes_by_id.get(tid)
        if not theme:
            continue
        members = (
            theme.members
            if hasattr(theme, "members")
            else theme.get("members", [])
        )
        for m in members:
            tags = (
                m.tags if hasattr(m, "tags")
                else (m.get("tags") if isinstance(m, dict) else None)
            )
            if tags:
                out.extend(tags)
        # Also include theme-level tags if present
        theme_tags = (
            theme.tags if hasattr(theme, "tags")
            else theme.get("tags", [])
        )
        out.extend(theme_tags or [])
    return out


def _score_strategy(
    strategy: Dict[str, Any],
    *,
    call_horizon: str,
    member_tags: List[str],
) -> Tuple[int, Dict[str, int]]:
    """Return (total_score, score_breakdown_dict)."""
    breakdown: Dict[str, int] = {}
    tag_set = set(member_tags)

    # Horizon agreement
    expected = HORIZON_MAP.get(call_horizon)
    if expected and expected == strategy.get("horizon"):
        breakdown["horizon_match"] = 3

    # Options coupling
    if strategy.get("asset_class") == "options":
        if any(t.startswith("technical:") or "options" in t for t in tag_set):
            breakdown["options_asset_class"] = 2

    # Earnings event coupling
    s_id = str(strategy.get("id", "")).lower()
    if "risk:earnings" in tag_set or "catalyst:earnings" in tag_set:
        if "earnings" in s_id or "post_earnings_drift" in s_id:
            breakdown["earnings_event"] = 2
        elif strategy.get("asset_class") == "options":
            breakdown["earnings_event_options"] = 1

    # Tax / compliance coupling — when the lattice has wash_sale /
    # pdt_breach / near_long_term L1 obs, prefer strategies that DO
    # have nontrivial tax handling (so user gets a strategy whose
    # docs/strategies/<id>.md actually addresses the risk).
    has_compliance = any(
        t in tag_set for t in (
            "risk:wash_sale", "risk:pdt_breach",
            "compliance:tax_inefficiency", "compliance:near_long_term",
        )
    )
    if has_compliance:
        wash_risk = strategy.get("tax_treatment", {}).get("wash_sale_risk", "low")
        if wash_risk != "low":
            breakdown["tax_compliance_relevant"] = 1

    # Penalise PDT-relevant short-horizon strategies if assumed <$25k
    if (
        _ASSUMED_ACCOUNT_UNDER_25K
        and strategy.get("pdt_relevant")
        and call_horizon in _PDT_AWARE_HORIZON
    ):
        breakdown["pdt_under_25k_penalty"] = -5

    # Penalise infeasible-at-$10k strategies
    if strategy.get("feasible_at_10k") is False:
        breakdown["infeasible_at_10k"] = -2

    # Tiny boost for low-difficulty matches when horizons agree
    # (helps the user pick a strategy they can actually execute)
    if breakdown.get("horizon_match"):
        diff = int(strategy.get("difficulty", 5))
        if diff <= 2:
            breakdown["low_difficulty_boost"] = 1

    return sum(breakdown.values()), breakdown


# Reverse map: catalog horizon → ("call.time_horizon" the matcher accepts)
# Used when scoring strategies WITHOUT a real call (theme-level relevance).
_REVERSE_HORIZON_MAP: Dict[str, str] = {
    "intraday":  "intraday",
    "days":      "days",
    "weeks":     "weeks",
    "swing":     "weeks",
    "months":    "quarter",
    "long_term": "long",
}


def match_all_against_themes(themes: List[Any]) -> List[Dict[str, Any]]:
    """Score every catalog strategy against today's L2 themes' aggregate
    tag context — *without* requiring a real L3 call.

    This is the "no L3 call today" fallback the user explicitly asked
    for: when the lattice doesn't produce any high-conviction calls,
    the Strategies tab can still surface "which strategies are most
    aligned with what today's data is showing?" by pulling tags off
    every theme's member observations.

    Returns sorted list (highest score first); no threshold filter,
    so even score=0 strategies are present (UI can sort/filter).

    Each strategy gets scored at its OWN horizon (so horizon_match
    fires automatically — we want to see how the OTHER signals like
    options-coupling / earnings / compliance light up).
    """
    strategies = _load_strategies()
    if not strategies:
        return []

    # Aggregate every observation tag across all themes
    all_tags: List[str] = []
    for t in themes:
        members = (
            t.members if hasattr(t, "members")
            else (t.get("members", []) if isinstance(t, dict) else [])
        )
        for m in members:
            tags = (
                m.tags if hasattr(m, "tags")
                else (m.get("tags", []) if isinstance(m, dict) else [])
            )
            if tags:
                all_tags.extend(tags)
        theme_tags = (
            t.tags if hasattr(t, "tags")
            else (t.get("tags", []) if isinstance(t, dict) else [])
        )
        all_tags.extend(theme_tags or [])

    out: List[Dict[str, Any]] = []
    for s in strategies:
        s_horizon = s.get("horizon", "weeks")
        call_horizon = _REVERSE_HORIZON_MAP.get(s_horizon, "weeks")
        score, bd = _score_strategy(
            s, call_horizon=call_horizon, member_tags=all_tags,
        )
        out.append({
            "strategy_id":     s["id"],
            "name_en":         s.get("name_en"),
            "name_zh":         s.get("name_zh"),
            "horizon":         s_horizon,
            "difficulty":      s.get("difficulty"),
            "asset_class":     s.get("asset_class"),
            "defined_risk":    s.get("defined_risk"),
            "pdt_relevant":    s.get("pdt_relevant"),
            "score":           score,
            "score_breakdown": bd,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def match_strategy(
    *,
    call: Any,                              # Call dataclass or dict
    themes_by_id: Dict[str, Any],
    threshold: int = 3,
) -> Optional[Dict[str, Any]]:
    """Return the best-fit catalog entry for a Call, or None.

    Output dict (the shape consumed by the API payload):
        {
          "strategy_id":  "covered_call_etf",
          "name_en":      "ETF Covered Call",
          "name_zh":      "ETF 备兑开仓",
          "score":        7,
          "score_breakdown": {"horizon_match": 3, "options_asset_class": 2, ...}
        }
    """
    strategies = _load_strategies()
    if not strategies:
        return None

    # Read the call's horizon + grounds defensively
    call_horizon = (
        call.time_horizon if hasattr(call, "time_horizon")
        else call.get("time_horizon", "")
    )
    grounds = (
        call.grounds if hasattr(call, "grounds")
        else call.get("grounds", [])
    )

    member_tags = _collect_member_tags(grounds, themes_by_id)

    scored: List[Tuple[int, Dict[str, int], Dict[str, Any]]] = []
    for s in strategies:
        score, bd = _score_strategy(
            s, call_horizon=call_horizon, member_tags=member_tags,
        )
        scored.append((score, bd, s))

    scored.sort(key=lambda t: t[0], reverse=True)
    if not scored:
        return None
    top_score, top_bd, top_s = scored[0]
    if top_score < threshold:
        return None

    return {
        "strategy_id":     top_s["id"],
        "name_en":         top_s.get("name_en"),
        "name_zh":         top_s.get("name_zh"),
        "horizon":         top_s.get("horizon"),
        "difficulty":      top_s.get("difficulty"),
        "defined_risk":    top_s.get("defined_risk"),
        "pdt_relevant":    top_s.get("pdt_relevant"),
        "score":           top_score,
        "score_breakdown": top_bd,
    }
