"""Portfolio attribution — which position (and sector) drove today's PnL.

One endpoint, three breakdowns. Same data the portfolio heatmap
already shows, just summed and ranked so "what moved me today?"
is a 1-second read.

Math is simple: per-position today's contribution = (current -
yesterday's close) × qty. Sum to portfolio; roll up to sector.

10-min cache per project. Depends on synthesis + yfinance history.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects, synthesis

logger = logging.getLogger(__name__)

_TTL_S = 600.0
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str) -> Optional[Dict[str, Any]]:
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


def _prior_closes(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Batch yfinance lookup — each symbol's close on the session
    before the current one. Used as the baseline for today's PnL."""
    import yfinance as yf
    if not symbols:
        return {}
    df = yf.download(
        symbols if len(symbols) > 1 else symbols,
        period="5d",
        interval="1d",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    out: Dict[str, Optional[float]] = {}
    for sym in symbols:
        try:
            # yf.download always returns multi-level columns (Ticker →
            # field) when group_by='ticker', even for a single symbol.
            # Access by ticker key; fall back to the flat Close if the
            # structure differs.
            sub = None
            try:
                sub = df[sym]["Close"].dropna()
            except Exception:
                try:
                    sub = df["Close"].dropna()
                except Exception:
                    sub = None
            if sub is not None and len(sub) >= 2:
                out[sym] = float(sub.iloc[-2])
            else:
                out[sym] = None
        except Exception as exc:
            logger.debug("prior_close failed for %s: %s", sym, exc)
            out[sym] = None
    return out


def _compute(project_id: str) -> Dict[str, Any]:
    proj = synthesis.synth_project_data(project_id)
    positions = proj.get("positions") or []
    if not positions:
        return {
            "project_id": project_id,
            "by_position": [],
            "by_sector": [],
            "total_pnl_today_usd": 0.0,
            "fetched_at_epoch": int(time.time()),
        }

    symbols = [p["symbol"] for p in positions]
    priors = _prior_closes(symbols)

    # Sector lookup via symbol synthesis (already cached elsewhere).
    sector_by_sym: Dict[str, str] = {}
    for sym in symbols:
        try:
            s = synthesis.synth_symbol_data(project_id, sym)
            sector_by_sym[sym] = (s.get("sector") or {}).get("sector") or "Unknown"
        except Exception:
            sector_by_sym[sym] = "Unknown"

    by_position: List[Dict[str, Any]] = []
    total_usd = 0.0
    for p in positions:
        sym = p["symbol"]
        cur = float(p.get("current_price") or 0)
        qty = float(p.get("quantity") or 0)
        prior = priors.get(sym)
        if prior is None or qty == 0:
            contrib = 0.0
            contrib_pct = None
        else:
            contrib = (cur - prior) * qty
            contrib_pct = ((cur - prior) / prior * 100.0) if prior else None
        total_usd += contrib
        by_position.append({
            "symbol": sym,
            "sector": sector_by_sym.get(sym, "Unknown"),
            "quantity": qty,
            "prior_close": round(prior, 3) if prior is not None else None,
            "current_price": round(cur, 3),
            "contrib_usd": round(contrib, 2),
            "contrib_pct_today": round(contrib_pct, 3) if contrib_pct is not None else None,
        })

    by_position.sort(key=lambda r: r["contrib_usd"], reverse=True)

    # Sector rollup
    sector_totals: Dict[str, float] = {}
    for r in by_position:
        sector_totals[r["sector"]] = sector_totals.get(r["sector"], 0.0) + r["contrib_usd"]
    by_sector = [
        {
            "sector": s,
            "contrib_usd": round(v, 2),
            "contrib_pct_of_total": round(v / total_usd * 100.0, 2) if total_usd else None,
        }
        for s, v in sector_totals.items()
    ]
    by_sector.sort(key=lambda r: r["contrib_usd"], reverse=True)

    # Per-position % of total
    for r in by_position:
        r["pct_of_total"] = (
            round(r["contrib_usd"] / total_usd * 100.0, 2) if total_usd else None
        )

    return {
        "project_id": project_id,
        "by_position": by_position,
        "by_sector": by_sector,
        "total_pnl_today_usd": round(total_usd, 2),
        "fetched_at_epoch": int(time.time()),
    }


def build_attribution_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/attribution")
    def attribution(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} not registered")
        if not fresh:
            cached = _cached(project_id)
            if cached is not None:
                return cached
        try:
            data = _compute(project_id)
        except ImportError as exc:
            raise HTTPException(503, f"yfinance unavailable: {exc}")
        except Exception as exc:
            logger.exception("attribution failed")
            raise HTTPException(502, f"attribution failed: {exc}")
        _put(project_id, data)
        return data

    return router
