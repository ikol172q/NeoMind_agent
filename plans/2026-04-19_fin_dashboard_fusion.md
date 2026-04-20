# Fin Dashboard Fusion — NeoMind ⊕ OpenBB Workspace ⊕ Streamlit Lab

**Date:** 2026-04-19
**Status (updated 2026-04-19 evening):** **PARTIALLY SUPERSEDED** —
see `plans/2026-04-19_frontend_architecture_final.md` for the final
frontend decision.

- Phase 1 (chat + news MVP) — ✅ SHIPPED (commits `d04cb5e` `4a02e80`)
- Phase 2 OpenBB Workspace integration — ⛔ RETRACTED: OpenBB
  Workspace (pro.openbb.co) is a closed-source SaaS; user has
  zero-leak security stance. The backend adapter code at
  `agent/finance/openbb_adapter.py` is KEPT (useful for OpenBB CLI
  clients and any future compatible UI) but Workspace-as-UI is
  ABANDONED.
- Phase 3 commercialization — updated plan in
  `2026-04-19_frontend_architecture_final.md` §7 (Tauri + React
  route, post-MVP).
- OpenBB Platform SDK as data layer — ✅ APPROVED (source audit
  showed zero telemetry, §3.1 of the new plan).

**Author context:** Individual non-pro investor (engineer background) who wants a single-entry investment system that works immediately and supports future deep NeoMind integration + commercialization
**Relates to:** `plans/2026-04-12_fin_deepening_fusion_plan.md` (Phase 5 shipped the baseline dashboard)
**Honors:** `CLAUDE.md` conventions (.venv python, LLM router, Investment root data firewall), memory `llm_model_preference.md` (DeepSeek reasoner default)

---

## 0. Premise (why this plan exists)

User asked: "how do I get a single entry point into all my investment tools without opening 5 apps?" The existing `agent/finance/dashboard_server.py` (Phase 5 MVP, FastAPI on `127.0.0.1:8001`) already covers US stock quote / chart + 5 indicators / paper trading / fleet-dispatched analyze / project history — but perceived as "too simple" because:

- No news aggregation
- No A-share / fund / futures coverage
- No real portfolio view (paper trading only)
- No conversational entry (must drop to Telegram / CLI)
- No interop with external polished UIs (OpenBB Workspace)
- No engineer scratchpad for "write 20 lines of Python to try an idea"

Goal of this plan: **fuse NeoMind dashboard (dominant) + OpenBB Workspace (external market explorer) + Streamlit Lab (R&D scratchpad) around a single FastAPI backend that serves all three front-ends.** Phased so Phase 1 is usable in one evening; Phase 3 sets up the commercialization fork.

---

## 1. Ground truth (2026-04-19 audit)

### 1.1 Existing dashboard (`agent/finance/dashboard_server.py`, ~1550 LOC)

| Capability | Status | Endpoint |
|---|---|---|
| Project selector | ✅ | `GET /api/projects` |
| Live quote (DataHub ladder: Finnhub → AV → yfinance) | ✅ | `GET /api/quote/{symbol}` |
| K-line + 5 indicators (SMA/EMA/BB/RSI/MACD/ATR) | ✅ | `GET /api/chart/{symbol}` |
| Synchronous analyze → writes to project | ✅ | `POST /api/analyze/{symbol}` |
| Fleet async analyze via `fin-rt` worker | ✅ | `POST /api/analyze/{symbol}?use_fleet=true` + `GET /api/tasks/{id}` |
| Analysis history | ✅ | `GET /api/history` |
| Paper trading: account / positions / orders / trades / reset | ✅ | `/api/paper/*` |
| News | ❌ | — |
| A-share / 港股 / fund / futures | ❌ | — |
| Real portfolio (Wealthfolio / brokerage) | ❌ | — |
| Chat entry into fin persona from dashboard UI | ❌ | — |
| External UI consumers (OpenBB Workspace, etc.) | ❌ | — |
| Cross-source price sanity check | ❌ | — |

