"""Fund / ETF deep-dive endpoint.

Consolidates yfinance's fund-specific fields — ``Ticker.info`` for
headline numbers, ``Ticker.funds_data`` for holdings + asset class
breakdown — into one ``/api/fund/{symbol}`` response so the widget
doesn't have to stitch three calls together.

Cache is 30 min per symbol — fund fundamentals (AUM, expense, top
holdings) publish monthly at most.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,16}$")
_TTL_S = 1800.0  # 30 min — fund data moves slowly

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


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except Exception:
        return None


def _as_pct(v) -> Optional[float]:
    """Normalise a yfinance return value to a percent.

    yfinance is inconsistent: ``ytdReturn`` often comes back as a
    percent (-3.96 = -3.96%), but ``threeYearAverageReturn`` comes
    back as a decimal (0.21 = 21%). Use magnitude as the signal —
    if |val| > 1 we assume percent, otherwise decimal-as-pct.
    """
    f = _safe_float(v)
    if f is None:
        return None
    return round(f if abs(f) > 1 else f * 100.0, 3)


def _fetch(symbol: str) -> Dict[str, Any]:
    import yfinance as yf

    t = yf.Ticker(symbol)
    info = {}
    try:
        info = t.info or {}
    except Exception as exc:
        logger.debug("info failed for %s: %s", symbol, exc)

    def g(k):
        return info.get(k)

    # Top holdings: yfinance 0.2.x → Ticker.funds_data.top_holdings
    holdings: List[Dict[str, Any]] = []
    asset_classes: Dict[str, float] = {}
    try:
        fd = t.funds_data
        if hasattr(fd, "top_holdings"):
            th = fd.top_holdings
            if th is not None and not th.empty:
                for sym, row in th.iterrows():
                    pct = _safe_float(row.get("Holding Percent"))
                    if pct is None:
                        continue
                    holdings.append({
                        "symbol": str(sym),
                        "name": str(row.get("Name") or ""),
                        "weight_pct": round(pct * 100.0, 3),
                    })
        if hasattr(fd, "asset_classes"):
            ac = fd.asset_classes or {}
            if isinstance(ac, dict):
                for k, v in ac.items():
                    f = _safe_float(v)
                    if f is None or f == 0:
                        continue
                    asset_classes[str(k)] = round(f * 100.0, 3)
    except Exception as exc:
        logger.debug("funds_data failed for %s: %s", symbol, exc)

    is_etf = bool(holdings) or (g("quoteType") or "").upper() == "ETF" or (g("fundFamily") is not None)

    return {
        "symbol": symbol,
        "short_name": g("shortName") or "",
        "long_name": g("longName") or "",
        "family": g("fundFamily") or "",
        "category": g("category") or "",
        "quote_type": g("quoteType") or "",
        "is_etf": is_etf,
        "nav_price": _safe_float(g("navPrice")) or _safe_float(g("regularMarketPrice")),
        "last_price": _safe_float(g("regularMarketPrice")),
        "total_assets": _safe_float(g("totalAssets")),
        # Expense ratio — yfinance returns this already as a percent
        # (e.g. 0.03 for VTI = 0.03%, NOT 3%). Pass through as-is.
        "expense_ratio_pct": _safe_float(g("netExpenseRatio"))
            if g("netExpenseRatio") is not None
            else _safe_float(g("annualReportExpenseRatio")),
        "yield_pct": _as_pct(g("yield")),
        "ytd_return_pct": _as_pct(g("ytdReturn")),
        "three_year_return_pct": _as_pct(g("threeYearAverageReturn")),
        "five_year_return_pct": _as_pct(g("fiveYearAverageReturn")),
        "trailing_pe": _safe_float(g("trailingPE")),
        "asset_classes": asset_classes,
        "top_holdings": holdings,
    }


def build_funds_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/fund/{symbol}")
    def get_fund(symbol: str) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        cached = _cached(sym)
        if cached is not None:
            return cached
        try:
            data = _fetch(sym)
        except ImportError as exc:
            raise HTTPException(503, f"yfinance unavailable: {exc}")
        except Exception as exc:
            logger.exception("fund fetch failed for %s", sym)
            raise HTTPException(502, f"fund fetch failed: {exc}")
        _put(sym, data)
        return data

    return router
