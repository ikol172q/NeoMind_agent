"""Walk-forward validation + Deflated Sharpe Ratio.

Implements Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio:
correcting for selection bias, backtest overfitting, and non-normality".
Journal of Portfolio Management, 40(5), 94–107.
https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf

Why this is the final gate before trusting any backtest number:

When you backtest N candidate strategies, the BEST observed Sharpe is
biased upward by approximately ``sqrt(2 ln N)`` standard errors under
the null hypothesis of zero true skill. For N = 36 (our catalog
size), that's ~2.68 σ — meaning even pure-noise strategies can show
"impressive" Sharpe ratios. DSR computes ``P(true SR > 0 | observed
SR, N trials, sample size, skewness, kurtosis)``.

Practical interpretation:
    DSR > 0.95  →  strategy survives multiple-testing correction
    DSR ≈ 0.50  →  observed SR is roughly what you'd expect by chance
    DSR < 0.50  →  observed SR is WORSE than the random null

Walk-forward: partition history by date, train on past, test on next
slice. Reports IS/OOS Sharpe gap. A gap > 1.5x indicates overfitting.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── normal CDF and its inverse (Beasley-Springer-Moro algorithm) ──


def _normal_cdf(x: float) -> float:
    """P(Z ≤ x) for standard normal Z."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_inv_cdf(p: float) -> float:
    """Φ⁻¹(p) — Beasley-Springer-Moro rational approximation.
    Numerically stable for p ∈ (1e-15, 1 - 1e-15)."""
    if not (0 < p < 1):
        raise ValueError(f"p must be in (0,1), got {p}")
    a = [-3.969683028665376e+01,  2.209460984245205e+02,
         -2.759285104469687e+02,  1.383577518672690e+02,
         -3.066479806614716e+01,  2.506628277459239e+00]
    b = [-5.447609879822406e+01,  1.615858368580409e+02,
         -1.556989798598866e+02,  6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)


# ── Sharpe + skewness/kurtosis ────────────────────────────────────


def _moments(xs: List[float]) -> Dict[str, float]:
    """Sample mean, std, skewness (g1), excess kurtosis (g2-3)."""
    n = len(xs)
    if n < 2:
        return {"n": n, "mean": 0.0, "std": 0.0, "skew": 0.0, "kurt": 3.0}
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return {"n": n, "mean": mean, "std": 0.0, "skew": 0.0, "kurt": 3.0}
    skew = sum(((x - mean) / std) ** 3 for x in xs) / n
    # Pearson kurtosis (NOT excess) — matches Bailey-LdP eq.3 convention
    kurt = sum(((x - mean) / std) ** 4 for x in xs) / n
    return {"n": n, "mean": mean, "std": std, "skew": skew, "kurt": kurt}


def _annualize(sr_per_period: float, periods_per_year: float) -> float:
    """SR_annual = SR_per_period × √(periods_per_year)."""
    return sr_per_period * math.sqrt(periods_per_year)


# ── Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014) ─────────


