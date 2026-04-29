"""Daily regime fingerprint — 5 buckets × 5 windows.

Reads from ``raw_market_data``, writes to ``regime_fingerprints``.  Pure
function over a (date, raw_market_data) input — given the same raw rows
it produces the same fingerprint, so the backfill path is idempotent.

Buckets (per design doc 2026-04-29_strategy-pipeline-v2 §1):

  🌡️ risk_appetite       — VIX, put/call, AAII, SPY RSI
  📈 volatility_regime    — SPY 30d RV, VIX-RV gap, vol term, QQQ 60d RV
  🌐 breadth              — % stocks > 50dMA, top10/bottom10, sector dispersion
  📅 event_density        — earnings count next 5d, FOMC distance, OPEX, holidays
  💸 flow                 — yield curve, USD, sector RS, HYG OAS

Each bucket is a 0–100 score (0 = low side of regime, 100 = high side),
plus per-component drill-down at 5 windows (1w/1m/3m/6m/1y).  "High"
side meanings:

  risk_appetite:       low VIX / high RSI / high bull% = greed (high)
  volatility_regime:   high RV / wide IV-RV gap = stretched (high)
  breadth:             many stocks above MA + low dispersion = broad (high)
  event_density:       many events soon = high
  flow:                steep curve / weak USD / tight credit = risk-on (high)
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


_WINDOWS = {
    "1w":  5,    # trading days
    "1m":  21,
    "3m":  63,
    "6m":  126,
    "1y":  252,
}


# ── helpers ────────────────────────────────────────────────────────


def _pct_rank(series: List[float], target: float) -> Optional[float]:
    """Percentile rank of ``target`` within ``series``.  None when series
    is empty.  Returns 0–1 (0 = lowest, 1 = highest)."""
    if not series:
        return None
    cleaned = [s for s in series if s is not None and not math.isnan(s)]
    if not cleaned:
        return None
    n_below = sum(1 for s in cleaned if s < target)
    n_eq    = sum(1 for s in cleaned if s == target)
    return (n_below + 0.5 * n_eq) / len(cleaned)


def _multi_window_pct_rank(
    history: List[float],
    target: float,
) -> Dict[str, Optional[float]]:
    """Compute ``target`` percentile rank against the trailing N values
    of ``history`` for each window.  Falls back to None when the history
    is shorter than the window."""
    out: Dict[str, Optional[float]] = {}
    n = len(history)
    for win_name, win_n in _WINDOWS.items():
        if n < win_n:
            out[win_name] = None
        else:
            slice_ = history[-win_n:]
            out[win_name] = _pct_rank(slice_, target)
    return out


def _log_returns(closes: List[float]) -> List[float]:
    if len(closes) < 2:
        return []
    out = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev is None or cur is None or prev <= 0 or cur <= 0:
            continue
        out.append(math.log(cur / prev))
    return out


def _annualised_vol(closes: List[float]) -> Optional[float]:
    rets = _log_returns(closes)
    if len(rets) < 2:
        return None
    return statistics.stdev(rets) * math.sqrt(252)


def _score_from_pct_rank(
    pct: Optional[float],
    *,
    invert: bool = False,
) -> Optional[float]:
    """Map a 0–1 percentile rank to a 0–100 bucket score.  ``invert=True``
    when low-rank means high-side-of-regime (e.g., low VIX = high greed)."""
    if pct is None:
        return None
    val = (1 - pct) if invert else pct
    return round(val * 100, 1)


# ── data loaders (per-bucket) ──────────────────────────────────────


def _load_close_history(
    symbol: str,
    as_of_date: str,
    n: int = 260,
) -> List[float]:
    from agent.finance.regime.store import closes_as_of
    rows = closes_as_of(symbol, as_of_date, n)
    return [r["close"] for r in rows if r.get("close") is not None]


# ── bucket compute fns — each returns (score, components, inputs, sources) ─


def _bucket_risk_appetite(as_of_date: str) -> Dict[str, Any]:
    """🌡️ Risk Appetite: greed vs fear."""
    sources: Dict[str, str] = {}
    inputs: Dict[str, Any] = {}
    components: Dict[str, Dict[str, Optional[float]]] = {}
    sub_scores: List[Optional[float]] = []

    # VIX percentile (low VIX = greed = high score → invert)
    vix_hist = _load_close_history("^VIX", as_of_date)
    if vix_hist:
        latest = vix_hist[-1]
        ranks = _multi_window_pct_rank(vix_hist[:-1], latest)
        components["vix_pct_rank"] = ranks
        inputs["vix_close"] = latest
        sources["^VIX"] = "raw_market_data:^VIX"
        # default-window sub-score (3m) — INVERTED (low rank = high score)
        sub_scores.append(_score_from_pct_rank(ranks.get("3m"), invert=True))

    # SPY RSI(14)
    spy_closes = _load_close_history("SPY", as_of_date, n=20)
    if len(spy_closes) >= 15:
        gains: List[float] = []
        losses: List[float] = []
        for i in range(1, 15):
            d = spy_closes[-15 + i] - spy_closes[-15 + i - 1]
            (gains if d > 0 else losses).append(abs(d))
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0
        rsi = 100 - 100 / (1 + (avg_gain / avg_loss)) if avg_loss > 0 else 100
        inputs["spy_rsi_14"] = round(rsi, 2)
        sources["SPY:rsi"] = "raw_market_data:SPY (last 15 closes)"
        # RSI 70+ overbought (greed), 30- oversold (fear).  Linear map 0-100.
        rsi_score = max(0, min(100, rsi))
        sub_scores.append(rsi_score)
        components["spy_rsi"] = {"value": rsi_score}

    # Put/Call ratio — TODO: no ingest yet (CBOE PCRATIO).  Skipped.
    # AAII bull/bear — TODO: no automatic feed.  Skipped.

    valid = [s for s in sub_scores if s is not None]
    score = round(sum(valid) / len(valid), 1) if valid else None

    return {
        "score":      score,
        "components": components,
        "inputs":     inputs,
        "sources":    sources,
        "todos":      ["put_call_ratio_feed", "aaii_survey_feed"],
    }


def _bucket_volatility_regime(as_of_date: str) -> Dict[str, Any]:
    """📈 Volatility regime: compressed vs stretched."""
    sources: Dict[str, str] = {}
    inputs: Dict[str, Any] = {}
    components: Dict[str, Dict[str, Optional[float]]] = {}
    sub_scores: List[Optional[float]] = []

    # SPY 30d realized vol percentile rank
    spy_hist = _load_close_history("SPY", as_of_date)
    if len(spy_hist) >= 32:
        rv_series: List[float] = []
        for end in range(31, len(spy_hist)):
            window = spy_hist[end - 30:end + 1]
            v = _annualised_vol(window)
            if v is not None:
                rv_series.append(v)
        if rv_series:
            latest_rv = rv_series[-1]
            inputs["spy_30d_rv"] = round(latest_rv, 4)
            sources["SPY:rv30d"] = "raw_market_data:SPY (rolling 30d log-ret stdev)"
            ranks = _multi_window_pct_rank(rv_series[:-1], latest_rv)
            components["spy_30d_rv_pct_rank"] = ranks
            sub_scores.append(_score_from_pct_rank(ranks.get("3m")))

    # VIX − SPY-RV gap (positive = IV expensive, neg = IV cheap)
    if "spy_30d_rv" in inputs:
        vix_hist = _load_close_history("^VIX", as_of_date)
        if vix_hist:
            vix_now = vix_hist[-1]
            spy_rv_pct = inputs["spy_30d_rv"] * 100  # convert to vol points
            gap = vix_now - spy_rv_pct
            inputs["vix_minus_rv"] = round(gap, 3)
            sources["VIX-RV_gap"] = "VIX close − SPY 30d RV (annualised)"
            # Map gap (-15..+15 typical) → 0-100
            gap_score = max(0, min(100, 50 + gap * (50 / 15)))
            components["vix_minus_rv"] = {"value": round(gap_score, 1)}
            sub_scores.append(gap_score)

    # Vol term slope: VIX9D − VIX (negative = backwardation = stress)
    vix9d = _load_close_history("^VIX9D", as_of_date)
    vix   = _load_close_history("^VIX", as_of_date)
    if vix9d and vix:
        slope = vix9d[-1] - vix[-1]
        inputs["vol_term_slope"] = round(slope, 3)
        sources["vol_term_slope"] = "VIX9D − VIX (negative = backwardation)"
        # Map slope (-3..+3) → 100..0  (backwardation = high vol regime)
        slope_score = max(0, min(100, 50 - slope * (50 / 3)))
        components["vol_term_slope"] = {"value": round(slope_score, 1)}
        sub_scores.append(slope_score)

    valid = [s for s in sub_scores if s is not None]
    score = round(sum(valid) / len(valid), 1) if valid else None

    return {
        "score":      score,
        "components": components,
        "inputs":     inputs,
        "sources":    sources,
        "todos":      ["real_iv_feed_replace_rv_proxy"],
    }


def _bucket_breadth(as_of_date: str) -> Dict[str, Any]:
    """🌐 Market breadth: narrow vs broad."""
    from agent.finance.regime.tiers import TIER3_SP500
    from agent.finance.regime.store import closes_as_of, universe_close_panel

    sources: Dict[str, str] = {}
    inputs: Dict[str, Any] = {}
    components: Dict[str, Dict[str, Optional[float]]] = {}
    sub_scores: List[Optional[float]] = []

    # % of S&P 500 components above their 50d MA
    pct_above = _pct_above_ma50(TIER3_SP500, as_of_date)
    if pct_above is not None:
        inputs["pct_sp500_above_50d_ma"] = round(pct_above * 100, 1)
        sources["breadth"] = f"raw_market_data:S&P 500 ({len(TIER3_SP500)} symbols, 50d MA)"
        score = pct_above * 100
        components["pct_above_50d_ma"] = {"value": round(score, 1)}
        sub_scores.append(score)

    # Sector dispersion: stdev of 5d returns across 11 sector ETFs
    sector_etfs = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
                   "XLI", "XLB", "XLU", "XLRE", "XLC"]
    sector_5d_rets: List[float] = []
    for etf in sector_etfs:
        rows = closes_as_of(etf, as_of_date, 6)
        if len(rows) >= 6:
            old, new = rows[0]["close"], rows[-1]["close"]
            if old and new and old > 0:
                sector_5d_rets.append((new - old) / old)
    if len(sector_5d_rets) >= 5:
        disp = statistics.stdev(sector_5d_rets)
        inputs["sector_dispersion_5d"] = round(disp, 4)
        sources["sector_dispersion"] = "stdev of 5d returns across 11 sector ETFs"
        # Low dispersion → broad → high score.  Typical disp 0–0.05.
        disp_score = max(0, min(100, 100 - disp * 100 * 20))
        components["sector_dispersion"] = {"value": round(disp_score, 1)}
        sub_scores.append(disp_score)

    valid = [s for s in sub_scores if s is not None]
    score = round(sum(valid) / len(valid), 1) if valid else None

    return {
        "score":      score,
        "components": components,
        "inputs":     inputs,
        "sources":    sources,
        "todos":      ["nyse_advance_decline_feed"],
    }


def _pct_above_ma50(symbols: List[str], as_of_date: str) -> Optional[float]:
    """Compute % of `symbols` whose latest close > 50d simple moving avg.
    Returns None when too few have data."""
    from agent.finance.regime.store import closes_as_of
    above = 0
    have_data = 0
    for sym in symbols:
        rows = closes_as_of(sym, as_of_date, 50)
        if len(rows) < 50:
            continue
        closes = [r["close"] for r in rows if r.get("close") is not None]
        if len(closes) < 50:
            continue
        latest = closes[-1]
        ma50 = sum(closes[-50:]) / 50
        have_data += 1
        if latest > ma50:
            above += 1
    if have_data == 0:
        return None
    return above / have_data


def _bucket_event_density(as_of_date: str) -> Dict[str, Any]:
    """📅 Event density: earnings + macro events."""
    sources: Dict[str, str] = {}
    inputs: Dict[str, Any] = {}
    components: Dict[str, Dict[str, Optional[float]]] = {}
    sub_scores: List[Optional[float]] = []

    # Distance to next OPEX (3rd Friday of month) — deterministic
    today = date.fromisoformat(as_of_date)
    opex = _next_third_friday(today)
    days_to_opex = (opex - today).days
    inputs["days_to_opex"] = days_to_opex
    sources["opex"] = "deterministic: third Friday of month"
    components["days_to_opex"] = {"value": days_to_opex}
    # 0 days → 100, 30+ days → 0
    sub_scores.append(max(0, min(100, 100 - (days_to_opex / 30) * 100)))

    # Earnings next 5d — TODO: hook in earnings calendar
    # FOMC distance — TODO: hook in FRED calendar

    valid = [s for s in sub_scores if s is not None]
    score = round(sum(valid) / len(valid), 1) if valid else None

    return {
        "score":      score,
        "components": components,
        "inputs":     inputs,
        "sources":    sources,
        "todos":      [
            "earnings_calendar_feed",
            "fomc_distance_via_FRED",
            "nyse_holidays_feed",
        ],
    }


def _next_third_friday(d: date) -> date:
    """Next third Friday at or after d."""
    # Start from this month's third Friday
    first = date(d.year, d.month, 1)
    # Friday is weekday 4
    offset = (4 - first.weekday()) % 7
    third_fri = date(d.year, d.month, 1 + offset + 14)
    if third_fri >= d:
        return third_fri
    # Roll to next month
    if d.month == 12:
        nm_year, nm_month = d.year + 1, 1
    else:
        nm_year, nm_month = d.year, d.month + 1
    nm_first = date(nm_year, nm_month, 1)
    nm_offset = (4 - nm_first.weekday()) % 7
    return date(nm_year, nm_month, 1 + nm_offset + 14)


def _bucket_flow(as_of_date: str) -> Dict[str, Any]:
    """💸 Flow: cross-asset / curve direction."""
    sources: Dict[str, str] = {}
    inputs: Dict[str, Any] = {}
    components: Dict[str, Dict[str, Optional[float]]] = {}
    sub_scores: List[Optional[float]] = []

    # 10y - 2y proxy via ^TNX − ^IRX (close to 2y)
    tnx = _load_close_history("^TNX", as_of_date, n=2)
    irx = _load_close_history("^IRX", as_of_date, n=2)
    if tnx and irx:
        slope = tnx[-1] - irx[-1]
        inputs["yield_curve_slope_10y_minus_2y_proxy"] = round(slope, 3)
        sources["yield_curve"] = "^TNX − ^IRX (10y − 13w T-bill, 2y proxy)"
        # Steep (>2%) → risk-on → high score.  Inverted (<-0.5) → risk-off → low.
        score_yc = max(0, min(100, 50 + slope * (50 / 2)))
        components["yield_curve"] = {"value": round(score_yc, 1)}
        sub_scores.append(score_yc)

    # USD index — strong USD = risk-off → invert
    dxy = _load_close_history("DX-Y.NYB", as_of_date)
    if not dxy:
        dxy = _load_close_history("UUP", as_of_date)
    if dxy and len(dxy) >= 2:
        latest = dxy[-1]
        ranks = _multi_window_pct_rank(dxy[:-1], latest)
        components["usd_index_pct_rank"] = ranks
        inputs["usd_index"] = round(latest, 3)
        sources["usd_index"] = "raw_market_data:DX-Y.NYB or UUP fallback"
        sub_scores.append(_score_from_pct_rank(ranks.get("3m"), invert=True))

    # HYG yield − IEF yield = HYG OAS proxy (tight = risk-on, wide = risk-off)
    # We don't have yields directly; use price ratio HYG/IEF as proxy
    hyg = _load_close_history("HYG", as_of_date)
    ief = _load_close_history("IEF", as_of_date)
    if hyg and ief and ief[-1] > 0:
        ratio_now = hyg[-1] / ief[-1]
        ratios_hist = [h / i for h, i in zip(hyg[:-1], ief[:-1]) if i > 0]
        if ratios_hist:
            ranks = _multi_window_pct_rank(ratios_hist, ratio_now)
            components["hyg_ief_ratio"] = ranks
            inputs["hyg_ief_ratio"] = round(ratio_now, 4)
            sources["credit_spread"] = "HYG / IEF price ratio (high = tight spreads = risk-on)"
            sub_scores.append(_score_from_pct_rank(ranks.get("3m")))

    valid = [s for s in sub_scores if s is not None]
    score = round(sum(valid) / len(valid), 1) if valid else None

    return {
        "score":      score,
        "components": components,
        "inputs":     inputs,
        "sources":    sources,
        "todos":      ["sector_relative_strength_panel"],
    }


# ── public API ────────────────────────────────────────────────────


def compute_fingerprint(as_of_date: str) -> Dict[str, Any]:
    """Compute the 5-bucket regime fingerprint for ``as_of_date``.

    Pure: re-running with the same raw_market_data state produces the
    same output.  Returns the dict shape that ``store.upsert_fingerprint``
    consumes."""
    risk      = _bucket_risk_appetite(as_of_date)
    vol       = _bucket_volatility_regime(as_of_date)
    breadth   = _bucket_breadth(as_of_date)
    events    = _bucket_event_density(as_of_date)
    flow      = _bucket_flow(as_of_date)

    return {
        "fingerprint_date":         as_of_date,
        "risk_appetite_score":      risk["score"],
        "volatility_regime_score":  vol["score"],
        "breadth_score":            breadth["score"],
        "event_density_score":      events["score"],
        "flow_score":               flow["score"],
        "components": {
            "risk_appetite":      risk["components"],
            "volatility_regime":  vol["components"],
            "breadth":            breadth["components"],
            "event_density":      events["components"],
            "flow":               flow["components"],
        },
        "inputs": {
            "risk_appetite":      risk["inputs"],
            "volatility_regime":  vol["inputs"],
            "breadth":            breadth["inputs"],
            "event_density":      events["inputs"],
            "flow":               flow["inputs"],
        },
        "sources": {
            "risk_appetite":      risk["sources"],
            "volatility_regime":  vol["sources"],
            "breadth":            breadth["sources"],
            "event_density":      events["sources"],
            "flow":               flow["sources"],
        },
        "todos": list(set(
            risk["todos"] + vol["todos"] + breadth["todos"]
            + events["todos"] + flow["todos"]
        )),
    }


def fingerprint_for_date(as_of_date: str, *, recompute: bool = False) -> Dict[str, Any]:
    """Cached compute: read from regime_fingerprints table, fall back to
    compute + upsert.  Recompute=True forces a fresh compute."""
    from agent.finance.regime.store import get_fingerprint, upsert_fingerprint
    if not recompute:
        cached = get_fingerprint(as_of_date)
        if cached:
            return cached
    fp = compute_fingerprint(as_of_date)
    upsert_fingerprint(fp)
    return fp


def backfill_fingerprints(
    *, since: str, until: Optional[str] = None,
    skip_existing: bool = True,
) -> Dict[str, Any]:
    """Compute & store fingerprints for every trading day between since
    and until (inclusive).  Skips weekends.  Returns counts."""
    from agent.finance.regime.store import get_fingerprint, upsert_fingerprint
    start = date.fromisoformat(since)
    end = date.fromisoformat(until) if until else date.today()
    total_days = (end - start).days + 1
    written = 0
    skipped = 0
    failed = 0
    cur = start
    while cur <= end:
        # Skip weekends (no trading)
        if cur.weekday() < 5:
            iso = cur.isoformat()
            if skip_existing and get_fingerprint(iso):
                skipped += 1
            else:
                try:
                    fp = compute_fingerprint(iso)
                    upsert_fingerprint(fp)
                    written += 1
                except Exception as exc:
                    logger.warning("fingerprint compute failed for %s: %s", iso, exc)
                    failed += 1
        cur = cur + timedelta(days=1)
    logger.info(
        "backfill_fingerprints: %s..%s — wrote %d skipped %d failed %d",
        since, end.isoformat(), written, skipped, failed,
    )
    return {
        "since": since,
        "until": end.isoformat(),
        "total_days_scanned": total_days,
        "written": written,
        "skipped": skipped,
        "failed": failed,
    }
