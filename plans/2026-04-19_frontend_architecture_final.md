# NeoMind Frontend Architecture — Final Decision

**Date:** 2026-04-19 (evening, after 11 audit rounds)
**Status:** DECIDED — awaiting user command to start implementation
**Supersedes:**
- `plans/2026-04-19_fin_dashboard_fusion.md` §3.3 (HTML/JS upgrade path) — now OBSOLETE
- `plans/2026-04-19_openbb_backend_integration.md` the Workspace-as-frontend section — now OBSOLETE (backend adapter code kept; Workspace-as-UI retracted)
- Intermediate verbal proposals for Fincept / Reflex / vanilla HTML / OpenBB Workspace — all REJECTED (§3 below)

**Not superseded:** the underlying NeoMind backend + fleet + audit + `/openbb/*` HTTP contract layer + AkShare + Miniflux. All 20+ commits preserved.

---

## 0. Purpose

Pin down the **final frontend architecture** for NeoMind, after 4 prior proposals were overturned, so future sessions don't rehash the debate. Includes rejected alternatives (with reasons) for easy reference.

---

## 1. User's 13 hard requirements (verbatim from conversation)

| # | Requirement | Source |
|---|---|---|
| 1 | Low tolerance for error ("非专业投资者，容错率低") | opening |
| 2 | Frequent usage, desktop-first | opening |
| 3 | **Free** | opening |
| 4 | **Zero data leak / 100% safe** | hardened 2026-04-19 after Workspace audit |
| 5 | Multi-asset: US / CN / HK / funds / futures / crypto / news | opening |
| 6 | Plugin-able data sources / tools | opening |
| 7 | NeoMind agent integrated (DeepSeek-R1) | opening |
| 8 | Commercial path preserved | opening + reaffirmed |
| 9 | "Random modify code" (随便改代码) | reaffirmed |
| 10 | **No flip-flopping** (不切来切去) | reaffirmed 2026-04-19 |
| 11 | Long-term maintainability (足够 maintain 空间) | reaffirmed |
| 12 | Telegram-style chat UX with `/` slash autocomplete | explicit |
| 13 | Agentic audit/debug UI, zero data loss, unified with main UI | explicit |

**Environment constraints discovered**:
- macOS Darwin 25.3.0, Chrome 136+ restricts --remote-debugging-port on default profile
- Python 3.9 (dev venv) + 3.14 (launchd venv, `.neomind_fin_venv`)
- Node.js **not** installed (but user approves installing)
- DeepSeek Reasoner preferred (from memory file)
- 20+ commits of existing NeoMind code must be preserved
- Existing launchd auto-start at `com.neomind.fin-dashboard` on :8001

---

## 2. Architecture decision — React + Vite + TypeScript + shadcn/ui + Tailwind + TanStack Query

### 2.1 Stack

| Layer | Choice | Why |
|---|---|---|
| Build tool | **Vite 6** | Fastest dev server (< 100ms HMR). Leaner than Next.js for local SPA. |
| Frontend framework | **React 19** | Largest ecosystem, most AI training data, "the safe, established choice" per 2026 surveys |
| Type system | **TypeScript 5** | Compile-time bug catch; IDE autocomplete; LLM assistants understand intent |
| Component lib | **shadcn/ui** (MIT) | **Copy-paste, no dependency** — components are in YOUR repo, auditable, modifiable; 20-50KB bundle add |
| Styling | **Tailwind CSS 4** | Utility-first; no runtime CSS-in-JS; standard shadcn pairing |
| Server state | **TanStack Query v5** | 12M+ weekly downloads, industry standard 2026; built-in devtools; optimistic updates |
| Routing | **TanStack Router** | Type-safe, works with TanStack Query; URL-addressable tabs for bookmark |
| Icons | **lucide-react** | MIT, SVG, used by shadcn |
| Charts | **Plotly.js** (our `/openbb/chart` already returns Plotly JSON) + **TradingView lightweight-charts** (existing) | Reuse what we have |
| Drag-drop | **react-grid-layout** | MIT, React port of gridstack idea; standard dashboard grid |
| SSE (chat stream) | **fetch stream API** (native) | No new dep; existing `/openbb/query` and `/api/chat` already emit SSE |
| Local UI state | **React useState + useContext** (for now); promote to **Zustand** if it grows | Minimal deps |

