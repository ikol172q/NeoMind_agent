"""OpenBB Workspace custom backend adapter for NeoMind.

Exposes two families of HTTP endpoints under ``/openbb/`` prefix:

1. **Data backend** — widgets that Workspace dashboards can consume:
     /openbb/widgets.json     — widget catalog
     /openbb/apps.json        — optional layout presets
     /openbb/quote            — metric  (?symbol=)
     /openbb/chart            — chart   (?symbol=&period=&interval=&indicators=)
     /openbb/news             — newsfeed (?symbols=&limit=)
     /openbb/history          — table    (?project_id=&limit=)
     /openbb/paper_account    — metric   (?project_id=)
     /openbb/paper_positions  — table    (?project_id=)
     /openbb/paper_trades     — table    (?project_id=&limit=)

2. **Agent backend** — exposes the fin-rt fleet worker as an OpenBB
   Copilot-compatible AI agent:
     /openbb/agents.json  — agent metadata
     /openbb/query        — POST SSE stream

Design principles:
- PURELY ADDITIVE — no existing NeoMind endpoint changes.
- REUSE existing data functions: ``data_hub.get_quote/get_history``,
  ``news_hub.fetch_entries``, ``investment_projects.list_analyses``,
  ``paper_trading.*``, ``fleet.dispatch_chat``.
- CORS limited to ``https://pro.openbb.co`` + localhost dev origins.
- Bind stays 127.0.0.1; the SaaS Workspace tab runs in the user's
  browser and connects out to their localhost, so no public exposure.

Contract source of truth (2026-04-15 snapshot):
  https://github.com/OpenBB-finance/backends-for-openbb/tree/main/getting-started
  https://docs.openbb.co/workspace/developers/data-integration
  https://docs.openbb.co/workspace/developers/agents-integration
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agent.finance import investment_projects
from agent.finance import technical_indicators as ti

logger = logging.getLogger(__name__)


# ── CORS ───────────────────────────────────────────────────────────

ALLOWED_ORIGINS = [
    "https://pro.openbb.co",      # cloud Workspace
    "http://localhost:1420",      # ODP desktop (future)
    "http://127.0.0.1:1420",
    "http://localhost:5050",      # reference-backend dev
    "http://127.0.0.1:5050",
]


def add_cors(app) -> None:
    """Attach CORSMiddleware for OpenBB origins. Idempotent — safe to
    call twice; FastAPI will layer them but only one is used."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ── widgets.json + apps.json ───────────────────────────────────────


