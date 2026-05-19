"""Read-only httpx wrappers around the local fin dashboard.

Every tool returns either a JSON-serializable dict/list, or {"error":
"..."} when the upstream call fails. The agent loop sees that error
shape and decides how to recover (retry / apologize / skip).

URLs are verified against the live dashboard at /api/health on import
via the openapi-style probe in tests/test_dashboard_agent_tools.py.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

BASE = os.getenv("NEOMIND_FIN_DASHBOARD_URL", "http://127.0.0.1:8001")
TIMEOUT = httpx.Timeout(30.0)


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{BASE}{path}", params=params or {})
            if r.status_code == 404:
                return {"error": f"endpoint not found: {path}"}
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# ── Tools ────────────────────────────────────────────────────────────


async def get_data_freshness() -> Dict[str, Any]:
    jobs = await _get("/api/scheduler/jobs")
    if "error" in jobs:
        return jobs
    out: List[Dict[str, Any]] = []
    for j in jobs.get("jobs", []):
        out.append({
            "scanner":         j.get("name"),
            "last_run_at":     j.get("last_run_at"),
            "last_run_status": j.get("last_run_status"),
            "next_run_at":     j.get("next_run_at"),
        })
    return {"scanners": out}


async def get_portfolio_snapshot(as_of: Optional[str] = None) -> Dict[str, Any]:
    portfolio = await _get("/api/lattice/portfolio_view",
                           {"as_of": as_of} if as_of else None)
    positions = await _get("/api/positions/summary", {"benchmark": "SPY"})
    # 2026-05-16: include per-position entry / current / PnL from paper
    # account. Without this the agent has no entry_price → made up
    # totally wrong PnL numbers from market_value alone.
    paper_pos = await _get("/api/paper/positions", {"project_id": "fin-core"})
    return {
        "portfolio_graph":    portfolio,
        "positions_summary":  positions,
        "paper_positions":    paper_pos,
    }


async def get_recent_signals(since_iso: Optional[str] = None,
                             scanner: Optional[str] = None,
                             limit: int = 50) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": min(max(limit, 1), 200)}
    if since_iso: params["since"] = since_iso
    if scanner:   params["scanner"] = scanner
    return await _get("/api/regime/signals/recent", params)


async def get_chain(ticker: str, hop: int = 2) -> Dict[str, Any]:
    t = (ticker or "").strip().upper()
    if not t:
        return {"error": "ticker required"}
    return await _get(f"/api/lattice/chain/{t}",
                      {"hop": max(1, min(3, hop))})


async def get_smart_money(ticker: str) -> Dict[str, Any]:
    """Exposure across 4 buckets: 13F whales, Congress, ARK, insider Form 4.

    Each 13F event is enriched with the whale's horizon / style /
    signal_weight (per WHALES_BY_KEY) so the agent can reason about
    e.g. 'Buffett 🐢 long-term clip vs Citadel 🤖 quant noise'.
    """
    t = (ticker or "").strip().upper()
    if not t:
        return {"error": "ticker required"}
    raw = await _get(f"/api/stock/{t}/exposure")
    if "error" in raw:
        return raw
    # Enrich 13F events with whale metadata (lookup at read time —
    # works retroactively for old events emitted before metadata was
    # embedded in body_json).
    try:
        from agent.finance.regime.scanners.whale_scanner import (
            WHALES_BY_KEY, HORIZON_EMOJI,
        )
    except ImportError:
        return raw
    import json as _json
    for ev in raw.get("events", []):
        if ev.get("scanner_name") != "13f":
            continue
        body = ev.get("body") or {}
        if isinstance(body, str):
            try: body = _json.loads(body)
            except _json.JSONDecodeError: body = {}
        key = body.get("whale_key")
        if not key:
            continue
        w = WHALES_BY_KEY.get(key, {})
        ev["whale_meta"] = {
            "horizon":        w.get("horizon", "unknown"),
            "horizon_emoji":  HORIZON_EMOJI.get(w.get("horizon", "unknown"), "·"),
            "style":          w.get("style", "unknown"),
            "signal_weight":  w.get("signal_weight", 1.0),
            "derivative_note": w.get("derivative_exposure_note"),
        }
    return raw


async def get_thesis(ticker: str) -> Dict[str, Any]:
    t = (ticker or "").strip().upper()
    if not t:
        return {"error": "ticker required"}
    return await _get("/api/theses", {"ticker": t})


async def get_delta_since_review(ticker: str) -> Dict[str, Any]:
    t = (ticker or "").strip().upper()
    if not t:
        return {"error": "ticker required"}
    return await _get(f"/api/stock/{t}/delta_since_review")


async def get_outside_ring(limit: int = 10) -> Dict[str, Any]:
    return await _get("/api/watchlist/outside_ring",
                      {"limit": min(max(limit, 1), 50)})


async def get_user_anchors() -> Dict[str, Any]:
    """Composite: watchlist core + held positions + recent decision tickers."""
    tiers = await _get("/api/watchlist/tiers")
    positions = await _get("/api/positions/summary", {"benchmark": "SPY"})
    decisions = await _get("/api/decisions/recent", {"limit": 20})

    anchors: Dict[str, Dict[str, Any]] = {}
    if "error" not in tiers:
        for e in (tiers.get("tiers", {}) or {}).get("core", []) or []:
            anchors[e["ticker"]] = {"sources": ["watchlist_core"]}
    if "error" not in positions:
        for p in positions.get("by_ticker", []) or []:
            t = p["ticker"]
            anchors.setdefault(t, {"sources": []})["sources"].append("held_position")
            anchors[t]["market_value"] = p.get("market_value")
    if "error" not in decisions:
        from collections import Counter
        cnt = Counter(d["ticker"] for d in decisions.get("items", []))
        for t, n in cnt.most_common():
            anchors.setdefault(t, {"sources": []})["sources"].append(
                f"recent_decisions_x{n}")
    return {"anchors": [{"ticker": t, **meta} for t, meta in anchors.items()]}


async def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Tavily web search for things not in dashboard (news, ad-hoc lookups).

    Use sparingly — dashboard is the source of truth. Use when:
      - user asks about a ticker / event not yet in news_pull
      - clarifying broader context the dashboard doesn't have
    """
    if not query or not query.strip():
        return {"error": "query required"}
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"error": "TAVILY_API_KEY not set"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
            r = await c.post(
                "https://api.tavily.com/search",
                json={
                    "api_key":       key,
                    "query":         query.strip(),
                    "max_results":   min(max(int(max_results), 1), 10),
                    "search_depth":  "basic",
                    "include_answer": False,
                },
            )
            if r.status_code >= 400:
                return {"error": f"tavily HTTP {r.status_code}: {r.text[:200]}"}
            data = r.json()
            return {
                "query":   query.strip(),
                "results": [
                    {"title": x.get("title"), "url": x.get("url"),
                     "snippet": (x.get("content") or "")[:400]}
                    for x in (data.get("results") or [])
                ],
            }
    except httpx.HTTPError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# ── OpenAI-compatible tool schemas (for function calling) ────────────


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_data_freshness",
            "description": (
                "Get last_run_at + status for each of the 12 scanners. "
                "Call this FIRST to know how fresh the dashboard data is. "
                "If any scanner is >2h stale, say so in the answer."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_snapshot",
            "description": (
                "Watchlist tiers (core/adjacent/watching) + held positions "
                "(real $ in paper account, with PnL) + onion graph of "
                "stocks the user cares about. The main 'how's my "
                "portfolio' tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "as_of": {
                        "type": "string",
                        "description": "ISO datetime for time-travel; omit for now.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_signals",
            "description": (
                "Recent signal_events from the 12 scanners. Use to answer "
                "'what's new'. Filter by scanner name to narrow: "
                "earnings_calendar (earnings within 14d), macro_calendar "
                "(FOMC/CPI), news, watchlist (price/RSI/MA/volume), 13f "
                "(whale moves), insider_form4, house_clerk_pdf, "
                "congressional, policy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "since_iso": {"type": "string", "description": "ISO datetime lower bound."},
                    "scanner":   {"type": "string", "description": "Optional scanner name filter."},
                    "limit":     {"type": "integer", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chain",
            "description": (
                "10-K extracted supply-chain BFS for a ticker — competitor/"
                "customer/supplier relations from the company's own SEC "
                "filings. Use to answer 'how does X propagate' / 'what's "
                "affected if X drops'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "hop":    {"type": "integer", "default": 2, "description": "1-3"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_smart_money",
            "description": (
                "Smart money exposure on a ticker across 4 buckets: 13F "
                "institutions (Buffett/Dalio/Ackman/Tepper/Cathie Wood/...), "
                "Congress (Pelosi/...), ARK funds, insider Form 4. Recent "
                "moves over the past ~90d. Use when user asks 'who's "
                "buying/selling X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_thesis",
            "description": (
                "User's active investment thesis on a ticker, plus its "
                "status (active / requires_review / invalidated) and "
                "supporting facts. Use to answer 'what's my thesis on X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_delta_since_review",
            "description": (
                "What changed on a ticker since the user's last review "
                "(last_reviewed_at): new signals, thesis health changes, "
                "new anchored facts. Use when user asks 'what's new on X' "
                "or 'should I re-review X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_outside_ring",
            "description": (
                "Tickers NOT in the user's watchlist but with strong "
                "recent signal confluence (≥2 scanners in 14d). Use to "
                "answer 'anything new I should look at'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_anchors",
            "description": (
                "User's core-attention tickers: watchlist core tier + held "
                "positions + tickers frequently in recent user_decisions. "
                "Use to orient yourself if user asks open-ended questions."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


TOOL_SCHEMAS.append({
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Tavily web search for info not yet in dashboard (e.g. a news "
            "story news_pull hasn't picked up, definition of a ticker the "
            "user mentioned, broader market context). Use sparingly — "
            "dashboard is source of truth; only reach out for ad-hoc "
            "lookups. Returns title/url/snippet for each hit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query":       {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
})


TOOL_FUNCTIONS = {
    "get_data_freshness":      get_data_freshness,
    "get_portfolio_snapshot":  get_portfolio_snapshot,
    "get_recent_signals":      get_recent_signals,
    "get_chain":               get_chain,
    "get_smart_money":         get_smart_money,
    "get_thesis":              get_thesis,
    "get_delta_since_review":  get_delta_since_review,
    "get_outside_ring":        get_outside_ring,
    "get_user_anchors":        get_user_anchors,
    "search_web":              search_web,
}


# ── Privacy redaction (applied to tool results before they hit LLM) ──


def _privacy_mode() -> str:
    return (os.getenv("NEOMIND_AGENT_PRIVACY_MODE") or "balanced").lower()


def _round_dollars(v: float, mode: str) -> Any:
    if mode == "strict":
        return None
    if mode == "off":
        return v
    av = abs(v)
    if av >= 10_000:
        return f"~${round(v / 1000)}k"
    if av >= 1_000:
        return f"~${round(v / 100) / 10}k"
    if av >= 100:
        return f"~${round(v / 10) * 10}"
    return f"~${round(v)}"


def _redact(obj: Any, mode: str) -> Any:
    """Recursively redact dollar/share-count fields based on privacy mode."""
    if mode == "off":
        return obj
    SENSITIVE_DOLLAR = {
        "market_value", "cost_basis", "total_cost", "total_value",
        "unrealized_pnl", "realized_pnl", "open_price", "close_price",
        "entry_price", "current_price", "cash", "equity", "value_usd",
        "total_pnl",
    }
    SENSITIVE_QTY = {"open_quantity", "close_quantity", "quantity"}
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, (int, float)) and k in SENSITIVE_DOLLAR:
                out[k] = _round_dollars(float(v), mode)
            elif isinstance(v, (int, float)) and k in SENSITIVE_QTY and mode == "strict":
                out[k] = None
            else:
                out[k] = _redact(v, mode)
        return out
    if isinstance(obj, list):
        return [_redact(x, mode) for x in obj]
    return obj


async def dispatch(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    result = await fn(**(args or {}))
    return _redact(result, _privacy_mode())
