"""Position state — manual entry into tax_lots, surfaced as portfolio
summary + per-ticker decision context.

Per plan §5 Pillar 5 (Decision Context Dimensions) + Pillar 6
(Information Dimension Coverage) + plan §11 OQ "Phase 1B positions
data source = manual UI" (default chosen 2026-05-10).

Open lot model:
  - Each `tax_lots` row with close_date IS NULL is an open position
  - Multiple lots per ticker possible (different open_date / open_price)
  - Aggregated per-ticker view: sum quantities, weighted avg cost basis

Endpoints under /api/positions:
  GET    /lots                          — all open lots, optionally filter by ticker
  POST   /lots                          — add a new lot (manual entry)
  PATCH  /lots/{lot_id}                 — edit an open lot (price / qty / fees / notes)
  DELETE /lots/{lot_id}                 — delete (only allowed for open lots that
                                          haven't generated tax events yet)
  POST   /lots/{lot_id}/close           — record a sell (full or partial)

  GET    /summary                       — portfolio total + per-ticker rollup +
                                          sector mix + vs benchmark (default SPY)
  GET    /by_ticker/{ticker}            — all positions for one ticker, with
                                          current price + unrealized P&L

Per plan §2 philosophy: positions are INFORMATION displayed in chain
context, NOT enforcement gates. We compute weight % vs portfolio and
show it; we don't refuse buys when over the threshold.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


_VALID_MARKETS = {"US", "CN", "HK"}
_VALID_ASSET = {"stock", "etf", "mutual_fund", "crypto", "option", "future"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Helpers ─────────────────────────────────────────────────────────


def _normalize_ticker(t: str) -> str:
    s = (t or "").strip().upper()
    if not s:
        raise HTTPException(400, "ticker required")
    return s


# In-process cache: portfolio_summary should not hit yfinance N times
# for N tickers when the user opens the dashboard 5 times in 60s.
# Keyed by ticker, value is (LiveQuote-or-None, fetched_unix).
_QUOTE_CACHE: Dict[str, Any] = {}
_QUOTE_TTL_SECONDS = 60


def _get_quote(ticker: str) -> Any:
    """Fetch live quote with 60s in-process cache. SHARED by both
    price and sector lookups so we don't double-hit yfinance per
    ticker. Earlier bug: separate calls → 2N yfinance hits + flaky
    behavior where price came back fine but sector returned 'Unknown'
    because the SECOND call rate-limited."""
    import time
    cached = _QUOTE_CACHE.get(ticker)
    now = time.time()
    if cached is not None:
        q, fetched = cached
        if now - fetched < _QUOTE_TTL_SECONDS:
            return q
    try:
        from agent.data_sources.market import get_live_quote
        q = get_live_quote(ticker)
        _QUOTE_CACHE[ticker] = (q, now)
        return q
    except Exception as exc:
        logger.warning("get_quote(%s) failed: %s", ticker, exc)
        # Cache the failure briefly so we don't hammer yfinance
        _QUOTE_CACHE[ticker] = (None, now)
        return None


def _get_current_price(ticker: str, market: str = "US") -> Optional[float]:
    """Best-effort current price via cached quote."""
    q = _get_quote(ticker)
    if q is None:
        return None
    price = q.price
    if hasattr(price, "value"):
        return float(price.value) if price.value is not None else None
    return float(price) if price is not None else None


def _get_sector(ticker: str) -> Optional[str]:
    """yfinance sector via the same cached quote — single call, two uses."""
    q = _get_quote(ticker)
    return getattr(q, "sector", None) if q else None


def _holding_period_days(open_date: str, ref_date: Optional[datetime] = None) -> int:
    """Days held — for ST vs LT tax determination (US: 365 days)."""
    ref = ref_date or datetime.now(timezone.utc)
    try:
        opened = datetime.fromisoformat(open_date)
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        return (ref - opened).days
    except Exception:
        return 0


# ── DAO ─────────────────────────────────────────────────────────────


def add_lot(
    *,
    symbol: str,
    market: str,
    asset_class: str,
    open_date: str,
    open_price: float,
    open_quantity: float,
    open_fees: float = 0.0,
    account_id: str = "main",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a new open lot. Returns the inserted row."""
    if market not in _VALID_MARKETS:
        raise HTTPException(400, f"market must be one of {sorted(_VALID_MARKETS)}")
    if asset_class not in _VALID_ASSET:
        raise HTTPException(400, f"asset_class must be one of {sorted(_VALID_ASSET)}")
    if open_quantity <= 0:
        raise HTTPException(400, "open_quantity must be > 0")
    if open_price < 0:
        raise HTTPException(400, "open_price must be ≥ 0 (use 0 for free shares)")
    ensure_schema()
    now = _now()
    sym = _normalize_ticker(symbol)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO tax_lots "
            "(account_id, symbol, market, asset_class, "
            " open_date, open_price, open_quantity, open_fees, "
            " notes, created_at, updated_at, is_simulated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (account_id, sym, market, asset_class,
             open_date, open_price, open_quantity, open_fees,
             notes, now, now),
        )
        return get_lot(cur.lastrowid)


