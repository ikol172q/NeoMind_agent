"""Minimal local fin dashboard — FastAPI on localhost:8001.

Phase 5 of the fin-deepening fusion plan
(``plans/2026-04-12_fin_deepening_fusion_plan.md`` §5). A single-page
dark-theme HTML UI sitting on top of the existing finance stack:

- ``data_hub.DataHub.get_quote`` for live quotes (Finnhub → Alpha Vantage
  → yfinance fallback ladder, already shipped).
- ``investment_projects.write_analysis`` for per-project analysis
  persistence under the ``~/Desktop/Investment/<project>/analyses/``
  data firewall.
- ``investment_projects.list_projects`` for the project selector.

Endpoints
---------
GET  /                       — HTML single-page UI
GET  /api/health             — liveness probe
GET  /api/projects           — {"projects": [...]} registered project ids
GET  /api/quote/{symbol}     — live quote via DataHub
POST /api/analyze/{symbol}   — synchronous minimal analysis; writes to
                               ``<project>/analyses/`` and returns the
                               serialised signal dict. Query param:
                               ``project_id`` (required, path-validated).
GET  /api/history            — list recent analysis files for a project.
                               Query params: ``project_id`` (required),
                               ``limit`` (default 20).

The analyze endpoint in Phase 5 MVP runs a **synchronous lightweight
analysis**: it fetches the current quote via DataHub, constructs a
conservative ``hold`` ``AgentAnalysis`` enriched with the live price
and timestamp, and writes it to the project's ``analyses/`` dir.
Fleet-based asynchronous dispatch
(``FleetLauncher.submit_task``) is deferred to a follow-up — the MVP
only needs to prove the dashboard wiring, UI, and data firewall write
path work end-to-end.

The dashboard is instantiated via ``create_app()`` so tests can inject
a custom investment root (``NEOMIND_INVESTMENT_ROOT`` env var) and use
a mock ``DataHub``. Run locally with::

    python -m agent.finance.dashboard_server

which boots uvicorn on ``127.0.0.1:8001``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from agent.finance import investment_projects
from agent.finance.signal_schema import AgentAnalysis
from agent.finance.paper_trading import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTradingEngine,
)

logger = logging.getLogger(__name__)

# Safety: anything going into a URL path segment or query param as a
# symbol must pass this regex. Same shape as _SYMBOL_RE in
# investment_projects.py so we never try to write a file we can't.
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9\.\-]{0,15}$")

# Project id regex mirrors investment_projects._PROJECT_ID_RE.
_PROJECT_ID_RE = re.compile(r"^[a-z0-9_\-]{2,40}$")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001


# ── HTML payload (inlined so no static file wrangling) ─────────────

_INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>neomind · fin dashboard</title>
<style>
:root {
  --bg: #0b0d12;
  --panel: #141822;
  --border: #1f2631;
  --text: #d8dde6;
  --dim: #7c8598;
  --accent: #4dd0e1;
  --green: #6fd07a;
  --red: #e57373;
  --yellow: #f3c969;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0;
  font-family: -apple-system, SF Mono, Monaco, Menlo, monospace;
  background: var(--bg); color: var(--text); font-size: 14px;
}
header {
  padding: 14px 22px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 18px;
  background: var(--panel);
}
header h1 { margin: 0; font-size: 16px; font-weight: 600; }
header .dim { color: var(--dim); font-size: 12px; }
main { max-width: 980px; margin: 0 auto; padding: 22px; }
section {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 6px; padding: 16px 18px; margin-bottom: 16px;
}
section h2 { margin: 0 0 10px; font-size: 13px; color: var(--dim);
  text-transform: uppercase; letter-spacing: 0.06em; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
input, select, button {
  background: #0e1219; color: var(--text);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 7px 11px; font-family: inherit; font-size: 13px;
}
input:focus, select:focus { outline: 1px solid var(--accent); }
button {
  cursor: pointer; color: var(--bg); background: var(--accent);
  border-color: var(--accent); font-weight: 600;
}
button.secondary {
  background: transparent; color: var(--accent);
}
button:disabled { opacity: 0.4; cursor: default; }
.quote {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px; margin-top: 12px;
}
.quote div { padding: 8px 10px; background: #0e1219;
  border: 1px solid var(--border); border-radius: 4px; }
.quote .label { color: var(--dim); font-size: 11px;
  text-transform: uppercase; }
.quote .value { font-size: 17px; margin-top: 2px; }
.up { color: var(--green); }
.down { color: var(--red); }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 7px 9px;
  border-bottom: 1px solid var(--border); font-size: 12px; }
th { color: var(--dim); text-transform: uppercase;
  font-weight: 500; letter-spacing: 0.04em; }
td.sig-buy { color: var(--green); font-weight: 600; }
td.sig-sell { color: var(--red); font-weight: 600; }
td.sig-hold { color: var(--yellow); font-weight: 600; }
.toast {
  position: fixed; bottom: 20px; right: 20px;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 4px; padding: 10px 14px; color: var(--text);
  font-size: 12px; opacity: 0; transition: opacity 0.2s;
}
.toast.show { opacity: 1; }
.empty { color: var(--dim); font-style: italic; padding: 8px 0; }
</style>
</head>
<body>
<header>
  <h1>◇ neomind / fin dashboard</h1>
  <span class="dim">local-only · <span id="api-health">…</span></span>
</header>
<main>
  <section>
    <h2>project</h2>
    <div class="row">
      <select id="project-select"></select>
      <button class="secondary" id="refresh-projects">↻</button>
    </div>
  </section>

  <section>
    <h2>quote</h2>
    <div class="row">
      <input id="symbol-input" placeholder="AAPL" autocomplete="off"
        style="width: 160px; text-transform: uppercase;">
      <button id="quote-btn">get quote</button>
      <button id="analyze-btn">analyze</button>
    </div>
    <div id="quote-out" class="empty">no quote yet</div>
  </section>

  <section>
    <h2>history</h2>
    <div id="history-out" class="empty">no analyses yet</div>
  </section>

  <section>
    <h2>paper trading · account</h2>
    <div id="account-out" class="empty">(no project selected)</div>
    <div class="row" style="margin-top: 10px;">
      <button class="secondary" id="refresh-paper">↻ refresh prices</button>
      <button class="secondary" id="reset-paper" style="border-color: var(--red); color: var(--red);">reset account</button>
    </div>
  </section>

  <section>
    <h2>paper trading · positions</h2>
    <div id="positions-out" class="empty">no positions</div>
  </section>

  <section>
    <h2>paper trading · place order</h2>
    <div class="row">
      <input id="order-symbol" placeholder="AAPL" autocomplete="off"
        style="width: 110px; text-transform: uppercase;">
      <select id="order-side">
        <option value="buy">buy</option>
        <option value="sell">sell</option>
      </select>
      <select id="order-type">
        <option value="market">market</option>
        <option value="limit">limit</option>
        <option value="stop">stop</option>
      </select>
      <input id="order-qty" type="number" placeholder="qty" min="1" step="1"
        style="width: 100px;">
      <input id="order-price" type="number" placeholder="price (limit/stop)"
        step="0.01" style="width: 180px;">
      <button id="place-order">place</button>
    </div>
  </section>

  <section>
    <h2>paper trading · recent trades</h2>
    <div id="trades-out" class="empty">no trades yet</div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
const $ = id => document.getElementById(id);
const show = (msg, isErr) => {
  const t = $("toast");
  t.textContent = msg;
  t.style.borderColor = isErr ? "var(--red)" : "var(--border)";
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2500);
};

async function api(path, opts) {
  const res = await fetch(path, opts || {});
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

async function refreshHealth() {
  try {
    const h = await api("/api/health");
    $("api-health").textContent = "healthy · " + (h.version || "");
  } catch (e) {
    $("api-health").textContent = "unreachable";
  }
}

async function refreshProjects() {
  try {
    const { projects } = await api("/api/projects");
    const sel = $("project-select");
    const prev = sel.value;
    sel.innerHTML = "";
    if (projects.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no projects — create one under ~/Desktop/Investment/)";
      sel.appendChild(opt);
    } else {
      projects.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        sel.appendChild(opt);
      });
      if (projects.includes(prev)) sel.value = prev;
    }
    if (sel.value) refreshHistory();
  } catch (e) {
    show("projects: " + e.message, true);
  }
}

function renderQuote(q) {
  const up = q.change >= 0;
  const arrow = up ? "▲" : "▼";
  const cls = up ? "up" : "down";
  $("quote-out").innerHTML = `
    <div class="quote">
      <div><div class="label">symbol</div><div class="value">${q.symbol}</div></div>
      <div><div class="label">price</div><div class="value">${q.price?.toFixed?.(2) ?? q.price}</div></div>
      <div><div class="label">change</div><div class="value ${cls}">${arrow} ${q.change?.toFixed?.(2) ?? q.change} (${q.change_pct?.toFixed?.(2) ?? q.change_pct}%)</div></div>
      <div><div class="label">volume</div><div class="value">${q.volume?.toLocaleString?.() ?? q.volume}</div></div>
      <div><div class="label">high · low</div><div class="value">${q.high?.toFixed?.(2)} · ${q.low?.toFixed?.(2)}</div></div>
      <div><div class="label">source</div><div class="value" style="font-size:12px">${q.source || "?"} · ${q.market_status || ""}</div></div>
    </div>`;
}

async function doQuote() {
  const sym = $("symbol-input").value.trim().toUpperCase();
  if (!sym) return show("enter a symbol", true);
  try {
    const q = await api("/api/quote/" + encodeURIComponent(sym));
    renderQuote(q);
  } catch (e) { show("quote: " + e.message, true); }
}

async function doAnalyze() {
  const sym = $("symbol-input").value.trim().toUpperCase();
  const pid = $("project-select").value;
  if (!sym) return show("enter a symbol", true);
  if (!pid) return show("select a project first", true);
  try {
    const r = await api(
      "/api/analyze/" + encodeURIComponent(sym) + "?project_id=" + encodeURIComponent(pid),
      { method: "POST" }
    );
    show("wrote analysis → " + (r.artifact || "ok"));
    refreshHistory();
  } catch (e) { show("analyze: " + e.message, true); }
}

async function refreshHistory() {
  const pid = $("project-select").value;
  if (!pid) return;
  try {
    const { items } = await api("/api/history?project_id=" + encodeURIComponent(pid) + "&limit=20");
    const out = $("history-out");
    if (!items.length) { out.className = "empty"; out.textContent = "no analyses yet"; return; }
    out.className = "";
    out.innerHTML = `<table><thead><tr><th>when</th><th>symbol</th><th>signal</th><th>conf</th><th>risk</th><th>reason</th></tr></thead><tbody>${
      items.map(it => {
        const s = it.signal?.signal || "?";
        return `<tr>
          <td>${it.written_at?.slice(0, 16) || ""}</td>
          <td>${it.symbol}</td>
          <td class="sig-${s}">${s}</td>
          <td>${it.signal?.confidence ?? ""}</td>
          <td>${it.signal?.risk_level ?? ""}</td>
          <td>${(it.signal?.reason ?? "").slice(0, 80)}</td>
        </tr>`;
      }).join("")
    }</tbody></table>`;
  } catch (e) { show("history: " + e.message, true); }
}

// ── Paper trading wiring ───────────────────────────────

const fmt = n => (n == null ? "—" : Number(n).toLocaleString(undefined, {maximumFractionDigits: 2}));
const pctCls = n => (n > 0 ? "up" : n < 0 ? "down" : "");

async function refreshAccount() {
  const pid = $("project-select").value;
  if (!pid) return;
  try {
    const a = await api("/api/paper/account?project_id=" + encodeURIComponent(pid));
    const cls = pctCls(a.total_pnl);
    $("account-out").className = "";
    $("account-out").innerHTML = `
      <div class="quote">
        <div><div class="label">cash</div><div class="value">$${fmt(a.cash)}</div></div>
        <div><div class="label">equity</div><div class="value">$${fmt(a.equity)}</div></div>
        <div><div class="label">total pnl</div><div class="value ${cls}">$${fmt(a.total_pnl)} (${fmt(a.total_pnl_pct)}%)</div></div>
        <div><div class="label">realized</div><div class="value">$${fmt(a.realized_pnl)}</div></div>
        <div><div class="label">unrealized</div><div class="value">$${fmt(a.unrealized_pnl)}</div></div>
        <div><div class="label">trades</div><div class="value">${a.total_trades} (${fmt(a.win_rate)}% win)</div></div>
      </div>`;
  } catch (e) { show("account: " + e.message, true); }
}

async function refreshPositions() {
  const pid = $("project-select").value;
  if (!pid) return;
  try {
    const { positions } = await api("/api/paper/positions?project_id=" + encodeURIComponent(pid));
    const out = $("positions-out");
    if (!positions.length) { out.className = "empty"; out.textContent = "no positions"; return; }
    out.className = "";
    out.innerHTML = `<table><thead><tr>
      <th>symbol</th><th>side</th><th>qty</th><th>entry</th><th>current</th><th>unreal. pnl</th><th>%</th><th>opened</th>
    </tr></thead><tbody>${
      positions.map(p => {
        const cls = pctCls(p.unrealized_pnl);
        return `<tr>
          <td><b>${p.symbol}</b></td>
          <td>${p.side}</td>
          <td>${fmt(p.quantity)}</td>
          <td>$${fmt(p.entry_price)}</td>
          <td>$${fmt(p.current_price)}</td>
          <td class="${cls}">$${fmt(p.unrealized_pnl)}</td>
          <td class="${cls}">${fmt(p.unrealized_pnl_pct)}%</td>
          <td>${(p.opened_at || "").slice(0, 10)}</td>
        </tr>`;
      }).join("")
    }</tbody></table>`;
  } catch (e) { show("positions: " + e.message, true); }
}

async function refreshTrades() {
  const pid = $("project-select").value;
  if (!pid) return;
  try {
    const { trades } = await api("/api/paper/trades?project_id=" + encodeURIComponent(pid) + "&limit=20");
    const out = $("trades-out");
    if (!trades.length) { out.className = "empty"; out.textContent = "no trades yet"; return; }
    out.className = "";
    out.innerHTML = `<table><thead><tr>
      <th>when</th><th>symbol</th><th>side</th><th>qty</th><th>price</th><th>comm</th><th>pnl</th>
    </tr></thead><tbody>${
      trades.map(t => {
        const cls = pctCls(t.pnl);
        return `<tr>
          <td>${(t.timestamp || "").slice(0, 16)}</td>
          <td><b>${t.symbol}</b></td>
          <td class="sig-${t.side === "buy" ? "buy" : "sell"}">${t.side}</td>
          <td>${fmt(t.quantity)}</td>
          <td>$${fmt(t.price)}</td>
          <td>$${fmt(t.commission)}</td>
          <td class="${cls}">$${fmt(t.pnl)}</td>
        </tr>`;
      }).join("")
    }</tbody></table>`;
  } catch (e) { show("trades: " + e.message, true); }
}

async function refreshPaperAll() {
  await refreshAccount();
  await refreshPositions();
  await refreshTrades();
}

async function doPaperRefresh() {
  const pid = $("project-select").value;
  if (!pid) return show("select a project first", true);
  try {
    const r = await api("/api/paper/refresh?project_id=" + encodeURIComponent(pid), { method: "POST" });
    show(`prices refreshed: ${r.updated.length} ok, ${r.failures.length} failed`);
    refreshPaperAll();
  } catch (e) { show("refresh: " + e.message, true); }
}

async function doPlaceOrder() {
  const pid = $("project-select").value;
  if (!pid) return show("select a project first", true);
  const sym = $("order-symbol").value.trim().toUpperCase();
  const side = $("order-side").value;
  const type = $("order-type").value;
  const qty = $("order-qty").value;
  const price = $("order-price").value;
  if (!sym || !qty) return show("symbol + qty required", true);

  const params = new URLSearchParams({
    project_id: pid,
    symbol: sym,
    side: side,
    order_type: type,
    quantity: qty,
  });
  if (price) params.set("price", price);
  if (type === "stop" && price) params.set("stop_price", price);

  try {
    const r = await api("/api/paper/order?" + params.toString(), { method: "POST" });
    const status = r.order.status;
    if (status === "filled") {
      show(`✓ ${side} ${qty} ${sym} @ $${fmt(r.order.filled_price)}`);
    } else if (status === "rejected") {
      show(`✗ rejected: ${r.order.error || "unknown"}`, true);
    } else {
      show(`${status}: ${sym}`);
    }
    $("order-qty").value = "";
    $("order-price").value = "";
    refreshPaperAll();
  } catch (e) { show("order: " + e.message, true); }
}

async function doReset() {
  const pid = $("project-select").value;
  if (!pid) return;
  if (!confirm(`Really reset paper trading account for "${pid}"?\nThis wipes all positions and history.`)) return;
  try {
    await api("/api/paper/reset?project_id=" + encodeURIComponent(pid) + "&confirm=yes", { method: "POST" });
    show("account reset");
    refreshPaperAll();
  } catch (e) { show("reset: " + e.message, true); }
}

$("quote-btn").onclick = doQuote;
$("analyze-btn").onclick = doAnalyze;
$("refresh-projects").onclick = refreshProjects;
$("refresh-paper").onclick = doPaperRefresh;
$("reset-paper").onclick = doReset;
$("place-order").onclick = doPlaceOrder;
$("project-select").onchange = () => { refreshHistory(); refreshPaperAll(); };
$("symbol-input").addEventListener("keydown", e => {
  if (e.key === "Enter") doQuote();
});
$("order-symbol").addEventListener("keydown", e => {
  if (e.key === "Enter") doPlaceOrder();
});

refreshHealth();
refreshProjects();
setInterval(refreshHealth, 15000);
</script>
</body>
</html>
"""


