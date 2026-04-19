# NeoMind as an OpenBB Workspace Custom Backend

**Date:** 2026-04-19
**Status:** DRAFT — executing immediately after user approval
**Supersedes:** Phase 2 of `plans/2026-04-19_fin_dashboard_fusion.md` (§4.1 was the abstract version; this is the concrete execution)
**Goal:** Make NeoMind speak OpenBB's standard HTTP contracts so **any** OpenBB-compatible UI (Workspace free cloud, Workspace self-host, third-party forks, future replacements) can drive NeoMind's data + agent without lock-in.

---

## 0. Why this plan, not "build own UI"

From the 2026-04-19 evaluation:
1. "最贴近 Workspace 的开源成品" 严格不存在
2. Workspace UI itself is closed source, **but** OpenBB publishes **open standards** (widget contract MIT, agent contract MIT) that any UI can implement
3. `openbb-platform-api` + `backends-for-openbb` templates (both MIT) show FastAPI → Workspace-ready backend is ~100-200 LOC of glue

**Therefore**: rather than committing to a specific UI (Streamlit / Reflex / Next.js), commit at the **protocol layer**. NeoMind becomes OpenBB-citizen. Every compatible UI — Workspace today, Reflex-clone tomorrow — works without touching NeoMind internals.

This ends "切来切去" because the commitment is to a contract, not a UI choice.

---

## 1. Ground truth (what NeoMind already has)

| Existing endpoint | Payload shape | OpenBB widget type target |
|---|---|---|
| `GET /api/quote/{symbol}` | dict: price / change / volume / high / low / name | **metric** (4 cards) |
| `GET /api/chart/{symbol}?period=&interval=&indicators=` | bars[] + indicators{} | **chart** (line / candlestick) |
| `GET /api/news?symbols=&limit=` | entries[]: id / title / url / published_at / feed_title / snippet | **newsfeed** |
| `GET /api/history?project_id=&limit=` | items[]: signal / confidence / risk / reason | **table** |
| `GET /api/paper/account?project_id=` | dict: cash / equity / total_pnl / win_rate | **metric** |
| `GET /api/paper/positions?project_id=` | positions[] | **table** |
| `GET /api/paper/trades?project_id=&limit=` | trades[] | **table** |
| `GET /api/projects` | projects[] | **table** (utility) |
| `POST /api/chat?project_id=&message=` → task_id | task ring buffer | wrap as **Copilot agent** (SSE query) |
| `GET /api/tasks/{task_id}` | status polling | internal, used by agent wrapper |

**Mostly 1:1 after reshape**. No new data plumbing required.

---

## 2. Architecture — new adapter module

### 2.1 File layout

```
agent/finance/
  openbb_adapter.py      ← NEW, ~350 LOC
    build_data_router(data_hub, engine_factory) → APIRouter
    build_agent_router(fleet) → APIRouter
    get_widgets_json()      static dict; rendered once at startup
    get_apps_json()         static dict; layout presets
    add_cors(app)           attaches CORSMiddleware for pro.openbb.co

agent/finance/dashboard_server.py  ← MODIFY
  Mount both routers under /openbb/ prefix:
    app.include_router(openbb_adapter.build_data_router(...), prefix="/openbb")
    app.include_router(openbb_adapter.build_agent_router(fleet), prefix="/openbb")
  Call openbb_adapter.add_cors(app) for the /openbb/* origins

tests/
  test_openbb_adapter.py  ← NEW, ~200 LOC
    widgets.json schema validity
    each endpoint reshape correctness
    CORS headers present
    agent SSE stream produces expected events
```

**Net code added**: ~550 LOC + adapter config. No existing endpoint changes.

### 2.2 Endpoint surface

Data backend (all GET):

```
/openbb/widgets.json        ← catalog of all widgets
/openbb/apps.json           ← optional layout presets
/openbb/quote               ← metric   ?symbol=AAPL
/openbb/chart               ← chart    ?symbol=AAPL&period=3mo&interval=1d
/openbb/news                ← newsfeed ?symbols=AAPL,TSLA&limit=20
/openbb/history             ← table    ?project_id=fin-core&limit=50
/openbb/paper_account       ← metric   ?project_id=fin-core
/openbb/paper_positions     ← table    ?project_id=fin-core
/openbb/paper_trades        ← table    ?project_id=fin-core&limit=50
```

Agent backend (Copilot integration):

```
/openbb/agents.json         ← GET, metadata
/openbb/query               ← POST, SSE stream; body {messages:[{role,content}]}
```

### 2.3 widgets.json skeleton