def _widgets_catalog() -> Dict[str, Any]:
    """The widget catalog returned at GET /openbb/widgets.json.

    Each widget maps to exactly one GET endpoint under /openbb/.
    gridData units follow the OpenBB 40-column grid convention.
    """
    return {
        "neomind_quote": {
            "name": "NeoMind Quote",
            "description": (
                "Live price, change, volume, high/low from the NeoMind "
                "DataHub fallback ladder (Finnhub → Alpha Vantage → yfinance)."
            ),
            "category": "NeoMind",
            "subcategory": "Markets",
            "type": "metric",
            "endpoint": "quote",
            "gridData": {"w": 15, "h": 5},
            "source": "NeoMind",
            "params": [
                {
                    "paramName": "symbol",
                    "value": "AAPL",
                    "label": "Symbol",
                    "type": "text",
                    "description": "Ticker (e.g. AAPL, MSFT, 600519).",
                },
            ],
        },
        "neomind_cn_quote": {
            "name": "NeoMind A股 Quote",
            "description": (
                "A股 realtime quote via AkShare (Eastmoney bid-ask). "
                "Includes 涨跌/涨幅/换手/涨停跌停. 6-digit codes: "
                "600519 沪, 000001 深, 300750 创业板, 688981 科创板."
            ),
            "category": "NeoMind",
            "subcategory": "A股",
            "type": "metric",
            "endpoint": "cn_quote",
            "gridData": {"w": 20, "h": 5},
            "source": "AkShare / 东方财富",
            "params": [
                {
                    "paramName": "code",
                    "value": "600519",
                    "label": "A股 代码",
                    "type": "text",
                    "description": "6 位数字代码（如 600519 贵州茅台）。",
                },
            ],
        },
        "neomind_chart": {
            "name": "NeoMind Chart + Indicators",
            "description": (
                "OHLCV chart with technical indicators (SMA/EMA/BB/RSI/MACD) "
                "computed by NeoMind's own technical_indicators module."
            ),
            "category": "NeoMind",
            "subcategory": "Markets",
            "type": "chart",
            "endpoint": "chart",
            "gridData": {"w": 30, "h": 12},
            "raw": True,
            "source": "NeoMind",
            "params": [
                {"paramName": "symbol", "value": "AAPL", "label": "Symbol",
                 "type": "text", "description": "Ticker."},
                {"paramName": "period", "value": "3mo", "label": "Period",
                 "type": "text",
                 "description": "1mo | 3mo | 6mo | 1y | 2y | 5y."},
                {"paramName": "interval", "value": "1d", "label": "Interval",
                 "type": "text", "description": "1d | 1wk | 1mo."},
            ],
        },
        "neomind_news": {
            "name": "NeoMind News",
            "description": (
                "Aggregated financial news from the user's self-hosted "
                "Miniflux instance, optionally filtered by symbol."
            ),
            "category": "NeoMind",
            "subcategory": "News",
            "type": "newsfeed",
            "endpoint": "news",
            "gridData": {"w": 25, "h": 15},
            "source": "Miniflux",
            "params": [
                {"paramName": "symbols", "value": "", "label": "Symbols",
                 "type": "text",
                 "description": "Comma-separated tickers to filter "
                                "titles against (blank = all)."},
                {"paramName": "limit", "value": "20", "label": "Limit",
                 "type": "number", "description": "Number of entries."},
            ],
        },
        "neomind_history": {
            "name": "NeoMind Analysis History",
            "description": (
                "Past fin-rt analyze signals for a given investment "
                "project (from ~/Desktop/Investment/<project>/analyses)."
            ),
            "category": "NeoMind",
            "subcategory": "Research",
            "type": "table",
            "endpoint": "history",
            "gridData": {"w": 30, "h": 15},
            "source": "NeoMind",
            "params": [
                {"paramName": "project_id", "value": "fin-core",
                 "label": "Project ID", "type": "text",
                 "description": "Registered investment project id."},
                {"paramName": "limit", "value": "20", "label": "Limit",
                 "type": "number",
                 "description": "Max analyses, newest first."},
            ],
        },
        "neomind_paper_account": {
            "name": "NeoMind Paper Account",
            "description": (
                "Paper-trading account summary: cash, equity, "
                "realized / unrealized PnL, win rate. Per project."
            ),
            "category": "NeoMind",
            "subcategory": "Paper Trading",
            "type": "metric",
            "endpoint": "paper_account",
            "gridData": {"w": 20, "h": 5},
            "source": "NeoMind",
            "params": [
                {"paramName": "project_id", "value": "fin-core",
                 "label": "Project ID", "type": "text",
                 "description": "Registered project id."},
            ],
        },
        "neomind_paper_positions": {
            "name": "NeoMind Paper Positions",
            "description": (
                "Open paper-trading positions for a project with live "
                "unrealized PnL."
            ),
            "category": "NeoMind",
            "subcategory": "Paper Trading",
            "type": "table",
            "endpoint": "paper_positions",
            "gridData": {"w": 25, "h": 10},
            "source": "NeoMind",
            "params": [
                {"paramName": "project_id", "value": "fin-core",
                 "label": "Project ID", "type": "text",
                 "description": "Registered project id."},
            ],
        },
        "neomind_paper_trades": {
            "name": "NeoMind Paper Trades",
            "description": "Historical paper-trade fills, newest first.",
            "category": "NeoMind",
            "subcategory": "Paper Trading",
            "type": "table",
            "endpoint": "paper_trades",
            "gridData": {"w": 30, "h": 12},
            "source": "NeoMind",
            "params": [
                {"paramName": "project_id", "value": "fin-core",
                 "label": "Project ID", "type": "text",
                 "description": "Registered project id."},
                {"paramName": "limit", "value": "50", "label": "Limit",
                 "type": "number", "description": "Max trades."},
            ],
        },
    }


