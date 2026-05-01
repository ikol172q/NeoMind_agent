"""Backtest harness for the regime pipeline.

For every historical fingerprint_date, score every strategy with the
model (no k-NN prior — to avoid circular reference) and compute a
forward-return proxy as the "realized" P&L over a hold window.

Stores results in the ``backtest_results`` SQLite table so the recall
UI can show predicted-vs-realized calibration without recomputing.

IMPORTANT — proxy P&L is NOT real options-chain P&L.  We don't have
historical option prices in raw_market_data.  We use the strategy's
``payoff_class`` to map the underlying's forward return to a rough
realized P&L (e.g. covered_call caps upside at +2% but keeps premium,
long_call demands a 4%+ move to break even, mean_reversion bets
against the move).  Treat as DIRECTIONAL signal — does the system's
score on each day correlate with what the underlying actually did?

When 100% accurate options data eventually flows in, we can plug in
the real payoff and the rest of this harness keeps working.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── anchor symbol pick ────────────────────────────────────────────


def _anchor_symbol(strategy: Dict[str, Any]) -> str:
    """Pick the underlying symbol to evaluate forward return against."""
    sid = strategy.get("id", "")
    asset = (strategy.get("asset_class") or "").lower()

    # Strategy-specific overrides (when the name implies a ticker)
    overrides = {
        "btc_dca":                 "BTC-USD",
        "eth_dca":                 "ETH-USD",
        "mchi_long_hold":          "MCHI",
        "kweb_momentum":           "KWEB",
        "fxi_china_vol":           "FXI",
        "fxi_options_china_vol":   "FXI",
        "qqq_iron_condor":         "QQQ",
        "spy_iron_condor":         "SPY",
        "spy_long_vol":            "SPY",
        "intl_developed_etf":      "VEA",
        "small_cap_value_etf":     "AVUV",
        "low_volatility_etf":      "USMV",
        "value_factor_etf":        "VLUE",
        "quality_factor_etf":      "QUAL",
        "dividend_growth_etf":     "DGRO",
        "total_market_index_dca":  "VTI",
    }
    if sid in overrides:
        return overrides[sid]

    if asset == "crypto":
        return "BTC-USD"
    # default everything else to SPY (a good majority anchor)
    return "SPY"


# ── proxy P&L per payoff_class ───────────────────────────────────


def _proxy_pnl(
    payoff_class: str,
    forward_ret: float,
    hold_days: int,
) -> float:
    """Map underlying forward return → realized P&L fraction for the
    given payoff_class.  Conservative, deliberately rough — the goal
    is to detect GROSS mis-fit (system loves X when X loses), not
    fine alpha.

    All returns are fractions (0.05 = +5%).
    """
    fr = forward_ret
    pc = payoff_class or "unknown"

    # Long-only (DCA / buy-and-hold)
    if pc in ("dca", "buy_and_hold", "lazy_portfolio_three_fund",
              "target_date_fund", "permanent_portfolio",
              "dollar_cost_averaging_index", "dividend_growth_etf"):
        return fr  # roughly 1:1 with anchor

    # Covered-call / wheel / cash-secured put — short-vol, capped upside
    if pc in ("covered_call", "covered_call_etf", "covered_strangle",
              "cash_secured_put", "wheel"):
        # Simplification: cap upside at +2%, keep ~1.2% / month premium,
        # full participation on downside (covered call doesn't hedge much).
        capped_up = min(fr, 0.02)
        return capped_up + 0.012 * (hold_days / 30.0)

    # Defined-risk credit spreads (iron condor, butterfly, vertical spreads)
    if pc in ("vertical_bull_put_spread", "vertical_bear_call_spread",
              "iron_condor", "iron_condor_index", "iron_butterfly",
              "credit_spread"):
        # Win if range-bound (|fr| < 3%), capped loss otherwise.
        if abs(fr) < 0.03:
            return 0.018 * (hold_days / 30.0)   # premium retained
        return -0.04                             # max loss approx

    # Long-vol / long-options (need a big move)
    if pc in ("long_call", "long_put", "long_straddle", "long_strangle"):
        premium = 0.05
        breakeven = 0.04
        if pc == "long_call":
            payout = max(0.0, fr - breakeven)
        elif pc == "long_put":
            payout = max(0.0, -fr - breakeven)
        else:  # long_straddle / strangle
            payout = max(0.0, abs(fr) - 0.06)
        return payout - premium

    # Calendar / diagonal spreads (short near, long far — benefits from theta)
    if pc in ("calendar_spread", "diagonal_spread",
              "vertical_bull_call_spread", "vertical_bear_put_spread",
              "debit_spread"):
        # Best when underlying lands near the strike.  Simplification:
        # win modestly if |fr| < 4%, lose modestly otherwise.
        if abs(fr) < 0.04:
            return 0.012 * (hold_days / 30.0)
        return -0.025

    # Momentum / trend-following — leveraged to direction
    if pc in ("momentum_breakout", "trend_following",
              "swing_breakout", "fifty_two_week_high_breakout_swing",
              "cross_sectional_momentum", "sector_rotation",
              "sector_rotation_business_cycle"):
        return 1.3 * fr - 0.005   # 30% extra leverage − costs

    # Mean reversion / hedges — bet AGAINST the move
    if pc in ("mean_reversion", "mean_reversion_oversold_bounce_rsi2",
              "low_volatility_factor", "value_factor"):
        return -0.6 * fr - 0.004

    # Tail / bear hedges
    if pc in ("bear_market_hedge", "tail_risk_hedge"):
        return -1.0 * fr - 0.008  # convex on downside, costs premium otherwise

    # Bond ladder — basically yield + small duration sensitivity
    if pc in ("bond_ladder", "treasury_ladder"):
        return 0.04 * (hold_days / 365.0) - 0.1 * fr   # mild inverse to equity

    # Event-specific (FOMC fade, four witches) — closer to mean reversion
    if pc in ("event_fade", "event_drift"):
        return -0.4 * fr - 0.003

    # Unknown → treat as long-only proxy with halved sensitivity
    return 0.5 * fr


# ── forward-return lookup from raw_market_data ───────────────────


def _forward_return(
    symbol: str,
    start_date: str,
    hold_days: int,
) -> Optional[float]:
    """Forward return from start_date close → start_date + hold_days
    close, using ``raw_market_data`` (no live yfinance call).

    Returns None if either bar is missing.  Searches ±5 calendar days
    to handle weekends / holidays around the boundaries.
    """
    from agent.finance.persistence import connect as _connect

    sql = """
        SELECT trade_date, close
        FROM raw_market_data
        WHERE symbol = ?
          AND trade_date >= ?
          AND trade_date <= ?
        ORDER BY trade_date
    """
    from datetime import date as _d, timedelta
    sd = _d.fromisoformat(start_date)
    end = (sd + timedelta(days=hold_days + 5)).isoformat()
    early = (sd - timedelta(days=5)).isoformat()
    with _connect() as conn:
        rows = conn.execute(sql, (symbol, early, end)).fetchall()
    if len(rows) < 2:
        return None

    # find close at-or-after start_date  (entry)
    entry = None
    for r in rows:
        if r["trade_date"] >= start_date:
            entry = r
            break
    if entry is None:
        return None

    # find close at-or-after start_date + hold_days  (exit)
    target = (sd + timedelta(days=hold_days)).isoformat()
    exit_row = None
    for r in rows:
        if r["trade_date"] >= target:
            exit_row = r
            break
    if exit_row is None:
        # take last available (still within search window)
        exit_row = rows[-1]
    if entry["trade_date"] == exit_row["trade_date"]:
        return None

    e0 = float(entry["close"])
    e1 = float(exit_row["close"])
    if e0 <= 0:
        return None
    return e1 / e0 - 1.0


# ── public: backtest runner ───────────────────────────────────────


def run_backtest(
    since: Optional[str] = None,
    until: Optional[str] = None,
    hold_days: int       = 30,
    top_n: int           = 36,                # full universe by default
    skip_existing: bool  = True,
) -> Dict[str, Any]:
    """For every fingerprint_date in [since, until], score all strategies
    (model only — no k-NN prior to avoid circular ref) and compute the
    realized 30d P&L for each.

    Writes to backtest_results.  Returns a summary dict.
    """
    from agent.finance.regime.store import list_fingerprints
    from agent.finance.persistence import connect as _connect
    from agent.finance.regime.scorer import score_all_strategies

    # 1) pull eligible fingerprint dates
    fps = list_fingerprints(limit=2000, since=since)
    fps = [f for f in fps if f.get("fingerprint_date")]
    if until:
        fps = [f for f in fps if f["fingerprint_date"] <= until]
    fps.sort(key=lambda x: x["fingerprint_date"])

    # 2) which (date, strategy) pairs already have a result?
    existing = set()
    if skip_existing:
        with _connect() as conn:
            for r in conn.execute(
                "SELECT fingerprint_date, strategy_id FROM backtest_results "
                "WHERE hold_days = ?", (hold_days,)
            ):
                existing.add((r["fingerprint_date"], r["strategy_id"]))

    n_dates = len(fps)
    n_written = 0
    n_skipped = 0
    n_no_forward = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    import time as _time
    t_start = _time.monotonic()
    logger.info(
        "[BACKTEST] starting %d dates · hold_days=%d · skip_existing=%s",
        n_dates, hold_days, skip_existing,
    )

    # 3) iterate
    for i, fp in enumerate(fps):
        date = fp["fingerprint_date"]
        try:
            scored = score_all_strategies(
                fp,
                apply_knn_prior=False,         # critical: avoid circularity
                include_unverified=True,
            )
        except Exception as exc:
            logger.warning("score failed for %s: %s", date, exc)
            continue

        scored = scored[:top_n]
        from agent.finance.lattice.strategy_matcher import _load_strategies
        catalog = {s["id"]: s for s in _load_strategies(include_unverified=True)}

        rows: List[tuple] = []
        for rank, entry in enumerate(scored, start=1):
            sid = entry["strategy_id"]
            if (date, sid) in existing:
                n_skipped += 1
                continue

            strategy = catalog.get(sid, {})
            anchor = _anchor_symbol(strategy)
            ufr = _forward_return(anchor, date, hold_days)
            if ufr is None:
                # not enough forward bars — skip this row but keep others
                n_no_forward += 1
                continue

            profile = strategy.get("quantitative_profile") or {}
            pc = profile.get("payoff_class", "unknown")
            realized = _proxy_pnl(pc, ufr, hold_days)
            notes = {
                "anchor":       anchor,
                "payoff_class": pc,
                "underlying_return": round(ufr, 4),
                "predicted":    entry["score"],
                "asset_class":  strategy.get("asset_class"),
            }
            rows.append((
                str(uuid.uuid4()),
                date, sid,
                float(entry["score"]),
                int(rank),
                int(hold_days),
                round(realized, 5),
                round(ufr, 5),
                "proxy_v1",
                json.dumps(notes, default=str),
                now,
            ))

        if rows:
            with _connect() as conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO backtest_results
                          (result_id, fingerprint_date, strategy_id,
                           predicted_score, rank, hold_days,
                           realized_pnl_pct, underlying_return,
                           method, notes_json, computed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            n_written += len(rows)

        if (i + 1) % 25 == 0 or i == n_dates - 1:
            elapsed = _time.monotonic() - t_start
            pct = 100.0 * (i + 1) / n_dates
            eta_total = elapsed * n_dates / max(1, i + 1)
            eta_left = max(0, eta_total - elapsed)
            logger.info(
                "[BACKTEST] %5.1f%% · day %d/%d (date=%s) · written=%d skipped=%d no_forward=%d · elapsed=%.0fs eta=%.0fs",
                pct, i + 1, n_dates, date,
                n_written, n_skipped, n_no_forward, elapsed, eta_left,
            )

    return {
        "n_dates_scanned":     n_dates,
        "n_rows_written":      n_written,
        "n_rows_skipped":      n_skipped,
        "n_no_forward_data":   n_no_forward,
        "hold_days":           hold_days,
    }


# ── public: recall / calibration summary ──────────────────────────


def recall_summary(
    *, hold_days: int = 30,
    strategy_id: Optional[str] = None,
    score_cutoff: float = 4.0,
) -> Dict[str, Any]:
    """Aggregate backtest_results into per-strategy calibration stats.

    Returns:
      {
        "strategies": [
          {
            "strategy_id": "covered_call_etf",
            "n_runs": 1234,
            "mean_predicted": 4.21,
            "mean_realized":  0.0142,
            "median_realized": 0.011,
            "hit_rate": 0.61,        // fraction predicted>=cutoff with realized>0
            "p_calibration_high": 0.013,  // mean realized when predicted >= cutoff
            "p_calibration_low":  -0.002, // mean realized when predicted <  cutoff
            "delta_high_low":     0.015,  // discrimination
            "spearman_corr":      0.18,
          },
          ...
        ],
        "n_total_rows": ...,
        "score_cutoff": 4.0,
      }
    """
    from agent.finance.persistence import connect as _connect

    sql = "SELECT strategy_id, predicted_score, realized_pnl_pct " \
          "FROM backtest_results WHERE hold_days = ?"
    args: List[Any] = [hold_days]
    if strategy_id:
        sql += " AND strategy_id = ?"
        args.append(strategy_id)

    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()

    by_strategy: Dict[str, List[tuple]] = {}
    for r in rows:
        by_strategy.setdefault(r["strategy_id"], []).append(
            (float(r["predicted_score"]),
             float(r["realized_pnl_pct"]) if r["realized_pnl_pct"] is not None else None)
        )

    out = []
    for sid, vals in by_strategy.items():
        clean = [(p, r) for p, r in vals if r is not None]
        n = len(clean)
        if n == 0:
            continue
        preds = [p for p, _ in clean]
        rels  = [r for _, r in clean]
        mean_pred = sum(preds) / n
        mean_real = sum(rels) / n
        sorted_rel = sorted(rels)
        median_real = sorted_rel[n // 2]

        high = [r for p, r in clean if p >= score_cutoff]
        low  = [r for p, r in clean if p <  score_cutoff]
        hit_rate = (sum(1 for r in high if r > 0) / max(1, len(high))) if high else None
        cal_h = (sum(high) / len(high)) if high else None
        cal_l = (sum(low)  / len(low))  if low  else None
        delta = (cal_h - cal_l) if (cal_h is not None and cal_l is not None) else None

        # Spearman: rank correlation
        rho = _spearman(preds, rels)

        out.append({
            "strategy_id":       sid,
            "n_runs":            n,
            "mean_predicted":    round(mean_pred, 3),
            "mean_realized":     round(mean_real, 5),
            "median_realized":   round(median_real, 5),
            "hit_rate":          round(hit_rate, 3) if hit_rate is not None else None,
            "p_calibration_high": round(cal_h, 5) if cal_h is not None else None,
            "p_calibration_low":  round(cal_l, 5) if cal_l is not None else None,
            "delta_high_low":     round(delta, 5) if delta is not None else None,
            "spearman_corr":      round(rho, 4) if rho is not None else None,
            "n_high":             len(high),
            "n_low":              len(low),
        })

    out.sort(key=lambda x: -(x.get("delta_high_low") or -1))
    return {
        "strategies":     out,
        "n_total_rows":   len(rows),
        "score_cutoff":   score_cutoff,
        "hold_days":      hold_days,
    }


# ── Phase F: v2 vs v3 head-to-head comparison ─────────────────────


def compare_v2_v3(
    *, hold_days: int = 30,
) -> Dict[str, Any]:
    """Apply BOTH the legacy v2 closed-form scorer AND the trained v3
    PDS to the same held-out backtest_results test fold.  Reports IC,
    Δ h-l, decile monotonicity for each.

    Side-by-side comparison so we can decide whether to ship v3.
    """
    from agent.finance.persistence import connect
    from agent.finance.lattice.strategy_matcher import _load_strategies
    from agent.finance.regime.scorer    import score_strategy as v2_score
    from agent.finance.regime.scorer_v3 import score_pds

    catalog = {s["id"]: s for s in _load_strategies(include_unverified=True)}

    with connect() as conn:
        cur = conn.execute(
            """SELECT b.fingerprint_date, b.strategy_id,
                      b.realized_pnl_pct, b.predicted_score,
                      f.risk_appetite_score, f.volatility_regime_score,
                      f.breadth_score, f.event_density_score, f.flow_score
                 FROM backtest_results b
                 JOIN regime_fingerprints f
                   ON b.fingerprint_date = f.fingerprint_date
                 WHERE b.hold_days = ?
                   AND b.realized_pnl_pct IS NOT NULL""",
            (hold_days,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return {"error": "no rows"}

    rows.sort(key=lambda r: r["fingerprint_date"])
    cut = int(len(rows) * 0.8)
    test_rows = rows[cut:]
    if len(test_rows) < 100:
        test_rows = rows  # use all if too small

    # Build (predicted_v2, predicted_v3, realized) triples
    triples: List[Tuple[float, float, float]] = []
    n_v3_fallback = 0
    for r in test_rows:
        strat = catalog.get(r["strategy_id"])
        if not strat:
            continue
        fp = {
            "fingerprint_date":            r["fingerprint_date"],
            "risk_appetite_score":         r["risk_appetite_score"],
            "volatility_regime_score":     r["volatility_regime_score"],
            "breadth_score":               r["breadth_score"],
            "event_density_score":         r["event_density_score"],
            "flow_score":                  r["flow_score"],
        }
        v2 = v2_score(strat, fp)["score"]
        v3 = score_pds(fp, strat, skip_confidence=True)
        if v3.get("scorer") == "v2_fallback":
            n_v3_fallback += 1
        triples.append((float(v2), float(v3["score"]), float(r["realized_pnl_pct"])))

    if not triples:
        return {"error": "no triples after enrichment"}

    v2s = [t[0] for t in triples]
    v3s = [t[1] for t in triples]
    rs  = [t[2] for t in triples]

    return {
        "n_test":           len(triples),
        "n_v3_fallback":    n_v3_fallback,
        "v2": _model_summary(v2s, rs),
        "v3": _model_summary(v3s, rs),
    }


def _model_summary(preds: List[float], rels: List[float]) -> Dict[str, Any]:
    n = len(preds)
    if n < 10:
        return {"n": n, "skip": "too_few"}

    rho = _spearman(preds, rels)
    median_pred = sorted(preds)[n // 2]
    high = [r for p, r in zip(preds, rels) if p >= median_pred]
    low  = [r for p, r in zip(preds, rels) if p <  median_pred]
    delta = (sum(high) / len(high) - sum(low) / len(low)) if (high and low) else None

    # Decile rank-correlation: are deciles monotonic in mean realized?
    sorted_pairs = sorted(zip(preds, rels), key=lambda p: p[0])
    deciles = []
    for d in range(10):
        lo = int(n *  d      / 10)
        hi = int(n * (d + 1) / 10)
        chunk = sorted_pairs[lo:hi]
        if chunk:
            deciles.append(sum(c[1] for c in chunk) / len(chunk))
    if len(deciles) >= 5:
        decile_rho = _spearman(list(range(len(deciles))), deciles)
    else:
        decile_rho = None

    return {
        "n":                  n,
        "ic_spearman":        rho,
        "delta_high_low":     round(delta, 5) if delta is not None else None,
        "decile_means":       [round(d, 5) for d in deciles],
        "decile_rho_to_rank": decile_rho,
    }


# ── Phase D: comprehensive validation harness ─────────────────────


def validation_report(
    *, hold_days: int = 30,
    n_permutations: int = 200,
    seed: int = 42,
) -> Dict[str, Any]:
    """The full algorithmic-correctness battery.

    Returns a dict with:

    1. ``cutoff_sweep`` — Δ h-l & hit rate at predicted cutoffs
       [2.0, 2.5, 3.0, 3.5, 4.0, 4.5].  Helps tune the threshold.
    2. ``information_coefficient`` — for each fingerprint_date, the
       Spearman rank correlation between the 30 strategies' predicted
       scores and their realized 30d P&L.  Returns mean / std /
       % positive days.  This is the standard quant metric — IC > 0.05
       sustained = real alpha.
    3. ``decile_analysis`` — pool ALL (date × strategy) observations,
       bucket by predicted score percentile (deciles), compute mean
       realized per decile.  Should be monotonically increasing if
       the system is information-efficient.
    4. ``long_short_spread`` — daily long top-decile minus short
       bottom-decile, then aggregate.  This is the hypothetical
       portfolio realized return assuming you traded the system's
       extreme picks.
    5. ``permutation_null`` — shuffle predicted_scores within each
       strategy across dates 200x; for each shuffle, compute Δ h-l
       and IC.  Returns the null distribution + p-value of observed.
    6. ``regime_stratification`` — split rows by regime fingerprint
       quintile (risk_appetite low/mid/high, vol low/mid/high), check
       if the IC is stable across regimes or only works in some.
    """
    import random
    from agent.finance.persistence import connect

    rng = random.Random(seed)

    # Load all rows ONCE — these are the (date × strategy × pred × real)
    with connect() as conn:
        cur = conn.execute(
            """SELECT fingerprint_date, strategy_id,
                      predicted_score, realized_pnl_pct
                 FROM backtest_results
                 WHERE hold_days = ? AND realized_pnl_pct IS NOT NULL""",
            (hold_days,),
        )
        all_rows = [dict(r) for r in cur.fetchall()]

    if not all_rows:
        return {"error": "no backtest_results — run regime_backtest.command first"}

    n_total = len(all_rows)
    logger.info("[VALIDATE] %d total rows, %d unique dates, %d unique strategies",
                n_total,
                len(set(r["fingerprint_date"] for r in all_rows)),
                len(set(r["strategy_id"] for r in all_rows)))

    # 1) cutoff sweep
    cutoff_sweep = []
    for c in [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]:
        high = [r["realized_pnl_pct"] for r in all_rows if r["predicted_score"] >= c]
        low  = [r["realized_pnl_pct"] for r in all_rows if r["predicted_score"] <  c]
        if not high:
            cutoff_sweep.append({"cutoff": c, "n_high": 0, "skip": "no_high_rows"})
            continue
        ch = sum(high) / len(high)
        cl = sum(low)  / len(low)  if low else 0.0
        hit = sum(1 for r in high if r > 0) / len(high)
        cutoff_sweep.append({
            "cutoff":   c,
            "n_high":   len(high),
            "n_low":    len(low),
            "cal_hi":   round(ch, 5),
            "cal_lo":   round(cl, 5),
            "delta_hl": round(ch - cl, 5),
            "hit_rate": round(hit, 3),
        })

    # 2) Information coefficient — per-day Spearman across strategies
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_rows:
        by_date.setdefault(r["fingerprint_date"], []).append(r)
    daily_ic: List[float] = []
    for date, day_rows in by_date.items():
        if len(day_rows) < 5:
            continue
        preds = [d["predicted_score"]   for d in day_rows]
        rels  = [d["realized_pnl_pct"] for d in day_rows]
        rho = _spearman(preds, rels)
        if rho is not None:
            daily_ic.append(rho)
    n_days = len(daily_ic)
    if daily_ic:
        ic_mean = sum(daily_ic) / n_days
        ic_var = sum((x - ic_mean) ** 2 for x in daily_ic) / max(1, n_days - 1)
        ic_std = ic_var ** 0.5
        ic_pos = sum(1 for x in daily_ic if x > 0) / n_days
    else:
        ic_mean = ic_std = ic_pos = None

    # 3) Decile analysis (pooled)
    sorted_by_pred = sorted(all_rows, key=lambda r: r["predicted_score"])
    deciles = []
    for d in range(10):
        lo = int(n_total *  d      / 10)
        hi = int(n_total * (d + 1) / 10)
        chunk = sorted_by_pred[lo:hi]
        if not chunk:
            deciles.append({"decile": d + 1, "n": 0})
            continue
        pred_min = chunk[0]["predicted_score"]
        pred_max = chunk[-1]["predicted_score"]
        rels = [c["realized_pnl_pct"] for c in chunk]
        deciles.append({
            "decile":     d + 1,
            "n":          len(chunk),
            "pred_min":   round(pred_min, 3),
            "pred_max":   round(pred_max, 3),
            "real_mean":  round(sum(rels) / len(rels), 5),
            "real_pos_pct": round(sum(1 for r in rels if r > 0) / len(rels), 3),
        })

    # 4) Long-short spread (daily) — for each date, mean(top 10%) − mean(bottom 10%)
    daily_ls = []
    for date, day_rows in by_date.items():
        if len(day_rows) < 10:
            continue
        srt = sorted(day_rows, key=lambda r: r["predicted_score"])
        k = max(1, len(srt) // 10)
        top    = srt[-k:]
        bottom = srt[:k]
        spread = (sum(t["realized_pnl_pct"] for t in top) / k
                  - sum(b["realized_pnl_pct"] for b in bottom) / k)
        daily_ls.append(spread)
    if daily_ls:
        ls_mean = sum(daily_ls) / len(daily_ls)
        ls_pos  = sum(1 for x in daily_ls if x > 0) / len(daily_ls)
        ls_var  = sum((x - ls_mean) ** 2 for x in daily_ls) / max(1, len(daily_ls) - 1)
        ls_std  = ls_var ** 0.5
        # Sharpe-like: mean / std × sqrt(252)
        ls_annualised_sharpe = (ls_mean / ls_std) * (252 ** 0.5) if ls_std > 0 else 0.0
    else:
        ls_mean = ls_std = ls_pos = ls_annualised_sharpe = None

    # 5) Permutation null — shuffle pred within each strategy, recompute IC + Δ h-l
    by_strategy: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_rows:
        by_strategy.setdefault(r["strategy_id"], []).append(r)

    null_ics: List[float] = []
    null_deltas: List[float] = []
    for _ in range(n_permutations):
        # Shuffle predicted_scores WITHIN each strategy (permute across dates)
        shuffled_rows: List[Dict[str, Any]] = []
        for sid, srows in by_strategy.items():
            preds = [r["predicted_score"] for r in srows]
            rng.shuffle(preds)
            for i, r in enumerate(srows):
                shuffled_rows.append({**r, "predicted_score": preds[i]})

        # Compute IC across days for this shuffle
        sh_by_date: Dict[str, List[Dict[str, Any]]] = {}
        for r in shuffled_rows:
            sh_by_date.setdefault(r["fingerprint_date"], []).append(r)
        day_ics = []
        for d, dr in sh_by_date.items():
            if len(dr) < 5:
                continue
            rho = _spearman([x["predicted_score"] for x in dr],
                            [x["realized_pnl_pct"] for x in dr])
            if rho is not None:
                day_ics.append(rho)
        sh_ic_mean = sum(day_ics) / len(day_ics) if day_ics else 0.0
        null_ics.append(sh_ic_mean)

        # Δ h-l at cutoff 3.0 (lower so we have rows)
        high = [r["realized_pnl_pct"] for r in shuffled_rows
                if r["predicted_score"] >= 3.0]
        low  = [r["realized_pnl_pct"] for r in shuffled_rows
                if r["predicted_score"] <  3.0]
        if high and low:
            ch = sum(high) / len(high)
            cl = sum(low)  / len(low)
            null_deltas.append(ch - cl)

    if null_ics and ic_mean is not None:
        # p-value: fraction of nulls more extreme than observed
        p_ic = sum(1 for x in null_ics if abs(x) >= abs(ic_mean)) / len(null_ics)
        null_ic_mean = sum(null_ics) / len(null_ics)
        null_ic_std  = (sum((x - null_ic_mean) ** 2 for x in null_ics)
                        / max(1, len(null_ics) - 1)) ** 0.5
    else:
        p_ic = null_ic_mean = null_ic_std = None

    # Observed Δ at cutoff 3.0 for p-value comparison
    high3 = [r["realized_pnl_pct"] for r in all_rows if r["predicted_score"] >= 3.0]
    low3  = [r["realized_pnl_pct"] for r in all_rows if r["predicted_score"] <  3.0]
    obs_delta_3 = (sum(high3) / len(high3) - sum(low3) / len(low3)) \
                   if (high3 and low3) else None
    if null_deltas and obs_delta_3 is not None:
        p_delta = sum(1 for x in null_deltas if abs(x) >= abs(obs_delta_3)) / len(null_deltas)
    else:
        p_delta = None

    # 6) Regime stratification — split by risk_appetite quintile
    fp_by_date: Dict[str, Dict[str, Any]] = {}
    with connect() as conn:
        for r in conn.execute(
            "SELECT fingerprint_date, risk_appetite_score, volatility_regime_score "
            "FROM regime_fingerprints"
        ):
            fp_by_date[r["fingerprint_date"]] = dict(r)

    risk_buckets: Dict[str, List[float]] = {"low": [], "mid": [], "high": []}
    for date, day_rows in by_date.items():
        fp = fp_by_date.get(date)
        if not fp or fp.get("risk_appetite_score") is None:
            continue
        ra = fp["risk_appetite_score"]
        bucket = "low" if ra < 33 else ("high" if ra > 66 else "mid")
        if len(day_rows) < 5:
            continue
        rho = _spearman([d["predicted_score"]   for d in day_rows],
                        [d["realized_pnl_pct"] for d in day_rows])
        if rho is not None:
            risk_buckets[bucket].append(rho)

    risk_strat = {
        b: {
            "n_days":  len(v),
            "ic_mean": round(sum(v) / len(v), 4) if v else None,
            "ic_pos":  round(sum(1 for x in v if x > 0) / len(v), 3) if v else None,
        }
        for b, v in risk_buckets.items()
    }

    return {
        "n_total_rows":   n_total,
        "n_unique_dates": len(by_date),
        "n_strategies":   len(by_strategy),
        "hold_days":      hold_days,

        "cutoff_sweep":   cutoff_sweep,

        "information_coefficient": {
            "n_days":  n_days,
            "mean":    round(ic_mean, 4) if ic_mean is not None else None,
            "std":     round(ic_std,  4) if ic_std  is not None else None,
            "pct_positive": round(ic_pos, 3) if ic_pos is not None else None,
            "interpretation": (
                "IC > 0.05 sustained = real alpha. "
                "IC ~ 0 = random. "
                "IC < 0 = system is anti-predictive (recommend low-fit days perform better)."
            ),
        },

        "decile_analysis": deciles,

        "long_short_spread": {
            "n_days":   len(daily_ls),
            "mean":     round(ls_mean, 5) if ls_mean is not None else None,
            "std":      round(ls_std,  5) if ls_std  is not None else None,
            "pos_pct":  round(ls_pos,  3) if ls_pos  is not None else None,
            "annualised_sharpe": round(ls_annualised_sharpe, 3) if ls_annualised_sharpe is not None else None,
            "interpretation": (
                "Mean > 0 + Sharpe > 0.5 = top-decile picks beat bottom-decile picks; "
                "the rank IS information."
            ),
        },

        "permutation_null": {
            "n_perms":      n_permutations,
            "obs_ic":       round(ic_mean, 4) if ic_mean is not None else None,
            "null_ic_mean": round(null_ic_mean, 4) if null_ic_mean is not None else None,
            "null_ic_std":  round(null_ic_std,  4) if null_ic_std  is not None else None,
            "p_value_ic":   round(p_ic, 4) if p_ic is not None else None,
            "obs_delta_at_3": round(obs_delta_3, 5) if obs_delta_3 is not None else None,
            "p_value_delta_3": round(p_delta, 4) if p_delta is not None else None,
            "interpretation": (
                "p < 0.05 = observed signal unlikely under null (real). "
                "p >= 0.10 = signal is statistically indistinguishable from random."
            ),
        },

        "regime_stratification_risk_appetite": risk_strat,
    }


def _spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman rank correlation. Returns None for n<3 or zero variance."""
    n = len(xs)
    if n < 3:
        return None

    def rank(v: List[float]) -> List[float]:
        order = sorted(range(n), key=lambda i: v[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sx2 = sum((x - mx) ** 2 for x in rx)
    sy2 = sum((y - my) ** 2 for y in ry)
    if sx2 == 0 or sy2 == 0:
        return None
    sxy = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    return sxy / math.sqrt(sx2 * sy2)
