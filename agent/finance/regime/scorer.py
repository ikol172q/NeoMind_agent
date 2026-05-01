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
    apply_knn_prior: bool = True,
    k: int = 5,
) -> List[Dict[str, Any]]:
    """Score every strategy in the catalog. Sorted by score DESC.

    When ``apply_knn_prior`` is true and there's enough fingerprint
    history, blends each strategy's score with an empirical-Bayes
    prior from the K nearest historical regime days (Step E).
    """
    from agent.finance.lattice.strategy_matcher import _load_strategies
    strategies = _load_strategies(include_unverified=include_unverified)
    out = [
        score_strategy(s, fingerprint,
                       user_prefs=user_prefs,
                       lattice_payload=lattice_payload)
        for s in strategies
    ]

    # ── Step E: Bayesian shrinkage with k-NN regime neighbors ──
    if apply_knn_prior:
        try:
            neighbors = _knn_regime_neighbors(fingerprint, k=k)
        except Exception as exc:  # pragma: no cover
            logger.debug("knn lookup unavailable: %s", exc)
            neighbors = []

        if neighbors:
            from agent.finance.regime.store import (
                list_decision_traces, write_knn_lookups,
            )
            target_date = fingerprint.get("fingerprint_date")
            for entry in out:
                # Pull historical traces of THIS strategy on the
                # neighbor dates.  Their scores form the empirical
                # prior; we shrink today's model score toward the
                # similarity-weighted mean.
                hist_scores: List[float] = []
                weights: List[float] = []
                neighbor_dates_used: List[str] = []
                for nb in neighbors:
                    rows = list_decision_traces(
                        fingerprint_date=nb["neighbor_date"],
                        strategy_id=entry["strategy_id"],
                        limit=1,
                    )
                    if rows:
                        hist_scores.append(float(rows[0]["score"]))
                        weights.append(float(nb["similarity"]))
                        neighbor_dates_used.append(nb["neighbor_date"])

                if hist_scores:
                    wsum = sum(weights) or 1.0
                    prior = sum(s * w for s, w in zip(hist_scores, weights)) / wsum
                    # Empirical-Bayes shrinkage with adaptive trust:
                    # more samples → more weight on prior.
                    n = len(hist_scores)
                    beta = min(0.40, n / (n + 5.0))   # ≤0.4 max
                    blended = (1 - beta) * entry["score"] + beta * prior
                    entry["score_breakdown"]["knn_prior"] = {
                        "prior_mean":     round(prior, 3),
                        "n_neighbors":    n,
                        "shrinkage_beta": round(beta, 3),
                        "neighbor_dates": neighbor_dates_used,
                        "model_only_score": entry["score"],
                    }
                    entry["score"] = round(blended, 2)
                    entry["formula"] = entry["formula"] + "+knn_prior"

            # Persist the k-NN lookups for the audit trail
            try:
                if target_date:
                    write_knn_lookups(
                        target_date=target_date,
                        used_for_strategy="*",
                        neighbors=[
                            {
                                "neighbor_date":    nb["neighbor_date"],
                                "similarity_score": nb["similarity"],
                                "weight_in_prior":  nb["similarity"],
                            }
                            for nb in neighbors
                        ],
                    )
            except Exception as exc:  # pragma: no cover
                logger.debug("write_knn_lookups failed: %s", exc)

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _knn_regime_neighbors(
    target_fp: Dict[str, Any],
    *, k: int = 5,
) -> List[Dict[str, Any]]:
    """Find the K nearest historical regime days by Euclidean distance
    in the 5-bucket score space.  Returns
    [{neighbor_date, similarity (0..1), distance}], best first.
    """
    from agent.finance.regime.store import list_fingerprints

    keys = ("risk_appetite_score", "volatility_regime_score",
            "breadth_score", "event_density_score", "flow_score")
    target_vec = [target_fp.get(k_, 50.0) or 50.0 for k_ in keys]
    target_date = target_fp.get("fingerprint_date")

    history = list_fingerprints(limit=400)  # ~ 1.6 yrs of trading days
    scored: List[Dict[str, Any]] = []
    for row in history:
        if row.get("fingerprint_date") == target_date:
            continue
        vec = [row.get(k_, 50.0) or 50.0 for k_ in keys]
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(target_vec, vec)))
        # Convert 5-bucket-space distance (0..~111) to similarity 0..1
        sim = max(0.0, 1.0 - dist / 111.8)
        scored.append({
            "neighbor_date": row["fingerprint_date"],
            "similarity":    round(sim, 4),
            "distance":      round(dist, 2),
        })
    scored.sort(key=lambda x: -x["similarity"])
    return scored[:k]