def deflated_sharpe(
    observed_sr: float,
    *,
    n_trials: int,
    n_obs: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> Dict[str, Any]:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio.

    Eq. 7 in the paper:
        SR_max_expected = √V[SR] · ((1−γ)·Φ⁻¹(1−1/N)
                                     + γ·Φ⁻¹(1−1/(N·e)))
    where γ ≈ 0.5772 (Euler-Mascheroni).

    Eq. 4 (with non-normality adjustment):
        V[SR] = (1 − γ₃·SR + (γ₄−1)/4·SR²) / (T−1)
    where γ₃ = skewness, γ₄ = kurtosis (Pearson, not excess).

    DSR is then:  P(true SR > 0) = Φ((SR* − SR_max_expected) / σ_SR)

    Args:
        observed_sr: per-period (NOT annualized) Sharpe — the formula
            applies in either, but inputs must be consistent.
        n_trials: number of strategies you SELECTED FROM (catalog size).
        n_obs: number of observations (rows in the test set).
        skewness, kurtosis: empirical higher moments. Pass kurtosis = 3
            if you want the normal-returns simplification.
    """
    EULER = 0.5772156649
    if n_trials < 2:
        n_trials = 2

    # SR estimator variance under non-normality (Mertens 2002)
    sr_var_per_period = (
        1.0 - skewness * observed_sr +
        (kurtosis - 1.0) / 4.0 * observed_sr ** 2
    )
    sr_var_per_period = max(sr_var_per_period, 1e-9)
    # Per-period; for "T sample periods" the SE is √(V/(T-1))
    sr_se = math.sqrt(sr_var_per_period / max(1, n_obs - 1))

    # Expected maximum Sharpe under null (no skill, N tries)
    p1 = 1 - 1.0 / n_trials
    p2 = 1 - 1.0 / (n_trials * math.e)
    sr_max_expected = sr_se * (
        (1 - EULER) * _normal_inv_cdf(p1) +
        EULER       * _normal_inv_cdf(p2)
    )

    # Deflated Sharpe: probability that the observed beats the null max
    z = (observed_sr - sr_max_expected) / sr_se if sr_se > 0 else 0.0
    dsr_prob = _normal_cdf(z)

    return {
        "observed_sr":     round(observed_sr, 4),
        "n_trials":        int(n_trials),
        "n_obs":           int(n_obs),
        "skewness":        round(skewness, 4),
        "kurtosis":        round(kurtosis, 4),
        "sr_max_expected": round(sr_max_expected, 4),
        "sr_se":           round(sr_se, 4),
        "z_score":         round(z, 4),
        "dsr_prob":        round(dsr_prob, 4),
        "interpretation":  (
            "DSR > 0.95: survives multiple-testing — high confidence true skill. "
            "DSR ≈ 0.50: observed SR is what noise would produce. "
            "DSR < 0.50: observed SR is below the random null."
        ),
    }


# ── walk-forward IS / OOS test ────────────────────────────────────


def walk_forward_sharpe(
    strategy_id: str,
    *,
    hold_days: int = 30,
    is_pct: float = 0.8,
    n_trials_for_dsr: int = 36,
) -> Dict[str, Any]:
    """Time-ordered IS/OOS split + DSR for one strategy.

    Reads ``backtest_results``, sorts by ``fingerprint_date``, splits
    into in-sample (first ``is_pct``) and out-of-sample (rest),
    computes annualized Sharpe on each, and runs DSR on the OOS leg.

    Args:
        is_pct: fraction of rows used as in-sample (default 80%).
        n_trials_for_dsr: number of strategies in the universe — DSR
            deflates by ``√(2 ln N)`` to account for cherry-picking.
    """
    from agent.finance.persistence import connect

    with connect() as conn:
        cur = conn.execute(
            "SELECT fingerprint_date, realized_pnl_pct "
            "FROM backtest_results "
            "WHERE strategy_id = ? AND hold_days = ? "
            "  AND realized_pnl_pct IS NOT NULL "
            "ORDER BY fingerprint_date",
            (strategy_id, hold_days),
        )
        rows = [(r["fingerprint_date"], float(r["realized_pnl_pct"]))
                for r in cur.fetchall()]

    n = len(rows)
    if n < 30:
        return {"strategy_id": strategy_id, "n": n,
                "error": "insufficient data (<30 rows)"}

    is_end = max(10, int(n * is_pct))
    is_rels  = [r[1] for r in rows[:is_end]]
    oos_rels = [r[1] for r in rows[is_end:]]

    if len(oos_rels) < 5:
        return {"strategy_id": strategy_id, "n": n,
                "is_n": is_end, "oos_n": len(oos_rels),
                "error": "OOS too small (<5)"}

    is_m  = _moments(is_rels)
    oos_m = _moments(oos_rels)

    # Sharpe per-period (per hold_days), then annualize × √(252 / hold_days)
    periods_per_year = 252.0 / hold_days
    is_sr_per   = (is_m["mean"]  / is_m["std"])  if is_m["std"]  > 0 else 0.0
    oos_sr_per  = (oos_m["mean"] / oos_m["std"]) if oos_m["std"] > 0 else 0.0
    is_sr_ann   = _annualize(is_sr_per,  periods_per_year)
    oos_sr_ann  = _annualize(oos_sr_per, periods_per_year)
    gap         = is_sr_ann - oos_sr_ann
    overfitting_ratio = (is_sr_ann / oos_sr_ann) if oos_sr_ann > 0 else None

    # DSR uses PER-PERIOD SR (since variance formula assumes that)
    dsr = deflated_sharpe(
        oos_sr_per,
        n_trials=n_trials_for_dsr,
        n_obs=oos_m["n"],
        skewness=oos_m["skew"],
        kurtosis=oos_m["kurt"],
    )

    return {
        "strategy_id":     strategy_id,
        "n_total":         n,
        "is_n":            is_end,
        "oos_n":           n - is_end,
        "is_sharpe_ann":   round(is_sr_ann,  4),
        "oos_sharpe_ann":  round(oos_sr_ann, 4),
        "is_oos_gap":      round(gap, 4),
        "overfitting_ratio":   round(overfitting_ratio, 4) if overfitting_ratio is not None else None,
        "deflated_sharpe": dsr,
        "verdict":         _verdict(oos_sr_ann, dsr["dsr_prob"], gap),
    }


def _verdict(oos_sr: float, dsr_prob: float, gap: float) -> str:
    if dsr_prob > 0.95 and oos_sr > 0.5 and gap < 1.0:
        return "ship"
    if dsr_prob > 0.80 and oos_sr > 0:
        return "promising"
    if dsr_prob < 0.50:
        return "noise"
    if gap > 2.0:
        return "overfit"
    return "uncertain"


def walk_forward_all(
    *,
    hold_days: int = 30,
    is_pct: float = 0.8,
) -> Dict[str, Any]:
    """Run walk-forward + DSR across every strategy in backtest_results.

    Returns survivor count at common DSR thresholds — the headline
    number for "how many strategies are real after multiple-testing
    correction?".
    """
    from agent.finance.persistence import connect

    with connect() as conn:
        cur = conn.execute(
            "SELECT DISTINCT strategy_id FROM backtest_results WHERE hold_days = ?",
            (hold_days,),
        )
        sids = [r["strategy_id"] for r in cur.fetchall()]
    n_trials = len(sids)

    results: List[Dict[str, Any]] = []
    for sid in sids:
        r = walk_forward_sharpe(
            sid, hold_days=hold_days, is_pct=is_pct,
            n_trials_for_dsr=n_trials,
        )
        if "error" in r:
            continue
        results.append(r)

    # Sort by DSR probability descending
    results.sort(key=lambda r: -((r.get("deflated_sharpe") or {}).get("dsr_prob") or 0))

    survivors_95 = [r for r in results
                    if (r["deflated_sharpe"]["dsr_prob"] or 0) > 0.95]
    survivors_80 = [r for r in results
                    if (r["deflated_sharpe"]["dsr_prob"] or 0) > 0.80]
    ships = [r for r in results if r.get("verdict") == "ship"]
    overfits = [r for r in results if r.get("verdict") == "overfit"]
    noise = [r for r in results if r.get("verdict") == "noise"]

    return {
        "n_strategies":            len(results),
        "n_trials":                n_trials,
        "is_pct":                  is_pct,
        "hold_days":               hold_days,
        "n_survivors_dsr_95":      len(survivors_95),
        "n_survivors_dsr_80":      len(survivors_80),
        "n_ship":                  len(ships),
        "n_overfit":               len(overfits),
        "n_noise":                 len(noise),
        "results":                 results,
    }
