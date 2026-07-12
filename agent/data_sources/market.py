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
        # Year change: prefer info["52WeekChange"] (a FRACTION, e.g. 0.383 =
        # +38.3%). fast_info.year_change is NaN in this yfinance build, and the
        # old code did `NaN * 100` → emitted NaN (a latent bug). NaN-guard both
        # (NaN != NaN is True).
        _yc = info.get("52WeekChange")
        if _yc is None or _yc != _yc:
            _yc = year_change_raw
        year_change_pct = (_yc * 100.0) if (_yc is not None and _yc == _yc) else None
        out = LiveQuote(
            ticker=ticker,
            price=last,
            market_cap=_safe(fi, "market_cap") or info.get("marketCap"),
            trailing_pe=info.get("trailingPE"),
            forward_pe=info.get("forwardPE"),
            fifty_two_week_high=_safe(fi, "year_high"),
            fifty_two_week_low=_safe(fi, "year_low"),
            day_change_pct=day_change,
            year_change_pct=year_change_pct,
            name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            currency=_safe(fi, "currency") or info.get("currency"),
            exchange=_safe(fi, "exchange") or info.get("exchange"),
            fetched_at=_now_iso(),
        )
    except Exception as exc:
        logger.warning("get_live_quote(%s) failed: %s", ticker, exc)
        out = None

    # Throttle backfill: yfinance's session gets rate-limited under load,
    # blanking price and silently killing the whole diagnostic. Finnhub is a
    # stable real-time source for the price fields — use it whenever yfinance
    # yields no price (whole-fetch failure OR partial throttle). PE/52w/sector
    # stay yfinance-only (None if throttled), but price/day-move never blank.
    if out is None or out.price is None:
        try:
            from agent.data_sources.finnhub_quote import get_finnhub_quote
            fh = get_finnhub_quote(ticker)
            if fh and fh.get("price"):
                if out is None:
                    out = LiveQuote(
                        ticker=ticker, price=fh["price"], market_cap=None,
                        trailing_pe=None, forward_pe=None,
                        fifty_two_week_high=None, fifty_two_week_low=None,
                        day_change_pct=fh.get("day_change_pct"), year_change_pct=None,
                        name=None, sector=None, industry=None,
                        currency="USD", exchange=None, fetched_at=_now_iso(),
                    )
                else:
                    out.price = fh["price"]
                    if out.day_change_pct is None:
                        out.day_change_pct = fh.get("day_change_pct")
        except Exception as exc:  # noqa: BLE001 — backfill is best-effort
            logger.debug("finnhub backfill failed for %s: %s", ticker, exc)

    if out is None:
        return None
    with _lock:
        _quote_cache[ticker] = (now, out)
    return out


# ─── Ownership / holders (UNIVERSAL: any US ticker incl. foreign) ──

@dataclass
class HoldersInfo:
    ticker: str
    pct_institutions: Optional[float]   # % of shares held by institutions
    pct_insiders: Optional[float]       # % held by insiders
    institutions_count: Optional[int]
    shares_outstanding: Optional[float]
    float_shares: Optional[float]
    pct_float: Optional[float]          # float / shares_outstanding
    pct_locked: Optional[float]         # 1 - pct_float (供给悬顶: low float = locked block, e.g. SoftBank/ARM)
    top_holders: list                   # [{holder, pct_held, shares, value, pct_change, date_reported}]
    source: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


_holders_cache: dict[str, tuple[float, "HoldersInfo"]] = {}
HOLDERS_TTL_S = 6 * 3600.0


