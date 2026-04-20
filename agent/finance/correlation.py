"""Pairwise correlation matrix across a project's watchlist/positions.

Useful because 5 "diversified" positions often move as one. A
correlation heatmap reveals the hidden concentration without the
user having to eyeball overlapping price charts.

- 90-day daily-return correlation by default.
- Batch yfinance download for efficiency.
- 1-hour cache per (project, window).
- Skips CN/HK — yfinance coverage unreliable there; v1 is US-only.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects

logger = logging.getLogger(__name__)

_TTL_S = 3600.0
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


def _us_symbols(project_id: str) -> List[str]:
    import json
    path = investment_projects.get_project_dir(project_id) / "watchlist.json"
    syms: List[str] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for e in data.get("entries", []):
                if str(e.get("market", "")).upper() == "US":
                    syms.append(e["symbol"])
        except Exception:
            pass
    # Also include paper-position US-style symbols (assume yfinance works).
    ppath = investment_projects.get_project_dir(project_id) / "paper_trading" / "state.json"
    if ppath.exists():
        try:
            ps = json.loads(ppath.read_text(encoding="utf-8"))
            for p in ps.get("positions", []):
                s = p.get("symbol")
                if s and s not in syms:
                    syms.append(s)
        except Exception:
            pass
    return syms


def _compute(project_id: str, days: int) -> Dict[str, Any]:
    syms = _us_symbols(project_id)
    if len(syms) < 2:
        return {
            "project_id": project_id,
            "symbols": syms,
            "matrix": [],
            "window_days": days,
            "note": "need at least 2 US symbols in watchlist/positions",
            "fetched_at_epoch": int(time.time()),
        }

    import yfinance as yf
    period = f"{max(days, 30)}d" if days <= 30 else f"{int(days * 1.5)}d"
    df = yf.download(
        syms,
        period=period,
        interval="1d",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
        threads=False,
    )

    # Build a Close dataframe
    import pandas as pd
    closes: Dict[str, "pandas.Series"] = {}
    for s in syms:
        try:
            col = df[s]["Close"] if len(syms) > 1 else df["Close"]
            closes[s] = col.dropna()
        except Exception as exc:
            logger.debug("no history for %s: %s", s, exc)

    usable = [s for s in syms if s in closes and len(closes[s]) >= 30]
    if len(usable) < 2:
        return {
            "project_id": project_id,
            "symbols": usable,
            "matrix": [],
            "window_days": days,
            "note": "not enough history to correlate",
            "fetched_at_epoch": int(time.time()),
        }

    # Compute returns (daily pct change), align
    ret_df = pd.DataFrame({s: closes[s].pct_change() for s in usable}).dropna()
    if ret_df.shape[0] < 20:
        return {
            "project_id": project_id,
            "symbols": usable,
            "matrix": [],
            "window_days": days,
            "note": "too few overlapping sessions",
            "fetched_at_epoch": int(time.time()),
        }

    tail = ret_df.tail(days)
    corr = tail.corr().round(3)
    matrix: List[List[float]] = []
    for a in usable:
        row: List[float] = []
        for b in usable:
            val = float(corr.loc[a, b]) if a in corr.index and b in corr.columns else 0.0
            row.append(round(val, 3))
        matrix.append(row)

    return {
        "project_id": project_id,
        "symbols": usable,
        "matrix": matrix,
        "window_days": int(tail.shape[0]),
        "note": None,
        "fetched_at_epoch": int(time.time()),
    }


def build_correlation_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/correlation")
    def correlation(
        project_id: str = Query(...),
        days: int = Query(90, ge=20, le=252),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} not registered")
        key = f"{project_id}:{days}"
        if not fresh:
            cached = _cached(key)
            if cached is not None:
                return cached
        try:
            data = _compute(project_id, days)
        except ImportError as exc:
            raise HTTPException(503, f"yfinance/pandas unavailable: {exc}")
        except Exception as exc:
            logger.exception("correlation failed")
            raise HTTPException(502, f"correlation failed: {exc}")
        _put(key, data)
        return data

    return router
