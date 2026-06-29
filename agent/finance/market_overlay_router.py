"""Live market overlay endpoints (yfinance).

Two thin endpoints used by the Stock Research Drawer Overview tab to
overlay live data on top of the (LLM-cached, often stale) profile:

    GET /api/stock/{t}/quote       — live price/cap/PE/52w/sector
    GET /api/stock/{t}/earnings    — next earnings date + estimates

No LLM, no DB persistence — both endpoints are simple read-throughs to
the in-process cache in agent/data_sources/market.py.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from agent.data_sources.market import (
    get_live_quote, get_next_earnings, get_holders, get_fundamentals,
)
from agent.finance.metric_snapshots import read_metrics_asof, list_snapshot_dates


def _normalize_ticker(t: str) -> str:
    t = (t or "").strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", t):
        raise HTTPException(400, f"invalid ticker: {t!r}")
    return t


def build_market_overlay_router() -> APIRouter:
    router = APIRouter(prefix="/api/stock", tags=["market-overlay"])

    @router.get("/{ticker}/quote")
    def quote(ticker: str) -> dict:
        t = _normalize_ticker(ticker)
        q = get_live_quote(t)
        if q is None:
            raise HTTPException(404, f"yfinance has no data for {t}")
        return q.to_dict()

    @router.get("/{ticker}/earnings")
    def earnings(ticker: str) -> dict:
        t = _normalize_ticker(ticker)
        e = get_next_earnings(t)
        if e is None:
            return {"ticker": t, "next_date": None}
        return e.to_dict()

    @router.get("/{ticker}/fundamentals")
    def fundamentals(ticker: str) -> dict:
        """Tier-1 quality/valuation metrics (PEG, margins, growth, FCF,
        ROE, net debt, P/S, P/B, beta, EV/EBITDA) — closes the diagnostic
        chain. yfinance-sourced (mark the source)."""
        t = _normalize_ticker(ticker)
        f = get_fundamentals(t)
        if f is None:
            return {"ticker": t, "supported": False}
        d = f.to_dict()
        d["supported"] = True
        return d

    @router.get("/{ticker}/metrics/asof")
    def metrics_asof(ticker: str, date: str | None = None) -> dict:
        """Verified metric snapshot as-of a past date (latest on-or-before
        `date`; omit for most recent). Reads the metric_snapshot table the
        daily metric_snapshot_pull job fills — current + historical, never
        hand-computed."""
        t = _normalize_ticker(ticker)
        snap = read_metrics_asof(t, date)
        if snap is None:
            return {"ticker": t, "available": False, "dates": list_snapshot_dates(t)}
        snap["available"] = True
        snap["dates"] = list_snapshot_dates(t)
        return snap

    @router.get("/{ticker}/holders")
    def holders(ticker: str) -> dict:
        """Universal ownership: institution / insider %, float-vs-locked
        (供给悬顶), top institutional holders with buy/sell direction.
        Works for any US ticker; from yfinance (mark the source)."""
        t = _normalize_ticker(ticker)
        h = get_holders(t)
        if h is None:
            return {"ticker": t, "supported": False, "top_holders": []}
        d = h.to_dict()
        d["supported"] = True
        return d

    @router.get("/{ticker}/earnings/history")
    def earnings_history(ticker: str, limit: int = 12) -> dict:
        """Phase 3 (2026-05-10): historical beat/miss data from
        cached earnings_history table (populated by the
        earnings_calendar daily job). Avoids hitting yfinance per
        drawer render."""
        from agent.finance.persistence import connect, ensure_schema
        t = _normalize_ticker(ticker)
        ensure_schema()
        with connect() as conn:
            rows = conn.execute(
                "SELECT earnings_date, eps_est, eps_actual, surprise_pct "
                "FROM earnings_history WHERE ticker = ? "
                "ORDER BY earnings_date DESC LIMIT ?",
                (t, limit),
            ).fetchall()
        return {
            "ticker": t,
            "history": [dict(r) for r in rows],
            "count": len(rows),
        }

    return router
