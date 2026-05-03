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

from agent.data_sources.market import get_live_quote, get_next_earnings


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

    return router
