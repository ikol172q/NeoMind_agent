"""A-share / HK / fund / futures data via AkShare — NeoMind
lightweight wrapper.

AkShare is a community library that scrapes free public sources
(Eastmoney, Sina, Tencent, etc.) with no registration. Tradeoffs:

- Pros: free, rich coverage of A-share / HK / public funds / futures
  / macro. Data points the global providers (Finnhub / Yahoo) miss.
- Cons: scraper — upstream site changes can break endpoints; must
  self-throttle to avoid IP bans; occasional stale data.

This module is the **single ingress** for CN data in NeoMind, so
all caching + rate limiting lives in one place. Every outbound
AkShare call goes through ``_throttled_call`` which:

1. Checks a local SQLite cache (``~/.neomind/cn_data_cache.sqlite3``)
   — if a non-expired row matches, returns it without hitting
   upstream.
2. Acquires a process-local lock before the real call so concurrent
   requests serialize (global 1 req/sec floor).
3. Writes the result to cache with a TTL configured per endpoint.

Exposed surface:

- ``get_cn_quote(code)`` — single A-share quote, returns a dict
  shaped like ``StockQuote`` but simplified. Raises
  ``UpstreamError`` on any failure (fail-closed, never stale).
- ``build_cn_router()`` → APIRouter exposing
  ``GET /api/cn/quote/{code}``.

CLAUDE.md note: commercial use concerns — AkShare is MIT-licensed
but the data it scrapes may have upstream TOS restrictions. See
``plans/2026-04-19_fin_dashboard_fusion.md`` §5.1 for the commercial
swap plan (Polygon / iFinD / Wind).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────

# A-share codes are 6 digits (600519, 000001, 300750, 688981)
_A_SHARE_RE = re.compile(r"^\d{6}$")

# Cache DB location. Gets created on first call.
_CACHE_DB = Path.home() / ".neomind" / "cn_data_cache.sqlite3"

# TTLs per endpoint kind (seconds). Short enough for useful updates,
# long enough to respect upstream sources.
_TTL_QUOTE = 60       # A-share live quote
_TTL_FUND = 1800      # fund NAV (updates nightly)
_TTL_FUTURES = 300

# Rate-limit floor. AkShare scrapers + shared backend IPs mean we
# MUST self-throttle. Per-process token bucket with 1 req/sec.
_RATE_LIMIT_SEC = 1.0

_rate_lock = threading.Lock()
_last_call_ts: float = 0.0

# Max retries per AkShare call after transient network errors.
# Tests monkeypatch this to 0 for speed.
_DEFAULT_RETRIES: int = 2


class UpstreamError(RuntimeError):
    """Fail-closed marker: upstream returned nothing usable. The
    caller should surface an error to the user, NOT fall back to
    stale data silently — that is a non-negotiable from the fusion
    plan §C (cross-source sanity)."""


# ── Cache ──────────────────────────────────────────────────────────


def _ensure_cache() -> sqlite3.Connection:
    _CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_CACHE_DB), timeout=5.0)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cn_cache ("
        "  key TEXT PRIMARY KEY, "
        "  payload TEXT NOT NULL, "
        "  expires_at REAL NOT NULL"
        ")"
    )
    return conn


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    try:
        with _ensure_cache() as conn:
            row = conn.execute(
                "SELECT payload, expires_at FROM cn_cache WHERE key=?",
                (key,),
            ).fetchone()
    except Exception as exc:
        logger.debug("cn_data cache read failed: %s", exc)
        return None
    if row is None:
        return None
    payload, expires_at = row
    if expires_at < time.time():
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def _cache_put(key: str, value: Dict[str, Any], ttl: float) -> None:
    try:
        with _ensure_cache() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cn_cache (key, payload, expires_at) "
                "VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), time.time() + ttl),
            )
    except Exception as exc:
        logger.debug("cn_data cache write failed: %s", exc)


# ── Throttled call ─────────────────────────────────────────────────


def _throttled_call(
    cache_key: str,
    ttl: float,
    fn: Callable[[], Dict[str, Any]],
    retries: Optional[int] = None,
) -> Dict[str, Any]:
    """Single entry point for every AkShare call.

    Order: cache hit → return early · else acquire lock · wait for
    rate-limit floor · call fn (with retry + backoff for transient
    network errors) · cache · return. On fn error, do NOT return
    stale cache — raise UpstreamError so the caller can surface it.

    retries: how many extra attempts AFTER the first try, with
    exponential backoff (2s, 4s, ...). Default 2 → up to 3 total
    attempts. Set to 0 in tests for speed.
    """
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if retries is None:
        retries = _DEFAULT_RETRIES

    global _last_call_ts
    with _rate_lock:
        last_exc: Optional[BaseException] = None
        for attempt in range(retries + 1):
            if attempt > 0:
                time.sleep(2.0 * attempt)  # 2s, 4s, 6s backoff
            now = time.time()
            wait = _RATE_LIMIT_SEC - (now - _last_call_ts)
            if wait > 0:
                time.sleep(wait)
            try:
                out = fn()
                _last_call_ts = time.time()
                if not isinstance(out, dict):
                    raise UpstreamError(
                        f"unexpected fn return type: {type(out)}"
                    )
                _cache_put(cache_key, out, ttl)
                return out
            except UpstreamError:
                # Parse-time errors are deterministic; retry won't help.
                raise
            except Exception as exc:
                _last_call_ts = time.time()
                last_exc = exc
                logger.warning(
                    "cn_data attempt %d/%d failed for %s: %s",
                    attempt + 1, retries + 1, cache_key, exc,
                )

    raise UpstreamError(str(last_exc)) from last_exc


# ── Quote ──────────────────────────────────────────────────────────


def _float_or_none(v: Any) -> Optional[float]:
    try:
        f = float(v)
        # Reject NaN / inf
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _parse_bid_ask_em(df: Any, code: str) -> Dict[str, Any]:
    """Parse the item→value DataFrame returned by
    ``ak.stock_bid_ask_em`` into a flat dict."""
    rows = {str(r["item"]): r["value"] for _, r in df.iterrows()}
    price = _float_or_none(rows.get("最新"))
    if price is None:
        raise UpstreamError(f"no 最新 price in response for {code!r}")
    # Volume 总手 is in lots (1 lot = 100 shares)
    vol_lots = _float_or_none(rows.get("总手"))
    volume = int(vol_lots * 100) if vol_lots is not None else None
    return {
        "symbol": code,
        "market": "cn",
        "currency": "CNY",
        "price": price,
        "change": _float_or_none(rows.get("涨跌")),
        "change_pct": _float_or_none(rows.get("涨幅")),
        "volume": volume,
        "turnover": _float_or_none(rows.get("金额")),
        "high": _float_or_none(rows.get("最高")),
        "low": _float_or_none(rows.get("最低")),
        "open": _float_or_none(rows.get("今开")),
        "prev_close": _float_or_none(rows.get("昨收")),
        "limit_up": _float_or_none(rows.get("涨停")),
        "limit_down": _float_or_none(rows.get("跌停")),
        "turnover_rate_pct": _float_or_none(rows.get("换手")),
        "source": "akshare/stock_bid_ask_em",
        "fetched_at": time.time(),
    }


def get_cn_quote(code: str, _ak_call: Optional[Callable] = None) -> Dict[str, Any]:
    """Fetch a live A-share quote. ``code`` is a 6-digit code like
    ``600519`` (沪) or ``000001`` (深) or ``300750`` (创业板) or
    ``688981`` (科创板)."""
    code = str(code).strip()
    if not _A_SHARE_RE.match(code):
        raise ValueError(f"A-share code must be 6 digits, got {code!r}")

    def _real_call():
        # Lazy import so the rest of NeoMind boots without akshare
        # installed. If you hit ImportError here, `pip install
        # akshare` into the active venv.
        if _ak_call is not None:
            df = _ak_call(code)
        else:
            import akshare as ak
            df = ak.stock_bid_ask_em(symbol=code)
        return _parse_bid_ask_em(df, code)

    return _throttled_call(
        cache_key=f"quote:{code}",
        ttl=_TTL_QUOTE,
        fn=_real_call,
    )


# ── History (K-line) ──────────────────────────────────────────────


def _parse_hist_em(df: Any, code: str) -> Dict[str, Any]:
    """Parse ``ak.stock_zh_a_hist`` (Eastmoney) OHLCV DataFrame into
    NeoMind's bars format (compatible with the existing /api/chart
    shape so the same UI can render it)."""
    bars = []
    for _, row in df.iterrows():
        d = str(row["日期"])
        bars.append({
            "date": d + "T00:00:00",
            "open": _float_or_none(row["开盘"]),
            "high": _float_or_none(row["最高"]),
            "low": _float_or_none(row["最低"]),
            "close": _float_or_none(row["收盘"]),
            "volume": int(_float_or_none(row["成交量"]) or 0),
            "turnover": _float_or_none(row["成交额"]),
            "change_pct": _float_or_none(row["涨跌幅"]),
            "turnover_rate_pct": _float_or_none(row["换手率"]),
        })
    if not bars:
        raise UpstreamError(f"no hist rows for {code!r}")
    return {
        "symbol": code,
        "market": "cn",
        "currency": "CNY",
        "bars": bars,
        "source": "akshare/stock_zh_a_hist",
        "fetched_at": time.time(),
    }


def _parse_hist_sina(df: Any, code: str) -> Dict[str, Any]:
    """Parse ``ak.stock_zh_a_daily`` (Sina) OHLCV.
    Columns: date / open / high / low / close / volume / amount /
    outstanding_share / turnover (fraction, 0.0077 = 0.77%).
    Sina's ``volume`` is already in shares (not lots)."""
    bars = []
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        turnover_frac = _float_or_none(row.get("turnover"))
        bars.append({
            "date": d + "T00:00:00",
            "open": _float_or_none(row["open"]),
            "high": _float_or_none(row["high"]),
            "low": _float_or_none(row["low"]),
            "close": _float_or_none(row["close"]),
            "volume": int(_float_or_none(row["volume"]) or 0),
            "turnover": _float_or_none(row.get("amount")),
            "turnover_rate_pct": (turnover_frac * 100) if turnover_frac is not None else None,
        })
    if not bars:
        raise UpstreamError(f"no hist rows for {code!r}")
    return {
        "symbol": code,
        "market": "cn",
        "currency": "CNY",
        "bars": bars,
        "source": "akshare/stock_zh_a_daily_sina",
        "fetched_at": time.time(),
    }


