"""Sector heatmap data source.

Two markets, two very different upstreams:

- ``US``  — batch-fetch SPDR sector ETFs (XLK, XLF, XLE, XLV, XLI,
  XLY, XLP, XLU, XLB, XLRE, XLC) via one ``yf.download`` call. The
  ETF serves as a proxy for its constituent sector; last-close vs
  prior-close gives the day's %.

- ``CN``  — AkShare's ``stock_board_industry_name_em`` returns all
  496 eastmoney industry boards in one shot, already enriched with
  涨跌幅 + 总市值. Sort by market cap desc, keep top ``_CN_TOP_N``
  for a readable treemap.

Both paths cache their output in-process for ``_TTL_S`` seconds so
the UI (which polls every 30 s by default) doesn't hammer upstreams.
Cache is scoped by (market,) so a change on one market can't knock
the other out of date.

No per-user state; no filesystem writes; no project_id required —
sectors are global market context.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

_TTL_S = 60.0
_CN_TOP_N = 30  # most meaningful sectors for a treemap
_US_SPDR: List[tuple[str, str]] = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLE", "Energy"),
    ("XLV", "Health Care"),
    ("XLI", "Industrials"),
    ("XLY", "Consumer Discretionary"),
    ("XLP", "Consumer Staples"),
    ("XLU", "Utilities"),
    ("XLB", "Materials"),
    ("XLRE", "Real Estate"),
    ("XLC", "Communication Services"),
]

_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str):
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    age = time.time() - entry[0]
    if age > _TTL_S:
        return None
    return entry[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


# ── US (SPDR sector ETFs) ────────────────────────────────
def _fetch_us_sectors() -> List[Dict[str, Any]]:
    import yfinance as yf  # late import so the module loads without yfinance

    symbols = [s for s, _ in _US_SPDR]
    # threads=False to avoid leaking sockets across calls — macOS's
    # default fd limit is 256 and the threaded path accumulates fast.
    df = yf.download(
        symbols,
        period="5d",
        interval="1d",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    out: List[Dict[str, Any]] = []
    for sym, name in _US_SPDR:
        try:
            sub = df[sym].dropna()
            if sub.empty or len(sub) < 2:
                continue
            last = float(sub["Close"].iloc[-1])
            prev = float(sub["Close"].iloc[-2])
            vol = float(sub["Volume"].iloc[-1]) if "Volume" in sub else 0.0
            pct = ((last - prev) / prev * 100.0) if prev else 0.0
            out.append({
                "name": name,
                "symbol": sym,
                "price": round(last, 3),
                "change_pct": round(pct, 3),
                # Dollar volume as a proxy for "size" — gives the
                # more-actively-traded sectors a bigger treemap cell.
                "size": round(last * vol, 0),
            })
        except Exception as exc:
            logger.debug("us sector %s skipped: %s", sym, exc)
    return out


# ── CN (eastmoney industry boards) ────────────────────────
def _fetch_cn_sectors() -> List[Dict[str, Any]]:
    import akshare as ak

    df = ak.stock_board_industry_name_em()
    # Columns: 排名, 板块名称, 板块代码, 最新价, 涨跌额, 涨跌幅, 总市值,
    # 换手率, 上涨家数, 下跌家数, 领涨股票, 领涨股票-涨跌幅
    # Sort by 总市值 desc, take top N
    df = df.dropna(subset=["总市值", "涨跌幅"])
    df = df.sort_values("总市值", ascending=False).head(_CN_TOP_N)
    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        try:
            mcap = float(r["总市值"])
            pct = float(r["涨跌幅"])
            out.append({
                "name": str(r["板块名称"]),
                "symbol": str(r["板块代码"]),
                "price": float(r["最新价"]),
                "change_pct": round(pct, 3),
                "size": mcap,
                "leader": str(r.get("领涨股票") or ""),
                "leader_pct": float(r.get("领涨股票-涨跌幅") or 0.0),
            })
        except Exception as exc:
            logger.debug("cn sector %s skipped: %s", r.get("板块名称"), exc)
    return out


def build_sectors_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/sectors")
    def list_sectors(market: str = Query("US", regex="^(US|CN)$")) -> Dict[str, Any]:
        key = market.upper()
        cached = _cached(key)
        if cached is not None:
            return cached
        try:
            if key == "US":
                sectors = _fetch_us_sectors()
            else:
                sectors = _fetch_cn_sectors()
        except ImportError as exc:
            raise HTTPException(
                503,
                f"upstream unavailable for {key}: {exc} "
                f"(install yfinance / akshare in the dashboard venv)",
            )
        except Exception as exc:
            logger.exception("sector fetch failed for %s", key)
            raise HTTPException(502, f"sector fetch failed: {exc}")

        payload = {
            "market": key,
            "count": len(sectors),
            "sectors": sectors,
            "fetched_at_epoch": int(time.time()),
        }
        _put(key, payload)
        return payload

    return router