def get_lot(lot_id: int) -> Dict[str, Any]:
    ensure_schema()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM tax_lots WHERE lot_id = ?", (lot_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, f"lot {lot_id} not found")
    return dict(row)


def update_lot(lot_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Edit an OPEN lot. Editing closed lots is forbidden — they may
    have already produced tax events. To revise a closed lot, delete +
    re-add (and trigger any downstream tax recalc separately)."""
    existing = get_lot(lot_id)
    if existing["close_date"] is not None:
        raise HTTPException(409, "cannot edit a closed lot — delete + re-add instead")
    fields = ("open_price", "open_quantity", "open_fees", "open_date",
              "notes", "account_id")
    sets = []
    params: List[Any] = []
    for f in fields:
        if f in patch:
            sets.append(f"{f} = ?")
            params.append(patch[f])
    if not sets:
        return existing
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(lot_id)
    with connect() as conn:
        conn.execute(f"UPDATE tax_lots SET {', '.join(sets)} WHERE lot_id = ?", params)
    return get_lot(lot_id)


def delete_lot(lot_id: int) -> None:
    """Delete an open lot. Closed lots cannot be deleted (tax-event
    integrity). User must demote to manual decision."""
    existing = get_lot(lot_id)
    if existing["close_date"] is not None:
        raise HTTPException(409, "cannot delete a closed lot")
    with connect() as conn:
        conn.execute("DELETE FROM tax_lots WHERE lot_id = ?", (lot_id,))


def close_lot(
    lot_id: int,
    close_date: str,
    close_price: float,
    close_quantity: Optional[float] = None,
    close_fees: float = 0.0,
) -> Dict[str, Any]:
    """Mark a lot closed (full or partial). Realized P&L computed on the
    fly from open_price * close_quantity. wash_sale_basis_adjustment is
    set to 0 here — wash-sale detector job runs separately and may
    backfill."""
    existing = get_lot(lot_id)
    if existing["close_date"] is not None:
        raise HTTPException(409, "lot already closed")
    qty = close_quantity if close_quantity is not None else existing["open_quantity"]
    if qty <= 0 or qty > existing["open_quantity"]:
        raise HTTPException(400, f"close_quantity must be in (0, {existing['open_quantity']}]")

    days = _holding_period_days(existing["open_date"],
                                 datetime.fromisoformat(close_date) if "T" in close_date
                                 else None)
    # US tax rule: > 1 year = long-term
    holding = "long_term" if days > 365 else "short_term"
    realized = (close_price - existing["open_price"]) * qty - close_fees - existing["open_fees"]

    with connect() as conn:
        conn.execute(
            "UPDATE tax_lots SET close_date = ?, close_price = ?, "
            " close_quantity = ?, close_fees = ?, "
            " holding_period_qualified = ?, realized_gain_loss = ?, "
            " updated_at = ? "
            "WHERE lot_id = ?",
            (close_date, close_price, qty, close_fees,
             holding, realized, _now(), lot_id),
        )
    return get_lot(lot_id)


def list_lots(
    *,
    open_only: bool = True,
    ticker: Optional[str] = None,
    account_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_schema()
    where = []
    params: List[Any] = []
    if open_only:
        where.append("close_date IS NULL")
    if ticker:
        where.append("symbol = ?")
        params.append(_normalize_ticker(ticker))
    if account_id:
        where.append("account_id = ?")
        params.append(account_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM tax_lots{where_sql} ORDER BY open_date DESC, lot_id DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def by_ticker(ticker: str) -> Dict[str, Any]:
    """All open lots for one ticker with current market value + P&L."""
    sym = _normalize_ticker(ticker)
    lots = list_lots(open_only=True, ticker=sym)
    if not lots:
        return {"ticker": sym, "lots": [], "summary": None}

    current = _get_current_price(sym, lots[0]["market"])
    total_qty = sum(l["open_quantity"] for l in lots)
    total_cost = sum(l["open_price"] * l["open_quantity"] + l["open_fees"] for l in lots)
    avg_cost = total_cost / total_qty if total_qty > 0 else 0.0
    market_value = current * total_qty if current is not None else None
    unrealized = (market_value - total_cost) if market_value is not None else None
    unrealized_pct = (unrealized / total_cost * 100.0) if (unrealized is not None and total_cost > 0) else None

    # Per-lot enriched (so chain panel can show "100sh @ $400 ST 60d")
    enriched = []
    for l in lots:
        days = _holding_period_days(l["open_date"])
        is_lt = days > 365
        lot_cost = l["open_price"] * l["open_quantity"] + l["open_fees"]
        lot_value = current * l["open_quantity"] if current is not None else None
        enriched.append({
            **l,
            "days_held":      days,
            "is_long_term":   is_lt,
            "days_until_lt":  max(0, 366 - days) if not is_lt else 0,
            "lot_cost_basis": lot_cost,
            "lot_market_value": lot_value,
            "lot_unrealized":   (lot_value - lot_cost) if lot_value is not None else None,
        })

    return {
        "ticker":          sym,
        "lots":            enriched,
        "summary": {
            "total_quantity":   total_qty,
            "total_cost":       total_cost,
            "avg_cost":         avg_cost,
            "current_price":    current,
            "market_value":     market_value,
            "unrealized":       unrealized,
            "unrealized_pct":   unrealized_pct,
            "n_lots":           len(lots),
        },
    }


def portfolio_summary(benchmark: str = "SPY") -> Dict[str, Any]:
    """Total portfolio value, per-ticker rollup, sector mix, vs
    benchmark return.

    Benchmark return is computed simply: portfolio total return %
    over 30/90/365d compared to (close[t] / close[t-N] - 1) of benchmark.
    Portfolio return is approximated via SUM(market_value - cost_basis)
    / SUM(cost_basis) for currently held positions — NOT a true time-
    weighted return, which would require historical position state."""
    ensure_schema()
    lots = list_lots(open_only=True)
    if not lots:
        return {
            "n_lots":         0,
            "total_value":    0,
            "total_cost":     0,
            "unrealized":     0,
            "unrealized_pct": 0,
            "by_ticker":      [],
            "by_sector":      [],
            "benchmark":      benchmark,
            "vs_benchmark":   None,
            "fetched_at":     _now(),
        }

    # Group by ticker
    grouped: Dict[str, Dict[str, Any]] = {}
    for l in lots:
        sym = l["symbol"]
        if sym not in grouped:
            grouped[sym] = {
                "ticker":   sym,
                "market":   l["market"],
                "quantity": 0.0,
                "cost":     0.0,
                "n_lots":   0,
            }
        grouped[sym]["quantity"] += l["open_quantity"]
        grouped[sym]["cost"]     += l["open_price"] * l["open_quantity"] + l["open_fees"]
        grouped[sym]["n_lots"]   += 1

    # Enrich with current price + sector
    by_ticker = []
    sector_value: Dict[str, float] = {}
    total_value = 0.0
    total_cost = 0.0
    for sym, g in grouped.items():
        price = _get_current_price(sym, g["market"])
        sector = _get_sector(sym) or "Unknown"
        market_value = price * g["quantity"] if price is not None else None
        unrealized = (market_value - g["cost"]) if market_value is not None else None
        if market_value is not None:
            total_value += market_value
            sector_value[sector] = sector_value.get(sector, 0.0) + market_value
        total_cost += g["cost"]
        by_ticker.append({
            "ticker":       sym,
            "quantity":     g["quantity"],
            "cost":         g["cost"],
            "current_price": price,
            "market_value": market_value,
            "unrealized":   unrealized,
            "unrealized_pct": (unrealized / g["cost"] * 100.0)
                                if (unrealized is not None and g["cost"] > 0) else None,
            "n_lots":       g["n_lots"],
            "sector":       sector,
            "weight_pct":   None,    # filled below once total known
        })

    # Backfill weight_pct + sort by market value desc
    for row in by_ticker:
        if row["market_value"] is not None and total_value > 0:
            row["weight_pct"] = row["market_value"] / total_value * 100.0
    by_ticker.sort(key=lambda r: -(r["market_value"] or 0))

    # Sector breakdown
    by_sector = sorted(
        [
            {"sector": s, "value": v, "pct": (v / total_value * 100.0 if total_value > 0 else 0)}
            for s, v in sector_value.items()
        ],
        key=lambda r: -r["value"],
    )

    # vs benchmark — simple snapshot return calc
    vs_benchmark = _vs_benchmark(total_value, total_cost, benchmark)

    return {
        "n_lots":         len(lots),
        "n_tickers":      len(grouped),
        "total_value":    total_value,
        "total_cost":     total_cost,
        "unrealized":     total_value - total_cost,
        "unrealized_pct": ((total_value - total_cost) / total_cost * 100.0)
                            if total_cost > 0 else 0,
        "by_ticker":      by_ticker,
        "by_sector":      by_sector,
        "benchmark":      benchmark,
        "vs_benchmark":   vs_benchmark,
        "fetched_at":     _now(),
    }


def _vs_benchmark(total_value: float, total_cost: float,
                  benchmark: str = "SPY") -> Optional[Dict[str, Any]]:
    """Compute portfolio vs benchmark over 30/90/365d.

    Approach: portfolio return is total_value/total_cost - 1 (a
    LIFETIME return for currently-held positions, not time-windowed).
    Benchmark return is the actual % change of `benchmark` over each
    window. These aren't strictly comparable — proper TWR (time-weighted
    return) requires per-day portfolio mark-to-market, which we'll
    add in a later phase. For now this is a directional signal.

    Phase 4 (2026-05-10): when market_data_daily lacks the benchmark
    (fresh install — no daily_market_pull has run for SPY yet), fall
    back to a one-shot live yfinance fetch. Cached for 60s via
    _get_quote so repeated dashboard opens don't hammer yfinance."""
    if total_cost <= 0:
        return None
    portfolio_return_pct = (total_value - total_cost) / total_cost * 100.0

    try:
        windows = {"30d": 30, "90d": 90, "365d": 365}
        out: Dict[str, Any] = {}
        # Try DB first (cheap); fall back to live yfinance history
        bench_closes = _benchmark_closes_from_db(benchmark)
        source = "market_data_daily"
        if not bench_closes:
            bench_closes = _benchmark_closes_from_yfinance(benchmark)
            source = "yfinance live (DB cache empty)"
        if not bench_closes:
            return {
                "benchmark":              benchmark,
                "portfolio_lifetime_pct": portfolio_return_pct,
                "windows":                {},
                "note":                   f"no {benchmark} data available from any source",
            }
        latest_date, latest_close = max(bench_closes.items())
        from datetime import datetime as _dt, timedelta as _td
        latest_dt = _dt.fromisoformat(latest_date) if isinstance(latest_date, str) else latest_date
        for label, days_back in windows.items():
            target_date = latest_dt - _td(days=days_back)
            target_iso = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
            # Find closest close on or before target_date
            past_closes = {d: c for d, c in bench_closes.items() if str(d) <= str(target_iso)}
            if past_closes:
                _, past_close = max(past_closes.items())
                if past_close > 0:
                    bench_pct = (latest_close - past_close) / past_close * 100.0
                    out[label] = {"benchmark_pct": bench_pct}
                    continue
            out[label] = {"benchmark_pct": None}
        return {
            "benchmark":              benchmark,
            "portfolio_lifetime_pct": portfolio_return_pct,
            "windows":                out,
            "source":                 source,
            "note":                   "portfolio lifetime return; benchmark windowed",
        }
    except Exception as exc:
        logger.warning("vs_benchmark calc failed: %s", exc)
        return None


