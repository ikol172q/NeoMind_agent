"""yfinance ingestion for the 3-tier watchlist.

One pull = one bulk yfinance call for ALL Tier 2 + Tier 3 symbols at
once (yfinance.download supports a tickers list).  Daily-bar granularity
only — intraday is a TODO (see design doc Section 11).

Usage::

    from agent.finance.regime.ingest import (
        ingest_yfinance_daily,   # incremental: pull last N days
        backfill_history,        # one-shot: pull entire history
    )

    # Backfill 1 year (run once on first install)
    backfill_history(period="1y")

    # Daily cron: incremental
    ingest_yfinance_daily(lookback_days=5)

Both functions write to ``raw_market_data`` via ``store.upsert_raw_bars``.

Failures: yfinance returns NaN for missing data and never raises on a
single ticker; we filter NaN rows before insert and log a warning per
symbol with no data.  A network outage on the whole call propagates as
an exception (caller decides what to do).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _import_yfinance() -> Any:
    """Lazy import so test environments / sandboxes without yfinance can
    still load the rest of the package."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError as e:
        raise ImportError(
            "yfinance not installed.  In the host venv: "
            "`/Users/paomian_kong/Desktop/Investment/cowork/"
            "neomind-fin-platform/.venv-host/bin/pip install yfinance`"
        ) from e
    return yf


def _df_to_bars(df: Any, tier_lookup: Dict[str, int]) -> List[Dict[str, Any]]:
    """yfinance.download returns a multi-index DataFrame when called
    with multiple tickers: rows=Date, cols=(Field, Ticker).  Flatten to
    a list of dicts.  Drop rows where close is NaN (yfinance leaves a
    NaN row when a ticker has no data on that date)."""
    import math
    bars: List[Dict[str, Any]] = []
    if df is None or df.empty:
        return bars
    # Single-ticker case: cols are flat Field names.  Multi-ticker:
    # cols are MultiIndex (Field, Ticker).
    if df.columns.nlevels == 1:
        # Caller should have passed tier explicitly via tier_lookup; if
        # there's only one ticker, we can recover it from the only key.
        if len(tier_lookup) != 1:
            return bars
        only_sym = next(iter(tier_lookup))
        for idx, row in df.iterrows():
            close = row.get("Close")
            if close is None or (isinstance(close, float) and math.isnan(close)):
                continue
            bars.append({
                "symbol":         only_sym,
                "trade_date":     idx.date().isoformat(),
                "open":           _f(row.get("Open")),
                "high":           _f(row.get("High")),
                "low":            _f(row.get("Low")),
                "close":          _f(close),
                "adjusted_close": _f(row.get("Adj Close", row.get("Close"))),
                "volume":         _i(row.get("Volume")),
                "tier":           tier_lookup.get(only_sym, 3),
            })
        return bars
    # Multi-ticker: pivot per symbol
    fields = df.columns.get_level_values(0).unique().tolist()
    syms   = df.columns.get_level_values(1).unique().tolist()
    for sym in syms:
        for idx in df.index:
            try:
                close = df[("Close", sym)].at[idx]
            except Exception:
                continue
            if close is None or (isinstance(close, float) and math.isnan(close)):
                continue
            row_data: Dict[str, Any] = {
                "symbol": sym,
                "trade_date": idx.date().isoformat(),
                "tier": tier_lookup.get(sym, 3),
            }
            for field in fields:
                try:
                    val = df[(field, sym)].at[idx]
                except Exception:
                    val = None
                key = {
                    "Open": "open", "High": "high", "Low": "low",
                    "Close": "close", "Adj Close": "adjusted_close",
                    "Volume": "volume",
                }.get(field)
                if key is None:
                    continue
                if key == "volume":
                    row_data[key] = _i(val)
                else:
                    row_data[key] = _f(val)
            row_data.setdefault("adjusted_close", row_data.get("close"))
            bars.append(row_data)
    return bars


def _f(x: Any) -> Optional[float]:
    import math
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _i(x: Any) -> Optional[int]:
    import math
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _build_tier_lookup(symbols: List[str]) -> Dict[str, int]:
    """Compute the tier of every symbol in the bulk pull."""
    from agent.finance.regime.tiers import TIER2_ANCHORS
    out: Dict[str, int] = {}
    for s in symbols:
        out[s] = 2 if s in TIER2_ANCHORS else 3
    return out


