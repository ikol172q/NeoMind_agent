"""Earnings calendar + IV tracker.

For a set of US symbols, returns for each:
  - next_earnings_date (ISO yyyy-mm-dd, or None)
  - days_until (int, negative if the date is past)
  - eps_estimate (analyst average consensus from yfinance calendar)
  - last post-earnings moves: list of (date, pct) for up to the last
    4 reported quarters — close-day-before vs close-day-after %.
  - avg_abs_move: mean |%| of those moves; None if no history
  - rv_30d: annualised 30-day realised vol, percent
  - atm_iv: ATM call implied volatility from the nearest option
    expiry, percent (annualised, per yfinance convention)

Symbol selection:
  - ``symbols=AAPL,MSFT,…`` — explicit comma-sep list (uppercased)
  - ``project_id=<pid>``     — fallback to the project's watchlist,
    US entries only. If neither is given, 400.

Upstream: yfinance. Per-symbol calls are serial; `threads=False`
to avoid the socket leak that killed sector+RS last session.

Caching: 10 min per symbol (earnings dates don't change intraday
and IV/RV shift slowly enough for the widget's 1-min poll). Cache
is per-symbol so a watchlist add doesn't invalidate peers.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,16}$")
_TTL_S = 600.0        # per-symbol cache
_MAX_SYMBOLS = 30     # prevent accidental huge fetches
_HIST_QUARTERS = 4    # look back this many earnings for |move| stats

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


def _watchlist_symbols(project_id: str) -> List[str]:
    """Read US entries out of the project's watchlist.json."""
    if project_id not in investment_projects.list_projects():
        raise HTTPException(404, f"project {project_id!r} is not registered")
    path = investment_projects.get_project_dir(project_id) / "watchlist.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: List[str] = []
    for e in data.get("entries", []):
        if str(e.get("market", "")).upper() != "US":
            continue
        sym = str(e.get("symbol", "")).upper()
        if _SYMBOL_RE.match(sym):
            out.append(sym)
    return out


def _realised_vol_30d(close_series) -> Optional[float]:
    """Annualised 30-day realised vol as a percent."""
    import math
    s = close_series.dropna()
    if len(s) < 21:
        return None
    rets = (s.pct_change().dropna()).tail(30)
    if len(rets) < 10:
        return None
    try:
        stdev = float(rets.std())
    except Exception:
        return None
    return round(stdev * math.sqrt(252.0) * 100.0, 2)


def _post_earnings_moves(hist, earnings_dates_df) -> List[Dict[str, Any]]:
    """For each past reported earnings date, return {date, pct} where
    pct is (close next session / close prior session - 1) * 100."""
    if hist is None or hist.empty or earnings_dates_df is None:
        return []
    try:
        past = earnings_dates_df[earnings_dates_df["Reported EPS"].notna()].head(_HIST_QUARTERS)
    except Exception:
        return []
    moves: List[Dict[str, Any]] = []
    for earn_ts in past.index:
        try:
            d = earn_ts.date()
        except Exception:
            continue
        # prior + next trading sessions around the earnings date
        before = hist.index[hist.index.date <= d]
        after = hist.index[hist.index.date > d]
        if len(before) == 0 or len(after) == 0:
            continue
        try:
            cb = float(hist.loc[before[-1], "Close"])
            ca = float(hist.loc[after[0], "Close"])
        except Exception:
            continue
        if not cb:
            continue
        moves.append({
            "date": d.isoformat(),
            "pct": round((ca / cb - 1.0) * 100.0, 2),
        })
    return moves


def _atm_iv(ticker, spot: Optional[float]) -> Optional[float]:
    """Pull ATM call IV from the nearest option expiry. Returns IV as
    a percent (yfinance stores it as a 0–1 decimal)."""
    if spot is None:
        return None
    try:
        expiries = ticker.options
    except Exception:
        return None
    if not expiries:
        return None
    try:
        chain = ticker.option_chain(expiries[0])
    except Exception:
        return None
    try:
        calls = chain.calls
        if calls is None or calls.empty:
            return None
        idx = (calls["strike"] - spot).abs().idxmin()
        iv = float(calls.loc[idx, "impliedVolatility"])
    except Exception:
        return None
    if not math.isfinite(iv) or iv <= 0:
        return None
    return round(iv * 100.0, 2)