def _sina_prefix(code: str) -> str:
    """Prefix A-share code for Sina endpoint: sh/sz/bj."""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sh{code}"  # default sensible


def get_cn_history(
    code: str,
    days: int = 90,
    adjust: str = "qfq",
    _ak_call: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Daily K-line for the last ``days`` calendar days. ``adjust``:
    ``qfq`` forward-adjusted (default, best for technical analysis),
    ``hfq`` backward, ``""`` raw.
    """
    import datetime as dt
    code = str(code).strip()
    if not _A_SHARE_RE.match(code):
        raise ValueError(f"A-share code must be 6 digits, got {code!r}")
    if adjust not in ("qfq", "hfq", ""):
        raise ValueError(f"adjust must be qfq|hfq|'' got {adjust!r}")
    days = max(1, min(int(days), 3650))

    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")

    def _real_call():
        if _ak_call is not None:
            df = _ak_call(code, start, end, adjust)
            return _parse_hist_em(df, code)
        import akshare as ak
        # Try Sina first (more reliable; Eastmoney often rate-limits
        # the K-line endpoint). Fall back to Eastmoney if Sina errors.
        try:
            df = ak.stock_zh_a_daily(
                symbol=_sina_prefix(code),
                start_date=start, end_date=end, adjust=adjust,
            )
            return _parse_hist_sina(df, code)
        except Exception as exc_sina:
            logger.warning(
                "Sina hist failed for %s (%s); trying Eastmoney",
                code, exc_sina,
            )
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust=adjust,
            )
            return _parse_hist_em(df, code)

    return _throttled_call(
        cache_key=f"hist:{code}:{days}:{adjust}",
        ttl=_TTL_QUOTE,  # daily bars update EOD, short TTL fine
        fn=_real_call,
    )


# ── Fundamentals (basic info) ──────────────────────────────────────


def _parse_info_em(df: Any, code: str) -> Dict[str, Any]:
    """Parse ``ak.stock_individual_info_em`` into a flat dict.
    Returned fields: 股票简称, 总市值, 流通市值, 总股本, 流通股,
    行业, 上市时间. No PE/PB — use a separate endpoint for those."""
    rows = {str(r["item"]): r["value"] for _, r in df.iterrows()}
    name = str(rows.get("股票简称") or "").strip()
    if not name:
        raise UpstreamError(f"no 股票简称 for {code!r}")

    def _int_or_none(v):
        try:
            return int(float(v))
        except Exception:
            return None

    return {
        "symbol": code,
        "name": name,
        "industry": str(rows.get("行业") or "").strip() or None,
        "listed_date": str(rows.get("上市时间") or "").strip() or None,
        "total_shares": _int_or_none(rows.get("总股本")),
        "float_shares": _int_or_none(rows.get("流通股")),
        "market_cap": _float_or_none(rows.get("总市值")),
        "float_market_cap": _float_or_none(rows.get("流通市值")),
        "last_price": _float_or_none(rows.get("最新")),
        "source": "akshare/stock_individual_info_em",
        "fetched_at": time.time(),
    }


def get_cn_info(code: str, _ak_call: Optional[Callable] = None) -> Dict[str, Any]:
    """Basic fundamentals (市值 / 流通 / 行业 / 上市) for an A-share."""
    code = str(code).strip()
    if not _A_SHARE_RE.match(code):
        raise ValueError(f"A-share code must be 6 digits, got {code!r}")

    def _real_call():
        if _ak_call is not None:
            df = _ak_call(code)
        else:
            import akshare as ak
            df = ak.stock_individual_info_em(symbol=code)
        return _parse_info_em(df, code)

    return _throttled_call(
        cache_key=f"info:{code}",
        ttl=3600,  # basic info rarely changes intraday
        fn=_real_call,
    )


# ── Router ─────────────────────────────────────────────────────────


def build_cn_router(ak_call: Optional[Callable] = None) -> APIRouter:
    """FastAPI router exposing /api/cn/* endpoints.

    ``ak_call`` is test-injectable; production leaves it None so the
    real ``akshare.stock_bid_ask_em`` is used lazily.
    """
    router = APIRouter()

    @router.get("/api/cn/quote/{code}")
    def cn_quote(code: str) -> JSONResponse:
        try:
            q = get_cn_quote(code, _ak_call=ak_call)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except UpstreamError as exc:
            raise HTTPException(
                502,
                f"AkShare upstream failed for {code!r}: {exc}. "
                f"Note: may indicate reverse-engineering drift or "
                f"rate-limit throttling."
            )
        except Exception as exc:
            logger.exception("cn_quote unexpected error")
            raise HTTPException(500, f"internal error: {exc}")
        return JSONResponse(content=q)

    @router.get("/api/cn/history/{code}")
    def cn_history(
        code: str,
        days: int = 90,
        adjust: str = "qfq",
    ) -> JSONResponse:
        try:
            h = get_cn_history(code, days=days, adjust=adjust)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except UpstreamError as exc:
            raise HTTPException(502, f"hist upstream failed: {exc}")
        return JSONResponse(content=h)

    @router.get("/api/cn/info/{code}")
    def cn_info(code: str) -> JSONResponse:
        try:
            i = get_cn_info(code)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except UpstreamError as exc:
            raise HTTPException(502, f"info upstream failed: {exc}")
        return JSONResponse(content=i)

    @router.get("/api/cn/cache/status")
    def cache_status() -> JSONResponse:
        """Debug helper — how many rows are in the cache, expiry."""
        try:
            with _ensure_cache() as conn:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(expires_at), MAX(expires_at) "
                    "FROM cn_cache"
                ).fetchone()
        except Exception as exc:
            return JSONResponse(content={"error": str(exc)}, status_code=500)
        count, min_exp, max_exp = row or (0, None, None)
        now = time.time()
        return JSONResponse(content={
            "rows": count,
            "earliest_expiry_in_s": (min_exp - now) if min_exp else None,
            "latest_expiry_in_s": (max_exp - now) if max_exp else None,
            "db_path": str(_CACHE_DB),
        })

    return router