def _apps_catalog() -> List[Dict[str, Any]]:
    """Optional: preset dashboard layouts.

    NOTE: OpenBB Workspace expects apps.json to be a JSON ARRAY, not
    a dict keyed by app-id (unlike widgets.json which IS keyed).
    Discovered 2026-04-19 via Workspace validation error
    ``Unknown App: [name]: Required, [tabs]: Required`` — the key
    strings were being iterated as "apps". Schema source of truth:
    backends-for-openbb/getting-started/hello-world/apps.json.
    """
    return [
        {
            "name": "NeoMind · Research",
            "img": "",
            "img_dark": "",
            "img_light": "",
            "description": "Quote + chart + news + analysis history.",
            "allowCustomization": True,
            "tabs": {
                "main": {
                    "id": "main",
                    "name": "Main",
                    "layout": [
                        {"i": "neomind_quote",
                         "x": 0, "y": 0, "w": 15, "h": 5, "groups": []},
                        {"i": "neomind_news",
                         "x": 15, "y": 0, "w": 25, "h": 15, "groups": []},
                        {"i": "neomind_chart",
                         "x": 0, "y": 5, "w": 40, "h": 12, "groups": []},
                        {"i": "neomind_history",
                         "x": 0, "y": 17, "w": 40, "h": 15, "groups": []},
                    ],
                },
            },
            "groups": [],
        },
        {
            "name": "NeoMind · Paper Trading",
            "img": "",
            "img_dark": "",
            "img_light": "",
            "description": "Account + positions + trades.",
            "allowCustomization": True,
            "tabs": {
                "main": {
                    "id": "main",
                    "name": "Main",
                    "layout": [
                        {"i": "neomind_paper_account",
                         "x": 0, "y": 0, "w": 40, "h": 5, "groups": []},
                        {"i": "neomind_paper_positions",
                         "x": 0, "y": 5, "w": 40, "h": 10, "groups": []},
                        {"i": "neomind_paper_trades",
                         "x": 0, "y": 15, "w": 40, "h": 12, "groups": []},
                    ],
                },
            },
            "groups": [],
        },
    ]


# ── Reshaping helpers ──────────────────────────────────────────────


def _reshape_quote_to_metric(quote: Any) -> List[Dict[str, Any]]:
    """NeoMind StockQuote → OpenBB metric array."""
    if quote is None:
        return [{"label": "Status", "value": "no quote available"}]

    price = None
    source = "?"
    price_obj = getattr(quote, "price", None)
    if price_obj is not None:
        price = getattr(price_obj, "value", None)
        source = getattr(price_obj, "source", "?") or "?"

    change = getattr(quote, "change", None)
    change_pct = getattr(quote, "change_pct", None)
    volume = getattr(quote, "volume", None)
    high = getattr(quote, "high", None)
    low = getattr(quote, "low", None)
    name = getattr(quote, "name", "") or getattr(quote, "symbol", "")

    def _fmt_num(v, digits=2):
        if v is None:
            return "—"
        try:
            return f"{float(v):,.{digits}f}"
        except Exception:
            return str(v)

    return [
        {"label": name or "Price",
         "value": (f"${_fmt_num(price)}" if price is not None else "—")},
        {"label": "Change",
         "value": (f"{_fmt_num(change)}" if change is not None else "—"),
         "delta": (f"{_fmt_num(change_pct, 2)}" if change_pct is not None else None)},
        {"label": "Volume",
         "value": (f"{int(volume):,}" if volume is not None else "—")},
        {"label": "High / Low",
         "value": f"{_fmt_num(high)} / {_fmt_num(low)}"},
        {"label": "Source",
         "value": source},
    ]


def _reshape_bars_to_plotly(
    symbol: str,
    bars: List[Dict[str, Any]],
    indicators: Dict[str, Any],
) -> Dict[str, Any]:
    """Bars + indicators → Plotly figure (raw chart widget payload)."""
    if not bars:
        return {"data": [], "layout": {"title": f"{symbol} (no data)"}}

    xs = [b.get("date") for b in bars]
    closes = [b.get("close") for b in bars]
    highs = [b.get("high") for b in bars]
    lows = [b.get("low") for b in bars]
    opens = [b.get("open") for b in bars]

    traces: List[Dict[str, Any]] = [
        {
            "x": xs, "open": opens, "high": highs, "low": lows, "close": closes,
            "type": "candlestick", "name": symbol,
            "increasing": {"line": {"color": "#6fd07a"}},
            "decreasing": {"line": {"color": "#e57373"}},
            "yaxis": "y",
        },
    ]

    def _line(series, name, color):
        return {
            "x": xs, "y": series, "type": "scatter", "mode": "lines",
            "name": name, "line": {"color": color, "width": 1.3},
            "yaxis": "y",
        }

    if "sma20" in indicators:
        traces.append(_line(indicators["sma20"], "SMA20", "#f3c969"))
    if "ema20" in indicators:
        traces.append(_line(indicators["ema20"], "EMA20", "#4dd0e1"))
    bb = indicators.get("bb")
    if isinstance(bb, dict):
        traces.append(_line(bb.get("upper", []), "BB upper", "#7c8598"))
        traces.append(_line(bb.get("lower", []), "BB lower", "#7c8598"))
    if "rsi" in indicators:
        traces.append({
            "x": xs, "y": indicators["rsi"], "type": "scatter", "mode": "lines",
            "name": "RSI(14)", "line": {"color": "#4dd0e1", "width": 1.3},
            "yaxis": "y2",
        })

    layout = {
        "title": f"{symbol}",
        "template": "plotly_dark",
        "dragmode": "pan",
        "xaxis": {"rangeslider": {"visible": False}},
        "yaxis": {"domain": [0.3, 1.0], "title": "Price"},
        "yaxis2": {"domain": [0.0, 0.25], "title": "RSI"},
        "margin": {"l": 40, "r": 30, "t": 40, "b": 30},
        "legend": {"orientation": "h"},
    }
    return {"data": traces, "layout": layout}


