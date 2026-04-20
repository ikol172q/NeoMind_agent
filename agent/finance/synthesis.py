"""Dashboard synthesis — the load-bearing middleware that turns
13 disconnected widget endpoints into a single "what does the
dashboard know about <X> right now" object.

Two endpoints:

    GET /api/synthesis/symbol/{symbol}?project_id=X
        Everything pertaining to a single ticker: quote, your
        paper position (if any), watchlist note (if any), technical
        pills (trend / momentum / 20d range position), upcoming
        earnings, RS rank, sector tag, recent news headlines,
        current market sentiment.

    GET /api/synthesis/project?project_id=X
        Project-wide snapshot: watchlist, paper positions, account
        summary, upcoming earnings across watchlist, sentiment,
        top-news titles, today's sector winners / losers.

Both are "best effort" — each sub-fetch is wrapped so a failing
upstream returns a null section rather than 502-ing the whole
response. The consumer (widget or chat context-injector) decides
how to present missing pieces.

Cache: 60s per composite at the top level. Individual subsystems
keep their own caches already.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from agent.finance import investment_projects

logger = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._-]{1,16}$")
_TTL_S = 60.0

_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _cached(key: str):
    with _cache_lock:
        e = _cache.get(key)
    if e is None:
        return None
    if time.time() - e[0] > _TTL_S:
        return None
    return e[1]


def _put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _detect_market(sym: str) -> str:
    if re.match(r"^\d{6}$", sym):
        return "CN"
    if re.match(r"^\d{4,5}$", sym):
        return "HK"
    return "US"


# ── Technical pill computation ──────────────────────────

def _technical_pills(hist_close: "pandas.Series") -> Optional[Dict[str, Any]]:
    """Compute trend / momentum / range-position signals.

    Trend:        SMA20 vs SMA50 + price vs SMA20
    Momentum:     RSI-14
    Range:        where the current close sits in the 20d high-low band (0-100)
    """
    try:
        import pandas as pd
    except Exception:
        return None
    s = hist_close.dropna()
    if len(s) < 55:
        return None

    sma20 = s.rolling(20).mean()
    sma50 = s.rolling(50).mean()
    last = float(s.iloc[-1])
    sma20_last = float(sma20.iloc[-1])
    sma50_last = float(sma50.iloc[-1])

    # Trend pill
    if sma20_last > sma50_last and last > sma20_last:
        trend = "up"
    elif sma20_last < sma50_last and last < sma20_last:
        trend = "down"
    else:
        trend = "mixed"

    # RSI-14 (standard Wilder smoothing)
    diff = s.diff().dropna()
    up = diff.clip(lower=0)
    dn = -diff.clip(upper=0)
    roll_up = up.ewm(alpha=1 / 14, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1 / 14, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0, float("nan"))
    rsi = (100 - 100 / (1 + rs)).dropna()
    rsi_last = float(rsi.iloc[-1]) if len(rsi) else None

    if rsi_last is None:
        momentum = "unknown"
    elif rsi_last >= 55:
        momentum = "up"
    elif rsi_last <= 45:
        momentum = "down"
    else:
        momentum = "neutral"

    # 20d range position
    last20 = s.tail(20)
    hi, lo = float(last20.max()), float(last20.min())
    rng_pct = None if hi == lo else round((last - lo) / (hi - lo) * 100.0, 1)

    # 5d short-term % change
    r5d = None
    if len(s) >= 6:
        r5d = round((last / float(s.iloc[-6]) - 1.0) * 100.0, 2)

    return {
        "trend": trend,
        "momentum": momentum,
        "rsi14": round(rsi_last, 1) if rsi_last is not None else None,
        "sma20_above": last > sma20_last,
        "range_pos_20d_pct": rng_pct,
        "return_5d_pct": r5d,
    }


# ── Sub-fetches (all swallow errors, return None on failure) ───

def _fetch_quote(symbol: str, market: str) -> Optional[Dict[str, Any]]:
    """Sync quote — avoids the async DataHub so synthesis can run
    inside FastAPI's threadpool without wrestling event loops."""
    try:
        if market == "CN":
            from agent.finance import cn_data
            q = cn_data.get_cn_quote(symbol)
            if q is None:
                return None
            return {
                "price": q.get("price"),
                "change_pct": q.get("change_pct"),
                "volume": q.get("volume"),
                "source": "akshare",
            }
        # US / HK — go direct to yfinance, same path the hub uses.
        import yfinance as yf
        t = yf.Ticker(symbol)
        fi = t.fast_info
        last = float(fi.last_price)
        prev = float(fi.previous_close)
        pct = ((last - prev) / prev * 100.0) if prev else None
        return {
            "price": round(last, 3),
            "change_pct": round(pct, 3) if pct is not None else None,
            "volume": int(getattr(fi, "last_volume", 0) or 0) or None,
            "source": "yfinance",
        }
    except Exception as exc:
        logger.debug("synth: quote failed for %s: %s", symbol, exc)
        return None


