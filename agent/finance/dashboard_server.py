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
from agent.finance import technical_indicators as ti
from agent.finance.signal_schema import AgentAnalysis
from agent.finance.paper_trading import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperTradingEngine,
)

# Fleet imports are intentionally lazy inside FleetBackend.ensure_started
# so the dashboard boots fast even when no one asks for fleet dispatch.

logger = logging.getLogger(__name__)

# Safety: anything going into a URL path segment or query param as a
# symbol must pass this regex. Same shape as _SYMBOL_RE in
# investment_projects.py so we never try to write a file we can't.
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9\.\-]{0,15}$")

# Project id regex mirrors investment_projects._PROJECT_ID_RE.
_PROJECT_ID_RE = re.compile(r"^[a-z0-9_\-]{2,40}$")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001
DEFAULT_FLEET_PROJECT_YAML = "projects/fin-core/project.yaml"


class FleetBackend:
    """Lazy singleton fleet-session holder for /api/analyze?use_fleet=1.

    The dashboard doesn't start a fleet on boot — that would pull in
    the full LLM service dep graph and slow every launchd restart.
    Instead, the FIRST request that asks for ``use_fleet=true``
    triggers ``ensure_started()``, which loads
    ``projects/fin-core/project.yaml`` and spawns a FleetSession on
    the uvicorn event loop. Subsequent requests reuse the live
    session.

    ``submit_to_member("fin-rt", ...)`` returns a task_id immediately.
    Results land asynchronously in the fin-rt AgentTranscript on
    disk; the GET /api/tasks/{task_id} endpoint resolves status +
    reply by walking the transcript for user+assistant turn pairs
    whose metadata contains the requested task_id.
    """

    def __init__(
        self,
        project_yaml: Optional[Path] = None,
        member: str = "fin-rt",
    ) -> None:
        self.project_yaml = project_yaml
        self.member = member
        self._session = None  # type: ignore[assignment]
        self._lock = asyncio.Lock()
        self._known_tasks: Dict[str, Dict[str, Any]] = {}

    def session_or_none(self):
        return self._session

    async def ensure_started(self):
        """Lazy init — safe to call from concurrent requests."""
        if self._session is not None:
            return self._session
        async with self._lock:
            if self._session is not None:
                return self._session
            try:
                from fleet.project_schema import load_project_config
                from fleet.session import FleetSession
            except Exception as exc:
                raise HTTPException(
                    503,
                    f"fleet module unavailable: {exc}",
                )

            yaml_path = self.project_yaml or (
                Path(__file__).resolve().parent.parent.parent
                / DEFAULT_FLEET_PROJECT_YAML
            )
            if not yaml_path.exists():
                raise HTTPException(
                    503,
                    f"fleet project yaml not found: {yaml_path}",
                )

            try:
                cfg = load_project_config(str(yaml_path))
                session = FleetSession(cfg)
                await session.start()
            except Exception as exc:
                logger.exception("fleet start failed")
                raise HTTPException(
                    503, f"fleet start failed: {exc}"
                )

            self._session = session
            logger.info(
                "dashboard fleet started: project=%s member=%s",
                cfg.project_id, self.member,
            )
            return self._session

    async def dispatch_analysis(
        self, symbol: str, project_id: str,
    ) -> str:
        """Send a fin-rt analysis task and return its task_id."""
        session = await self.ensure_started()
        task_desc = (
            f"Analyze {symbol} and return a buy/hold/sell signal with "
            f"confidence (1-10), reason, risk_level. Project: "
            f"{project_id}. Return JSON matching the AgentAnalysis "
            f"schema (signal, confidence, reason, target_price, "
            f"risk_level, sources)."
        )
        try:
            task_id = await session.submit_to_member(self.member, task_desc)
        except Exception as exc:
            raise HTTPException(
                502, f"fleet dispatch failed: {exc}"
            )
        self._known_tasks[task_id] = {
            "task_id": task_id,
            "symbol": symbol,
            "project_id": project_id,
            "member": self.member,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        return task_id

    async def dispatch_chat(
        self,
        prompt: str,
        project_id: str,
        original_message: Optional[str] = None,
    ) -> str:
        """Send a free-form chat prompt to the fin-rt worker and
        return its task_id. Shares the same task ring buffer as
        ``dispatch_analysis`` so ``GET /api/tasks/{id}`` works for
        both kinds of requests.
        """
        session = await self.ensure_started()
        try:
            task_id = await session.submit_to_member(self.member, prompt)
        except Exception as exc:
            raise HTTPException(502, f"fleet chat dispatch failed: {exc}")
        self._known_tasks[task_id] = {
            "task_id": task_id,
            "kind": "chat",
            "project_id": project_id,
            "message": original_message if original_message is not None else prompt,
            "member": self.member,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        return task_id

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Resolve task_id → current status + result by walking the
        member's transcript for the matching user/assistant turn pair.
        """
        if task_id not in self._known_tasks:
            raise HTTPException(404, f"unknown task_id {task_id!r}")
        cached = dict(self._known_tasks[task_id])

        session = self._session
        if session is None:
            return cached

        transcript = session.get_transcript(cached["member"])
        if transcript is None:
            return cached

        # Walk the transcript for the matching user turn and the next
        # assistant turn. The user turn metadata carries the task_id.
        turns = transcript.turns
        found_user_idx = None
        for i, t in enumerate(turns):
            if t.role == "user" and (t.metadata or {}).get("task_id") == task_id:
                found_user_idx = i
                break
        if found_user_idx is None:
            return cached

        for t in turns[found_user_idx + 1:]:
            if t.role == "assistant":
                cached["status"] = "completed"
                cached["reply"] = t.content
                # Try to parse the reply as an AgentAnalysis signal for
                # structured rendering. Falls back to raw text.
                try:
                    from agent.finance.signal_schema import parse_signal
                    analysis, layer = parse_signal(t.content)
                    cached["signal"] = analysis.model_dump()
                    cached["layer_used"] = layer
                except Exception as exc:
                    logger.debug("signal parse failed for %s: %s", task_id, exc)
                self._known_tasks[task_id] = cached
                return cached

        # Check for task_failed event in the session's event buffer
        events = session.recent_events(cached["member"], limit=50)
        for ev in events:
            if (ev.metadata or {}).get("task_id") == task_id:
                if ev.kind == "task_failed":
                    cached["status"] = "failed"
                    cached["error"] = ev.content
                    return cached

        # Still pending
        return cached

    async def shutdown(self) -> None:
        if self._session is not None:
            try:
                await self._session.stop()
            except Exception as exc:
                logger.warning("fleet shutdown failed: %s", exc)
            self._session = None


# ── HTML payload (inlined so no static file wrangling) ─────────────

_INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>neomind · fin dashboard</title>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
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

/* ── News list ── */
.news-list { list-style: none; margin: 0; padding: 0; }
.news-list li {
  padding: 8px 10px; border-bottom: 1px solid var(--border);
  display: flex; gap: 10px; align-items: baseline;
}
.news-list li:last-child { border-bottom: none; }
.news-list a {
  color: var(--text); text-decoration: none; font-size: 13px;
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.news-list a:hover { color: var(--accent); }
.news-list .feed { color: var(--dim); font-size: 11px; flex-shrink: 0; }
.news-list .when { color: var(--dim); font-size: 11px; flex-shrink: 0; }

/* ── Chat floater ── */
#chat-floater {
  position: fixed; right: 20px; bottom: 70px;
  z-index: 999;
}
#chat-toggle {
  padding: 10px 16px; border-radius: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.4);
}
#chat-panel {
  position: absolute; bottom: 50px; right: 0;
  width: 420px; height: 520px;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 6px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  display: flex; flex-direction: column;
}
#chat-panel header {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  background: transparent;
}
#chat-panel header h3 {
  margin: 0; font-size: 13px; color: var(--dim);
  text-transform: uppercase; letter-spacing: 0.05em;
}
#chat-messages {
  flex: 1; overflow-y: auto; padding: 10px 14px;
  font-size: 13px; line-height: 1.5;
}
.chat-msg { margin-bottom: 10px; white-space: pre-wrap; word-break: break-word; }
.chat-user { color: var(--text); }
.chat-user::before { content: "› "; color: var(--accent); font-weight: 600; }
.chat-assistant { color: var(--text); }
.chat-assistant::before { content: "◆ "; color: var(--green); font-weight: 600; }
.chat-status { color: var(--dim); font-style: italic; font-size: 12px; }
.chat-error { color: var(--red); }
.chat-error::before { content: "✗ "; }
#chat-input-row {
  padding: 10px 12px; border-top: 1px solid var(--border);
  display: flex; gap: 8px;
}
#chat-input {
  flex: 1; padding: 6px 10px;
}
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
    <h2>news <button class="secondary" id="refresh-news" style="float:right; margin-top:-4px;">↻</button></h2>
    <div id="news-out" class="empty">loading…</div>
  </section>

  <section>
    <h2>quote</h2>
    <div class="row">
      <input id="symbol-input" placeholder="AAPL" autocomplete="off"
        style="width: 160px; text-transform: uppercase;">
      <button id="quote-btn">get quote</button>
      <button id="chart-btn">load chart</button>
      <button id="analyze-btn">analyze</button>
      <label style="color: var(--dim); font-size: 12px;">
        <input type="checkbox" id="use-fleet"> fleet (real LLM)
      </label>
    </div>
    <div id="quote-out" class="empty">no quote yet</div>
  </section>

  <section>
    <h2>chart</h2>
    <div class="row" style="margin-bottom: 10px;">
      <select id="chart-period">
        <option value="1mo">1M</option>
        <option value="3mo" selected>3M</option>
        <option value="6mo">6M</option>
        <option value="1y">1Y</option>
        <option value="2y">2Y</option>
        <option value="5y">5Y</option>
      </select>
      <select id="chart-interval">
        <option value="1d" selected>daily</option>
        <option value="1wk">weekly</option>
        <option value="1mo">monthly</option>
      </select>
      <label style="color: var(--dim); font-size: 12px;">
        <input type="checkbox" id="ind-sma20" checked> SMA20
      </label>
      <label style="color: var(--dim); font-size: 12px;">
        <input type="checkbox" id="ind-ema20" checked> EMA20
      </label>
      <label style="color: var(--dim); font-size: 12px;">
        <input type="checkbox" id="ind-bb" checked> BB
      </label>
      <label style="color: var(--dim); font-size: 12px;">
        <input type="checkbox" id="ind-rsi" checked> RSI
      </label>
      <label style="color: var(--dim); font-size: 12px;">
        <input type="checkbox" id="ind-macd" checked> MACD
      </label>
    </div>
    <div id="price-chart" style="width: 100%; height: 320px; background: #0e1219; border: 1px solid var(--border); border-radius: 4px;"></div>
    <div id="rsi-chart" style="width: 100%; height: 100px; background: #0e1219; border: 1px solid var(--border); border-radius: 4px; margin-top: 6px;"></div>
    <div id="macd-chart" style="width: 100%; height: 110px; background: #0e1219; border: 1px solid var(--border); border-radius: 4px; margin-top: 6px;"></div>
    <div id="chart-status" class="empty" style="margin-top: 6px;">(enter a symbol above and click "get quote" or "load chart")</div>
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

<div id="chat-floater">
  <button id="chat-toggle">◈ chat fin</button>
  <div id="chat-panel" style="display:none">
    <header>
      <h3>fin persona · deepseek-r1</h3>
      <button class="secondary" id="chat-close" style="padding:3px 9px; font-size:11px;">close</button>
    </header>
    <div id="chat-messages">
      <div class="chat-msg chat-status">select a project, then ask anything. audit log at ~/Desktop/Investment/&lt;project&gt;/chat_log/</div>
    </div>
    <div id="chat-input-row">
      <input id="chat-input" placeholder="ask fin…" autocomplete="off" maxlength="4000">
      <button id="chat-send">send</button>
    </div>
  </div>
</div>

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
  const useFleet = $("use-fleet").checked;
  const url = "/api/analyze/" + encodeURIComponent(sym) +
    "?project_id=" + encodeURIComponent(pid) +
    (useFleet ? "&use_fleet=true" : "");
  try {
    const r = await api(url, { method: "POST" });
    if (useFleet) {
      show("dispatched to fin-rt · task " + r.task_id.slice(0, 8) + "…");
      pollTask(r.task_id);
    } else {
      show("wrote analysis → " + (r.artifact || "ok"));
      refreshHistory();
    }
  } catch (e) { show("analyze: " + e.message, true); }
}

async function pollTask(taskId) {
  // Show a pending row in the history pane so the user sees it
  const out = $("history-out");
  const poll = async () => {
    try {
      const r = await api("/api/tasks/" + encodeURIComponent(taskId));
      if (r.status === "completed") {
        const sig = r.signal || {};
        show("✓ " + r.symbol + " · " + (sig.signal || "?").toUpperCase() +
             " · conf " + (sig.confidence ?? "?"));
        refreshHistory();
        return;
      }
      if (r.status === "failed") {
        show("✗ " + r.symbol + " · " + (r.error || "failed"), true);
        return;
      }
      // still pending — keep polling
      setTimeout(poll, 1500);
    } catch (e) {
      show("task poll: " + e.message, true);
    }
  };
  setTimeout(poll, 1000);
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

// ── Chart + indicators wiring ───────────────────────────

let priceChart = null, priceCandles = null;
let priceSma20 = null, priceEma20 = null;
let priceBbUpper = null, priceBbMiddle = null, priceBbLower = null;
let rsiChart = null, rsiLine = null;
let macdChart = null, macdLine = null, macdSignal = null, macdHist = null;

function _chartOpts() {
  if (typeof LightweightCharts === "undefined") return null;
  return {
    layout: { background: { color: "#0e1219" }, textColor: "#d8dde6" },
    grid: {
      vertLines: { color: "#1a1f2c" },
      horzLines: { color: "#1a1f2c" },
    },
    rightPriceScale: { borderColor: "#1f2631" },
    timeScale: { borderColor: "#1f2631", timeVisible: true },
    crosshair: { mode: 1 },
    handleScroll: true,
    handleScale: true,
  };
}

function _ensureCharts() {
  if (typeof LightweightCharts === "undefined") {
    $("chart-status").textContent = "(lightweight-charts CDN blocked — chart disabled)";
    return false;
  }
  const opts = _chartOpts();
  if (!priceChart) {
    priceChart = LightweightCharts.createChart($("price-chart"), opts);
    priceCandles = priceChart.addCandlestickSeries({
      upColor: "#6fd07a", downColor: "#e57373",
      borderVisible: false,
      wickUpColor: "#6fd07a", wickDownColor: "#e57373",
    });
  }
  if (!rsiChart) {
    rsiChart = LightweightCharts.createChart($("rsi-chart"), { ...opts, rightPriceScale: { borderColor: "#1f2631", autoScale: false, minValue: 0, maxValue: 100 }});
    rsiLine = rsiChart.addLineSeries({ color: "#4dd0e1", lineWidth: 1.5 });
    // 30 / 70 reference lines
    rsiChart.addLineSeries({ color: "#7c8598", lineWidth: 1, lineStyle: 2 });
    rsiChart.addLineSeries({ color: "#7c8598", lineWidth: 1, lineStyle: 2 });
  }
  if (!macdChart) {
    macdChart = LightweightCharts.createChart($("macd-chart"), opts);
    macdHist = macdChart.addHistogramSeries({ color: "#4dd0e1" });
    macdLine = macdChart.addLineSeries({ color: "#f3c969", lineWidth: 1.5 });
    macdSignal = macdChart.addLineSeries({ color: "#e57373", lineWidth: 1.5 });
  }
  return true;
}

function _toTime(isoStr) {
  // lightweight-charts accepts { year, month, day } for daily bars
  // or a unix timestamp in seconds. Use UTC date to avoid tz slippage.
  const d = new Date(isoStr);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
  };
}

function _seriesFromIndicator(bars, values) {
  const out = [];
  for (let i = 0; i < bars.length; i++) {
    if (values[i] != null) {
      out.push({ time: _toTime(bars[i].date), value: values[i] });
    }
  }
  return out;
}

async function loadChart() {
  const sym = $("symbol-input").value.trim().toUpperCase();
  if (!sym) return show("enter a symbol", true);
  if (!_ensureCharts()) return;

  const period = $("chart-period").value;
  const interval = $("chart-interval").value;
  const wanted = [];
  if ($("ind-sma20").checked) wanted.push("sma20");
  if ($("ind-ema20").checked) wanted.push("ema20");
  if ($("ind-bb").checked) wanted.push("bb");
  if ($("ind-rsi").checked) wanted.push("rsi");
  if ($("ind-macd").checked) wanted.push("macd");

  $("chart-status").textContent = "loading…";
  try {
    const r = await api(
      `/api/chart/${encodeURIComponent(sym)}?period=${period}&interval=${interval}&indicators=${wanted.join(",")}`
    );
    const bars = r.bars;
    if (!bars.length) {
      $("chart-status").textContent = "no data";
      return;
    }
    // Candles
    priceCandles.setData(bars.map(b => ({
      time: _toTime(b.date),
      open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    // Overlay indicators on the price chart
    for (const [ref, key, color] of [
      ["priceSma20", "sma20", "#f3c969"],
      ["priceEma20", "ema20", "#4dd0e1"],
    ]) {
      if (r.indicators[key]) {
        if (!window[ref]) {
          window[ref] = priceChart.addLineSeries({ color, lineWidth: 1.3 });
        }
        window[ref].setData(_seriesFromIndicator(bars, r.indicators[key]));
      } else if (window[ref]) {
        window[ref].setData([]);
      }
    }
    if (r.indicators.bb) {
      if (!priceBbUpper) {
        priceBbUpper = priceChart.addLineSeries({ color: "#7c8598", lineWidth: 1, lineStyle: 2 });
        priceBbLower = priceChart.addLineSeries({ color: "#7c8598", lineWidth: 1, lineStyle: 2 });
      }
      priceBbUpper.setData(_seriesFromIndicator(bars, r.indicators.bb.upper));
      priceBbLower.setData(_seriesFromIndicator(bars, r.indicators.bb.lower));
    }

    // RSI pane
    if (r.indicators.rsi) {
      rsiLine.setData(_seriesFromIndicator(bars, r.indicators.rsi));
    } else {
      rsiLine.setData([]);
    }

    // MACD pane
    if (r.indicators.macd) {
      macdLine.setData(_seriesFromIndicator(bars, r.indicators.macd.line));
      macdSignal.setData(_seriesFromIndicator(bars, r.indicators.macd.signal));
      macdHist.setData(
        bars.map((b, i) => {
          const h = r.indicators.macd.histogram[i];
          if (h == null) return null;
          return {
            time: _toTime(b.date),
            value: h,
            color: h >= 0 ? "#6fd07a" : "#e57373",
          };
        }).filter(Boolean)
      );
    } else {
      macdLine.setData([]); macdSignal.setData([]); macdHist.setData([]);
    }

    priceChart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();
    macdChart.timeScale().fitContent();
    $("chart-status").textContent = `${sym} · ${period} · ${interval} · ${bars.length} bars`;
  } catch (e) {
    $("chart-status").textContent = "error: " + e.message;
  }
}

// ── News ──────────────────────────────────────────────
function _fmtRelative(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const secs = Math.round((Date.now() - t) / 1000);
  if (secs < 60) return secs + "s ago";
  if (secs < 3600) return Math.round(secs / 60) + "m ago";
  if (secs < 86400) return Math.round(secs / 3600) + "h ago";
  return Math.round(secs / 86400) + "d ago";
}
async function loadNews() {
  const out = $("news-out");
  out.className = "empty"; out.textContent = "loading…";
  try {
    const r = await api("/api/news?limit=15");
    if (!r.entries || !r.entries.length) {
      out.textContent = "no entries (subscribe to feeds in miniflux at http://127.0.0.1:8080)";
      return;
    }
    out.className = "";
    const items = r.entries.map(e => {
      const safeTitle = (e.title || "(no title)").replace(/</g, "&lt;");
      const safeUrl = (e.url || "#").replace(/"/g, "&quot;");
      const safeFeed = (e.feed_title || "").replace(/</g, "&lt;");
      return `<li>
        <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" title="${safeTitle}">${safeTitle}</a>
        <span class="feed">${safeFeed}</span>
        <span class="when">${_fmtRelative(e.published_at)}</span>
      </li>`;
    }).join("");
    out.innerHTML = `<ul class="news-list">${items}</ul>`;
  } catch (e) {
    out.className = "empty";
    out.textContent = "news unavailable: " + e.message;
  }
}

// ── Chat floater ──────────────────────────────────────
function toggleChat(force) {
  const p = $("chat-panel");
  const open = force !== undefined ? force :
    (p.style.display === "none" || !p.style.display);
  p.style.display = open ? "flex" : "none";
  if (open) setTimeout(() => $("chat-input").focus(), 60);
}
function appendChat(role, content) {
  const div = document.createElement("div");
  div.className = "chat-msg chat-" + role;
  div.textContent = content;
  $("chat-messages").appendChild(div);
  $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
  return div;
}
async function sendChat() {
  const input = $("chat-input");
  const msg = input.value.trim();
  const pid = $("project-select").value;
  if (!msg) return;
  if (!pid) { appendChat("error", "select a project first"); return; }
  appendChat("user", msg);
  input.value = "";
  const statusRow = appendChat("status", "⏳ dispatching to fin-rt…");
  try {
    const url = "/api/chat?project_id=" + encodeURIComponent(pid) +
      "&message=" + encodeURIComponent(msg);
    const r = await api(url, { method: "POST" });
    statusRow.textContent = "⏳ fin-rt thinking (task " + r.task_id.slice(0, 8) + "…)";
    pollChatTask(r.task_id, statusRow);
  } catch (e) {
    statusRow.remove();
    appendChat("error", e.message);
  }
}
async function pollChatTask(taskId, statusRow) {
  const started = Date.now();
  const poll = async () => {
    try {
      const r = await api("/api/tasks/" + encodeURIComponent(taskId));
      if (r.status === "completed") {
        if (statusRow) statusRow.remove();
        const body = r.reply || (r.signal ? JSON.stringify(r.signal, null, 2) : "(empty reply)");
        appendChat("assistant", body);
        return;
      }
      if (r.status === "failed") {
        if (statusRow) statusRow.remove();
        appendChat("error", r.error || "fleet task failed");
        return;
      }
      // pending — keep polling, but abort after 120s
      if (Date.now() - started > 120000) {
        if (statusRow) statusRow.textContent = "⚠ timed out after 2min — check fleet logs";
        return;
      }
      if (statusRow) {
        const secs = Math.round((Date.now() - started) / 1000);
        statusRow.textContent = "⏳ fin-rt thinking (" + secs + "s)";
      }
      setTimeout(poll, 1500);
    } catch (e) {
      if (statusRow) statusRow.remove();
      appendChat("error", "poll: " + e.message);
    }
  };
  setTimeout(poll, 800);
}

$("quote-btn").onclick = doQuote;
$("chart-btn").onclick = loadChart;
$("analyze-btn").onclick = doAnalyze;
$("refresh-projects").onclick = refreshProjects;
$("refresh-paper").onclick = doPaperRefresh;
$("reset-paper").onclick = doReset;
$("place-order").onclick = doPlaceOrder;
$("refresh-news").onclick = loadNews;
$("chat-toggle").onclick = () => toggleChat();
$("chat-close").onclick = () => toggleChat(false);
$("chat-send").onclick = sendChat;
$("project-select").onchange = () => { refreshHistory(); refreshPaperAll(); };
$("symbol-input").addEventListener("keydown", e => {
  if (e.key === "Enter") doQuote();
});
$("order-symbol").addEventListener("keydown", e => {
  if (e.key === "Enter") doPlaceOrder();
});
$("chat-input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

refreshHealth();
refreshProjects();
loadNews();
setInterval(refreshHealth, 15000);
setInterval(loadNews, 120000);
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
    fleet_backend: Optional[FleetBackend] = None,
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

    # ── Phase 1 (2026-04-25): mount fin SQLite + scheduler + integrity ──
    # /api/db/...         → read-only views of the new SQLite store
    # /api/scheduler/...  → list jobs + force-rerun
    # /api/integrity/...  → live invariant check (UI badge: N/N pass)
    # Lazy import keeps dashboard boot cheap when these layers aren't
    # being used (e.g., legacy projects on the file-based store).
    try:
        from agent.finance.persistence.api import router as _fin_db_router
        from agent.finance.scheduler.api import router as _fin_scheduler_router
        from agent.finance.integrity.api import router as _fin_integrity_router
        from agent.finance.strategies_catalog import router as _fin_strategies_router
        from agent.finance.lattice.widget_router import router as _fin_widgets_router
        from agent.finance.raw_store.api import router as _fin_raw_store_router
        from agent.finance.compute.api import router as _fin_compute_router
        from agent.finance.regime.api import router as _fin_regime_router
        from agent.finance.stock_research import build_stock_research_router
        from agent.finance.architecture_router import build_architecture_router
        from agent.finance.anchored_research import build_anchored_research_router
        from agent.finance.market_overlay_router import build_market_overlay_router
        app.include_router(_fin_db_router)
        app.include_router(_fin_scheduler_router)
        app.include_router(_fin_integrity_router)
        app.include_router(_fin_strategies_router)
        app.include_router(_fin_widgets_router)
        app.include_router(_fin_regime_router)
        app.include_router(_fin_raw_store_router)
        app.include_router(_fin_compute_router)
        app.include_router(build_stock_research_router())
        app.include_router(build_architecture_router())
        app.include_router(build_anchored_research_router())
        app.include_router(build_market_overlay_router())
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fin platform routers not mounted: %s "
            "(dashboard remains functional without them)", exc,
        )

    def _get_hub():
        nonlocal data_hub
        if data_hub is None:
            from agent.finance.data_hub import FinanceDataHub
            data_hub = FinanceDataHub()
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

    # Optional fleet backend for async analyze. None means fleet
    # dispatch is disabled and /api/analyze?use_fleet=true returns 503.
    # Tests inject a mock; production uses the default which lazily
    # loads projects/fin-core/project.yaml on first call.
    fleet = fleet_backend if fleet_backend is not None else FleetBackend()

    @app.on_event("shutdown")
    async def _fleet_shutdown() -> None:
        await fleet.shutdown()

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

    # ── Serve React SPA (web/dist/) when available ──
    # The new frontend is a Vite-built React SPA. In dev the user
    # runs `npm run dev` on :5173 (Vite handles HMR and proxies back
    # to :8001). In prod we serve the static build from web/dist/.
    # Fallback: if no build exists, serve the legacy inline HTML so
    # the server is still functional before first `npm run build`.
    _WEB_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"

    if _WEB_DIST.exists() and (_WEB_DIST / "index.html").exists():
        from fastapi.staticfiles import StaticFiles

        # Serve Vite's hashed assets at /assets/*
        app.mount(
            "/assets",
            StaticFiles(directory=str(_WEB_DIST / "assets")),
            name="spa_assets",
        )

        @app.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            return HTMLResponse(
                content=(_WEB_DIST / "index.html").read_text(encoding="utf-8"),
                status_code=200,
            )

        # Any other static files in web/dist/ root (favicon, icons, etc.)
        # Covered manually because we don't want to shadow /api /openbb etc.
        _STATIC_ROOT_FILES = (
            "favicon.ico", "favicon.svg", "robots.txt",
            "manifest.json", "apple-touch-icon.png",
        )
        for _fname in _STATIC_ROOT_FILES:
            _path = _WEB_DIST / _fname
            if _path.exists():
                @app.get(f"/{_fname}", include_in_schema=False)
                def _serve_static(_p: Path = _path):
                    return HTMLResponse(
                        content=_p.read_bytes().decode("utf-8", errors="replace"),
                        status_code=200,
                    )

        @app.get("/legacy", response_class=HTMLResponse)
        def legacy_index() -> HTMLResponse:
            """Old inline HTML dashboard — kept as fallback during
            React migration. Access via /legacy."""
            return HTMLResponse(content=_INDEX_HTML, status_code=200)
    else:
        # No React build yet → legacy HTML at /, and /legacy aliases it.
        @app.get("/", response_class=HTMLResponse)
        def index() -> HTMLResponse:
            return HTMLResponse(content=_INDEX_HTML, status_code=200)

        @app.get("/legacy", response_class=HTMLResponse)
        def legacy_alias() -> HTMLResponse:
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
        use_fleet: bool = Query(
            False,
            description="dispatch to fleet fin-rt worker for real "
                        "LLM analysis (async, returns task_id)",
        ),
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

        # Async fleet path: dispatch to fin-rt worker, return task_id
        if use_fleet:
            task_id = await fleet.dispatch_analysis(sym, project_id)
            return {
                "project_id": project_id,
                "symbol": sym,
                "task_id": task_id,
                "status": "pending",
                "use_fleet": True,
            }

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

    @app.get("/api/tasks/{task_id}")
    def task_status(task_id: str) -> Dict[str, Any]:
        """Poll status of a fleet-dispatched analyze task."""
        return fleet.get_task_status(task_id)

    # ── Chart + technical indicators (Phase 5.7) ─────────────────

    _ALLOWED_PERIODS = {
        "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max",
    }
    _ALLOWED_INTERVALS = {
        "1m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo",
    }
    _ALLOWED_INDICATORS = {
        "sma20", "sma50", "ema20", "ema50",
        "rsi", "macd", "bb", "atr",
    }

    @app.get("/api/chart/{symbol}")
    async def chart(
        symbol: str,
        period: str = Query("3mo"),
        interval: str = Query("1d"),
        indicators: str = Query(
            "sma20,ema20,rsi,macd,bb",
            description="comma-separated subset of "
                        "sma20,sma50,ema20,ema50,rsi,macd,bb,atr",
        ),
        market: str = "us",
    ) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        if not _SYMBOL_RE.match(sym):
            raise HTTPException(400, f"invalid symbol {symbol!r}")
        if period not in _ALLOWED_PERIODS:
            raise HTTPException(
                400,
                f"invalid period {period!r}; allowed: "
                f"{sorted(_ALLOWED_PERIODS)}",
            )
        if interval not in _ALLOWED_INTERVALS:
            raise HTTPException(
                400,
                f"invalid interval {interval!r}; allowed: "
                f"{sorted(_ALLOWED_INTERVALS)}",
            )

        wanted = {
            s.strip() for s in indicators.split(",") if s.strip()
        }
        bad = wanted - _ALLOWED_INDICATORS
        if bad:
            raise HTTPException(
                400, f"unknown indicators: {sorted(bad)}"
            )

        hub = _get_hub()
        try:
            bars = await hub.get_history(sym, period=period, interval=interval)
        except Exception as exc:
            logger.warning("chart history fetch failed: %s", exc)
            raise HTTPException(502, f"upstream history failed: {exc}")
        if not bars:
            raise HTTPException(
                404, f"no historical data for {sym} ({period}/{interval})"
            )

        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]

        computed: Dict[str, Any] = {}
        if "sma20" in wanted:
            computed["sma20"] = ti.sma(closes, 20)
        if "sma50" in wanted:
            computed["sma50"] = ti.sma(closes, 50)
        if "ema20" in wanted:
            computed["ema20"] = ti.ema(closes, 20)
        if "ema50" in wanted:
            computed["ema50"] = ti.ema(closes, 50)
        if "rsi" in wanted:
            computed["rsi"] = ti.rsi(closes, 14)
        if "macd" in wanted:
            line, signal, hist = ti.macd(closes)
            computed["macd"] = {
                "line": line, "signal": signal, "histogram": hist,
            }
        if "bb" in wanted:
            upper, mid, lower = ti.bollinger_bands(closes, 20, 2.0)
            computed["bb"] = {
                "upper": upper, "middle": mid, "lower": lower,
            }
        if "atr" in wanted:
            computed["atr"] = ti.atr(highs, lows, closes, 14)

        return {
            "symbol": sym,
            "period": period,
            "interval": interval,
            "bars": bars,
            "indicators": computed,
        }

    # ── News + Chat (Phase 1 fusion MVP) ─────────────────────────
    # News proxies Miniflux; chat forwards to fleet fin-rt worker
    # and reuses the same /api/tasks/{id} polling path.
    try:
        from agent.finance.news_hub import build_news_router
        app.include_router(build_news_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("news router unavailable: %s", exc)

    # Fleet-backed /api/chat router removed 2026-05-01 — SPA only uses
    # /api/chat_stream (chat_streaming.py). OpenBB Workspace copilot
    # still goes through fleet via openbb_adapter.build_agent_router
    # below.

    try:
        from agent.finance.cn_data import build_cn_router
        app.include_router(build_cn_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("cn_data router unavailable: %s", exc)

    try:
        from agent.finance.agent_audit import build_audit_router
        app.include_router(build_audit_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("audit router unavailable: %s", exc)

    try:
        from agent.finance.chat_streaming import build_chat_stream_router
        app.include_router(build_chat_stream_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("chat_stream router unavailable: %s", exc)

    try:
        from agent.finance.chat_sessions import build_chat_sessions_router
        app.include_router(build_chat_sessions_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("chat_sessions router unavailable: %s", exc)

    try:
        from agent.finance.watchlist_web import build_watchlist_router
        app.include_router(build_watchlist_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("watchlist router unavailable: %s", exc)

    try:
        from agent.finance.sectors import build_sectors_router
        app.include_router(build_sectors_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("sectors router unavailable: %s", exc)

    try:
        from agent.finance.relative_strength import build_rs_router
        app.include_router(build_rs_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("rs router unavailable: %s", exc)

    try:
        from agent.finance.earnings import build_earnings_router
        app.include_router(build_earnings_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("earnings router unavailable: %s", exc)

    try:
        from agent.finance.funds import build_funds_router
        app.include_router(build_funds_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("funds router unavailable: %s", exc)

    try:
        from agent.finance.sentiment import build_sentiment_router
        app.include_router(build_sentiment_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("sentiment router unavailable: %s", exc)

    try:
        from agent.finance.synthesis import build_synthesis_router
        app.include_router(build_synthesis_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("synthesis router unavailable: %s", exc)

    try:
        from agent.finance.research_brief import build_research_brief_router
        app.include_router(build_research_brief_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("research_brief router unavailable: %s", exc)

    try:
        from agent.finance.insight import build_insight_router
        app.include_router(build_insight_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("insight router unavailable: %s", exc)

    try:
        from agent.finance.factors import build_factors_router
        app.include_router(build_factors_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("factors router unavailable: %s", exc)

    try:
        from agent.finance.anomalies import build_anomalies_router
        app.include_router(build_anomalies_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("anomalies router unavailable: %s", exc)

    try:
        from agent.finance.attribution import build_attribution_router
        app.include_router(build_attribution_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("attribution router unavailable: %s", exc)

    try:
        from agent.finance.correlation import build_correlation_router
        app.include_router(build_correlation_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("correlation router unavailable: %s", exc)

    try:
        from agent.finance.lattice.router import build_lattice_router
        app.include_router(build_lattice_router())
    except Exception as exc:  # pragma: no cover
        logger.warning("lattice router unavailable: %s", exc)

    # ── OpenBB Workspace custom backend (Phase 2) ────────────────
    # Same NeoMind data + fleet agent exposed via OpenBB's standard
    # widget + Copilot HTTP contracts. Lets any OpenBB-compatible UI
    # (Workspace free cloud, self-host, third-party) drive NeoMind
    # without touching internals. See
    # plans/2026-04-19_openbb_backend_integration.md.
    try:
        from agent.finance import openbb_adapter
        openbb_adapter.add_cors(app)
        app.include_router(
            openbb_adapter.build_data_router(
                get_hub=_get_hub,
                get_engine=_get_engine,
                list_recent_analyses=_list_recent_analyses,
            ),
            prefix="/openbb",
        )
        app.include_router(
            openbb_adapter.build_agent_router(fleet),
            prefix="/openbb",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("openbb adapter unavailable: %s", exc)

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


def _raise_fd_limit(target: int = 4096) -> None:
    """Bump the process's soft open-file limit. macOS defaults to 256,
    which yfinance blows through in under an hour of polling (its
    threaded batch fetcher opens many concurrent sockets and doesn't
    always release them promptly). A 4096 soft limit keeps us well
    clear without touching the kernel hard limit."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(target, hard), hard))
    except Exception as exc:
        logging.warning("could not raise fd limit: %s", exc)


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

    _raise_fd_limit()

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