```json
{
  "neomind_quote": {
    "name": "NeoMind Quote",
    "description": "Live price + change + volume from NeoMind DataHub (Finnhub / AV / yfinance ladder).",
    "category": "NeoMind",
    "subcategory": "Markets",
    "type": "metric",
    "endpoint": "quote",
    "gridData": {"w": 12, "h": 5},
    "source": "NeoMind",
    "params": [
      {"paramName": "symbol", "value": "AAPL", "label": "Symbol", "type": "text",
       "description": "US ticker (AAPL) or A-share code (600519)."}
    ]
  },
  "neomind_chart": { ... type: "chart", gridData 24×10, period/interval/indicators params ... },
  "neomind_news":  { ... type: "newsfeed", symbols+limit params ... },
  "neomind_history":         { ... type: "table", project_id param ... },
  "neomind_paper_account":   { ... type: "metric" ... },
  "neomind_paper_positions": { ... type: "table" ... },
  "neomind_paper_trades":    { ... type: "table" ... }
}
```

### 2.4 Response reshaping rules

**metric** → array of `{label, value, delta?}`:
```python
# /openbb/quote reshape
[
  {"label": "Price", "value": f"${q.price:.2f}"},
  {"label": "Change", "value": f"{q.change:+.2f}", "delta": f"{q.change_pct:+.2f}"},
  {"label": "Volume", "value": f"{q.volume:,}"},
  {"label": "High / Low", "value": f"{q.high:.2f} / {q.low:.2f}"},
]
```

**table** → array of flat dicts (keys become column headers, OpenBB auto-discovers):
```python
# /openbb/history reshape — flatten AgentAnalysis signal
[{"when": "...", "symbol": "...", "signal": "hold", "confidence": 3, ...}, ...]
```

**chart** → Plotly JSON (`{data: [...], layout: {...}}`) when `raw: true`, else Highcharts config:
```python
# /openbb/chart reshape — construct plotly line trace for close + SMA/EMA overlays
{"data": [{"x": dates, "y": closes, "type": "scatter", "name": "Close"}, ...],
 "layout": {"title": symbol, "template": "plotly_dark", ...}}
```

**newsfeed** → array of `{title, url, publishedDate, source, summary}`:
```python
# /openbb/news reshape from Miniflux entries
[{"title": e.title, "url": e.url, "publishedDate": e.published_at,
  "source": e.feed_title, "summary": e.snippet}, ...]
```

### 2.5 Agent backend (Copilot) implementation

`GET /openbb/agents.json`:
```json
{
  "neomind_fin": {
    "name": "NeoMind Fin Persona",
    "description": "DeepSeek-R1 backed fin-rt fleet worker with paper trading awareness, backed by the Investment-root data firewall.",
    "image": "https://...",  // optional
    "endpoints": {"query": "/openbb/query"},
    "features": {
      "streaming": true,
      "widget-dashboard-select": false,
      "widget-dashboard-search": false
    }
  }
}
```

`POST /openbb/query`:
- Body: `{"messages": [{"role": "human"|"ai", "content": "..."}]}`
- Extract last human message → same `build_chat_prompt()` from `chat_stream.py`
- Call `fleet.dispatch_chat()` → task_id
- Return SSE stream via `sse_starlette.EventSourceResponse`:
  - While task pending → emit `{"event": "message", "data": {"content": "⏳ thinking..."}}` every 1.5s
  - On complete → emit final content chunks
  - Emit `event: end` to close stream
- Audit log entry written same as current `/api/chat`

### 2.6 CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pro.openbb.co",     # cloud workspace
        "http://localhost:1420",     # ODP desktop (future)
        "http://127.0.0.1:1420",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Hard constraint: still bind to `127.0.0.1:8001`. Workspace browser tab connects from user's local browser to local NeoMind — no external exposure.

### 2.7 Auth

Phase 1: **none**. Loopback-only.  
Phase 2 (optional, if user later exposes via tailscale etc.): add `X-API-KEY` header validation, key stored in `.env`.

---

## 3. Dependencies to add

| Package | Purpose | Size | Required? |
|---|---|---|---|
| `sse-starlette` | SSE for agent `/query` streaming | ~15 KB | Yes |
| `openbb-ai` | Official helper for SSE message types | ~50 KB | No — we hand-roll |
| `openbb-platform-api` | Auto-gen widgets from OpenAPI | ~1 MB | No — we write widgets.json by hand for control |

Only `sse-starlette` strictly needed. Already likely in FastAPI transitive deps — verify.

---

## 4. Tests

`tests/test_openbb_adapter.py`:

