"""Relative-strength grid — ranks a US equity universe by trailing
returns over 3M / 6M / YTD in a single batch yfinance call.

Deliberately US-only for now. A proper CN rank would need ~500 per-
stock ``stock_zh_a_hist`` calls (akshare's spot endpoint carries only
day-of %), which is 30+ s. When we care we can add a separate path
with a narrower universe (HS300 constituents, say).

Universe: S&P 100 (curated, not fetched — the list is stable enough
that it's not worth a network hop on every reload).

Output: one row per symbol with return_3m, return_6m, return_ytd in
percent. Client sorts client-side.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

# S&P 100 — top 100 US large caps. Hand-curated, stable. Refresh the
# list if a major index reshuffle happens; no hot need for dynamic.
_US_UNIVERSE: List[str] = [
    "AAPL","MSFT","NVDA","GOOGL","GOOG","AMZN","META","TSLA","AVGO","JPM",
    "V","WMT","UNH","XOM","MA","JNJ","PG","LLY","HD","CVX",
    "ORCL","COST","MRK","ABBV","NFLX","CRM","KO","BAC","PEP","ADBE",
    "TMO","AMD","MCD","CSCO","ACN","ABT","LIN","WFC","PM","DIS",
    "IBM","CAT","TXN","GE","VZ","INTU","CMCSA","NOW","MS","AXP",
    "DHR","PFE","UNP","NEE","QCOM","ISRG","T","GS","SPGI","BLK",
    "AMGN","RTX","NKE","C","INTC","PLD","AMAT","BKNG","HON","LMT",
    "ELV","MDT","SYK","TJX","DE","VRTX","GILD","ADP","UPS","PYPL",
    "LRCX","MDLZ","REGN","SBUX","SCHW","PANW","BA","MMC","ADI","ETN",
    "KLAC","SO","BX","CB","TMUS","ZTS","FI","BMY","CI","DUK",
]

_TTL_S = 900.0  # 15 min — trailing returns drift slowly
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str):
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry[0] > _TTL_S:
        return None
    return entry[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _compute_us_rs() -> List[Dict[str, Any]]:
    import yfinance as yf
    import pandas as pd
    from datetime import datetime

    # threads=False — see the same note in sectors.py; yfinance's
    # threaded batch path leaks sockets across calls and blows the
    # process's fd limit on macOS.
    df = yf.download(
        _US_UNIVERSE,
        period="1y",
        interval="1d",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    year_start = pd.Timestamp(datetime(datetime.now().year, 1, 1), tz=None)

    rows: List[Dict[str, Any]] = []
    for sym in _US_UNIVERSE:
        try:
            sub = df[sym]["Close"].dropna()
        except Exception:
            continue
        if sub.empty:
            continue
        last = float(sub.iloc[-1])

        def ret(n: int):
            if len(sub) < n + 1:
                return None
            base = float(sub.iloc[-n - 1])
            return (last / base - 1.0) * 100.0 if base else None

        r3m = ret(63)   # ~3 trading months
        r6m = ret(126)  # ~6 trading months
        ytd_slice = sub[sub.index >= year_start]
        r_ytd = None
        if not ytd_slice.empty:
            base = float(ytd_slice.iloc[0])
            r_ytd = (last / base - 1.0) * 100.0 if base else None

        rows.append({
            "symbol": sym,
            "price": round(last, 3),
            "return_3m": None if r3m is None else round(r3m, 2),
            "return_6m": None if r6m is None else round(r6m, 2),
            "return_ytd": None if r_ytd is None else round(r_ytd, 2),
        })
    return rows


def build_rs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/rs")
    def list_rs(
        market: str = Query("US", regex="^(US)$"),
        limit: int = Query(50, ge=1, le=200),
    ) -> Dict[str, Any]:
        key = market.upper()
        cached = _cached(key)
        if cached is not None:
            entries = cached["entries"][:limit]
            return {**cached, "entries": entries, "count": len(entries)}

        try:
            if key == "US":
                rows = _compute_us_rs()
            else:
                raise HTTPException(400, f"market {key!r} not supported yet")
        except ImportError as exc:
            raise HTTPException(
                503,
                f"upstream unavailable for {key}: {exc} "
                f"(install yfinance in the dashboard venv)",
            )
        except Exception as exc:
            logger.exception("rs compute failed for %s", key)
            raise HTTPException(502, f"rs compute failed: {exc}")

        payload = {
            "market": key,
            "count": len(rows),
            "entries": rows,
            "fetched_at_epoch": int(time.time()),
        }
        _put(key, payload)
        return {**payload, "entries": rows[:limit], "count": len(rows[:limit])}

    return router