# ── Helpers ─────────────────────────────────────────────────────────

def _quote_to_dict(quote) -> Dict[str, Any]:
    """Flatten a DataHub ``StockQuote`` into a JSON-friendly dict.
    ``price`` is a ``VerifiedDataPoint`` so we unwrap it to the raw
    float and surface the source as a sibling field.
    """
    if quote is None:
        return {}
    price_val = None
    source = None
    freshness = None
    price = getattr(quote, "price", None)
    if price is not None:
        price_val = getattr(price, "value", None)
        source = getattr(price, "source", None)
        freshness = getattr(price, "freshness", None)
    return {
        "symbol": quote.symbol,
        "price": price_val,
        "change": quote.change,
        "change_pct": quote.change_pct,
        "volume": quote.volume,
        "high": quote.high,
        "low": quote.low,
        "open": quote.open,
        "prev_close": quote.prev_close,
        "market_cap": quote.market_cap,
        "pe_ratio": quote.pe_ratio,
        "name": quote.name,
        "market": quote.market,
        "currency": quote.currency,
        "market_status": quote.market_status,
        "source": source,
        "freshness": freshness,
    }


def _paper_state_filename() -> str:
    """Relative filename under the engine's ``data_dir``. We use a
    fixed name per project since each project gets its own engine
    instance with its own data_dir."""
    return "state.json"