### 1.2 Baseline is good — don't rewrite

The dashboard already has:
- Symbol regex injection defense (`_SYMBOL_RE`)
- Project-id path validation (`_PROJECT_ID_RE`)
- localhost-only bind (DEFAULT_HOST = `127.0.0.1`)
- Paper trading `confirm=yes` two-step
- Inlined HTML (zero asset-pipeline complexity)
- Lazy fleet init (first `use_fleet=true` request triggers load)

These are all security/ops patterns we keep and extend. New endpoints will mirror these guards.

### 1.3 DeepSeek reality check (user-requested)

User asked whether DeepSeek's parent company (High-Flyer 幻方) has released a retail trading product. Findings:

- **High-Flyer** (parent) is a quant hedge fund; returned ~57% in 2025. Not retail-accessible — hedge fund model requires qualified/institutional investors.
- **DeepSeek** (AI lab) raised $300M at $10B valuation in April 2026. Stated focus: LLM research (V3.2, R2). **No official retail investment product.**
- Third-party sites branded "DeepSeek Stock" (e.g. deepseekstock.one) are NOT official DeepSeek — they wrap the DeepSeek-R1 API. **Violate user's "100% safe" requirement** (unknown ops, unvetted data handling). Do not integrate.
- **Conclusion:** DeepSeek will likely not release a consumer product (conflicts with High-Flyer's hedge fund business). The right move is to **build NeoMind Fin using DeepSeek-R1 via the LiteLLM router** (already shipped per memory `llm_model_preference.md`) — this is market gap, not market crowding.

---

## 2. Architecture decision

### 2.1 Who dominates

```
┌───────────────────────────────────────────────────────────────┐
│   Single entry: http://127.0.0.1:8001                         │
│   Header tabs:  [Dashboard]  [Lab ↗]  [Workspace ↗]           │
└────┬────────────────┬──────────────────────┬─────────────────┘
     │                │                      │
   NeoMind        Streamlit Lab        OpenBB Workspace
   FastAPI        localhost:8002       (SaaS, user's browser)
   :8001          (engineer R&D)       points to NeoMind via
   DOMINANT                            /openbb/* HTTP contract
     │                │                      │
     └────────────────┴──────────────────────┘
                      │
           Shared Python kernel
           agent/finance/* modules
           (DataHub, AkShare, fleet, paper_trading, portfolio_agg)
```

- **NeoMind Dashboard = dominant daily driver** (already shipped, local-only, deep NeoMind integration, commercializable)
- **Streamlit Lab = R&D scratchpad** (writes no prod data, imports same modules, engineer's REPL-with-charts)
- **OpenBB Workspace = external polished UI** (optional; for broader market context; Copilot backend = NeoMind fin fleet)

### 2.2 Why NOT merge UIs into one framework

- Streamlit's auto-rerun breaks SSE streaming, chart imperative state, and `lightweight-charts` v4 integration. Porting = lose features + ship bugs.
- OpenBB Workspace is SaaS — can't run offline, conflicts with "100% safe" for primary use.
- Each UI optimal for its niche. Share backend, not frontend.

### 2.3 Shared backend contract

Every new data source becomes a Python module in `agent/finance/` with a stable interface. All three UIs consume via FastAPI. **Adding a data source = one Python module + one endpoint = free for all three UIs.** This is the fusion mechanism.

---

## 3. Phase 1 — 48-hour MVP ("tonight it works")

### 3.1 Goal

Transform "8-panel US-only dashboard" → "multi-market + news + chat + portfolio" without touching existing code paths. All additions are **new files** or **additive sections**.

### 3.2 New modules

| File | LOC est. | Responsibility |
|---|---|---|
| `agent/finance/cn_data.py` | ~250 | AkShare wrapper: A-share quote, 公募基金 NAV, 期货. Local SQLite TTL cache (60s). Rate limit 1 req/sec per endpoint. Fail-closed on upstream error (no silent stale data). |
| `agent/finance/news_hub.py` | ~120 | Miniflux `/v1/entries` proxy client. Filter by symbol tag. Never call Miniflux with user-provided SQL; only parameterized URL query. |
| `agent/finance/chat_stream.py` | ~180 | `POST /api/chat` SSE endpoint. Forwards to `FleetBackend.dispatch_analysis` re-purposed as general chat (fin persona). Stream tokens back. Audit log every call to `~/Desktop/Investment/<project>/chat_log/YYYY-MM-DD.jsonl`. |
| `agent/finance/portfolio_agg.py` | ~200 | Read-only Wealthfolio SQLite at `~/Library/Application Support/com.wealthfolio.app/app.db` (if exists) + merge with `paper_trading` positions. Tag each position with `real` / `paper`. |
| `agent/finance/crosscheck.py` | ~100 | Given a symbol, pull DataHub price + AkShare price (if A-share/港股) in parallel, return `{agree: bool, diff_pct, sources}`. |

### 3.3 New endpoints (all added to `dashboard_server.py`)

```
POST   /api/chat                     SSE stream, forwards to fleet
GET    /api/news                     ?symbols=AAPL,TSLA&limit=20
GET    /api/cn/quote/{code}          000001, 600519, ...
GET    /api/cn/fund/{code}           公募基金 6-digit code
GET    /api/cn/futures/{code}        期货合约代码
GET    /api/portfolio/aggregate      ?project_id=
GET    /api/crosscheck/{symbol}      returns agree/diff/sources
```

Each endpoint: path-validation regex (mirror `_SYMBOL_RE`), fail-closed on upstream error, never cross the Investment-root data firewall.

### 3.4 UI additions (inline HTML/JS in `dashboard_server.py`)

| Section | Location | Behavior |
|---|---|---|
| Header tab bar | Top of page | `[Dashboard]` (active) `[Lab ↗]` (opens :8002 new tab) `[Workspace ↗]` (opens docs page + setup wizard) |
| News section | Top, above `project` selector | List of 20 latest entries from Miniflux, filtered by currently-selected project's symbols |
| Market selector | Quote section | Dropdown: US / CN / HK / Fund / Futures — changes which backend endpoint is called |
| Cross-check badge | Below quote | Green ✓ if sources agree within 0.5%; yellow warn otherwise |
| Portfolio section | New, above paper trading | Combined real (Wealthfolio) + paper (NeoMind) positions table, tagged |
| Chat floater | Bottom-right fixed | Round button; click → slide-in panel with SSE chat to fin persona |

### 3.5 Docker compose additions

```yaml
# docker-compose.yml additions
services:
  miniflux:
    image: miniflux/miniflux:latest
    ports: ["127.0.0.1:8080:8080"]
    environment:
      DATABASE_URL: postgres://miniflux:secret@miniflux-db/miniflux
      RUN_MIGRATIONS: "1"
      CREATE_ADMIN: "1"
      ADMIN_USERNAME: ${MINIFLUX_USER}
      ADMIN_PASSWORD: ${MINIFLUX_PASS}
    depends_on: [miniflux-db]
  miniflux-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: miniflux
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: miniflux
    volumes:
      - miniflux-data:/var/lib/postgresql/data
volumes:
  miniflux-data: {}
```

### 3.6 Tests

| Test file | Covers |
|---|---|
| `tests/test_cn_data.py` | AkShare wrapper with mocked responses; cache hit/miss; rate limit; fail-closed on upstream error |
| `tests/test_news_hub.py` | Miniflux client with mock server; symbol-tag filter; URL injection defense |
| `tests/test_chat_stream.py` | SSE stream end-to-end with mock fleet; audit log written; invalid input rejected |
| `tests/test_portfolio_agg.py` | Wealthfolio DB absent → graceful empty; DB present → positions merged; paper tag preserved |
| `tests/test_crosscheck.py` | Both sources agree → green; divergence → warn; one source down → partial result |
| `tests/test_dashboard_full.py` | Extend existing — assert new endpoints registered, new UI sections present |

All run under existing `tests/qa_archive/` pattern. Hard requirement: `pytest tests/ -k "cn_data or news_hub or chat_stream or portfolio_agg or crosscheck"` green before merge.

### 3.7 Ship criteria (Phase 1 done when)

1. User opens `http://127.0.0.1:8001`, sees news at top, chat floater bottom-right.
2. User types "最近茅台怎么样" in chat → SSE streams reply using fin persona + DeepSeek-R1.
3. User switches market selector to CN, enters `600519` → quote appears from AkShare.
4. User clicks `[Lab ↗]` in header → Phase 2 stub shows (link not broken).
5. `pytest tests/ -k fin_phase1` green (new marker for Phase 1 tests).
6. No new lint violation; existing Phase 5 endpoints unchanged.

---

## 4. Phase 2 — Week 1-2: Workspace + Lab

### 4.1 OpenBB Workspace interop

New router mount `/openbb/*` — adapter layer, no new business logic:

| Endpoint | Purpose | Spec reference |
|---|---|---|
| `GET /openbb/widgets.json` | Declare widget catalog | OpenBB widget contract |
| `GET /openbb/widgets/quote` | Reshape `/api/quote` to Workspace JSON | — |
| `GET /openbb/widgets/news` | Reshape `/api/news` | — |
| `GET /openbb/widgets/portfolio` | Reshape `/api/portfolio/aggregate` | — |
| `GET /openbb/widgets/chart` | Reshape `/api/chart` to Workspace candle format | — |
| `POST /openbb/agent/query` (SSE) | Copilot backend → fin fleet | OpenBB agent contract |

**Config flow (documented in repo):**
1. User creates free OpenBB account (one-time)
2. Workspace → "Add custom backend" → `http://localhost:8001/openbb`
3. Dashboard grid: drag any NeoMind widget; Copilot backend URL pointed at NeoMind

**Licensing guard:** this mode uses OpenBB Workspace's free tier and their HTTP contract only. We do not vendor any OpenBB AGPL code into NeoMind. If user later commercializes, this layer stays legal as long as OpenBB is treated as an external client, not an embedded library.

### 4.2 Streamlit Lab

New file `agent/finance/lab.py`. Runs standalone on port 8002.

```python
# agent/finance/lab.py — high-level shape
import streamlit as st
from agent.finance import data_hub, cn_data, technical_indicators as ti
from agent.finance import paper_trading, portfolio_agg

st.set_page_config(page_title="NeoMind Fin Lab", layout="wide")
tab1, tab2, tab3, tab4 = st.tabs([
    "Strategy backtest", "Multi-symbol compare",
    "Custom indicator", "AkShare explorer",
])
# Each tab ~50-80 lines
```

Launcher: `scripts/run_lab.sh` → `streamlit run agent/finance/lab.py --server.port 8002 --server.address 127.0.0.1`

Lab constraints (enforce in code):
- Never calls `paper_trading.place_order` (read-only)
- Never writes to `<project>/analyses/` (read-only analytics)
- Imports DataHub / AkShare via the same modules → share cache & rate limits
- Session state scoped to lab; does not leak into main dashboard

### 4.3 Phase 2 ship criteria

1. User opens OpenBB Workspace, adds NeoMind backend, sees NeoMind-sourced widgets render.
2. User clicks `[Lab ↗]` → Streamlit opens with 4 tabs functional, no prod data writes.
3. `tests/test_openbb_adapter.py` green — widget contract JSON matches OpenBB spec.
4. `tests/test_lab_readonly.py` green — lab module cannot call forbidden writers.

---

## 5. Phase 3 — Commercialization preparation (weeks 3-6, exploratory)

This phase is **optional** — only triggered if user decides to pursue the product path. Included here so Phase 1-2 decisions do not close the door.

### 5.1 Licensing clean-split

| Component | Personal edition | Commercial edition | Swap cost |
|---|---|---|---|
| Core dashboard (FastAPI + your code) | same | same | 0 |
| AkShare (MIT lib, but scraped data) | ✅ | ❌ — swap to Finnhub/Polygon via `DataHub` provider slot | < 1 day |
| Tushare free | ✅ | ❌ — swap to paid tier with commercial TOS | < 1 day |
| Miniflux | ✅ Apache 2.0 | ✅ | 0 |
| OpenBB Workspace integration | ✅ (external client) | ✅ if not vendoring AGPL code | 0 |
| Wealthfolio DB read | ✅ (individual self-use) | ⚠️ verify license; may need direct brokerage API | TBD |
| DeepSeek-R1 via LiteLLM | ✅ | ✅ (respect DeepSeek API TOS — currently permits commercial use) | 0 |

### 5.2 Product hypothesis

**"NeoMind Fin Desktop"** — local-first personal investment copilot, Tauri-wrapped, single binary, paid tier.

- **Unique position:** Wealthfolio has no agent; OpenBB is for institutions; this is the middle.
- **Pricing model (draft):** Free tier (personal, local-only, single project) / Pro $19/mo (multi-project, premium data, priority LLM quota) / Teams $99/mo (small quant teams).
- **Moat:** Deep fleet integration + multi-agent deliberation (TradingAgents-inspired 7-role) + fin-specific Iron Rules validator + Chinese-market-first but cross-market.

### 5.3 What to avoid in Phase 1-2

- Do not import `openbb` Python package into NeoMind source. Keep as external client only.
- Do not hard-code AkShare as the only CN data source — wrap behind the `DataHub` interface so a paid provider can drop in.
- Do not let Wealthfolio DB schema leak into NeoMind persistence — read-only adapter only.
- Every new feature: ask "does this feature lock me into an AGPL code path?" If yes, refactor.

---

## 6. Non-goals

- Rewriting the existing `dashboard_server.py` HTML in React/Vue. Cost ≫ value.
- Replacing FastAPI with Streamlit as the main UI. Explicitly rejected — Streamlit's auto-rerun breaks SSE and imperative chart state.
- Implementing real-brokerage live trading in Phase 1-2. Paper trading + signal-only until commercialization path is confirmed.
- Integrating any third-party "DeepSeek Stock" wrapper. Not official, violates safety requirement.
- Supporting mobile-first. Telegram bot already covers mobile read/query.

---

## 7. Security invariants (enforced every phase)

1. **localhost-only bind** for all services (8001, 8002, 8080 Miniflux). Never `0.0.0.0`.
2. **Fin tool schema minimization**: no `place_real_order` / `execute_trade` / `transfer` in any agent's toolset. Paper only.
3. **Audit log**: every chat, every analyze call → JSONL in `<project>/chat_log/` with model + tokens + tools + timestamp.
4. **Cross-source sanity**: quotes auto-crosscheck via `/api/crosscheck`; UI shows warn badge on divergence.
5. **Fail-closed data sources**: on upstream error, return HTTP 502 + clear message. Never silently fall back to stale data.
6. **AkShare rate limit**: 1 req/sec per endpoint, SQLite cache with 60s TTL. Prevents IP ban and respects upstream.
7. **Investment-root data firewall**: zero writes outside `~/Desktop/Investment/<project>/`. Git never sees user positions.

---

## 8. Open questions (need user input before Phase 1 executes)

- **Q1:** Miniflux credentials — user to set `MINIFLUX_USER` / `MINIFLUX_PASS` in `~/.zshrc` or accept defaults?
- **Q2:** Wealthfolio installed? If not, skip `portfolio_agg.py` Wealthfolio path in Phase 1 (paper-only until installed).
- **Q3:** RSS feed list — default to a curated set (Bloomberg, WSJ Markets, 华尔街见闻 English, 财新 English) or leave empty for user to subscribe manually via Miniflux UI?
- **Q4:** Chat model — use existing fin persona default (DeepSeek-R1) or allow per-message model override in the UI?

Defaults if user doesn't answer: (1) generate random creds, write to `.env` not `.zshrc`. (2) skip Wealthfolio path, leave stub. (3) leave empty. (4) use persona default, no override UI in Phase 1.

---

## 9. Execution checklist

### Phase 1 (48h MVP) — `[ ]` items

- [ ] Approve this plan (user)
- [ ] Write `agent/finance/cn_data.py` + tests
- [ ] Write `agent/finance/news_hub.py` + tests
- [ ] Write `agent/finance/chat_stream.py` + tests (SSE)
- [ ] Write `agent/finance/portfolio_agg.py` + tests
- [ ] Write `agent/finance/crosscheck.py` + tests
- [ ] Extend `agent/finance/dashboard_server.py` — 7 new endpoints, UI sections
- [ ] Docker-compose additions for Miniflux
- [ ] Update `README.md` with new service URLs
- [ ] `pytest tests/ -k fin_phase1` green
- [ ] Manual smoke: open browser, chat works, news shows, CN quote works
- [ ] Commit

### Phase 2 (Week 1-2) — `[ ]` items

- [ ] `/openbb/*` adapter routes + tests against OpenBB widget JSON schema
- [ ] `agent/finance/lab.py` + 4 tabs
- [ ] `scripts/run_lab.sh`
- [ ] Header `[Lab ↗]` / `[Workspace ↗]` links live
- [ ] Doc: `docs/openbb_workspace_setup.md` step-by-step
- [ ] Commit

### Phase 3 (deferred) — triggered only on commercialization decision

- [ ] License audit: confirm no AGPL code vendored into NeoMind source
- [ ] `DataHub` provider slot validated for Polygon/Finnhub paid swap
- [ ] Tauri packaging spike
- [ ] Pricing / positioning doc

---

## 10. Rollback plan

Phase 1 touches only **new files** + **additive sections** in `dashboard_server.py`. Rollback = `git revert <commit>`. Existing Phase 5 routes untouched — if new code breaks, dashboard's original 8 panels still work.

Phase 2 adds a new router mount `/openbb/*` and a new service file `lab.py`. Both independently togglable via env var `NEOMIND_OPENBB_ENABLED=0` / `NEOMIND_LAB_ENABLED=0`.

---

## 11. Why this plan is right (self-review)

- ✅ **Immediate usability:** Phase 1 in one evening, visibly changes UX from "simple" to "rich".
- ✅ **Single entry point:** one URL, three tabs. No 5-app juggling.
- ✅ **Deep NeoMind integration:** chat endpoint uses fin fleet; same audit log pipeline; same Investment-root firewall.
- ✅ **Commercialization path open:** licensing clean-split plan (§5.1); no AGPL vendored; data sources abstracted.
- ✅ **Safety first:** localhost-only, paper-only, fail-closed, audit log, cross-source check. Matches user's low-error-tolerance requirement.
- ✅ **No rewrite:** every existing Phase 5 endpoint preserved; new code is additive.
- ✅ **Not blocked by external product:** DeepSeek is unlikely to release a retail competitor; this is market gap.

---

## 12. Sources consulted

- OpenBB Workspace agent + widget HTTP contracts — docs.openbb.co/workspace/developers
- OpenBB AGPL licensing FAQ — docs.openbb.co/platform/faqs/license
- High-Flyer / DeepSeek corporate structure — Wikipedia, Benzinga, Hedgeweek
- AkShare commercial / rate-limit norms — zhuanlan.zhihu.com (2026 量化数据源对比)
- Ghostfolio / Wealthfolio / Maybe Finance 2026 comparison — openalternative.co
- TradingAgents 7-role architecture (reference for §5.2 fleet evolution) — TauricResearch/TradingAgents
