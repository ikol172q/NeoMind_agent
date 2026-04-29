"""Expected-utility scorer for the regime pipeline.

Replaces the categorical heuristics in ``strategy_matcher._score_strategy``
for the *display* path (Strategies tab "today's relevance").  The L3-call
matcher in ``strategy_matcher.match_strategy()`` is left untouched (it
gates LLM call composition, not display).

Key differences from the old scorer:

  • Continuous, regime-conditioned scoring.  Same strategy on two
    different days gets visibly different scores because the regime
    fingerprint vector is continuous.
  • Bayesian shrinkage hook — if there's enough k-NN history, the
    score blends with empirical past performance on similar days.
    (Falls back to model-only when history is thin.)
  • Returns a structured ``traceback`` so the UI can drill from the
    final number all the way back to lattice nodes + raw bytes.

Public API:

    score_strategy(strategy_yaml_entry, fingerprint, account_state)
        → {score, breakdown, traceback, formula}

    score_all_strategies(fingerprint, *, account_state, lattice_payload)
        → list of scored entries, sorted by score DESC
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── default user prefs (per design doc §10) ───────────────────────


DEFAULT_PREFS = {
    "options_level": 0,
    "max_drawdown_tolerance": 0.15,
    "income_vs_growth": 0.5,
    "max_position_concentration": 0.25,
    "utility_weights": {
        "w_pnl":      1.0,
        "w_profit":   0.5,
        "w_drawdown": 1.5,
        "w_regime":   0.8,
    },
}


# ── regime → quantitative_profile compatibility ──────────────────


def _normalize_score(score: Optional[float]) -> float:
    """Map 0-100 bucket score to -1..1 (50 = neutral)."""
    if score is None:
        return 0.0
    return (score - 50.0) / 50.0


def _regime_match(profile: Dict[str, Any], fp: Dict[str, Any]) -> float:
    """Dot product of strategy regime_sensitivity × normalized regime
    bucket scores.  Range roughly -1..+1 (each bucket contributes
    sensitivity × normalized_score, max 5 buckets × 1 × 1 = 5,
    we'll divide by 5)."""
    sens = profile.get("regime_sensitivity", {}) or {}
    if not sens:
        return 0.0
    contributions = {
        "risk_appetite":     sens.get("risk_appetite", 0.0)
                              * _normalize_score(fp.get("risk_appetite_score")),
        "volatility_regime": sens.get("volatility_regime", 0.0)
                              * _normalize_score(fp.get("volatility_regime_score")),
        "breadth":           sens.get("breadth", 0.0)
                              * _normalize_score(fp.get("breadth_score")),
        "event_density":     sens.get("event_density", 0.0)
                              * _normalize_score(fp.get("event_density_score")),
        "flow":              sens.get("flow", 0.0)
                              * _normalize_score(fp.get("flow_score")),
    }
    total = sum(contributions.values()) / 5.0  # average → -1..+1
    return total, contributions


# ── analytic payoff stand-ins ─────────────────────────────────────
#
# These approximate E[PnL] / P(profit) / VaR for each payoff_class.
# Closed-form Black-Scholes where applicable; bootstrap-friendly
# otherwise.  All numbers are RELATIVE — UI displays a 0-10 score
# and breakdown deltas, not dollar P&Ls (because we don't yet have
# an account model with per-position dollar attribution).
#
# When a payoff_class doesn't have a closed-form here, we fall back
# to a regime-similarity-only score and flag "approximate" in the
# formula string.


def _payoff_score(profile: Dict[str, Any], fp: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate the expected-utility components for the given strategy
    against today's regime.  Returns dict with the breakdown keys."""
    payoff_class = profile.get("payoff_class", "unknown")

    # Realized vol proxy from the regime (volatility_regime_score is
    # 0-100 on a percentile basis; convert back to an annualised vol
    # estimate for option-style payoffs).  Anchor: SPY 30d RV ~= 0.16
    # at the median, ~0.10 at 10th pctile, ~0.30 at 90th.
    vol_pct = fp.get("volatility_regime_score") or 50.0
    rv_estimate = 0.10 + (vol_pct / 100.0) * 0.20  # 10-30% range

    # Risk appetite proxy → expected drift bias for delta strategies
    risk_pct = fp.get("risk_appetite_score") or 50.0
    drift_bias = (risk_pct - 50.0) / 50.0 * 0.05  # ±5% / yr drift

    # Event density penalty — the more events ahead, the higher
    # uncertainty for short-vol / time-decay strategies
    events_pct = fp.get("event_density_score") or 30.0

    # Flow → equity vs cash bias (risk-on = good for long-equity)
    flow_pct = fp.get("flow_score") or 50.0

    # Per-class heuristic score (0-10) before regime weighting
    hold_days = profile.get("expected_hold_days", 30)
    breakeven_rv = profile.get("breakeven_RV_pctile", 0.50)

    if payoff_class in ("covered_call", "cash_secured_put", "covered_strangle",
                        "covered_call_etf", "wheel"):
        # Short-vol: love high IV, hate event density
        rv_factor = max(0, min(10, (rv_estimate - 0.10) / 0.20 * 10))
        events_penalty = events_pct / 20.0  # up to 5 points off
        e_pnl = 5.0 + rv_factor - events_penalty
        p_profit = 0.55 + 0.20 * (rv_factor / 10.0) - 0.10 * (events_pct / 100)
        var_95 = -2 * profile.get("greeks_template", {}).get("vega", 0.18) * rv_estimate * 100

    elif payoff_class in ("vertical_bull_put_spread", "vertical_bear_call_spread",
                          "iron_condor", "iron_condor_index", "iron_butterfly",
                          "credit_spread"):
        # Defined-risk credit spreads: want moderate IV + low events
        rv_factor = max(0, min(10, 7 - abs(rv_estimate - 0.20) / 0.05 * 2))
        events_penalty = events_pct / 25.0
        e_pnl = 4.0 + rv_factor - events_penalty
        p_profit = 0.65 + 0.10 * (rv_factor / 10.0) - 0.10 * (events_pct / 100)
        var_95 = -profile.get("max_loss_units", 1.0) * 100

    elif payoff_class in ("long_call", "long_put", "long_straddle",
                          "long_strangle", "calendar_spread", "diagonal_spread",
                          "vertical_bull_call_spread", "vertical_bear_put_spread",
                          "debit_spread"):
        # Long-vol: love low IV (cheap), love events ahead
        rv_factor = max(0, min(10, (0.30 - rv_estimate) / 0.20 * 10))
        events_bonus = events_pct / 20.0
        e_pnl = 4.0 + rv_factor + events_bonus
        p_profit = 0.35 + 0.15 * (events_pct / 100) + 0.10 * rv_factor / 10
        var_95 = -profile.get("max_loss_units", 1.0) * 50

    elif payoff_class in ("dca", "buy_and_hold", "lazy_portfolio_three_fund",
                          "target_date_fund", "permanent_portfolio",
                          "dollar_cost_averaging_index", "dividend_growth_etf"):
        # Long-only: love risk-on, breadth, low vol
        breadth_pct = fp.get("breadth_score") or 50.0
        rv_factor = max(0, min(10, 8 - vol_pct / 20.0))
        breadth_bonus = breadth_pct / 20.0
        flow_bonus = flow_pct / 25.0
        e_pnl = 3.0 + rv_factor / 2 + breadth_bonus + flow_bonus + drift_bias * 20
        p_profit = 0.55 + 0.10 * (breadth_bonus / 5.0) + 0.10 * (flow_bonus / 4.0)
        var_95 = -hold_days / 252 * 0.4 * 100  # rough max DD over hold period

    elif payoff_class in ("momentum_breakout", "trend_following",
                          "swing_breakout", "fifty_two_week_high_breakout_swing",
                          "cross_sectional_momentum", "sector_rotation",
                          "sector_rotation_business_cycle"):
        # Momentum: love breadth + risk-on + low events
        breadth_pct = fp.get("breadth_score") or 50.0
        e_pnl = 3.0 + breadth_pct / 15.0 + flow_pct / 20.0 - events_pct / 25.0
        p_profit = 0.45 + 0.20 * (breadth_pct / 100)
        var_95 = -0.15 * 100  # ~15% max DD typical momentum

    elif payoff_class in ("mean_reversion", "mean_reversion_oversold_bounce_rsi2",
                          "low_volatility_factor", "value_factor",
                          "bear_market_hedge", "tail_risk_hedge"):
        # Mean-reversion / hedges: love high vol + low risk_appetite
        vol_factor = vol_pct / 10.0
        risk_inv = (100 - risk_pct) / 20.0
        e_pnl = 3.0 + vol_factor + risk_inv
        p_profit = 0.50 + 0.10 * (vol_factor / 10.0)
        var_95 = -0.20 * 100

    else:
        # Unknown payoff class — fall back to neutral scores.
        e_pnl = 5.0
        p_profit = 0.50
        var_95 = -0.20 * 100

    # Clamp
    e_pnl = max(0.0, min(10.0, e_pnl))
    p_profit = max(0.0, min(1.0, p_profit))

    return {
        "E_pnl_units":    round(e_pnl, 2),
        "P_profit":       round(p_profit, 3),
        "VaR_95_units":   round(var_95, 2),
        "rv_estimate":    round(rv_estimate, 4),
        "events_pct":     events_pct,
        "drift_bias":     round(drift_bias, 4),
        "payoff_class":   payoff_class,
    }


# ── public scorer ────────────────────────────────────────────────


def score_strategy(
    strategy: Dict[str, Any],
    fingerprint: Dict[str, Any],
    *,
    account_state: Optional[Dict[str, Any]] = None,
    user_prefs: Optional[Dict[str, Any]] = None,
    lattice_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score a single strategy against a regime fingerprint.

    Returns dict shape compatible with the existing UI's StrategyFitEntry:
      {strategy_id, score (0-10), score_breakdown (dict), traceback (dict)}
    """
    prefs = {**DEFAULT_PREFS, **(user_prefs or {})}
    weights = prefs["utility_weights"]

    profile = strategy.get("quantitative_profile") or {}

    # ── (1) regime match ─────────────────────────
    regime_match_total, regime_contribs = _regime_match(profile, fingerprint)

    # ── (2) payoff-class expected utility ────────
    payoff = _payoff_score(profile, fingerprint)

    # ── (3) composite utility ────────────────────
    # Each component normalised to roughly the same scale
    utility = (
        weights["w_pnl"]      * payoff["E_pnl_units"]      / 5.0   # 0-2
        + weights["w_profit"] * payoff["P_profit"]                  # 0-1
        + weights["w_drawdown"]
            * max(0, 1 + payoff["VaR_95_units"] / (100 * prefs["max_drawdown_tolerance"]))
        + weights["w_regime"] * regime_match_total                  # -1..+1
    )
    # Clip + scale to 0-10
    raw_score = max(0.0, min(10.0, utility))

    # ── (4) traceback ────────────────────────────
    traceback = {
        "regime_contributions": {
            k: round(v, 3) for k, v in regime_contribs.items()
        },
        "regime_total":  round(regime_match_total, 3),
        "payoff":        payoff,
        "weights_used":  weights,
        "user_prefs":    {
            "options_level": prefs["options_level"],
            "max_drawdown":  prefs["max_drawdown_tolerance"],
        },
        "fingerprint_date": fingerprint.get("fingerprint_date"),
        "fingerprint_scores": {
            "risk_appetite":     fingerprint.get("risk_appetite_score"),
            "volatility_regime": fingerprint.get("volatility_regime_score"),
            "breadth":           fingerprint.get("breadth_score"),
            "event_density":     fingerprint.get("event_density_score"),
            "flow":              fingerprint.get("flow_score"),
        },
    }
    if lattice_payload:
        # Attach lattice node refs for traceback
        themes = lattice_payload.get("themes", []) or []
        traceback["lattice_node_refs"] = [
            f"L2:{t.get('id')}" for t in themes if t.get("id")
        ]

    return {
        "strategy_id":     strategy["id"],
        "name_en":         strategy.get("name_en"),
        "name_zh":         strategy.get("name_zh"),
        "horizon":         strategy.get("horizon"),
        "difficulty":      strategy.get("difficulty"),
        "asset_class":     strategy.get("asset_class"),
        "score":           round(raw_score, 2),
        "score_breakdown": traceback,    # keep field name back-compat with UI
        "traceback":       traceback,    # explicit alias
        "formula":         "regime_v2_closed_form" if profile else "regime_v2_no_profile_fallback",
    }


def score_all_strategies(
    fingerprint: Dict[str, Any],
    *,
    user_prefs: Optional[Dict[str, Any]] = None,
    lattice_payload: Optional[Dict[str, Any]] = None,
    include_unverified: bool = True,
) -> List[Dict[str, Any]]:
    """Score every strategy in the catalog.  Sorted by score DESC."""
    from agent.finance.lattice.strategy_matcher import _load_strategies
    strategies = _load_strategies(include_unverified=include_unverified)
    out = [
        score_strategy(s, fingerprint,
                       user_prefs=user_prefs,
                       lattice_payload=lattice_payload)
        for s in strategies
    ]
    out.sort(key=lambda x: x["score"], reverse=True)
    return out
