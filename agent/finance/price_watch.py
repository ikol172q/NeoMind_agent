"""Slice 1 surfaces — validated quote + 股价异动 observation.

Two read endpoints over the cross-source validated price:
  GET /api/stock/{t}/validated_quote — price + confidence + divergence + sources
  GET /api/portfolio/price_moves     — holdings whose price moved beyond a
                                       threshold SINCE last review (observation)

Boundary (per 投资理念): price movement alone is an OBSERVATION, never a
buy/sell signal nor a thesis-break — "今天跌了不构成卖出". This surface only
says "X 自上次复盘 ±Y%,去看看",  feeding your own a→b→c→d→e, not deciding.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from agent.data_sources.finnhub_quote import get_finnhub_quote
from agent.data_sources.validated_quote import get_validated_quote
from agent.finance.persistence import connect, ensure_schema
from agent.finance.positions import list_lots

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD_PCT = 6.0   # |move since review| ≥ this surfaces as 异动
_FALLBACK_LOOKBACK_DAYS = 30


def _held() -> List[str]:
    return sorted({(l.get("symbol") or "").upper()
                   for l in list_lots(open_only=True) if l.get("symbol")})


def _anchor(conn, ticker: str) -> str:
    row = conn.execute(
        "SELECT last_reviewed_at FROM user_watchlist WHERE ticker = ?", (ticker,)
    ).fetchone()
    last = row["last_reviewed_at"] if row else None
    if last:
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date().isoformat()
        except Exception:
            pass
    return (datetime.now(timezone.utc) - timedelta(days=_FALLBACK_LOOKBACK_DAYS)).date().isoformat()


def _close_at_or_before(conn, ticker: str, date_iso: str):
    row = conn.execute(
        "SELECT trade_date, close FROM market_data_daily "
        "WHERE symbol = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 1",
        (ticker, date_iso),
    ).fetchone()
    return (row["trade_date"], float(row["close"])) if row and row["close"] else (None, None)


def compute_price_moves(threshold_pct: float = _DEFAULT_THRESHOLD_PCT) -> Dict[str, Any]:
    """Holdings whose TODAY's move exceeds the threshold (the reliable real-time
    anomaly, from Finnhub). Cumulative move-since-review is included as honest
    context — but EOD history (market_data_daily) may be stale, so each carries
    `ref_date` + `ref_stale` rather than pretending it's "since your review"."""
    ensure_schema()
    held = _held()
    moves: List[Dict[str, Any]] = []
    n_stale_ref = 0
    with connect() as conn:
        for tk in held:
            # Portfolio scan uses Finnhub directly (fast, real-time) — the full
            # Finnhub×yfinance cross-check is reserved for the single-ticker
            # /validated_quote (per-ticker yfinance is slow under server throttle).
            fh = get_finnhub_quote(tk)
            cur = fh.get("price") if fh else None
            day = fh.get("day_change_pct") if fh else None
            if cur is None or day is None:
                continue
            anchor_date = _anchor(conn, tk)
            ref_date, ref_close = _close_at_or_before(conn, tk, anchor_date)
            cum = round((cur - ref_close) / ref_close * 100.0, 2) if ref_close else None
            # stale only if EOD lags the review by >7d (a normal 1-3d EOD lag
            # behind a same-day review is expected, not stale)
            ref_stale = False
            if ref_date:
                try:
                    from datetime import date as _date
                    ref_stale = (_date.fromisoformat(anchor_date) - _date.fromisoformat(ref_date)).days > 7
                except Exception:
                    ref_stale = False
            if ref_stale:
                n_stale_ref += 1
            # Trigger on TODAY's move (reliable). Cumulative is context only.
            if abs(day) >= threshold_pct:
                moves.append({
                    "ticker": tk,
                    "price": cur,
                    "day_change_pct": round(day, 2),
                    "move_since_review": cum,
                    "ref_date": ref_date,
                    "ref_stale": ref_stale,
                    "confidence": "finnhub",
                    "sources": ["finnhub"],
                })
        eod_row = conn.execute("SELECT MAX(trade_date) AS m FROM market_data_daily").fetchone()
        eod_asof = eod_row["m"] if eod_row else None
    moves.sort(key=lambda m: -abs(m["day_change_pct"]))
    return {
        "moves": moves,
        "threshold_pct": threshold_pct,
        "n_held": len(held),
        "note": "今日价格异动(观察,非买卖信号);move_since_review 为参考,EOD 数据可能滞后",
        "eod_data_stale": n_stale_ref > 0,
        "eod_asof": eod_asof,
        "asof": datetime.now(timezone.utc).isoformat(),
    }


def build_price_watch_router() -> APIRouter:
    router = APIRouter(tags=["price-watch"])

    @router.get("/api/stock/{ticker}/validated_quote")
    def validated_quote(ticker: str) -> Dict[str, Any]:
        return get_validated_quote(ticker)

    @router.get("/api/portfolio/price_moves")
    def price_moves(
        threshold_pct: float = Query(_DEFAULT_THRESHOLD_PCT, ge=0.0, le=100.0),
    ) -> Dict[str, Any]:
        return compute_price_moves(threshold_pct)

    return router
