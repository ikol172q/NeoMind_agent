"""Live market data fetcher (yfinance) — pure deterministic.

Replaces the LLM-fabricated quick_stats (price/cap/PE) and earnings
catalysts in stock_profiles. yfinance is free, well-tested, and the
single-user / low-volume use case fits its rate-limit profile.

This module only fetches. No LLM. No business logic. Cache TTL is
short (60s for live quotes) since the user expects current prices.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, date, timezone
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class LiveQuote:
    ticker: str
    price: Optional[float]
    market_cap: Optional[float]
    trailing_pe: Optional[float]
    forward_pe: Optional[float]
    fifty_two_week_high: Optional[float]
    fifty_two_week_low: Optional[float]
    day_change_pct: Optional[float]
    year_change_pct: Optional[float]
    name: Optional[str]
    sector: Optional[str]
    industry: Optional[str]
    currency: Optional[str]
    exchange: Optional[str]
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EarningsRef:
    ticker: str
    next_date: Optional[str]            # ISO 'YYYY-MM-DD'
    days_until: Optional[int]
    eps_estimate_avg: Optional[float]
    eps_estimate_low: Optional[float]
    eps_estimate_high: Optional[float]
    revenue_estimate_avg: Optional[float]
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Thread-safe in-process cache (per-ticker, short TTL) ──────────

import threading
import time as _time

_lock = threading.Lock()
_quote_cache: dict[str, tuple[float, LiveQuote]] = {}
_earnings_cache: dict[str, tuple[float, Optional[EarningsRef]]] = {}

QUOTE_TTL_S = 60.0
EARNINGS_TTL_S = 12 * 3600.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_live_quote(ticker: str) -> Optional[LiveQuote]:
    """Live quote + 52w / live PE / sector / industry. Returns None
    if yfinance can't resolve the ticker (e.g. delisted or invalid).
    Cached for 60s per-ticker in-process."""
    ticker = ticker.upper().strip()
    now = _time.time()
    with _lock:
        hit = _quote_cache.get(ticker)
        if hit and (now - hit[0]) < QUOTE_TTL_S:
            return hit[1]

    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        # fast_info may raise individually per attribute; collect defensively
        last = _safe(fi, "last_price")
        prev_close = _safe(fi, "regular_market_previous_close") or _safe(fi, "previous_close")
        day_change = (
            ((last - prev_close) / prev_close * 100.0)
            if (last and prev_close) else None
        )
        year_change_raw = _safe(fi, "year_change")
        # info has the slower-but-richer fields (sector, PE, name)
        info = t.info or {}
        out = LiveQuote(
            ticker=ticker,
            price=last,
            market_cap=_safe(fi, "market_cap") or info.get("marketCap"),
            trailing_pe=info.get("trailingPE"),
            forward_pe=info.get("forwardPE"),
            fifty_two_week_high=_safe(fi, "year_high"),
            fifty_two_week_low=_safe(fi, "year_low"),
            day_change_pct=day_change,
            year_change_pct=(year_change_raw * 100.0) if year_change_raw is not None else None,
            name=info.get("longName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            currency=_safe(fi, "currency") or info.get("currency"),
            exchange=_safe(fi, "exchange") or info.get("exchange"),
            fetched_at=_now_iso(),
        )
    except Exception as exc:
        logger.warning("get_live_quote(%s) failed: %s", ticker, exc)
        return None

    with _lock:
        _quote_cache[ticker] = (now, out)
    return out


def get_next_earnings(ticker: str) -> Optional[EarningsRef]:
    """Next earnings date + EPS / revenue estimates (yfinance.calendar).
    Returns None if no calendar entry. Cached 12h."""
    ticker = ticker.upper().strip()
    now = _time.time()
    with _lock:
        hit = _earnings_cache.get(ticker)
        if hit and (now - hit[0]) < EARNINGS_TTL_S:
            return hit[1]

    try:
        cal = yf.Ticker(ticker).calendar or {}
    except Exception as exc:
        logger.warning("get_next_earnings(%s) failed: %s", ticker, exc)
        return None

    raw_dates = cal.get("Earnings Date") or []
    next_date: Optional[date] = None
    if isinstance(raw_dates, list) and raw_dates:
        # yfinance returns a list of date objects; the soonest future is what we want
        today = date.today()
        future = [d for d in raw_dates if isinstance(d, date) and d >= today]
        next_date = min(future) if future else (raw_dates[0] if isinstance(raw_dates[0], date) else None)

    if next_date is None:
        with _lock:
            _earnings_cache[ticker] = (now, None)
        return None

    days_until = (next_date - date.today()).days
    out = EarningsRef(
        ticker=ticker,
        next_date=next_date.isoformat(),
        days_until=days_until,
        eps_estimate_avg=cal.get("Earnings Average"),
        eps_estimate_low=cal.get("Earnings Low"),
        eps_estimate_high=cal.get("Earnings High"),
        revenue_estimate_avg=cal.get("Revenue Average"),
        fetched_at=_now_iso(),
    )
    with _lock:
        _earnings_cache[ticker] = (now, out)
    return out


def _safe(obj, attr):
    """Safely fetch a yfinance attribute that may raise."""
    try:
        v = getattr(obj, attr)
        return v if not callable(v) else None
    except Exception:
        return None