def _fetch_one(symbol: str) -> Dict[str, Any]:
    import yfinance as yf

    t = yf.Ticker(symbol)

    # Next earnings from calendar (dict in recent yfinance)
    next_date: Optional[str] = None
    eps_avg: Optional[float] = None
    eps_high: Optional[float] = None
    eps_low: Optional[float] = None
    try:
        cal = t.calendar or {}
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                try:
                    next_date = ed[0].isoformat()
                except Exception:
                    next_date = str(ed[0])
            eps_avg = cal.get("Earnings Average")
            eps_high = cal.get("Earnings High")
            eps_low = cal.get("Earnings Low")
    except Exception as exc:
        logger.debug("calendar failed for %s: %s", symbol, exc)

    days_until: Optional[int] = None
    if next_date:
        try:
            target = datetime.fromisoformat(next_date).date()
            days_until = (target - datetime.now(timezone.utc).date()).days
        except Exception:
            pass

    # History for RV + post-earnings moves
    try:
        hist = t.history(period="2y", interval="1d", auto_adjust=False)
    except Exception as exc:
        logger.debug("history failed for %s: %s", symbol, exc)
        hist = None

    # Past earnings dates
    try:
        ed_df = t.earnings_dates
    except Exception as exc:
        logger.debug("earnings_dates failed for %s: %s", symbol, exc)
        ed_df = None

    moves = _post_earnings_moves(hist, ed_df) if hist is not None else []
    avg_abs_move = (
        round(sum(abs(m["pct"]) for m in moves) / len(moves), 2)
        if moves else None
    )

    rv_30d = _realised_vol_30d(hist["Close"]) if hist is not None and not hist.empty else None

    spot = None
    try:
        spot = float(t.fast_info.last_price)
    except Exception:
        try:
            if hist is not None and not hist.empty:
                spot = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    atm_iv = _atm_iv(t, spot)

    return {
        "symbol": symbol,
        "next_earnings_date": next_date,
        "days_until": days_until,
        "eps_estimate_avg": _safe_float(eps_avg),
        "eps_estimate_high": _safe_float(eps_high),
        "eps_estimate_low": _safe_float(eps_low),
        "hist_moves": moves,
        "avg_abs_move_pct": avg_abs_move,
        "rv_30d_pct": rv_30d,
        "atm_iv_pct": atm_iv,
        "price": round(spot, 3) if spot is not None else None,
    }


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if not math.isfinite(f):
            return None
        return round(f, 4)
    except Exception:
        return None


def fetch_symbols(symbols: List[str]) -> List[Dict[str, Any]]:
    """Look each symbol up with per-symbol cache. Skip bad ones
    rather than 502-ing the whole request."""
    out: List[Dict[str, Any]] = []
    for sym in symbols:
        cached = _cached(sym)
        if cached is not None:
            out.append(cached)
            continue
        try:
            rec = _fetch_one(sym)
        except ImportError:
            raise
        except Exception as exc:
            logger.warning("earnings fetch failed for %s: %s", sym, exc)
            rec = {"symbol": sym, "error": str(exc)[:160]}
        _put(sym, rec)
        out.append(rec)
    return out


def build_earnings_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/earnings")
    def list_earnings(
        symbols: Optional[str] = Query(None, description="comma-separated US symbols"),
        project_id: Optional[str] = Query(None, description="fall back to this project's watchlist (US only)"),
    ) -> Dict[str, Any]:
        sym_list: List[str] = []
        if symbols:
            for s in symbols.split(","):
                s = s.strip().upper()
                if _SYMBOL_RE.match(s):
                    sym_list.append(s)
        elif project_id:
            sym_list = _watchlist_symbols(project_id)
        else:
            raise HTTPException(400, "need ?symbols=... or ?project_id=...")

        # Dedup + clamp
        seen = set()
        deduped = []
        for s in sym_list:
            if s in seen:
                continue
            seen.add(s)
            deduped.append(s)
        if len(deduped) > _MAX_SYMBOLS:
            deduped = deduped[:_MAX_SYMBOLS]

        if not deduped:
            return {"count": 0, "entries": [], "fetched_at_epoch": int(time.time())}

        try:
            entries = fetch_symbols(deduped)
        except ImportError as exc:
            raise HTTPException(
                503,
                f"yfinance not available: {exc} — install in the dashboard venv",
            )

        # Sort: upcoming first (0+ days), then past (neg days desc), then unknown
        def sort_key(e):
            du = e.get("days_until")
            if du is None:
                return (2, 0)
            if du >= 0:
                return (0, du)
            return (1, -du)
        entries.sort(key=sort_key)

        return {
            "count": len(entries),
            "entries": entries,
            "fetched_at_epoch": int(time.time()),
        }

    return router
