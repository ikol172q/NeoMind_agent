"""Watchlist + supply chain scanner.

Runs against raw_market_data (already daily-refreshed by regime_daily
scheduler).  Emits signal_events when a watched ticker (or one of its
supply-chain neighbors) crosses one of the configured thresholds:

  - price_break:   close crosses 200d MA (up / down)
  - rsi_extreme:   RSI(14) > 70 or < 30
  - vol_spike:     volume > 2σ above 20d avg
  - new_high:      close at 52-week high
  - new_low:       close at 52-week low
  - mom_reversal:  RSI(14) crosses 50 from extreme

Idempotency: deduplicate by (ticker, signal_type, calendar_day).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _wilder_rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """Wilder (1978) RSI."""
    if len(closes) < n + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    # Wilder smoothing
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def _ma(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _volume_zscore(volumes: List[float]) -> Optional[float]:
    if len(volumes) < 21:
        return None
    last = volumes[-1]
    base = volumes[-21:-1]
    mean = sum(base) / len(base)
    var = sum((v - mean) ** 2 for v in base) / max(1, len(base) - 1)
    sigma = var ** 0.5
    if sigma <= 0:
        return None
    return (last - mean) / sigma


def _already_emitted_today(ticker: str, signal_type: str) -> bool:
    """Idempotency check: did we emit this (ticker, signal_type) today?"""
    from agent.finance.persistence import connect
    today = date.today().isoformat()
    with connect() as conn:
        cur = conn.execute(
            "SELECT event_id FROM signal_events "
            "WHERE ticker = ? AND signal_type = ? AND date(detected_at) = ?",
            (ticker, signal_type, today),
        )
        return cur.fetchone() is not None


def scan_ticker(ticker: str) -> Dict[str, Any]:
    """Scan one ticker, emit any signals that fire.  Returns count."""
    from agent.finance.regime.signals import emit_event
    from agent.finance.persistence import connect

    # Pull last 260 trading days (one year + buffer)
    with connect() as conn:
        cur = conn.execute(
            "SELECT trade_date, close, volume FROM raw_market_data "
            "WHERE symbol = ? ORDER BY trade_date DESC LIMIT 260",
            (ticker,),
        )
        rows = cur.fetchall()
    if len(rows) < 50:
        return {"ticker": ticker, "emitted": 0, "skipped": "insufficient_data",
                "n_rows": len(rows)}

    rows = list(reversed(rows))   # ascending date
    closes  = [float(r["close"])  for r in rows]
    volumes = [float(r["volume"]) for r in rows if r["volume"] is not None]
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else last_close

    n_emitted = 0

    # 1. RSI extremes
    rsi = _wilder_rsi(closes, 14)
    if rsi is not None:
        if rsi > 70 and not _already_emitted_today(ticker, "rsi_overbought"):
            emit_event(
                "watchlist", signal_type="rsi_overbought", severity="med",
                ticker=ticker,
                title=f"{ticker} RSI={rsi:.0f} (overbought)",
                body={"rsi_14": round(rsi, 2), "close": last_close},
            )
            n_emitted += 1
        elif rsi < 30 and not _already_emitted_today(ticker, "rsi_oversold"):
            emit_event(
                "watchlist", signal_type="rsi_oversold", severity="med",
                ticker=ticker,
                title=f"{ticker} RSI={rsi:.0f} (oversold)",
                body={"rsi_14": round(rsi, 2), "close": last_close},
            )
            n_emitted += 1

    # 2. 200d MA cross
    ma200 = _ma(closes, 200)
    prev_ma200 = _ma(closes[:-1], 200)
    if ma200 and prev_ma200:
        crossed_up = prev_close < prev_ma200 and last_close > ma200
        crossed_down = prev_close > prev_ma200 and last_close < ma200
        if crossed_up and not _already_emitted_today(ticker, "ma200_cross_up"):
            emit_event(
                "watchlist", signal_type="ma200_cross_up", severity="high",
                ticker=ticker,
                title=f"{ticker} 突破 200d MA (${ma200:.2f}) — bullish",
                body={"close": last_close, "ma200": round(ma200, 2)},
            )
            n_emitted += 1
        elif crossed_down and not _already_emitted_today(ticker, "ma200_cross_down"):
            emit_event(
                "watchlist", signal_type="ma200_cross_down", severity="high",
                ticker=ticker,
                title=f"{ticker} 跌破 200d MA (${ma200:.2f}) — bearish",
                body={"close": last_close, "ma200": round(ma200, 2)},
            )
            n_emitted += 1

    # 3. 52-week high/low
    if len(closes) >= 252:
        last_252 = closes[-252:]
        if last_close >= max(last_252) and not _already_emitted_today(ticker, "new_52w_high"):
            emit_event(
                "watchlist", signal_type="new_52w_high", severity="high",
                ticker=ticker,
                title=f"{ticker} 创 52 周新高 ${last_close:.2f}",
                body={"close": last_close, "prev_high": max(last_252[:-1])},
            )
            n_emitted += 1
        if last_close <= min(last_252) and not _already_emitted_today(ticker, "new_52w_low"):
            emit_event(
                "watchlist", signal_type="new_52w_low", severity="high",
                ticker=ticker,
                title=f"{ticker} 创 52 周新低 ${last_close:.2f}",
                body={"close": last_close, "prev_low": min(last_252[:-1])},
            )
            n_emitted += 1

    # 4. Volume spike
    vol_z = _volume_zscore(volumes)
    if vol_z is not None and vol_z > 2.0:
        if not _already_emitted_today(ticker, "vol_spike"):
            emit_event(
                "watchlist", signal_type="vol_spike",
                severity="med" if vol_z < 3 else "high",
                ticker=ticker,
                title=f"{ticker} 成交量异常 (z={vol_z:.1f}σ)",
                body={"volume_zscore": round(vol_z, 2),
                      "today_vol": volumes[-1]},
            )
            n_emitted += 1

    return {"ticker": ticker, "emitted": n_emitted}


def run_watchlist_scan() -> Dict[str, Any]:
    """Scan all watchlist tickers + supply-chain expansion."""
    from agent.finance.regime.signals import (
        list_watchlist, expand_supply_chain,
    )

    t0 = time.monotonic()
    wl = list_watchlist()
    user_tickers = [w["ticker"] for w in wl]
    expanded = expand_supply_chain(user_tickers)
    all_tickers = sorted(set(user_tickers + expanded))
    logger.info("[watchlist_scanner] %d user + %d supply chain = %d total",
                len(user_tickers), len(expanded), len(all_tickers))

    n_emitted = 0
    n_skipped = 0
    per_ticker: List[Dict[str, Any]] = []
    for t in all_tickers:
        try:
            r = scan_ticker(t)
            per_ticker.append(r)
            n_emitted += r.get("emitted", 0)
            if "skipped" in r:
                n_skipped += 1
        except Exception as exc:
            logger.warning("scan failed for %s: %s", t, exc)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return {
        "scanner":     "watchlist",
        "n_tickers":   len(all_tickers),
        "n_user":      len(user_tickers),
        "n_expanded":  len(expanded),
        "n_emitted":   n_emitted,
        "n_skipped":   n_skipped,
        "took_ms":     elapsed_ms,
        "per_ticker":  per_ticker,
    }