def _paper_state(project_id: str) -> Optional[Dict[str, Any]]:
    """Read the paper-engine state.json directly. Simpler than
    wrestling the closure-bound engine dict inside dashboard_server."""
    try:
        path = investment_projects.get_project_dir(project_id) / "paper_trading" / "state.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("synth: paper state read failed: %s", exc)
        return None


def _pnl_for_position(p: Dict[str, Any]) -> tuple[float, float]:
    """Compute unrealized_pnl / pct from state-file fields."""
    qty = float(p.get("quantity") or 0)
    entry = float(p.get("entry_price") or 0)
    cur = float(p.get("current_price") or entry)
    side = str(p.get("side") or "buy").lower()
    if not entry or not qty:
        return 0.0, 0.0
    if side == "sell":
        pnl = (entry - cur) * qty
        pct = (entry - cur) / entry * 100.0
    else:
        pnl = (cur - entry) * qty
        pct = (cur - entry) / entry * 100.0
    return round(pnl, 4), round(pct, 4)


def _fetch_position(project_id: str, symbol: str) -> Optional[Dict[str, Any]]:
    st = _paper_state(project_id)
    if st is None:
        return None
    for p in st.get("positions", []):
        if str(p.get("symbol", "")).upper() == symbol.upper():
            pnl, pct = _pnl_for_position(p)
            return {
                "quantity": p.get("quantity"),
                "entry_price": p.get("entry_price"),
                "current_price": p.get("current_price"),
                "side": p.get("side"),
                "opened_at": p.get("opened_at"),
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pct,
            }
    return None


def _fetch_watch_entry(project_id: str, symbol: str, market: str) -> Optional[Dict[str, Any]]:
    try:
        path = investment_projects.get_project_dir(project_id) / "watchlist.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        for e in data.get("entries", []):
            if (
                str(e.get("market", "")).upper() == market
                and str(e.get("symbol", "")).upper() == symbol.upper()
            ):
                return {"note": e.get("note", ""), "added_at": e.get("added_at")}
    except Exception as exc:
        logger.debug("synth: watchlist failed: %s", exc)
    return None


def _fetch_technical(symbol: str, market: str) -> Optional[Dict[str, Any]]:
    try:
        if market == "US":
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                return None
            return _technical_pills(hist["Close"])
        if market == "CN":
            import akshare as ak
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date="20240101",
                adjust="qfq",
            )
            if df is None or df.empty:
                return None
            return _technical_pills(df["收盘"])
    except Exception as exc:
        logger.debug("synth: technical failed for %s: %s", symbol, exc)
    return None