def ingest_yfinance_daily(
    *,
    lookback_days: int = 5,
    symbols: Optional[List[str]] = None,
    tier1_watchlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Incremental pull of the last ``lookback_days`` days for every
    Tier 2 + Tier 3 symbol (and optional Tier 1 watchlist additions).

    Returns ``{n_symbols, n_rows, since, until, errors}``.  Idempotent.
    """
    yf = _import_yfinance()
    from agent.finance.regime.store import upsert_raw_bars
    from agent.finance.regime.tiers import all_symbols

    syms = symbols or [s for s, _t in all_symbols()]
    if tier1_watchlist:
        for s in tier1_watchlist:
            if s not in syms:
                syms.append(s)

    until = date.today()
    since = until - timedelta(days=int(lookback_days))

    logger.info(
        "ingest_yfinance_daily: %d symbols, %s → %s",
        len(syms), since, until,
    )

    df = yf.download(
        tickers=syms,
        start=since.isoformat(),
        end=(until + timedelta(days=1)).isoformat(),
        progress=False,
        group_by="column",
        auto_adjust=False,
        threads=True,
    )

    tier_lookup = _build_tier_lookup(syms)
    if tier1_watchlist:
        for s in tier1_watchlist:
            tier_lookup[s] = 1
    bars = _df_to_bars(df, tier_lookup)

    n_written = upsert_raw_bars(bars, source="yfinance")
    logger.info("ingest_yfinance_daily: wrote %d bars", n_written)

    # Ticker-level coverage report
    by_sym: Dict[str, int] = {}
    for b in bars:
        by_sym[b["symbol"]] = by_sym.get(b["symbol"], 0) + 1
    missing = [s for s in syms if s not in by_sym]
    if missing:
        logger.warning(
            "ingest_yfinance_daily: %d symbols had no rows: %s",
            len(missing), missing[:20],
        )

    return {
        "n_symbols":       len(syms),
        "n_rows_written":  n_written,
        "since":           since.isoformat(),
        "until":           until.isoformat(),
        "missing_symbols": missing,
    }


def backfill_history(
    *,
    period: str = "1y",
    symbols: Optional[List[str]] = None,
    tier1_watchlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One-shot historical backfill.  ``period`` is yfinance-style:
    '1mo', '3mo', '6mo', '1y', '2y', '5y', 'max'.

    Recommended on first install: ``backfill_history(period='1y')``.
    Takes ~3-10 minutes for the full 3-tier watchlist (depends on
    yfinance throttling)."""
    yf = _import_yfinance()
    from agent.finance.regime.store import upsert_raw_bars
    from agent.finance.regime.tiers import all_symbols

    syms = symbols or [s for s, _t in all_symbols()]
    if tier1_watchlist:
        for s in tier1_watchlist:
            if s not in syms:
                syms.append(s)

    logger.info(
        "backfill_history: %d symbols, period=%s",
        len(syms), period,
    )

    df = yf.download(
        tickers=syms,
        period=period,
        progress=False,
        group_by="column",
        auto_adjust=False,
        threads=True,
    )

    tier_lookup = _build_tier_lookup(syms)
    if tier1_watchlist:
        for s in tier1_watchlist:
            tier_lookup[s] = 1
    bars = _df_to_bars(df, tier_lookup)

    n_written = upsert_raw_bars(bars, source="yfinance")

    by_sym: Dict[str, int] = {}
    for b in bars:
        by_sym[b["symbol"]] = by_sym.get(b["symbol"], 0) + 1
    missing = [s for s in syms if s not in by_sym]
    coverage_min = min(by_sym.values()) if by_sym else 0
    coverage_max = max(by_sym.values()) if by_sym else 0
    coverage_avg = sum(by_sym.values()) / len(by_sym) if by_sym else 0

    logger.info(
        "backfill_history: wrote %d rows, coverage min=%d max=%d avg=%.1f, %d missing",
        n_written, coverage_min, coverage_max, coverage_avg, len(missing),
    )

    return {
        "n_symbols":       len(syms),
        "n_rows_written":  n_written,
        "period":          period,
        "coverage_min":    coverage_min,
        "coverage_max":    coverage_max,
        "coverage_avg":    coverage_avg,
        "missing_symbols": missing,
    }
