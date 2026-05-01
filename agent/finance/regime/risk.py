"""Risk Dashboard — 6-dimension quantitative risk view per strategy.

Pivots from "predict alpha" (which v2/v3 showed isn't reliably possible
on proxy P&L) to "describe historical distribution + give forward-
looking risk-control tools".  All metrics here are math-grounded and
have no future-prediction component.

Six dimensions per (strategy, fingerprint):

  1. return_distribution    — μ ± σ + p10/p90 from k-NN regime analogs
  2. tail_risk              — VaR(95%) + CVaR(95%) + max drawdown
  3. position_sizing        — half-Kelly suggested capital fraction
  4. hedge_candidates       — top 3 negatively-correlated strategies
  5. stop_loss              — ATR-based stop-loss + time stop
  6. regime_fit             — per-bucket ✓/⚠/✗ + nearest analogs

Sources:
  - Rockafellar & Uryasev (2002) — CVaR / Expected Shortfall
  - Kelly (1956) — optimal capital growth
  - Markowitz (1952) — portfolio variance + correlation hedge
  - Wilder (1978) — Average True Range stop
  - Vovk (2005) — conformal prediction (used internally for CI)

All metrics computed from ``backtest_results`` SQLite table — no future
look-ahead.  Uses purely historical realized P&L distributions.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────


def _percentile(sorted_xs: List[float], p: float) -> Optional[float]:
    """Linear-interpolated percentile (p in [0, 1]).  None for empty."""
    if not sorted_xs:
        return None
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    idx = p * (len(sorted_xs) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# ── 1) return distribution from k-NN regime analogs ─────────────


def return_distribution(
    strategy_id: str,
    fingerprint: Dict[str, Any],
    *,
    k: int = 30,
    hold_days: int = 30,
) -> Dict[str, Any]:
    """Empirical return distribution conditioned on regime.

    Find K historical days closest to today's regime (Euclidean over the
    5 normalized bucket scores), pull realized 30d P&L for the same
    strategy on those days, return summary stats.
    """
    from agent.finance.persistence import connect

    keys = ("risk_appetite_score", "volatility_regime_score",
            "breadth_score", "event_density_score", "flow_score")
    target = [float(fingerprint.get(k_) or 50.0) for k_ in keys]

    sql = (
        "SELECT b.fingerprint_date, b.realized_pnl_pct, "
        "       f.risk_appetite_score, f.volatility_regime_score, "
        "       f.breadth_score, f.event_density_score, f.flow_score "
        "FROM backtest_results b "
        "JOIN regime_fingerprints f ON b.fingerprint_date = f.fingerprint_date "
        "WHERE b.strategy_id = ? AND b.hold_days = ? "
        "  AND b.realized_pnl_pct IS NOT NULL"
    )
    with connect() as conn:
        rows = conn.execute(sql, (strategy_id, hold_days)).fetchall()
    if not rows:
        return {"n": 0, "error": "no historical realized for strategy"}

    # k-NN by regime distance
    target_date = fingerprint.get("fingerprint_date")
    scored: List[Tuple[float, float, str]] = []
    for r in rows:
        if target_date and r["fingerprint_date"] == target_date:
            continue
        v = [float(r[k_] or 50.0) for k_ in keys]
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(target, v)))
        scored.append((d, float(r["realized_pnl_pct"]), r["fingerprint_date"]))
    scored.sort(key=lambda x: x[0])
    nearest = scored[:k]
    if not nearest:
        return {"n": 0, "error": "no neighbors"}

    rels = sorted(r for _, r, _ in nearest)
    return {
        "n":           len(rels),
        "median":      round(_percentile(rels, 0.50), 5),
        "p10":         round(_percentile(rels, 0.10), 5),
        "p25":         round(_percentile(rels, 0.25), 5),
        "p75":         round(_percentile(rels, 0.75), 5),
        "p90":         round(_percentile(rels, 0.90), 5),
        "mean":        round(_mean(rels), 5),
        "std":         round(_std(rels), 5),
        "k_nn":        k,
        "neighbor_dates": [d for _, _, d in nearest[:5]],
    }


# ── 2) tail risk: VaR + CVaR + Max DD ────────────────────────────


def tail_risk(
    strategy_id: str,
    *,
    hold_days: int = 30,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """Rockafellar-Uryasev CVaR + Max DD over full strategy history.

    VaR(α): the value such that P[loss > VaR] = 1 − α
    CVaR(α): E[loss | loss > VaR(α)] — the average loss in the worst
             (1−α) tail
    """
    from agent.finance.persistence import connect

    with connect() as conn:
        cur = conn.execute(
            "SELECT realized_pnl_pct, fingerprint_date FROM backtest_results "
            "WHERE strategy_id = ? AND hold_days = ? AND realized_pnl_pct IS NOT NULL "
            "ORDER BY fingerprint_date",
            (strategy_id, hold_days),
        )
        rows = cur.fetchall()
    if not rows:
        return {"n": 0, "error": "no rows"}

    rels = [float(r["realized_pnl_pct"]) for r in rows]
    losses = sorted(rels)  # ascending — losses at the bottom

    var = _percentile(losses, 1 - confidence)
    # CVaR = mean of values at-or-below VaR
    tail_pct = 1 - confidence
    n_tail = max(1, int(len(losses) * tail_pct))
    cvar = _mean(losses[:n_tail])

    # Max realized drawdown — single worst row (not running peak-to-trough,
    # since each row is a 30-day sample, not a continuous PnL series)
    worst_idx = min(range(len(rels)), key=lambda i: rels[i])
    max_dd_pnl = rels[worst_idx]
    max_dd_date = rows[worst_idx]["fingerprint_date"]

    return {
        "n":                  len(rels),
        "confidence":         confidence,
        "var":                round(var, 5),
        "cvar":               round(cvar, 5),
        "max_drawdown":       round(max_dd_pnl, 5),
        "max_drawdown_date":  max_dd_date,
        "win_rate":           round(sum(1 for x in rels if x > 0) / len(rels), 3),
        "loss_rate":          round(sum(1 for x in rels if x < 0) / len(rels), 3),
    }


# ── 3) position sizing: half-Kelly ───────────────────────────────


def position_sizing(
    strategy_id: str,
    *,
    hold_days: int = 30,
    fraction: float = 0.5,
) -> Dict[str, Any]:
    """Half-Kelly recommended position fraction.

    Kelly formula (binary outcome): f* = (b·p − q) / b
      b = avg_win / avg_loss   (positive — gain-loss ratio)
      p = win rate
      q = 1 − p

    Use ``fraction=0.5`` (half-Kelly) which is the standard practitioner
    safety margin: lower drawdown for ~75% of full Kelly's growth rate.
    """
    from agent.finance.persistence import connect

    with connect() as conn:
        cur = conn.execute(
            "SELECT realized_pnl_pct FROM backtest_results "
            "WHERE strategy_id = ? AND hold_days = ? AND realized_pnl_pct IS NOT NULL",
            (strategy_id, hold_days),
        )
        rels = [float(r["realized_pnl_pct"]) for r in cur.fetchall()]
    if not rels:
        return {"n": 0, "error": "no rows"}

    wins = [r for r in rels if r > 0]
    losses = [r for r in rels if r < 0]
    if not wins or not losses:
        return {
            "n":           len(rels),
            "kelly":       None,
            "half_kelly":  None,
            "error":       "all wins or all losses — Kelly undefined",
        }

    p = len(wins) / len(rels)
    q = 1 - p
    avg_win = _mean(wins)
    avg_loss = abs(_mean(losses))
    if avg_loss == 0:
        return {"n": len(rels), "kelly": None, "error": "zero avg loss"}

    b = avg_win / avg_loss
    kelly = (b * p - q) / b
    # Cap to [0, 1] — negative Kelly = don't trade
    kelly = max(0.0, min(1.0, kelly))
    half_k = kelly * fraction

    return {
        "n":             len(rels),
        "win_rate":      round(p, 3),
        "avg_win":       round(avg_win, 5),
        "avg_loss":      round(-avg_loss, 5),
        "gain_loss_ratio": round(b, 3),
        "kelly":         round(kelly, 4),
        "half_kelly":    round(half_k, 4),
        "interpretation": (
            f"Math suggests sizing ≤{half_k*100:.1f}% of capital. "
            f"Negative or zero Kelly = don't trade this."
        ),
    }


# ── 4) hedge candidates: top negatively-correlated strategies ────


def _get_strategy_history(
    strategy_id: str, hold_days: int,
) -> Dict[str, float]:
    from agent.finance.persistence import connect
    with connect() as conn:
        cur = conn.execute(
            "SELECT fingerprint_date, realized_pnl_pct FROM backtest_results "
            "WHERE strategy_id = ? AND hold_days = ? AND realized_pnl_pct IS NOT NULL",
            (strategy_id, hold_days),
        )
        return {r["fingerprint_date"]: float(r["realized_pnl_pct"])
                for r in cur.fetchall()}


def _correlation(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 5:
        return None
    mx, my = _mean(xs), _mean(ys)
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sxx = sum((xs[i] - mx) ** 2 for i in range(n))
    syy = sum((ys[i] - my) ** 2 for i in range(n))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def hedge_candidates(
    strategy_id: str,
    *,
    hold_days: int = 30,
    top_n: int = 3,
) -> Dict[str, Any]:
    """Find strategies most NEGATIVELY correlated with this one.

    Pairs (target, hedge_candidate) over the same fingerprint dates,
    compute Pearson correlation of realized 30d P&L, return the
    top_n most-negative.

    Markowitz: var(target + h × hedge) is minimized at
        h* = -cov(target, hedge) / var(hedge)
    """
    from agent.finance.persistence import connect

    target = _get_strategy_history(strategy_id, hold_days)
    if not target:
        return {"error": "no target history"}

    with connect() as conn:
        cur = conn.execute(
            "SELECT DISTINCT strategy_id FROM backtest_results "
            "WHERE strategy_id != ? AND hold_days = ?",
            (strategy_id, hold_days),
        )
        candidates = [r["strategy_id"] for r in cur.fetchall()]

    correlations: List[Tuple[str, float, int, float]] = []
    target_var = _std(list(target.values())) ** 2
    for sid in candidates:
        hist = _get_strategy_history(sid, hold_days)
        common_dates = set(target) & set(hist)
        if len(common_dates) < 30:
            continue
        xs = [target[d] for d in common_dates]
        ys = [hist[d]   for d in common_dates]
        rho = _correlation(xs, ys)
        if rho is None:
            continue
        # Optimal hedge ratio: h* = -cov / var(hedge)
        cand_var = _std(ys) ** 2
        cov_xy = rho * math.sqrt(target_var * cand_var)
        h_star = -cov_xy / cand_var if cand_var > 0 else 0.0
        correlations.append((sid, round(rho, 4), len(common_dates), round(h_star, 4)))

    correlations.sort(key=lambda x: x[1])  # ascending — most negative first
    top = correlations[:top_n]
    return {
        "n_candidates": len(correlations),
        "top": [
            {
                "strategy_id":    sid,
                "correlation":    rho,
                "n_overlap":      n_o,
                "size_ratio":     h_star,
            }
            for sid, rho, n_o, h_star in top
        ],
    }


# ── 5) stop-loss: ATR + time stop ────────────────────────────────


def stop_loss(
    strategy_id: str,
    *,
    hold_days: int = 30,
    atr_multiple: float = 1.0,
) -> Dict[str, Any]:
    """ATR-based stop-loss: use this strategy's historical 1σ realized
    return as the stop level (so that ~70% of historical paths stay
    within one stop's distance from entry).

    Time stop = 1.5 × historical mean hold = roughly 45 days for a 30d
    strategy.
    """
    from agent.finance.persistence import connect

    with connect() as conn:
        cur = conn.execute(
            "SELECT realized_pnl_pct FROM backtest_results "
            "WHERE strategy_id = ? AND hold_days = ? AND realized_pnl_pct IS NOT NULL",
            (strategy_id, hold_days),
        )
        rels = [float(r["realized_pnl_pct"]) for r in cur.fetchall()]
    if not rels:
        return {"error": "no rows"}

    sigma = _std(rels)
    suggested_stop = -atr_multiple * sigma  # negative = stop at -X%
    time_stop_days = int(round(hold_days * 1.5))

    # Coverage: % of historical returns that would NOT have hit stop
    n_above = sum(1 for x in rels if x > suggested_stop)
    coverage = n_above / len(rels)

    return {
        "n":                len(rels),
        "sigma":            round(sigma, 5),
        "suggested_stop":   round(suggested_stop, 5),
        "atr_multiple":     atr_multiple,
        "time_stop_days":   time_stop_days,
        "coverage":         round(coverage, 3),
        "interpretation":   (
            f"Stop at {suggested_stop*100:.1f}% historically lets ~{coverage*100:.0f}% "
            f"of paths run to expiration; tightens losses on the other "
            f"{(1-coverage)*100:.0f}% to ≤1σ."
        ),
    }


# ── 6) regime fit: per-bucket ✓/⚠/✗ + nearest analogs ────────────


def regime_fit(
    strategy: Dict[str, Any],
    fingerprint: Dict[str, Any],
) -> Dict[str, Any]:
    """For each of the 5 regime buckets, check whether today's reading
    matches the strategy's preferred direction (from regime_sensitivity
    in quantitative_profile).

    Sensitivity > 0.3  → strategy LIKES high in this bucket
    Sensitivity < -0.3 → strategy LIKES low
    Else neutral.
    """
    profile = strategy.get("quantitative_profile") or {}
    sens = profile.get("regime_sensitivity", {}) or {}
    bucket_keys = [
        ("risk_appetite",     "risk_appetite_score"),
        ("volatility_regime", "volatility_regime_score"),
        ("breadth",           "breadth_score"),
        ("event_density",     "event_density_score"),
        ("flow",              "flow_score"),
    ]
    out_buckets = {}
    n_good = 0
    n_warn = 0
    n_bad  = 0
    for sens_key, fp_key in bucket_keys:
        s = float(sens.get(sens_key, 0.0))
        v = float(fingerprint.get(fp_key) or 50.0)
        # Strategy preference
        if s > 0.3:
            pref = "high"
        elif s < -0.3:
            pref = "low"
        else:
            pref = "neutral"
        # Today's regime
        if v > 66:
            today = "high"
        elif v < 33:
            today = "low"
        else:
            today = "neutral"
        # Fit
        if pref == "neutral":
            fit = "neutral"
        elif pref == today:
            fit = "good"
            n_good += 1
        elif (pref == "high" and today == "low") or (pref == "low" and today == "high"):
            fit = "bad"
            n_bad += 1
        else:
            fit = "warning"
            n_warn += 1
        out_buckets[sens_key] = {
            "strategy_pref": pref,
            "sensitivity":   round(s, 2),
            "today":         today,
            "today_value":   round(v, 1),
            "fit":           fit,
        }

    n_active = n_good + n_warn + n_bad  # exclude neutral
    score = (n_good - n_bad) / max(1, n_active)  # range -1..+1

    return {
        "buckets":      out_buckets,
        "n_good":       n_good,
        "n_warning":    n_warn,
        "n_bad":        n_bad,
        "n_neutral":    5 - n_active,
        "fit_score":    round(score, 3),  # -1 worst, +1 best
        "verdict":      (
            "strong_fit"  if score > 0.4 else
            "ok_fit"      if score > 0   else
            "weak_fit"    if score > -0.4 else
            "bad_fit"
        ),
    }


# ── full dashboard composer ──────────────────────────────────────


# ── data quality classification ──────────────────────────────────
#
# A strategy's ``realized_pnl_pct`` in backtest_results is REAL iff the
# strategy is "buy and hold the anchor asset" — the underlying's
# forward return IS the strategy's return.  For options / momentum /
# hedges / event-driven strategies, the proxy formula doesn't capture
# the actual P&L mechanics; those numbers must NOT be used for
# real-money decisions.  Show only the regime fit (which is rule-based
# and real) for those, plus a "paper trade first" banner.

REAL_PAYOFF_CLASSES = {
    # passive buy-and-hold
    "dca", "buy_and_hold",
    "lazy_portfolio_three_fund", "target_date_fund", "permanent_portfolio",
    "dollar_cost_averaging_index", "dividend_growth_etf",
    # factor ETFs that you just hold (no active trading required)
    "low_volatility_factor", "value_factor",
}


def is_real_data(strategy: Dict[str, Any]) -> bool:
    """True iff backtest_results.realized_pnl_pct accurately captures
    real-money outcomes for this strategy.  False for options / active
    trading / hedges where proxy P&L is a stand-in."""
    profile = strategy.get("quantitative_profile") or {}
    return profile.get("payoff_class", "") in REAL_PAYOFF_CLASSES


def risk_dashboard(
    strategy: Dict[str, Any],
    fingerprint: Dict[str, Any],
    *,
    hold_days: int = 30,
) -> Dict[str, Any]:
    """Compose all 6 dimensions into one dashboard payload.

    For REAL-data strategies, returns the full math-backed view.
    For PROXY strategies, returns only the regime fit (which IS real)
    and a banner stating that VaR/Kelly/etc. cannot be trusted until
    paper trading produces real realized P&L.
    """
    sid = strategy["id"]
    real = is_real_data(strategy)
    out: Dict[str, Any] = {
        "strategy_id":      sid,
        "name_zh":          strategy.get("name_zh"),
        "name_en":          strategy.get("name_en"),
        "horizon":          strategy.get("horizon"),
        "asset_class":      strategy.get("asset_class"),
        "hold_days":        hold_days,
        "fingerprint_date": fingerprint.get("fingerprint_date"),
        "data_quality":     "real" if real else "proxy_only",
    }

    if not real:
        # PROXY: Skip everything that depends on realized_pnl_pct.
        # Only regime_fit is rule-based and trustworthy.
        out["return_distribution"] = {"skipped": "proxy", "n": 0}
        out["tail_risk"]        = {"skipped": "proxy", "n": 0}
        out["position_sizing"]  = {"skipped": "proxy", "n": 0}
        out["hedge_candidates"] = {"skipped": "proxy"}
        out["stop_loss"]        = {"skipped": "proxy"}
        out["regime_fit"]       = regime_fit(strategy, fingerprint)
        out["recommendation"]   = {
            "color":           "gray",
            "reasons_for":     [],
            "reasons_against": [],
            "interpretation":  (
                "PROXY strategy (options / active trading / hedge). "
                "Backtest realized_pnl_pct is a simplified estimate that "
                "doesn't capture real options pricing, slippage, or "
                "execution.  Paper trade first to populate real numbers, "
                "then come back."
            ),
            "paper_trade_required": True,
        }
        return out

    # REAL data path — everything below is from anchor's actual forward returns.
    out["return_distribution"] = return_distribution(
        sid, fingerprint, k=30, hold_days=hold_days,
    )
    out["tail_risk"]        = tail_risk(sid, hold_days=hold_days)
    out["position_sizing"]  = position_sizing(sid, hold_days=hold_days)
    out["hedge_candidates"] = hedge_candidates(sid, hold_days=hold_days, top_n=3)
    out["stop_loss"]        = stop_loss(sid, hold_days=hold_days)
    out["regime_fit"]       = regime_fit(strategy, fingerprint)

    # Phase K1: walk-forward + Deflated Sharpe Ratio gate.
    # This is the ONLY "is this strategy real?" check that survives
    # multiple-testing correction. Without it, the metrics above are
    # 20-40% inflated by selection bias (PBO > 50% with N=36 trials).
    try:
        from agent.finance.regime.walk_forward import walk_forward_sharpe
        out["walk_forward"] = walk_forward_sharpe(sid, hold_days=hold_days)
    except Exception as exc:
        logger.warning("walk_forward for %s failed: %s", sid, exc)
        out["walk_forward"] = {"error": str(exc)}

    # Composite "go/caution/avoid" recommendation — based on multiple
    # dimensions, NOT a single fit score.
    rec_reasons_for: List[str] = []
    rec_reasons_against: List[str] = []

    rd = out["return_distribution"]
    tr = out["tail_risk"]
    ps = out["position_sizing"]
    rf = out["regime_fit"]

    if rd.get("median") and rd["median"] > 0.005:
        rec_reasons_for.append(f"k-NN median {rd['median']*100:+.1f}% (positive)")
    elif rd.get("median") and rd["median"] < -0.005:
        rec_reasons_against.append(f"k-NN median {rd['median']*100:+.1f}% (negative)")

    if tr.get("cvar") and tr["cvar"] < -0.05:
        rec_reasons_against.append(f"CVaR(95) = {tr['cvar']*100:.1f}% (heavy tail)")

    if ps.get("half_kelly") and ps["half_kelly"] > 0.05:
        rec_reasons_for.append(f"half-Kelly = {ps['half_kelly']*100:.1f}% (positive expectation)")
    elif ps.get("half_kelly") == 0:
        rec_reasons_against.append("Kelly = 0 (don't trade)")

    if rf.get("verdict") == "strong_fit":
        rec_reasons_for.append(f"regime fit_score = {rf['fit_score']:+.2f} (strong)")
    elif rf.get("verdict") == "bad_fit":
        rec_reasons_against.append(f"regime fit_score = {rf['fit_score']:+.2f} (against)")

    # Walk-forward DSR is the gate: <0.50 means worse than random null
    wf = out.get("walk_forward") or {}
    dsr_prob = (wf.get("deflated_sharpe") or {}).get("dsr_prob")
    if dsr_prob is not None:
        if dsr_prob > 0.95:
            rec_reasons_for.append(
                f"DSR = {dsr_prob:.2f} (survives multiple-testing N={wf['deflated_sharpe']['n_trials']})"
            )
        elif dsr_prob < 0.50:
            rec_reasons_against.append(
                f"DSR = {dsr_prob:.2f} (worse than random null — likely noise)"
            )

    n_for = len(rec_reasons_for)
    n_against = len(rec_reasons_against)
    # DSR can override: <0.50 → red regardless
    if dsr_prob is not None and dsr_prob < 0.50:
        color = "red"
    elif n_for > n_against and n_against == 0:
        color = "green"
    elif n_for > n_against:
        color = "amber"
    elif n_against > n_for:
        color = "red"
    else:
        color = "amber"

    out["recommendation"] = {
        "color":           color,
        "reasons_for":     rec_reasons_for,
        "reasons_against": rec_reasons_against,
        "interpretation": (
            "GREEN = math+regime align positively, no major risk flag. "
            "AMBER = mixed signals, OK for paper trade. "
            "RED = math says avoid or hedge."
        ),
    }
    return out