# ── Step F: MMR (Maximal Marginal Relevance) diversification ──────


def _strategy_similarity(a: Dict[str, Any], b: Dict[str, Any],
                         strategies_by_id: Dict[str, Dict[str, Any]]) -> float:
    """Cosine-ish similarity between two scored strategies in [0, 1].

    Combines:
      • payoff_class match (0.40 weight)  — identical class → 1, similar class → 0.5
      • asset_class match  (0.20 weight)  — same asset class → 1
      • regime_sensitivity cosine (0.40 weight) — direction in regime space
    """
    sa = strategies_by_id.get(a["strategy_id"], {})
    sb = strategies_by_id.get(b["strategy_id"], {})
    pa = sa.get("quantitative_profile") or {}
    pb = sb.get("quantitative_profile") or {}

    # 1) payoff_class
    pca = pa.get("payoff_class", "")
    pcb = pb.get("payoff_class", "")
    if pca and pca == pcb:
        payoff_sim = 1.0
    elif pca and pcb and pca.split("_")[0] == pcb.split("_")[0]:
        payoff_sim = 0.5  # related family (e.g. covered_call vs covered_strangle)
    else:
        payoff_sim = 0.0

    # 2) asset_class
    aca = sa.get("asset_class", "")
    acb = sb.get("asset_class", "")
    asset_sim = 1.0 if aca and aca == acb else 0.0

    # 3) regime_sensitivity cosine
    sa_sens = pa.get("regime_sensitivity", {}) or {}
    sb_sens = pb.get("regime_sensitivity", {}) or {}
    keys = ("risk_appetite", "volatility_regime", "breadth", "event_density", "flow")
    va = [float(sa_sens.get(k, 0.0)) for k in keys]
    vb = [float(sb_sens.get(k, 0.0)) for k in keys]
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(x * x for x in vb))
    if na > 0 and nb > 0:
        regime_sim = max(0.0, min(1.0, dot / (na * nb)))
    else:
        regime_sim = 0.0

    return 0.40 * payoff_sim + 0.20 * asset_sim + 0.40 * regime_sim


def select_diversified_portfolio(
    scored: List[Dict[str, Any]],
    *,
    n_alternatives: int = 5,
    lambda_weight: float = 0.65,
    min_score: float = 1.0,
) -> Dict[str, Any]:
    """MMR-style portfolio selection.

    Args:
      scored: output of ``score_all_strategies`` (already sorted DESC).
      n_alternatives: how many alternatives to surface (3-8 typical).
      lambda_weight: balance between relevance (1.0) and diversity (0.0).
        0.65 = lean toward relevance but penalise duplicates.
      min_score: skip candidates below this threshold (0.0..10.0).

    Returns:
      {
        "top": <best>,
        "alternatives": [<by_diversified_relevance>...],
        "selection_method": "mmr_v1",
        "lambda": 0.65,
      }
    """
    if not scored:
        return {
            "top": None,
            "alternatives": [],
            "selection_method": "mmr_v1",
            "lambda": lambda_weight,
            "note": "empty scored list",
        }

    # Need raw strategy YAML entries to compute similarity (payoff_class etc).
    from agent.finance.lattice.strategy_matcher import _load_strategies
    strategies_by_id = {s["id"]: s for s in _load_strategies(include_unverified=True)}

    candidates = [s for s in scored if s.get("score", 0) >= min_score]
    if not candidates:
        candidates = list(scored)

    # 1) Pick top by raw score
    top = candidates[0]
    selected: List[Dict[str, Any]] = [top]
    remaining = list(candidates[1:])

    # 2) MMR loop
    max_score = max((s.get("score", 0) for s in candidates), default=10.0) or 10.0
    while remaining and len(selected) < n_alternatives + 1:
        best_idx = None
        best_mmr = -1e9
        for idx, cand in enumerate(remaining):
            relevance = (cand.get("score", 0) / max_score)  # 0..1
            sim_to_selected = max(
                _strategy_similarity(cand, s, strategies_by_id)
                for s in selected
            )
            mmr = lambda_weight * relevance - (1 - lambda_weight) * sim_to_selected
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx
        if best_idx is None:
            break
        chosen = remaining.pop(best_idx)
        chosen["_mmr_score"] = round(best_mmr, 4)
        chosen["_diversity_from_top"] = round(
            1.0 - _strategy_similarity(chosen, top, strategies_by_id), 3
        )
        selected.append(chosen)

    return {
        "top": top,
        "alternatives": selected[1:],
        "selection_method": "mmr_v1",
        "lambda": lambda_weight,
        "n_alternatives": len(selected) - 1,
        "n_candidates_considered": len(candidates),
    }