def _order_to_dict(order) -> Dict[str, Any]:
    return {
        "id": order.id,
        "symbol": order.symbol,
        "side": order.side.value,
        "order_type": order.order_type.value,
        "quantity": order.quantity,
        "price": order.price,
        "stop_price": order.stop_price,
        "status": order.status.value,
        "filled_quantity": order.filled_quantity,
        "filled_price": order.filled_price,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "filled_at": order.filled_at.isoformat() if order.filled_at else None,
        "commission": order.commission,
        "error": order.metadata.get("error"),
    }


def _position_to_dict(pos) -> Dict[str, Any]:
    return {
        "symbol": pos.symbol,
        "quantity": pos.quantity,
        "entry_price": pos.entry_price,
        "current_price": pos.current_price,
        "side": pos.side.value,
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
        "unrealized_pnl": pos.unrealized_pnl,
        "unrealized_pnl_pct": pos.unrealized_pnl_pct,
    }


def _trade_to_dict(trade) -> Dict[str, Any]:
    return {
        "id": trade.id,
        "order_id": trade.order_id,
        "symbol": trade.symbol,
        "side": trade.side.value,
        "quantity": trade.quantity,
        "price": trade.price,
        "commission": trade.commission,
        "pnl": trade.pnl,
        "timestamp": trade.timestamp.isoformat() if trade.timestamp else None,
    }