def _reshape_news_to_feed(entries: List[Any]) -> List[Dict[str, Any]]:
    """NewsEntry list → OpenBB newsfeed list."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        out.append({
            "title": getattr(e, "title", "") or "",
            "url": getattr(e, "url", "") or "",
            "publishedDate": getattr(e, "published_at", "") or "",
            "source": getattr(e, "feed_title", "") or "",
            "summary": getattr(e, "snippet", "") or "",
        })
    return out


def _reshape_history_to_table(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten AgentAnalysis rows (strip nested 'signal' dict into
    columns) for OpenBB table widget."""
    rows: List[Dict[str, Any]] = []
    for it in items:
        sig = it.get("signal") if isinstance(it, dict) else None
        if isinstance(sig, dict):
            flat = {
                "when": it.get("written_at", ""),
                "symbol": it.get("symbol", ""),
                "signal": sig.get("signal", ""),
                "confidence": sig.get("confidence", ""),
                "risk_level": sig.get("risk_level", ""),
                "target_price": sig.get("target_price"),
                "reason": (sig.get("reason") or "")[:200],
            }
        else:
            flat = {
                "when": it.get("written_at", ""),
                "symbol": it.get("symbol", ""),
                "reason": str(it)[:200],
            }
        rows.append(flat)
    return rows


# ── Data router ────────────────────────────────────────────────────


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")