def _benchmark_closes_from_db(benchmark: str) -> Dict[str, float]:
    """Return {trade_date: close} for last 400 days of cached benchmark
    data. Empty dict if not cached. Cheap (single SQL query)."""
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT trade_date, close FROM market_data_daily "
                "WHERE symbol = ? AND market = 'US' "
                "  AND trade_date >= date('now', '-400 days') "
                "  AND close IS NOT NULL",
                (benchmark,),
            ).fetchall()
        return {r["trade_date"]: float(r["close"]) for r in rows}
    except Exception:
        return {}


def _benchmark_closes_from_yfinance(benchmark: str) -> Dict[str, float]:
    """One-shot fallback: fetch ~400d of EOD closes via yfinance.
    Cached implicitly via yfinance's own session pool. Returns
    {trade_date_iso: close}. Empty on failure."""
    try:
        import yfinance as yf
        t = yf.Ticker(benchmark)
        df = t.history(period="400d", interval="1d", auto_adjust=False)
        if df is None or df.empty:
            return {}
        out = {}
        for idx, row in df.iterrows():
            try:
                date_str = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
                out[date_str] = float(row["Close"])
            except Exception:
                continue
        return out
    except Exception as exc:
        logger.warning("yfinance benchmark fallback %s failed: %s", benchmark, exc)
        return {}