def _list_recent_analyses(project_id: str, limit: int) -> List[Dict[str, Any]]:
    """Read the most recent ``<project>/analyses/*.json`` files,
    newest first, up to ``limit``. Malformed JSON entries are skipped
    with a debug log — never raise to the caller."""
    proj = investment_projects.get_project_dir(project_id)
    analyses_dir = proj / "analyses"
    if not analyses_dir.exists():
        return []
    files = sorted(
        (p for p in analyses_dir.iterdir() if p.suffix == ".json"),
        reverse=True,
    )[:limit]
    out: List[Dict[str, Any]] = []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.debug("dashboard: skipping malformed %s: %s", f, exc)
    return out


# ── App factory ─────────────────────────────────────────────────────

def create_app(
    data_hub: Optional[Any] = None,
    version: str = "phase5-mvp",
    paper_engine_factory: Optional[Any] = None,
) -> FastAPI:
    """Build a FastAPI app with all dashboard routes registered.

    ``data_hub`` is injected so tests can pass a mock without importing
    the real yfinance / finnhub stack. ``paper_engine_factory`` is
    optional dependency-injection for paper-trading state isolation
    in tests: a callable ``(project_id: str) -> PaperTradingEngine``.
    In production the default factory builds one engine per project
    with state persisted under
    ``<project>/paper_trading/state.json``.
    """
    app = FastAPI(title="neomind-fin-dashboard", version=version)

    def _get_hub():
        nonlocal data_hub
        if data_hub is None:
            from agent.finance.data_hub import DataHub
            data_hub = DataHub()
        return data_hub

    # Per-project paper trading engines, lazily constructed and cached
    # so hot reloads of the UI don't re-parse state.json on every
    # request. Keyed by project_id.
    paper_engines: Dict[str, PaperTradingEngine] = {}

    def _default_paper_factory(project_id: str) -> PaperTradingEngine:
        proj_dir = investment_projects.get_project_dir(project_id)
        data_dir = proj_dir / "paper_trading"
        data_dir.mkdir(parents=True, exist_ok=True)
        eng = PaperTradingEngine(
            initial_capital=100_000.0,
            data_dir=data_dir,
        )
        # Restore prior state if present
        eng.load_state(_paper_state_filename())
        return eng

    engine_factory = paper_engine_factory or _default_paper_factory

    def _get_engine(project_id: str) -> PaperTradingEngine:
        if not _PROJECT_ID_RE.match(project_id):
            raise HTTPException(400, f"invalid project_id {project_id!r}")
        if project_id not in investment_projects.list_projects():
            raise HTTPException(
                404, f"project {project_id!r} is not registered"
            )
        if project_id not in paper_engines:
            paper_engines[project_id] = engine_factory(project_id)
        return paper_engines[project_id]

    def _persist(engine: PaperTradingEngine) -> None:
        try:
            engine.save_state(_paper_state_filename())
        except Exception as exc:
            logger.warning("paper_trading save_state failed: %s", exc)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(content=_INDEX_HTML, status_code=200)

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": version,
            "investment_root": str(investment_projects.get_investment_root()),
        }

    @app.get("/api/projects")
    def projects() -> Dict[str, Any]:
        return {"projects": investment_projects.list_projects()}

    @app.get("/api/quote/{symbol}")
    async def quote(symbol: str, market: str = "us") -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        hub = _get_hub()
        try:
            q = await hub.get_quote(sym, market=market)
        except Exception as exc:
            logger.warning("dashboard quote failed for %s: %s", sym, exc)
            raise HTTPException(502, f"upstream quote failed: {exc}")
        if q is None:
            raise HTTPException(
                404, f"no quote available for {sym} (tried all providers)"
            )
        return _quote_to_dict(q)

    @app.post("/api/analyze/{symbol}")
    async def analyze(
        symbol: str,
        project_id: str = Query(..., description="registered project id"),
        market: str = "us",
    ) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        if not _PROJECT_ID_RE.match(project_id):
            raise HTTPException(400, f"invalid project_id {project_id!r}")
        if project_id not in investment_projects.list_projects():
            raise HTTPException(
                404, f"project {project_id!r} is not registered"
            )

        hub = _get_hub()
        try:
            q = await hub.get_quote(sym, market=market)
        except Exception as exc:
            logger.warning("dashboard analyze quote failed: %s", exc)
            q = None

        # Phase 5 MVP: synthesise a conservative AgentAnalysis from
        # the live quote. Richer LLM-based analysis will come via the
        # fleet submit_task path in a follow-up.
        price_val = None
        source = "unknown"
        if q is not None and getattr(q, "price", None) is not None:
            price_val = q.price.value
            source = q.price.source or "unknown"

        if price_val is None:
            # No quote → still write a conservative hold with a clear
            # reason, so the user sees evidence of the attempt.
            analysis = AgentAnalysis(
                signal="hold",
                confidence=1,
                reason=f"[dashboard] no live quote available for {sym}",
                target_price=None,
                risk_level="high",
                sources=["dashboard"],
            )
        else:
            analysis = AgentAnalysis(
                signal="hold",
                confidence=3,
                reason=(
                    f"[dashboard] live quote snapshot {sym} @ {price_val} "
                    f"(change {q.change_pct:+.2f}%) — MVP analysis, no "
                    f"fundamentals or indicators yet"
                ),
                target_price=None,
                risk_level="medium",
                sources=[source, "dashboard"],
            )

        try:
            path = investment_projects.write_analysis(
                project_id, sym, analysis.model_dump()
            )
        except Exception as exc:
            raise HTTPException(500, f"write_analysis failed: {exc}")

        return {
            "project_id": project_id,
            "symbol": sym,
            "artifact": str(path),
            "signal": analysis.model_dump(),
            "quote": _quote_to_dict(q) if q is not None else None,
        }

    @app.get("/api/history")
    def history(
        project_id: str = Query(..., description="registered project id"),
        limit: int = Query(20, ge=1, le=200),
    ) -> Dict[str, Any]:
        if not _PROJECT_ID_RE.match(project_id):
            raise HTTPException(400, f"invalid project_id {project_id!r}")
        if project_id not in investment_projects.list_projects():
            raise HTTPException(
                404, f"project {project_id!r} is not registered"
            )
        items = _list_recent_analyses(project_id, limit)
        return {"project_id": project_id, "count": len(items), "items": items}

    # ── Paper trading (Phase 5.6 additions) ──────────────────────

    @app.get("/api/paper/account")
    def paper_account(
        project_id: str = Query(...),
    ) -> Dict[str, Any]:
        engine = _get_engine(project_id)
        summary = engine.get_account_summary()
        summary["project_id"] = project_id
        return summary

    @app.get("/api/paper/positions")
    def paper_positions(
        project_id: str = Query(...),
    ) -> Dict[str, Any]:
        engine = _get_engine(project_id)
        positions = [_position_to_dict(p) for p in engine.get_all_positions()]
        return {"project_id": project_id, "positions": positions}

    @app.get("/api/paper/orders")
    def paper_orders(
        project_id: str = Query(...),
    ) -> Dict[str, Any]:
        engine = _get_engine(project_id)
        return {
            "project_id": project_id,
            "open": [_order_to_dict(o) for o in engine.get_open_orders()],
        }

    @app.get("/api/paper/trades")
    def paper_trades(
        project_id: str = Query(...),
        limit: int = Query(50, ge=1, le=500),
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        engine = _get_engine(project_id)
        trades = engine.get_trade_history(symbol=symbol)
        # Newest first, limit N
        trades = sorted(
            trades,
            key=lambda t: t.timestamp or datetime.min,
            reverse=True,
        )[:limit]
        return {
            "project_id": project_id,
            "trades": [_trade_to_dict(t) for t in trades],
        }

    @app.post("/api/paper/order")
    async def paper_place_order(
        project_id: str = Query(...),
        symbol: str = Query(...),
        side: str = Query(..., description="buy | sell"),
        quantity: float = Query(..., gt=0),
        order_type: str = Query("market", description="market | limit | stop"),
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        market: str = "us",
    ) -> Dict[str, Any]:
        engine = _get_engine(project_id)
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        try:
            side_enum = OrderSide(side.lower())
        except ValueError:
            raise HTTPException(400, f"invalid side {side!r} (buy|sell)")
        try:
            type_enum = OrderType(order_type.lower())
        except ValueError:
            raise HTTPException(
                400, f"invalid order_type {order_type!r} (market|limit|stop)"
            )

        # For market orders, fetch a fresh price from DataHub so the
        # engine has something to fill against. The engine's own
        # _prices cache may be stale if the dashboard hasn't polled
        # quotes recently.
        if type_enum == OrderType.MARKET:
            try:
                q = await _get_hub().get_quote(sym, market=market)
            except Exception as exc:
                logger.warning(
                    "paper_order quote fetch failed for %s: %s", sym, exc
                )
                q = None
            if q is None or getattr(q, "price", None) is None:
                raise HTTPException(
                    502,
                    f"could not fetch quote for {sym} to fill market order",
                )
            engine.update_price(sym, q.price.value)

        order = engine.place_order(
            symbol=sym,
            side=side_enum,
            quantity=quantity,
            order_type=type_enum,
            price=price,
            stop_price=stop_price,
        )
        _persist(engine)
        return {
            "project_id": project_id,
            "order": _order_to_dict(order),
        }

    @app.post("/api/paper/refresh")
    async def paper_refresh(
        project_id: str = Query(...),
        market: str = "us",
    ) -> Dict[str, Any]:
        """Pull fresh quotes from DataHub for every currently-held
        symbol and feed them into the engine so unrealized PnL is
        up-to-date. Also triggers any pending limit/stop orders that
        have crossed their trigger price."""
        engine = _get_engine(project_id)
        hub = _get_hub()
        updated: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        # Symbols we care about: held positions + open order targets
        symbols = set(engine.account.positions.keys())
        for o in engine.get_open_orders():
            symbols.add(o.symbol)

        for sym in sorted(symbols):
            try:
                q = await hub.get_quote(sym, market=market)
            except Exception as exc:
                failures.append({"symbol": sym, "error": str(exc)})
                continue
            if q is None or getattr(q, "price", None) is None:
                failures.append({"symbol": sym, "error": "no quote"})
                continue
            engine.update_price(sym, q.price.value)
            updated.append({"symbol": sym, "price": q.price.value})

        _persist(engine)
        return {
            "project_id": project_id,
            "updated": updated,
            "failures": failures,
        }

    @app.post("/api/paper/reset")
    def paper_reset(
        project_id: str = Query(...),
        confirm: str = Query(
            "", description="must equal 'yes' to actually reset"
        ),
        initial_capital: float = Query(100_000.0, gt=0),
    ) -> Dict[str, Any]:
        if confirm != "yes":
            raise HTTPException(
                400,
                "reset requires ?confirm=yes (this wipes all paper "
                "positions and history for the project)",
            )
        engine = _get_engine(project_id)
        engine.reset(initial_capital=initial_capital)
        _persist(engine)
        return {"project_id": project_id, "reset": True}

    return app


def main() -> None:
    """CLI entrypoint — ``python -m agent.finance.dashboard_server``."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="neomind fin dashboard (Phase 5 MVP)"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(
        f"◇ neomind fin dashboard → http://{args.host}:{args.port}",
        flush=True,
    )
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