def _fetch_earnings(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from agent.finance import earnings
        recs = earnings.fetch_symbols([symbol])
        if not recs:
            return None
        r = recs[0]
        if r.get("error"):
            return None
        # Trim to the fields chat / widget most care about
        return {
            "next_earnings_date": r.get("next_earnings_date"),
            "days_until": r.get("days_until"),
            "avg_abs_move_pct": r.get("avg_abs_move_pct"),
            "rv_30d_pct": r.get("rv_30d_pct"),
            "atm_iv_pct": r.get("atm_iv_pct"),
            "eps_estimate_avg": r.get("eps_estimate_avg"),
        }
    except Exception as exc:
        logger.debug("synth: earnings failed for %s: %s", symbol, exc)
    return None


def _fetch_rs(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from agent.finance import relative_strength as rs
        payload = rs._cached("US")
        if payload is None:
            rows = rs._compute_us_rs()
            payload = {
                "market": "US",
                "count": len(rows),
                "entries": rows,
                "fetched_at_epoch": int(time.time()),
            }
            rs._put("US", payload)
        entries = payload.get("entries", [])
        # Rank by 3m return desc
        sorted_by_3m = sorted(
            [e for e in entries if e.get("return_3m") is not None],
            key=lambda e: -e["return_3m"],
        )
        rank = next(
            (i + 1 for i, e in enumerate(sorted_by_3m) if e["symbol"].upper() == symbol.upper()),
            None,
        )
        if rank is None:
            return None  # not in S&P 100 universe
        row = next(e for e in entries if e["symbol"].upper() == symbol.upper())
        return {
            "rank_in_sp100_3m": rank,
            "universe_size": len(sorted_by_3m),
            "return_3m": row.get("return_3m"),
            "return_6m": row.get("return_6m"),
            "return_ytd": row.get("return_ytd"),
        }
    except Exception as exc:
        logger.debug("synth: rs failed for %s: %s", symbol, exc)
    return None


def _fetch_sector(symbol: str, market: str) -> Optional[Dict[str, Any]]:
    try:
        if market == "US":
            import yfinance as yf
            info = yf.Ticker(symbol).info or {}
            sector = info.get("sector")
            industry = info.get("industry")
            if not sector:
                return None
            return {"sector": sector, "industry": industry}
        if market == "CN":
            # cn_data has the raw endpoint we already expose at /api/cn/info
            from agent.finance import cn_data
            info = cn_data.get_cn_info(symbol)
            if info is None:
                return None
            return {"sector": info.get("industry"), "industry": info.get("industry")}
    except Exception as exc:
        logger.debug("synth: sector failed for %s: %s", symbol, exc)
    return None


def _fetch_news(symbol: str, limit: int = 5) -> Optional[Dict[str, Any]]:
    try:
        from agent.finance import news_hub
        entries = news_hub.fetch_entries(limit=50, symbols=[symbol])
        headlines = [
            {"title": e.title, "url": e.url, "feed_title": e.feed_title, "published_at": e.published_at}
            for e in entries[:limit]
        ]
        return {
            "count_7d_approx": len(entries),
            "headlines": headlines,
        }
    except Exception as exc:
        logger.debug("synth: news failed for %s: %s", symbol, exc)
    return None


def _fetch_market_sentiment() -> Optional[Dict[str, Any]]:
    try:
        from agent.finance import sentiment
        cached = sentiment._cached()
        if cached is None:
            cached = sentiment._compute()
            sentiment._put(cached)
        return {
            "composite_score": cached.get("composite_score"),
            "label": cached.get("label"),
            "components": cached.get("components"),
        }
    except Exception as exc:
        logger.debug("synth: sentiment failed: %s", exc)
    return None


# ── Endpoints ────────────────────────────────────────────

def build_synthesis_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/synthesis/symbol/{symbol}")
    def synth_symbol(
        symbol: str,
        project_id: str = Query(..., description="project id for position / watchlist context"),
        fresh: bool = Query(False, description="bypass the 60s cache"),
    ) -> Dict[str, Any]:
        sym = symbol.upper()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        cache_key = f"sym::{project_id}::{sym}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        market = _detect_market(sym)

        payload: Dict[str, Any] = {
            "symbol": sym,
            "market": market,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "quote": _fetch_quote(sym, market),
            "position": _fetch_position(project_id, sym),
            "watchlist": _fetch_watch_entry(project_id, sym, market),
            "technical": _fetch_technical(sym, market),
            "earnings": _fetch_earnings(sym) if market == "US" else None,
            "rs": _fetch_rs(sym) if market == "US" else None,
            "sector": _fetch_sector(sym, market),
            "news": _fetch_news(sym),
            "market_sentiment": _fetch_market_sentiment() if market == "US" else None,
        }
        _put(cache_key, payload)
        return payload

    @router.get("/api/synthesis/project")
    def synth_project(
        project_id: str = Query(...),
        fresh: bool = Query(False),
    ) -> Dict[str, Any]:
        if project_id not in investment_projects.list_projects():
            raise HTTPException(404, f"project {project_id!r} is not registered")

        cache_key = f"proj::{project_id}"
        if not fresh:
            cached = _cached(cache_key)
            if cached is not None:
                return cached

        # Watchlist
        watchlist: List[Dict[str, Any]] = []
        try:
            path = investment_projects.get_project_dir(project_id) / "watchlist.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                watchlist = data.get("entries", [])
        except Exception as exc:
            logger.debug("synth: watchlist read failed: %s", exc)

        # Paper state (read state.json directly — avoids the engine
        # accessor that lives inside dashboard_server's closure).
        positions: List[Dict[str, Any]] = []
        account: Optional[Dict[str, Any]] = None
        st = _paper_state(project_id)
        if st is not None:
            for p in st.get("positions", []):
                pnl, pct = _pnl_for_position(p)
                positions.append({
                    "symbol": p.get("symbol"),
                    "quantity": p.get("quantity"),
                    "entry_price": p.get("entry_price"),
                    "current_price": p.get("current_price"),
                    "unrealized_pnl": pnl,
                    "unrealized_pnl_pct": pct,
                })
            acct = st.get("account", {}) or {}
            cash = float(acct.get("cash") or 0)
            realized = float(acct.get("realized_pnl") or 0)
            total_unrealized = sum(p["unrealized_pnl"] for p in positions)
            # Equity = cash + market value of open positions
            mv = sum(
                float(p.get("current_price") or 0) * float(p.get("quantity") or 0)
                for p in st.get("positions", [])
            )
            equity = cash + mv
            initial = float(acct.get("initial_capital") or 100000.0)
            total_pnl = realized + total_unrealized
            account = {
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pnl_pct": round((total_pnl / initial * 100.0) if initial else 0.0, 4),
                "positions": len(positions),
                "realized_pnl": round(realized, 2),
                "unrealized_pnl": round(total_unrealized, 2),
            }

        # Upcoming earnings — union of watchlist US + position US symbols
        earn_syms = {w["symbol"] for w in watchlist if str(w.get("market", "")).upper() == "US"}
        earn_syms.update(p["symbol"] for p in positions)
        upcoming: List[Dict[str, Any]] = []
        if earn_syms:
            try:
                from agent.finance import earnings
                recs = earnings.fetch_symbols(sorted(earn_syms))
                for r in recs:
                    du = r.get("days_until")
                    if du is None or du < -2 or du > 30:
                        continue
                    upcoming.append({
                        "symbol": r.get("symbol"),
                        "next_earnings_date": r.get("next_earnings_date"),
                        "days_until": du,
                        "avg_abs_move_pct": r.get("avg_abs_move_pct"),
                        "atm_iv_pct": r.get("atm_iv_pct"),
                    })
                upcoming.sort(key=lambda r: r["days_until"])
            except Exception as exc:
                logger.debug("synth: project earnings failed: %s", exc)

        # Sectors — use existing US endpoint
        sector_movers: Optional[Dict[str, Any]] = None
        try:
            from agent.finance import sectors
            sec_payload = sectors._cached("US")
            if sec_payload is None:
                secs = sectors._fetch_us_sectors()
                sec_payload = {"sectors": secs}
            secs = sec_payload.get("sectors") or []
            sorted_secs = sorted(secs, key=lambda s: -s.get("change_pct", 0))
            sector_movers = {
                "top": [{"name": s["name"], "change_pct": s["change_pct"]} for s in sorted_secs[:3]],
                "bottom": [{"name": s["name"], "change_pct": s["change_pct"]} for s in sorted_secs[-3:]],
            }
        except Exception as exc:
            logger.debug("synth: sectors failed: %s", exc)

        # Market sentiment
        sentiment_payload = _fetch_market_sentiment()

        # News filtered to watched+held symbols
        relevant_news: List[Dict[str, Any]] = []
        try:
            from agent.finance import news_hub
            all_syms = sorted({
                *earn_syms,
                *(w["symbol"] for w in watchlist),
                *(p["symbol"] for p in positions),
            })
            if all_syms:
                entries = news_hub.fetch_entries(limit=50, symbols=all_syms)
                for e in entries[:15]:
                    relevant_news.append({
                        "title": e.title,
                        "url": e.url,
                        "feed_title": e.feed_title,
                        "published_at": e.published_at,
                    })
        except Exception as exc:
            logger.debug("synth: project news failed: %s", exc)

        payload: Dict[str, Any] = {
            "project_id": project_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "watchlist": watchlist,
            "positions": positions,
            "account": account,
            "upcoming_earnings": upcoming,
            "sector_movers": sector_movers,
            "market_sentiment": sentiment_payload,
            "relevant_news": relevant_news,
        }
        _put(cache_key, payload)
        return payload

    return router