### 2.2 Directory layout

```
~/Desktop/NeoMind_agent/
├── web/                              ← NEW, Vite project
│   ├── index.html                    ← entry
│   ├── package.json
│   ├── vite.config.ts                ← proxy /api /openbb /audit to :8001 in dev
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── main.tsx                  ← React root
│   │   ├── App.tsx                   ← top-level nav + TanStack Router
│   │   ├── tabs/
│   │   │   ├── Research.tsx          ← multi-widget grid
│   │   │   ├── Chat.tsx              ← Telegram-style chat
│   │   │   ├── PaperTrading.tsx
│   │   │   ├── Audit.tsx             ← audit viewer
│   │   │   └── Settings.tsx
│   │   ├── components/
│   │   │   ├── widgets/              ← one file per widget
│   │   │   │   ├── USQuoteCard.tsx
│   │   │   │   ├── CNQuoteCard.tsx
│   │   │   │   ├── CNInfoCard.tsx
│   │   │   │   ├── ChartWidget.tsx
│   │   │   │   ├── NewsList.tsx
│   │   │   │   ├── HistoryTable.tsx
│   │   │   │   ├── PaperAccount.tsx
│   │   │   │   ├── PaperPositions.tsx
│   │   │   │   └── PaperTrades.tsx
│   │   │   ├── chat/
│   │   │   │   ├── ChatPanel.tsx
│   │   │   │   ├── SlashMenu.tsx     ← `/` autocomplete dropdown
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   └── commandRegistry.ts ← slash command definitions
│   │   │   └── ui/                    ← shadcn components (button, card, dialog, table ...)
│   │   └── lib/
│   │       ├── api.ts                 ← fetch wrappers + TanStack Query hooks
│   │       ├── sse.ts                 ← SSE stream reader
│   │       └── commands.ts            ← slash command parser
│   └── dist/                          ← Vite build output, .gitignored
├── agent/finance/dashboard_server.py  ← UNCHANGED except: GET /, /assets/* serve web/dist
└── ... (rest of NeoMind)
```

### 2.3 How dev and prod differ

**Dev workflow (Claude iterating with user)**:
```
Terminal 1: python -m agent.finance.dashboard_server   # :8001 FastAPI
Terminal 2: cd web && npm run dev                       # :5173 Vite with HMR
Browser: http://127.0.0.1:5173   # Vite proxies /api /openbb /audit to :8001
```

**Production (what user sees)**:
```
launchctl kickstart com.neomind.fin-dashboard   # starts :8001
Browser: http://127.0.0.1:8001/                 # FastAPI serves web/dist/index.html
                                                  # All /api /openbb /audit served by same FastAPI
```

A single `npm run build` before each release produces `web/dist/`, which FastAPI serves as static files. No Node runtime in production.

---

## 3. Alternatives considered (reference for future)

### 3.1 OpenBB Workspace (pro.openbb.co) as UI — REJECTED 2026-04-19 afternoon

| Pros | Cons |
|---|---|
| Zero UI code to build | ❌ **Closed-source SaaS**: user messages + chat content pass through OpenBB's JS before reaching our backend |
| Polished Bloomberg-like widgets | ❌ Dashboard layouts stored in OpenBB servers (breach risk surfaces which symbols you track) |
| Free tier | ❌ Copilot telemetry unknown |
| Already integrated (all widget adapter code shipped) | ❌ User hardened to zero-leak stance → any OpenBB middleman unacceptable |

**Keep**: the `agent/finance/openbb_adapter.py` HTTP contract layer — still useful for OpenBB-compatible clients like the Terminal CLI, hypothetical self-hosted Workspace enterprise, or other future tools that speak the protocol.