def build_data_router(
    get_hub: Callable[[], Any],
    get_engine: Callable[[str], Any],
    list_recent_analyses: Callable[[str, int], List[Dict[str, Any]]],
) -> APIRouter:
    """Build the /openbb data-backend router.

    Injected callables let tests swap the data layer without importing
    heavy providers. In production, dashboard_server wires these to
    the real DataHub / PaperTradingEngine / investment_projects.
    """
    router = APIRouter()

    @router.get("/widgets.json")
    def widgets() -> JSONResponse:
        return JSONResponse(content=_widgets_catalog())

    @router.get("/apps.json")
    def apps() -> JSONResponse:
        return JSONResponse(content=_apps_catalog())

    # ── Metric: CN A-share quote ──
    @router.get("/cn_quote")
    def cn_quote(code: str = Query("600519")) -> JSONResponse:
        from agent.finance import cn_data
        try:
            q = cn_data.get_cn_quote(code)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except cn_data.UpstreamError as exc:
            return JSONResponse(content=[{
                "label": "Status",
                "value": f"AkShare upstream error: {str(exc)[:140]}",
            }])
        chg = q.get("change") or 0
        chg_pct = q.get("change_pct") or 0
        return JSONResponse(content=[
            {"label": f"{q['symbol']} 最新",
             "value": f"¥{q['price']:,.2f}"},
            {"label": "涨跌",
             "value": f"{chg:+.2f}",
             "delta": f"{chg_pct:+.2f}"},
            {"label": "成交量",
             "value": (f"{q['volume']:,}" if q.get("volume") is not None else "—")},
            {"label": "成交额",
             "value": (f"¥{q['turnover']:,.0f}" if q.get("turnover") is not None else "—")},
            {"label": "今开 / 昨收",
             "value": f"¥{q.get('open', 0):.2f} / ¥{q.get('prev_close', 0):.2f}"},
            {"label": "最高 / 最低",
             "value": f"¥{q.get('high', 0):.2f} / ¥{q.get('low', 0):.2f}"},
            {"label": "换手率",
             "value": (f"{q['turnover_rate_pct']:.2f}%"
                       if q.get("turnover_rate_pct") is not None else "—")},
        ])

    # ── Metric: quote ──
    @router.get("/quote")
    async def quote(symbol: str = Query("AAPL")) -> JSONResponse:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        hub = get_hub()
        try:
            q = await hub.get_quote(sym)
        except Exception as exc:
            logger.warning("openbb quote failed: %s", exc)
            q = None
        return JSONResponse(content=_reshape_quote_to_metric(q))

    # ── Chart ──
    @router.get("/chart")
    async def chart(
        symbol: str = Query("AAPL"),
        period: str = Query("3mo"),
        interval: str = Query("1d"),
    ) -> JSONResponse:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        hub = get_hub()
        try:
            bars = await hub.get_history(sym, period=period, interval=interval)
        except Exception as exc:
            raise HTTPException(502, f"history fetch failed: {exc}")
        if not bars:
            return JSONResponse(
                content=_reshape_bars_to_plotly(sym, [], {})
            )
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        indicators: Dict[str, Any] = {
            "sma20": ti.sma(closes, 20),
            "ema20": ti.ema(closes, 20),
            "rsi": ti.rsi(closes, 14),
        }
        up, mid, lo = ti.bollinger_bands(closes, 20, 2.0)
        indicators["bb"] = {"upper": up, "middle": mid, "lower": lo}
        return JSONResponse(
            content=_reshape_bars_to_plotly(sym, bars, indicators)
        )

    # ── Newsfeed ──
    @router.get("/news")
    def news(
        symbols: str = Query(""),
        limit: int = Query(20, ge=1, le=100),
    ) -> JSONResponse:
        from agent.finance import news_hub
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()] or None
        try:
            entries = news_hub.fetch_entries(limit=limit, symbols=sym_list)
        except HTTPException as exc:
            # Return empty feed + surfaceable hint rather than 503 so
            # the widget doesn't render as "broken" — it shows a single
            # row with the config hint.
            return JSONResponse(content=[{
                "title": "Miniflux not configured",
                "url": "", "publishedDate": "", "source": "setup",
                "summary": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            }])
        return JSONResponse(content=_reshape_news_to_feed(entries))

    # ── Table: history ──
    @router.get("/history")
    def history(
        project_id: str = Query("fin-core"),
        limit: int = Query(20, ge=1, le=200),
    ) -> JSONResponse:
        if not investment_projects._PROJECT_ID_RE.match(project_id):
            raise HTTPException(400, f"invalid project_id {project_id!r}")
        if project_id not in investment_projects.list_projects():
            return JSONResponse(content=[])
        items = list_recent_analyses(project_id, limit)
        return JSONResponse(content=_reshape_history_to_table(items))

    # ── Metric: paper account ──
    @router.get("/paper_account")
    def paper_account(project_id: str = Query("fin-core")) -> JSONResponse:
        try:
            engine = get_engine(project_id)
        except HTTPException as exc:
            return JSONResponse(content=[{
                "label": "Status",
                "value": str(exc.detail)[:120],
            }])
        s = engine.get_account_summary()
        return JSONResponse(content=[
            {"label": "Cash",     "value": f"${s.get('cash', 0):,.2f}"},
            {"label": "Equity",   "value": f"${s.get('equity', 0):,.2f}"},
            {"label": "Total PnL",
             "value": f"${s.get('total_pnl', 0):,.2f}",
             "delta": f"{s.get('total_pnl_pct', 0):+.2f}"},
            {"label": "Realized",
             "value": f"${s.get('realized_pnl', 0):,.2f}"},
            {"label": "Unrealized",
             "value": f"${s.get('unrealized_pnl', 0):,.2f}"},
            {"label": "Trades",
             "value": f"{s.get('total_trades', 0)} ({s.get('win_rate', 0):.0f}% win)"},
        ])

    # ── Table: paper positions ──
    @router.get("/paper_positions")
    def paper_positions(project_id: str = Query("fin-core")) -> JSONResponse:
        try:
            engine = get_engine(project_id)
        except HTTPException:
            return JSONResponse(content=[])
        rows = []
        for p in engine.get_all_positions():
            rows.append({
                "symbol": p.symbol,
                "side": p.side.value if hasattr(p.side, "value") else str(p.side),
                "quantity": p.quantity,
                "entry": p.entry_price,
                "current": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pct": p.unrealized_pnl_pct,
                "opened_at": p.opened_at.isoformat() if p.opened_at else "",
            })
        return JSONResponse(content=rows)

    # ── Table: paper trades ──
    @router.get("/paper_trades")
    def paper_trades(
        project_id: str = Query("fin-core"),
        limit: int = Query(50, ge=1, le=500),
    ) -> JSONResponse:
        try:
            engine = get_engine(project_id)
        except HTTPException:
            return JSONResponse(content=[])
        trades = engine.get_trade_history()
        trades = sorted(
            trades,
            key=lambda t: t.timestamp or datetime.min,
            reverse=True,
        )[:limit]
        rows = []
        for t in trades:
            rows.append({
                "when": t.timestamp.isoformat() if t.timestamp else "",
                "symbol": t.symbol,
                "side": t.side.value if hasattr(t.side, "value") else str(t.side),
                "qty": t.quantity,
                "price": t.price,
                "commission": t.commission,
                "pnl": t.pnl,
            })
        return JSONResponse(content=rows)

    return router