1. `test_widgets_json_schema` — parse widgets.json, assert every widget has required fields (name / description / category / type / endpoint / gridData / params)
2. `test_apps_json_valid` — apps.json parseable
3. `test_quote_metric_shape` — hit `/openbb/quote?symbol=AAPL` with mock DataHub, assert returns `list[dict]` with `label` + `value` keys
4. `test_news_feed_shape` — mock Miniflux entries, assert OpenBB newsfeed shape
5. `test_history_table_shape` — fixture project with analyses, assert flat-dict rows
6. `test_chart_plotly_shape` — mock bars, assert `{data: [...], layout: {...}}` shape
7. `test_paper_account_metric` / `test_paper_positions_table` / `test_paper_trades_table`
8. `test_cors_allow_origin_pro_openbb` — OPTIONS request from `Origin: https://pro.openbb.co`, expect `Access-Control-Allow-Origin` header
9. `test_agents_json_schema` — agent metadata present
10. `test_query_sse_stream` — mock fleet, POST `/openbb/query` with human message, assert SSE events arrive in order: status → completed

All run under existing pytest config. Hard gate: `pytest tests/test_openbb_adapter.py -v` green.

---

## 5. User onboarding (what happens after code ships)

Steps for the user once adapter is deployed:

1. **Already running**: `com.neomind.fin-dashboard` launchd agent (currently at `http://127.0.0.1:8001`)
2. **One-time**: register free account at https://pro.openbb.co
3. **One-time**: Workspace → ⚙ → Data Connectors → Add Custom Backend →
   - URL: `http://127.0.0.1:8001/openbb`
   - Name: `NeoMind`
   - Click "Fetch Widgets" → should show 7 NeoMind widgets
4. **One-time**: Workspace → Copilot settings → Add Agent Backend →
   - URL: `http://127.0.0.1:8001/openbb/query`
   - Name: `NeoMind Fin`
5. **Daily**: drag widgets onto Workspace dashboards, chat via Copilot → talks to NeoMind fleet.

Existing NeoMind FastAPI HTML UI at `http://127.0.0.1:8001/` remains untouched as lightweight local fallback.

---

## 6. What this explicitly does NOT do (non-goals for this plan)

- Does NOT replace NeoMind's current HTML dashboard
- Does NOT install Reflex / Next.js / Streamlit
- Does NOT auto-start OpenBB Workspace anywhere (user keeps using cloud tier)
- Does NOT change any existing NeoMind endpoint; purely additive
- Does NOT commit to Workspace UI specifically — protocol layer is portable

---

## 7. Ship criteria (done when)

1. `pytest tests/test_openbb_adapter.py` all green
2. `curl http://127.0.0.1:8001/openbb/widgets.json` returns valid JSON with 7 widgets
3. `curl "http://127.0.0.1:8001/openbb/quote?symbol=AAPL"` returns metric array
4. `curl "http://127.0.0.1:8001/openbb/news?limit=3"` returns newsfeed array OR 503 with clear Miniflux hint (already graceful)
5. `curl -X OPTIONS -H "Origin: https://pro.openbb.co" http://127.0.0.1:8001/openbb/widgets.json` returns CORS headers
6. SSE smoke: `curl -N -X POST "http://127.0.0.1:8001/openbb/query" -H "Content-Type: application/json" -d '{"messages":[{"role":"human","content":"hi"}]}'` streams events then closes
7. User opens Workspace, adds backend, sees NeoMind widgets (this step requires user to do it)
8. Single commit

---

## 8. Rollback

All changes live under `/openbb/*` prefix. Remove by deleting two `app.include_router(...)` lines in `dashboard_server.py` + `git rm agent/finance/openbb_adapter.py`. Zero existing-code touched.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Workspace's HTTPS blocking HTTP localhost | Chrome treats 127.0.0.1 as secure since v94. Tested safe. |
| OpenBB widget contract version drift | Pin to examples from `backends-for-openbb@main` as of 2026-04-15. Template is MIT. Can regen adapter later. |
| Agent SSE shape mismatch | Follow `backends-for-openbb/widget-examples/matching-widget-mcp-tool` reference. Tests assert our shape is parseable. |
| CORS misconfigured blocks Workspace | Test OPTIONS explicitly; Origin = `https://pro.openbb.co`. |
| Existing test suite regression | Pure addition — existing 124 tests unaffected; verify green. |

---

## 10. Estimated time

- Write adapter module: ~60 min
- Tests: ~30 min
- Manual verification (curl all endpoints): ~15 min
- Documentation (README tweak pointing at /openbb/*): ~10 min
- **Total ~2 hours**

Commit: single `feat(fin): NeoMind as OpenBB Workspace custom backend`.