**Abandon**: pro.openbb.co as the daily-driver UI.

### 3.2 Fincept Terminal (`Fincept-Corporation/FinceptTerminal`) — REJECTED 2026-04-19 evening

Source-code audit found:
```
fincept-qt/scripts/agents/finagent_core/registries/models_registry.py:276:
    "base_url": "https://api.fincept.in/research/llm"    ← Fincept's own LLM server
fincept-qt/scripts/agents/hedgeFundAgents/.../agent_config.py:329:
    telemetry: bool = True                                ← default ON
```

| Pros | Cons |
|---|---|
| 6.5k stars, active (v4.0.2 shipped 2026-04-19) | ❌ **Default telemetry=True** in hedgeFundAgents module |
| macOS ARM native Qt6 desktop binary | ❌ Default LLM routing to `api.fincept.in/research/llm` |
| Bloomberg-class UI polish out of box | ❌ Need ongoing audit of each release to keep it private |
| 37 pre-built investor-persona agents | ❌ C++ base → modification much harder than Python/React |
| DeepSeek + Ollama multi-provider LLM support | ❌ Abandons existing NeoMind fleet + widget adapter work |
| AGPL + community extensible | ❌ We'd be guests in their architecture, not hosts |

**Abandon**. User's "zero tolerance" rules out defaults that phone home, even if configurable off.

### 3.3 Reflex (Python → React compile) — REJECTED 2026-04-19