# ── Pydantic ────────────────────────────────────────────────────────


class AddLotBody(BaseModel):
    symbol: str
    market: str = "US"
    asset_class: str = "stock"
    open_date: str = Field(..., description="YYYY-MM-DD")
    open_price: float
    open_quantity: float
    open_fees: float = 0.0
    account_id: str = "main"
    notes: Optional[str] = None


class UpdateLotBody(BaseModel):
    open_price: Optional[float] = None
    open_quantity: Optional[float] = None
    open_fees: Optional[float] = None
    open_date: Optional[str] = None
    notes: Optional[str] = None
    account_id: Optional[str] = None


class CloseLotBody(BaseModel):
    close_date: str = Field(..., description="YYYY-MM-DD")
    close_price: float
    close_quantity: Optional[float] = None
    close_fees: float = 0.0


# ── Router ──────────────────────────────────────────────────────────


def build_positions_router() -> APIRouter:
    router = APIRouter(prefix="/api/positions", tags=["positions"])

    @router.get("/lots")
    def list_endpoint(
        ticker: Optional[str] = Query(None),
        account_id: Optional[str] = Query(None),
        open_only: bool = Query(True),
    ) -> Dict[str, Any]:
        rows = list_lots(open_only=open_only, ticker=ticker, account_id=account_id)
        return {"lots": rows, "count": len(rows)}

    @router.post("/lots")
    def add_endpoint(body: AddLotBody) -> Dict[str, Any]:
        return add_lot(
            symbol=body.symbol,
            market=body.market.upper(),
            asset_class=body.asset_class.lower(),
            open_date=body.open_date,
            open_price=body.open_price,
            open_quantity=body.open_quantity,
            open_fees=body.open_fees,
            account_id=body.account_id,
            notes=body.notes,
        )

    @router.patch("/lots/{lot_id}")
    def patch_endpoint(lot_id: int, body: UpdateLotBody) -> Dict[str, Any]:
        patch = {k: v for k, v in body.dict().items() if v is not None}
        return update_lot(lot_id, patch)

    @router.delete("/lots/{lot_id}")
    def delete_endpoint(lot_id: int) -> Dict[str, Any]:
        delete_lot(lot_id)
        return {"ok": True, "lot_id": lot_id}

    @router.post("/lots/{lot_id}/close")
    def close_endpoint(lot_id: int, body: CloseLotBody) -> Dict[str, Any]:
        return close_lot(
            lot_id,
            close_date=body.close_date,
            close_price=body.close_price,
            close_quantity=body.close_quantity,
            close_fees=body.close_fees,
        )

    @router.get("/summary")
    def summary_endpoint(
        benchmark: Optional[str] = Query(None,
            description="Override benchmark; default reads from user_preferences"),
    ) -> Dict[str, Any]:
        # Phase 4: default to user_preferences.benchmark_ticker (SPY
        # by default but user can change). Per plan §5 Pillar 5.
        if benchmark is None:
            try:
                from agent.finance.user_prefs import get_pref
                benchmark = get_pref("benchmark_ticker") or "SPY"
            except Exception:
                benchmark = "SPY"
        return portfolio_summary(benchmark=benchmark)

    @router.get("/by_ticker/{ticker}")
    def by_ticker_endpoint(ticker: str) -> Dict[str, Any]:
        return by_ticker(ticker)

    return router