# ── Agent router (Copilot) ─────────────────────────────────────────


def build_agent_router(fleet: Any) -> APIRouter:
    """Expose /agents.json + /query SSE for OpenBB Copilot."""
    router = APIRouter()

    @router.get("/agents.json")
    def agents_meta() -> JSONResponse:
        # Schema mirrors the canonical vanilla agent examples at
        # copilot-for-openbb/30-vanilla-agent-raw-widget-data/...
        # Workspace does strict validation; "image" must be a real
        # URL if present — omit entirely rather than pass an empty
        # string (discovered 2026-04-19 via
        # "Invalid agents schema from the server" error).
        return JSONResponse(content={
            "neomind_fin": {
                "name": "NeoMind Fin Persona",
                "description": (
                    "DeepSeek-R1 backed fin-rt fleet worker. Paper-trading "
                    "aware, Investment-root data firewall. Responds in "
                    "the user's language."
                ),
                "endpoints": {"query": "/openbb/query"},
                "features": {
                    "streaming": True,
                    "widget-dashboard-select": False,
                    "widget-dashboard-search": False,
                },
            },
        })

    @router.post("/query")
    async def query(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "invalid JSON body")

        messages = body.get("messages") or []
        # Extract the latest human message
        last_human = ""
        for m in reversed(messages):
            if m.get("role") in ("human", "user"):
                last_human = str(m.get("content") or "").strip()
                break
        if not last_human:
            raise HTTPException(400, "no human message in request")
        if len(last_human) > 4000:
            raise HTTPException(400, "message too long (max 4000 chars)")

        # Default project for Copilot queries. Future: read from
        # widget-dashboard-select feature when we enable it.
        project_id = body.get("project_id") or "fin-core"
        if project_id not in investment_projects.list_projects():
            raise HTTPException(
                404, f"project {project_id!r} is not registered"
            )

        # Build the same tool-free chat prompt used by /api/chat
        from agent.finance.chat_stream import build_chat_prompt
        prompt = build_chat_prompt(last_human, project_id)

        try:
            task_id = await fleet.dispatch_chat(
                prompt, project_id, original_message=last_human
            )
        except Exception as exc:
            logger.exception("openbb agent dispatch failed")
            raise HTTPException(502, f"fleet dispatch failed: {exc}")

        async def event_generator():
            # Emit initial status so Copilot UI shows something
            yield {
                "event": "message",
                "data": json.dumps({"content": f"⏳ fin-rt working (task {task_id[:8]}…)"}),
            }
            deadline = time.time() + 180
            last_status = "pending"
            while time.time() < deadline:
                try:
                    status = fleet.get_task_status(task_id)
                except HTTPException:
                    yield {"event": "message",
                           "data": json.dumps({"content": "✗ task lookup failed"})}
                    return
                st = status.get("status")
                if st == "completed":
                    reply = status.get("reply") or "(empty reply)"
                    yield {"event": "message",
                           "data": json.dumps({"content": reply})}
                    return
                if st == "failed":
                    err = status.get("error") or "task failed"
                    yield {"event": "message",
                           "data": json.dumps({"content": f"✗ {err}"})}
                    return
                if st != last_status:
                    last_status = st
                    yield {"event": "status",
                           "data": json.dumps({"content": st})}
                await asyncio.sleep(1.5)
            yield {"event": "message",
                   "data": json.dumps({"content": "⚠ timed out after 180s"})}

        return EventSourceResponse(event_generator())

    return router