def get_holders(ticker: str, top_n: int = 8) -> Optional["HoldersInfo"]:
    """Universal ownership snapshot (yfinance): institution / insider %,
    float-vs-outstanding (→ locked %, the supply-overhang signal), and the
    top institutional holders with their recent % change (buy/sell
    direction). Works for any US ticker incl. foreign filers (ARM).
    Cached 6h — ownership moves slowly (13F is quarterly)."""
    ticker = ticker.upper().strip()
    now = _time.time()
    with _lock:
        hit = _holders_cache.get(ticker)
        if hit and (now - hit[0]) < HOLDERS_TTL_S:
            return hit[1]
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        shares_out = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        float_shares = info.get("floatShares")
        pct_float = (float_shares / shares_out) if (float_shares and shares_out) else None
        # Guard: float can't exceed shares outstanding for a single class.
        # pct_float > 1 means yfinance mixed MULTI-CLASS counts — e.g. GOOGL
        # (Class A/B/C): floatShares spans all classes while sharesOutstanding
        # is one class, giving float% ≈ 184% and locked% ≈ -84%. Drop the
        # derived float%/locked% (供给悬顶) rather than render nonsense.
        if pct_float is not None and pct_float > 1.001:
            pct_float = None
        inst_count = None
        try:
            mh = t.major_holders
            if mh is not None and "institutionsCount" in list(mh.index):
                inst_count = int(float(mh.loc["institutionsCount"].iloc[0]))
        except Exception:
            pass

        def _f(row, col):
            v = row.get(col)
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        top = []
        try:
            ih = t.institutional_holders
            if ih is not None and len(ih):
                for _, r in ih.head(top_n).iterrows():
                    sh = _f(r, "Shares")
                    top.append({
                        "holder":        str(r.get("Holder", "")).strip(),
                        "pct_held":      _f(r, "pctHeld"),
                        "shares":        (int(sh) if sh is not None else None),
                        "value":         _f(r, "Value"),
                        "pct_change":    _f(r, "pctChange"),
                        "date_reported": str(r.get("Date Reported", ""))[:10],
                    })
        except Exception:
            pass

        out = HoldersInfo(
            ticker=ticker,
            pct_institutions=info.get("heldPercentInstitutions"),
            pct_insiders=info.get("heldPercentInsiders"),
            institutions_count=inst_count,
            shares_outstanding=shares_out,
            float_shares=float_shares,
            pct_float=pct_float,
            pct_locked=((1.0 - pct_float) if pct_float is not None else None),
            top_holders=top,
            source="yfinance",
            fetched_at=_now_iso(),
        )
    except Exception as exc:
        logger.warning("get_holders(%s) failed: %s", ticker, exc)
        return None

    # Don't poison the 6h cache with a degraded/near-empty .info fetch (same
    # reasoning as get_fundamentals — a tiny .info dict would lock all None).
    if len(info) >= 30:
        with _lock:
            _holders_cache[ticker] = (now, out)
    else:
        logger.warning("get_holders(%s): degraded .info (%d keys), not caching", ticker, len(info))
    return out


# ─── Fundamentals / quality metrics (the diagnostic-chain Tier-1) ──

@dataclass
class Fundamentals:
    ticker: str
    peg: Optional[float]
    gross_margin: Optional[float]
    profit_margin: Optional[float]
    operating_margin: Optional[float]
    revenue_growth: Optional[float]
    earnings_growth: Optional[float]
    fcf: Optional[float]                # free cash flow (absolute $)
    operating_cf: Optional[float]
    roe: Optional[float]               # ROIC isn't in yfinance — ROE used as proxy
    roa: Optional[float]
    total_debt: Optional[float]
    total_cash: Optional[float]
    net_debt: Optional[float]          # total_debt - total_cash (negative = net cash)
    price_to_sales: Optional[float]
    price_to_book: Optional[float]
    debt_to_equity: Optional[float]
    beta: Optional[float]
    dividend_yield: Optional[float]
    ev_ebitda: Optional[float]
    capex: Optional[float]              # total/gross capex (PP&E spend, positive)
    dep_amort: Optional[float]          # D&A — proxy for maintenance capex
    revenue: Optional[float]
    capex_intensity: Optional[float]    # capex / revenue (asset-light vs heavy)
    # 市场/卖方预期 (Goal-1 dim #8, borrowed from TOPS) — the filtered consensus
    analyst_rating: Optional[float]     # recommendationMean 1(强买)–5(卖)
    analyst_rating_key: Optional[str]   # "buy" / "hold" / …
    analyst_count: Optional[int]        # # of analysts
    target_mean: Optional[float]        # consensus 12m target price
    target_high: Optional[float]
    target_low: Optional[float]
    source: str
    fetched_at: str

    def to_dict(self) -> dict:
        return asdict(self)


_fund_cache: dict[str, tuple[float, "Fundamentals"]] = {}
FUND_TTL_S = 6 * 3600.0


def _dividend_yield_fraction(info: dict) -> Optional[float]:
    """Dividend yield as a FRACTION (0.0038 = 0.38%), version-robustly.
    Prefer dividendRate ($/share annual) ÷ price (unambiguous); fall back to
    yfinance's dividendYield, which is percent-magnitude (0.38 = 0.38%) in
    current builds. NaN-guarded."""
    rate = info.get("dividendRate")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if rate and price and rate == rate and price == price:
        return rate / price
    dy = info.get("dividendYield")
    if dy is not None and dy == dy:
        return dy / 100.0
    return None