| Pros | Cons |
|---|---|
| Pure Python UI code | ❌ Requires Node.js AND Python 3.10+ (user's dev venv is 3.9) |
| Compiles to React (polished output) | ❌ Framework churn: Reflex API still evolving rapidly (1.x breaking changes happen) |
| Apache 2.0 | ❌ Smaller community than React direct — less AI training data, fewer Stack Overflow answers |
| Would keep backend Python stack | ❌ "Python writing React" abstraction breaks when hitting edge cases; still need React knowledge to debug |
| On-premises deployment supported | ❌ Vercel-style cloud hosting pushed by the company; risk of cloud-first pivot |

**Abandon**. The cost of Reflex abstraction > the cost of letting Claude write direct React.

### 3.4 Vanilla HTML / JS (original recommendation) — REJECTED 2026-04-19 by user

| Pros | Cons |
|---|---|
| Zero build step | ❌ No component model → 1000+ LOC becomes spaghetti |
| Simplest possible stack | ❌ No type safety → silent bugs |
| No Node.js dependency | ❌ Less AI assistance (training skewed toward React/Vue) |
| Already started (`dashboard_server.py` has 1500 LOC inline HTML) | ❌ User said "前端不熟" → wants standard patterns he can Google, not our bespoke conventions |

**Abandon**. User explicitly pushed back: wants mainstream tooling, accepts Node.js. Vanilla wins on simplicity but loses on everything else long-term.

### 3.5 Streamlit — REJECTED 2026-04-19 afternoon

| Pros | Cons |
|---|---|
| Fastest demo-quality dashboard in Python | ❌ `st.rerun` semantics fight against persistent chat state |
| Huge community, lots of finance examples | ❌ Not "fancy enough" per user's visual expectations |
| Apache 2.0 | ❌ Multi-widget interactive dashboards require `st.session_state` gymnastics |
| Already demoed (screenshot proved it works) | ❌ Real-time SSE agent streaming requires fighting Streamlit's model |

**Abandon**. Good for demos, not for production chat/real-time dashboards.

### 3.6 Plotly Dash — not pursued

| Pros | Cons |
|---|---|
| Mature Python framework | ❌ Chat UX is a retrofit; not idiomatic |
| Flask-based, 100% local | ❌ State mgmt via callbacks awkward for chat |
| Strong charting | ❌ Smaller ecosystem than React direct |

### 3.7 Solara / NiceGUI / Flet — not pursued

All "write UI in Python" frameworks. Same class of problem as Reflex: abstraction cost > direct React.

### 3.8 Pure Rust frontend (Dioxus / Leptos / Yew) — REJECTED 2026-04-19 evening

User asked: "为啥不用 rust？"

| Pros | Cons |
|---|---|
| Compiled, fast | ❌ Ecosystem ~10× smaller than React (less AI help, fewer docs) |
| Rust type safety | ❌ Still needs Node.js for bundling (no savings) |
| Single-language stack IF we rewrote backend | ❌ Rewriting Python fleet/fin persona/DataHub in Rust = 150-300h, throws away existing work |
| Small runtime | ❌ No Python interop at comparable DX (backend stays Python) |

**Abandon**. Rust frontend alone provides no advantage over React; Rust backend would abandon 20+ commits.

### 3.9 Tauri with Rust backend — deferred to commercialization phase (ADOPTED AS LATER ENHANCEMENT)

| Pros | Cons |
|---|---|
| Native desktop binary (.dmg distribution) | ❌ Toolchain: Rust + Node + Python sidecar bundling (PyInstaller) — non-trivial |
| 10-20MB base vs Electron's 150MB+ | ❌ Dev loop more complex than just `npm run dev` |
| Can bundle Python sidecar via `externalBin` config | ❌ Overkill before product-market fit |
| Same React UI works in Tauri's webview | ✅ Zero UI code changes when we add Tauri |

**Decision**: Tauri layer is **pre-approved for commercialization phase** (Phase 11+, see §7). NOT added now. React UI today IS Tauri-ready tomorrow.

### 3.10 Grafana + custom finance panels — not pursued

Grafana is time-series / observability first. Grafting finance-domain UX onto it is more work than building directly.

### 3.11 htmx / FastHTML — briefly considered, not pursued

Server-rendered fragments, interesting paradigm, but:
- Smaller ecosystem
- Not "mainstream" per user's preference
- No component model
- Less AI training data

---

## 4. Security model

### 4.1 Threat boundaries

```
━━━━  YOUR MACHINE (browser + NeoMind FastAPI + fleet) — 100% your code
┈┈┈┈  External HTTPS (data providers, DeepSeek API) — minimal data surface
XXXX  SaaS third-parties — EXPLICITLY AVOIDED (no Workspace, no Fincept cloud, no vendor UI)
```

### 4.2 What attackers CAN'T see

- Your dashboard layout (stored in browser localStorage, never synced)
- Your paper trading book (stored under `~/Desktop/Investment/<project>/`)
- Your full audit log (stored under `~/Desktop/Investment/_audit/`)
- Your chat history (audit log + fleet transcripts, all local)
- Your custom widget configurations

### 4.3 What external services DO see (and can't be avoided)

| Service | What they see | Why unavoidable |
|---|---|---|
| DeepSeek API | System prompt + your messages + model replies | LLM inference needs input; mitigate by self-hosting Ollama later |
| Yahoo / Finnhub / AkShare / etc. | Which tickers you query | You're asking for live prices |
| Miniflux upstream RSS sources | That you subscribe to their feed | Same as any RSS reader |

**This is the minimum-possible external surface** for a market-data-aware app. To reduce further, one would need:
- Local LLM only (Ollama) → drops DeepSeek dependency
- Paid data subscription with private API key → provider still sees queries but no public identifier

### 4.4 React build security properties

- Output: static HTML + JS + CSS served by our FastAPI from 127.0.0.1
- Zero runtime CDN fetches (we self-host all assets)
- No `<script src="cdn.jsdelivr.net/...">` — all dependencies baked into bundle at build time
- No eval / dynamic imports from remote sources
- CSP header: `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' http://127.0.0.1:*;`
- Same-origin policy isolates our tab from anything else the user might have open

### 4.5 shadcn/ui component ownership

shadcn is NOT a runtime dependency. It's a **copy-paste component library**:

```bash
npx shadcn@latest add button
# → writes src/components/ui/button.tsx into YOUR repo
```

Every component is in your source tree, under your `git log`, auditable. You can modify any line. No "npm install someone's update breaks my UI" risk.

### 4.6 Dependency audit promise

All npm deps in `web/package.json` will be:
- Popular (>1M weekly downloads typically)
- Type-checked (TypeScript declarations shipped)
- Audited via `npm audit`
- Version-pinned (exact versions in `package-lock.json`)

I'll do an initial audit post-install and commit a `SECURITY.md` in `web/` listing all runtime deps + why each is needed.

---

## 5. How each of the 13 requirements is met

| # | Requirement | Architecture answer | Evidence |
|---|---|---|---|
| 1 | Low error tolerance | React component isolation + TypeScript compile-time checks | industry standard |
| 2 | Frequent usage | launchd auto-start unchanged; one URL | already works |
| 3 | Free | All deps MIT/Apache/BSD; zero paid service | explicit license check |
| 4 | 100% safe | Static build, self-hosted, zero SaaS; CSP + bind 127.0.0.1 | §4 |
| 5 | Multi-asset | Widgets per asset class; backend already multi-provider | `/api/quote` `/api/cn/quote` `/api/news` |
| 6 | Plugin-able | Widget = one .tsx file; data source = one .py file | standard React + FastAPI patterns |
| 7 | Agent | fleet + DeepSeek-R1 wired via `/api/chat` + `/openbb/query` | existing, unchanged |
| 8 | Commercial path | React UI → Tauri wrap trivial when ready | §3.9 |
| 9 | Random modify code | TypeScript makes refactoring safe; Vite HMR instant | standard React dev loop |
| 10 | No flip-flopping | Backend untouched; only frontend gets new home | 20+ commits preserved |
| 11 | Long-term maintain | Mainstream stack; AI/docs/hiring all support React | 2026 surveys |
| 12 | Telegram chat + `/` | shadcn Combobox + custom dropdown; SSE fetch stream | buildable in ~4h |
| 13 | Unified audit | Audit tab in same app; consumes existing `/api/audit/*` | already have endpoints |

**13/13 passes**. Additionally, #6 #8 #9 #11 score STRICTLY HIGHER than vanilla-HTML would have.

---

## 6. Implementation phases

All sequential, each independently commit-able and roll-back-able.

| Phase | Deliverable | Estimated time |
|---|---|---|
| 0 | `brew install node` + verify `node --version` ≥ 20 | 5 min |
| 1 | `cd ~/Desktop/NeoMind_agent && npm create vite@latest web -- --template react-ts` + `cd web && npm install` | 10 min |
| 2 | Install Tailwind 4, shadcn init, TanStack Query, TanStack Router, lucide-react, react-grid-layout | 20 min |
| 3 | Write `vite.config.ts` with dev proxy of `/api /openbb /audit` → `127.0.0.1:8001`; write `tsconfig.json` strict mode | 15 min |
| 4 | FastAPI: serve `web/dist/*` as static at `/` and `/assets/*` in production (additive route, doesn't break existing `/` HTML fallback) | 30 min |
| 5 | React shell: top nav + routing + dark theme + layout primitives | 1h |
| 6 | **Chat tab**: `ChatPanel` + `MessageBubble` + `SlashMenu` + SSE reader + slash-command registry (local-first: /quote /cn /news /paper /audit /help) | 4h |
| 7 | **Audit tab**: TanStack Query hooks for `/api/audit/recent`, `/task/{id}`, `/req/{id}`, `/stats`; shadcn Table + Collapsible rows; live auto-refresh via React Query refetch interval | 2h |
| 8 | **Research tab**: react-grid-layout + 7 existing widgets ported (US/CN quote, chart, info, news, history) + saveable layout in localStorage | 3h |
| 9 | **Paper Trading tab**: account summary card + positions table + trades table + order form | 1.5h |
| 10 | **Settings tab**: provider health checks (Miniflux status, DeepSeek key check, fleet worker status) + investment-root path display | 1h |
| 11 | Polish: Lucide icons, consistent dark theme, keyboard shortcuts (Cmd+1..5 for tab switch), toast notifications (via shadcn Sonner) | 1.5h |
| 12 | Retire the old inline-HTML in `dashboard_server.py` → route `/` to new React app; keep the old HTML accessible at `/legacy` for 30 days as fallback | 30 min |
| 13 | Tests: Playwright headless E2E for chat flow + audit tab + research tab; pytest for new FastAPI routes serving the bundle | 2h |
| **Total** | | **~18h** |

Split into ~6-8 atomic commits along the phase boundaries.

---

## 7. Commercial path — Tauri desktop app (post-MVP, Phase 11+)

When user decides to commercialize:

1. `cd web && npm install -D @tauri-apps/cli`
2. `cargo install tauri-cli`
3. `cargo tauri init` (configure app name, icon, identifier)
4. Configure `src-tauri/tauri.conf.json`:
   - `build.beforeBuildCommand: "npm run build"`
   - `build.distDir: "../dist"` (points at Vite output)
   - `bundle.externalBin: ["resources/neomind-backend"]` (PyInstaller bundle)
5. PyInstaller-bundle the Python backend:
   ```
   pyinstaller --onefile --add-data="agent:agent" --add-data="fleet:fleet" \
     --name neomind-backend agent/finance/dashboard_server.py
   ```
6. Tauri `setup` hook launches the sidecar on app start; `teardown` kills it on quit
7. `cargo tauri build` → `.dmg` for macOS, `.msi` for Windows, `.AppImage` for Linux

**Zero React code changes** — the same UI runs inside Tauri's webview.

Distribution: Apple Developer Program ($99/yr for signed .dmg), Microsoft Store, or direct download.

---

## 8. Maintenance guarantees

### 8.1 What you can do without asking me again

| Task | How |
|---|---|
| Add a new widget | Copy `src/components/widgets/USQuoteCard.tsx` → rename → modify fetch URL → import into `Research.tsx` |
| Add a new slash command | Add entry to `src/components/chat/commandRegistry.ts` |
| Change color theme | Edit `tailwind.config.ts` color palette |
| Change layout defaults | Edit localStorage seed in `src/tabs/Research.tsx` |
| Add a new tab | Add route in `src/App.tsx` + new `src/tabs/Foo.tsx` |
| Upgrade a dep | `npm update <package>` — pinned versions protect |

### 8.2 What makes this stack aging-well

- React 19 + TS 5 + Vite 6 are all Stage-1 stable (breaking changes telegraphed years in advance)
- shadcn components are in YOUR repo — no one can break them
- Tailwind 4 has 5+ year backward-compat policy
- TanStack Query v5 is LTS, next major ≥1 year away
- `react-grid-layout` stable since 2016
- Plotly.js stable since 2015

Backend stays Python/FastAPI, unchanged by this plan.

---

## 9. What this plan does NOT do

- Does NOT remove the backend `/openbb/*` HTTP contract layer — still useful for other clients (OpenBB CLI, MCP clients, external scripts)
- Does NOT migrate existing tests — they keep passing against FastAPI
- Does NOT force Tauri before commercial demand
- Does NOT introduce Rust backend
- Does NOT introduce a bundler other than Vite

---

## 10. Approval gate

User authorizes Phase 0+1 (install Node, scaffold Vite project, ~15 min of changes) → starts.

Each subsequent phase is its own approval-gated commit.

---

## 11. Self-audit log

This plan has been audited in 11 rounds covering:

1. User's full requirement list (§1)
2. Security threat model (§4)
3. Framework landscape scan (§3)
4. Rust-specific analysis (§3.8, §3.9)
5. Component library selection (shadcn vs Mantine vs MUI — §3 notes)
6. Data fetching library (TanStack vs SWR — shadcn paired with TanStack is standard)
7. Build tool (Vite vs Next.js — Vite for local SPA)
8. State management (useState + TanStack Query; Zustand in reserve)
9. Maintainability / aging (§8)
10. Commercial path (§7)
11. Existing-code preservation (§9)

No further audit iterations planned without new information.