def get_fundamentals(ticker: str) -> Optional["Fundamentals"]:
    """Tier-1 quality/valuation metrics (yfinance .info): PEG, margins,
    growth, FCF, ROE(≈ROIC proxy), net debt, P/S, P/B, beta, EV/EBITDA.
    These close the diagnostic chain (PE→PEG→increase→quality). Cached 6h."""
    ticker = ticker.upper().strip()
    now = _time.time()
    with _lock:
        hit = _fund_cache.get(ticker)
        if hit and (now - hit[0]) < FUND_TTL_S:
            return hit[1]
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        td, tc = info.get("totalDebt"), info.get("totalCash")
        net_debt = (td - tc) if (td is not None and tc is not None) else None
        # capex + D&A from the cashflow statement (authoritative line items;
        # info.freeCashflow uses a different TTM calc, so derive from here)
        capex = dep_amort = None
        try:
            cf = t.cashflow
            if cf is not None and len(cf.columns):
                col = cf.columns[0]
                def _cf(name: str):
                    try:
                        if name in cf.index:
                            v = float(cf.loc[name, col])
                            return v if v == v else None   # NaN guard
                    except Exception:
                        return None
                    return None
                cap_raw = _cf("Capital Expenditure")
                capex = abs(cap_raw) if cap_raw is not None else None
                dep_amort = _cf("Depreciation And Amortization")
        except Exception:
            pass
        revenue = info.get("totalRevenue")
        capex_intensity = (capex / revenue) if (capex and revenue) else None
        # Dividend yield (fraction). info.dividendRate/Yield are intermittently
        # absent in yfinance AND the 6h cache locks the gap → fall back to the
        # dividends-history endpoint (stable), TTM ≈ last 4 quarterly payments.
        dividend_yield = _dividend_yield_fraction(info)
        if dividend_yield is None:
            _px = info.get("currentPrice") or info.get("regularMarketPrice")
            try:
                _d = t.dividends
                if _px and _d is not None and len(_d):
                    _ttm = float(_d.tail(4).sum())
                    if _ttm > 0:
                        dividend_yield = _ttm / _px
            except Exception:
                pass
        out = Fundamentals(
            ticker=ticker,
            peg=info.get("trailingPegRatio"),
            gross_margin=info.get("grossMargins"),
            profit_margin=info.get("profitMargins"),
            operating_margin=info.get("operatingMargins"),
            revenue_growth=info.get("revenueGrowth"),
            earnings_growth=info.get("earningsGrowth"),
            fcf=info.get("freeCashflow"),
            operating_cf=info.get("operatingCashflow"),
            roe=info.get("returnOnEquity"),
            roa=info.get("returnOnAssets"),
            total_debt=td,
            total_cash=tc,
            net_debt=net_debt,
            price_to_sales=info.get("priceToSalesTrailing12Months"),
            price_to_book=info.get("priceToBook"),
            debt_to_equity=info.get("debtToEquity"),
            beta=info.get("beta"),
            # Dividend yield as a FRACTION (UI ×100 → 0.38%). yfinance's
            # dividendYield is percent-magnitude (0.38 = 0.38%) in this build —
            # fragile across versions. Prefer the unambiguous dividendRate
            # ($/share) ÷ price; fall back to dividendYield/100. (Was a 100× bug
            # that rendered 38%/26%.)
            dividend_yield=dividend_yield,
            ev_ebitda=info.get("enterpriseToEbitda"),
            capex=capex,
            dep_amort=dep_amort,
            revenue=revenue,
            capex_intensity=capex_intensity,
            analyst_rating=info.get("recommendationMean"),
            analyst_rating_key=info.get("recommendationKey"),
            analyst_count=info.get("numberOfAnalystOpinions"),
            target_mean=info.get("targetMeanPrice"),
            target_high=info.get("targetHighPrice"),
            target_low=info.get("targetLowPrice"),
            source="yfinance",
            fetched_at=_now_iso(),
        )
    except Exception as exc:
        logger.warning("get_fundamentals(%s) failed: %s", ticker, exc)
        return None
    # Don't poison the 6h cache with a degraded/near-empty .info fetch
    # (yfinance intermittently returns a tiny dict → every field None, locked
    # for 6h). A healthy .info has 100+ keys; only cache a complete fetch.
    # Degraded results are still returned (so the caller gets best-effort) but
    # not cached, so the next call retries.
    if len(info) >= 30:
        with _lock:
            _fund_cache[ticker] = (now, out)
    else:
        logger.warning("get_fundamentals(%s): degraded .info (%d keys), not caching", ticker, len(info))
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
