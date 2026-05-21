# Lattice + Portfolio Onion Integration — Design Doc v2

Status: v2 drafted 2026-05-10 by Claude Sonnet 4.6 + repo owner
Last revisit: TBD (see §10 triggers)

## Changelog

- **v1** (2026-05-10 morning): 4-pillar plan — Visualization / Algorithm Correctness /
  Information Freshness / Decision Feedback Loop. Phase order: Decision Feedback first.
- **v2** (2026-05-10 evening) — *current*. After user pushback on philosophy, restructured:
  - **Philosophy correction**: 信息质量 > 决策纪律. User is the decision-maker; dashboard is
    a *理解放大器* (understanding amplifier), not an advisor or gate-keeper. Direct quote:
    > "我必须作为真正执行人可以用最有效的方法来理解到为啥我会做这个决定，因此质量必须重要"
  - **Pillar 5 redefined** from "Decision Discipline" → "Decision Context Dimensions".
    Position-sizing / thesis / exit-rules / tax-lot / vs-benchmark data become **NODES IN
    THE CHAIN** (information surfaced when user clicks a ticker), not **GATES** that
    constrain user actions. **Zero forced UI gates**.
  - **Pillar 6 added**: "Information Dimension Coverage" — 6 information types still missing
    after Pillar 1-5 (technical chart / position state / portfolio vs benchmark / sector
    concentration / macro calendar / earnings beat-miss history).
  - **Chain enhanced**: (a) chain nodes can be 1-3 hops deep with progressive expand,
    (b) time-travel via `as_of` date picker reuses existing `analysis_runs` snapshot infra,
    (c) **PRO vs CONTRA forced display** in the chain (anti-confirmation-bias mechanism —
    every selected ticker's chain shows BOTH supporting AND contradicting evidence side by
    side, you can't *not* see the bear case).
  - **Phase order**: user said order doesn't matter as long as final result is correct.
    Plan still proposes an order based on data-dependency (viz needs Adjacent populated,
    Adjacent needs Suggestion Panel use, etc.) but flagged as flexible.
  - **§8 added** (honest limitations): what this dashboard CANNOT do. Explicit so 5 years
    from now we don't blame the tool for problems it never claimed to solve.

This v2 supersedes v1 entirely. v1's content is reconstructible from the conversation
transcript on 2026-05-10 if needed.

---

## §1. Problem statement (verbatim from user, 2026-05-10)

> "我要的是直接+全面+及时+准确的信息处理"

> "onion 模型更多的是 [关注点 + 持仓 + 计划中的持仓 + 已做的 + 可能做的 + 投资架构]；
>  而 chain 模型是信息蒸馏+因果关系+为什么+怎么来的+根据已有信息我能得到什么"

> "信息质量远远大于决策。我并不想要复杂全面的决策手段来帮我避坑，因为我的体量并没有成长到这个份上...
>  我必须作为真正执行人可以用最有效的方法来理解到为啥我会做这个决定，因此质量必须重要。"

> "结构性纪律可以做，因为你可以加到 chain 架构里作为最后得出结论时多个维度的解释，
>  而不是只是泛泛而谈。"

Distilled to 5 testable goals:

| # | Goal | "Done" looks like |
|---|---|---|
| G1 | **Onion 视图** — my universe state | At a glance: Core/Adjacent/Watching tiers + which are stale + which have fresh signals |
| G2 | **Chain 视图** — causality + decision context, on demand | Click any ticker → see (a) why on radar, (b) what it touches, (c) decision context (position/thesis/exit/tax/benchmark), (d) PRO vs CONTRA evidence side by side |
| G3 | **Algorithm 100% correct** — every shown number traceable | Every fact has provenance (raw://sha256), verbatim quote from source, confidence score; numbers without provenance get "?" badge |
| G4 | **Information timely** — no decision is made on stale data | Every node shows "as of when"; staleness alerts proactively; new signals push without manual refresh |
| G5 | **Decision feedback loop** — why-tracking | Every promotion/note records its trigger (signal_event_id / fact_id / thesis_id / "manual"); thesis tracker monitors whether the why-still-holds; user can answer "why did I add ARM 6 months ago" by querying audit trail |

The DASHBOARD's success metric: user can confidently understand the WHY behind any state on
the dashboard within 30 seconds of clicking. Not: "user makes more money than SPY" — see
§8 honest limitations.

---

## §2. Philosophy: information > discipline

This section exists because v1 got it wrong, and v2's whole structure follows from this.

**User's philosophy** (from 2026-05-10 conversation):
- Individual investor, modest capital, can be agile
- Wants to UNDERSTAND, then decide; doesn't want a system that DECIDES FOR THEM
- Discipline gates (forced thesis, mandatory rebalance, stop-loss enforcement) feel
  paternalistic and don't fit individual-investor scale
- Discipline DATA (current weight%, sector concentration, thesis health, tax-lot status)
  is highly useful — but as INFORMATION DIMENSIONS in the chain, not as ENFORCEMENT

**Implication for design**:
- ALL "discipline" data exists and is computed automatically
- ALL of it is surfaced in the chain when user clicks a ticker
- NONE of it blocks user actions
- Examples:
  - System computes "NVDA is 8% of portfolio, max 15%". Shows in chain. Doesn't block buy.
  - System tracks "thesis: AI inference scaling, 5/5 supporting facts fresh". Shows. Doesn't
    require thesis exists before promote — if no thesis, chain shows "⚠ no thesis recorded"
    but you CAN still promote without writing one.
  - System computes "exit trigger: -30% drawdown at $400 entry → fires at $280, current $352".
    Shows. Doesn't auto-sell.

**Why this matters**: a small individual investor's edge is AGILITY + FOCUSED ATTENTION,
not process discipline. Process gates would slow down agility for marginal correctness gain.
Information visibility allows focused attention without slowing down agility.

---

## §3. Mental model — onion ≠ chain (user-confirmed 2026-05-10)

| Dimension | Onion (state) | Chain (causality + context) |
|---|---|---|
| Encodes | What I track + own + plan to track. **Investment architecture** | Why something is true. **Distilled cause→effect + decision context** |
| Topology | Each node in exactly ONE ring | Each node on multiple chains, with PRO/CONTRA polarity |
| Reading order | Center-out (importance) | INCOMING (why on radar) → OUTGOING (what it touches) → CONTEXT (decision data) → PRO vs CONTRA |
| Update cadence | Slow — promotions are weeks apart | Fast — new signals every minute |
| Time dimension | Always current | Has `as_of` (default today, picker for snapshot replay) |
| Failure if shown alone | "Looks structured but no actionability" | "Hairball, no priority" |

**Resolution**: progressive disclosure. Default view = onion only. Click a node → its chain
materializes in side panel. Other nodes dim. Click empty space → back to onion.

Pattern reference: Shneiderman 1996 *Information Seeking Mantra* — "overview first, zoom and
filter, then details on demand". Mature interaction design.

---

## §4. Prior art research (2026-05-10 web search, 5 queries)

Honest verdict: NO production tool combines onion (tier) + chain (causality) + me-centric
+ LLM-extracted edges + PRO/CONTRA forced display. The components exist; the integration
is novel.

| Source | Match degree | Take-away |
|---|---|---|
| Buffett **Circle of Competence** ([Wikipedia](https://en.wikipedia.org/wiki/Circle_of_competence) / fs.blog) | Conceptually identical to onion tiers | Validates idea; static mental model — no interactive implementation |
| Bloomberg **SPLC** ([Bloomberg Pro](https://professional.bloomberg.com/solutions/corporations/supply-chain/)) | Best industry analog for chain — center company + suppliers/customers/competitors | Chain only, not concentric, not user-centric, no PRO/CONTRA |
| Bloomberg **RELS** | Corporate family tree | Single-axis hierarchy |
| **FinDKG** ([arXiv 2407.10909](https://arxiv.org/abs/2407.10909)) / **FinCaKG-Onto** ([Springer](https://link.springer.com/article/10.1007/s10489-025-06247-1)) / **FinCARE** ([arXiv 2510.20221](https://arxiv.org/html/2510.20221v1)) | LLM-extracted financial causal knowledge graphs — conceptually closest to our `stock_anchored_facts` approach | Academic prototypes, no consumer UI |
| **Radial Tree / Dendrogram** ([Vega](https://vega.github.io/vega/examples/radial-tree-layout/)) | Pure technique for hierarchical concentric viz | Building block only |
| **Cytoscape.js + fcose** ([fcose](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose), [cola.js](https://ialab.it.monash.edu/webcola/)) | Mature libs supporting concentric + force-directed + constraint-based hybrid layouts | Right tool for implementation |

PRO/CONTRA forced display has prior art in:
- Annie Duke *Thinking in Bets* — "premortem" practice
- Mauboussin "outside view" framework
- Devil's-advocate review processes (US intelligence community Red Team)
- Decision matrices in formal decision analysis (Howard, Raiffa)

But no fintech product I found surfaces PRO + CONTRA with forced visual symmetry. This is
a meaningful design contribution.

---

## §5. Six-pillar design

### Pillar 1 — Visualization (Design B with progressive disclosure + 4 enhancements)

**Default view** (onion):
- Center: ⊙ ME node showing portfolio summary (total value / 90d vs SPY / sector mix)
- Ring 1 (innermost): Core (≤10), large nodes, gold border, bold ticker
- Ring 2: Adjacent (10-50), medium nodes, emerald border, with thin spoke lines back to
  parent_ticker (always visible since this defines membership)
- Ring 3: Watching (50-200), small dim nodes
- Ring 4 (outer): Outside-ring candidates, violet
- Each node visual encoding:
  - Color: tier
  - Size: `n_facts` (proxy for research depth)
  - Border thickness: importance (1 normal / 2 priority)
  - **Pulse**: fresh signal_event in last 24h
  - **Stale dot (amber)**: `days_since_review` > tier threshold (Core 14d / Adj 30d / Watch 90d)
  - **Conflict ring (red)**: any unresolved `signal_disagreement` for this ticker

**On click ticker — chain materializes in side panel** with 4 sections:

```
═══════ NVDA ═══════ [as_of: TODAY ▾]

╔══════ INCOMING (why on radar) ══════╗
├─ promoted to Core 2026-04-01 by user
│  thesis: "AI inference scaling"
│  trigger: news article (link)
├─ today's L3 call mentions NVDA (link)
└─ recent signals (last 7d):
   ├─ news: earnings beat Q4 [link]
   ├─ insider: 3 buys @ $480-500 [link]
   └─ analyst: BAC upgrade $550 [link]

╔══════ OUTGOING (what it touches) ═══╗
├─ in theme: "AI capex" "semiconductor cycle"
├─ supplier of: AAPL? MSFT? (parsed from 10-K)
├─ correlated with: AMD (0.82), TSM (0.88)
└─ macro factors affecting: USD/CNY, EU AI act

╔══════ DECISION CONTEXT (Pillar 5) ═══╗
├─ portfolio weight: 8% (your max: 15%)
├─ sector concentration: tech 67% (warn: 50%)
├─ thesis health: 🟢 5/5 supporting facts fresh
├─ exit triggers status:
│  ├─ ☐ -30% drawdown (current: -12%)
│  ├─ ☐ 2 consecutive earnings miss (last: beat)
│  └─ ☐ China export ban (current: tightened but OK)
├─ tax lot: 100sh @ $400, +25%, ST (60d to LT)
└─ vs SPY 90d: NVDA +18% / SPY +6% / alpha +12%

╔══════ EVIDENCE: PRO vs CONTRA ═══════╗
✅ Pro thesis (8):              ❌ Contra thesis (3):
├─ Q4 earnings beat 15%        ├─ valuation 91x PE (ATH)
├─ AI capex CY26 +30% YoY      ├─ AMD MI300X taking share
├─ NVL72 contracts secured     └─ 中美关税升级
├─ Hyperscaler CY26 capex 1.2T
├─ TSMC CoWoS expansion
├─ Margins 75% +5pp YoY
├─ 13F: smart money +5%
└─ Theme regime supportive

╔══════ Provenance ══════════════════════╗
[All quotes verbatim, click to view source]
```

**Chain enhancement #1 — Multi-hop expand**:
- 1st hop nodes shown in full (e.g. NVDA's TSMC supplier shown)
- 2nd hop nodes shown as gray placeholder + "click to expand" (e.g. TSMC's risks)
- Max 3 hops total to prevent infinite recursion / cognitive overload
- Visual: hop 1 = solid, hop 2 = dashed, hop 3 = dotted

**Chain enhancement #2 — Time travel**:
- Date picker at top: TODAY | YESTERDAY | 7d ago | 30d ago | custom date
- Reuses existing `analysis_runs` snapshot infra (already storing every job's output)
- "What did the chain look like when I made that promote decision in April?" → answerable

**Chain enhancement #3 — PRO vs CONTRA forced display** (anti-confirmation-bias):
- ALWAYS render two columns: ✅ Pro thesis evidence | ❌ Contra thesis evidence
- Even if Contra column has 0 items: show it explicitly empty with "(no contra evidence
  recorded — actively look for some?)" prompt — visual void IS the message
- Source of contra evidence:
  - signal_events with severity='high' but signal_type contradicts thesis direction
  - signal_disagreements where this ticker is involved
  - User-recorded "bear case bullets" (in `investment_theses.body_md` should explicitly
    have a `## Bear case` section)
  - LLM extraction with `polarity = 'contra'` flag (extend stock_anchored_facts schema)
- Color contrast strong (green/red), so the eye can't skip the contra side

**Chain enhancement #4 — Conflict highlighting**:
- If signal_disagreements has unresolved entries for this ticker → big red banner at top
  of chain panel: "⚠ 2 sources disagree on this ticker — review before action"
- Each disagreement shows the two sources side by side

**Tech stack**: cytoscape.js + cytoscape-fcose + cytoscape-popper. Side panel is regular
React component (no graph lib needed there).

**Mobile**: list view (current Watchlist behavior). Onion graph not rendered below 768px.
Side-panel chain is just a vertical scroll of the same 4 sections.

---

### Pillar 2 — Algorithm correctness (provenance + confidence + conflict)

Goal: every number rendered is either traceable or marked unknown. No silent corruption.

| Layer | Already in place | What v2 adds |
|---|---|---|
| Fact extraction (10-K) | Verbatim quote substring match (anti-hallucination skill enforces) | `confidence` column (LLM self-rated or substring-match-strength); `polarity` column (pro/contra/neutral) |
| URL claims | `tools/verify_seed_urls.py` HEAD-checks seed URLs | Same check on runtime-extracted URLs (signal_event source_url) on weekly schedule |
| LLM model drift | `stock_anchored_facts.extractor_model` records model | When model bumps, mark old facts as `requires_reextract`; surface in UI |
| Strategy match | `decision_traces.formula` + `breakdown_json` records each component | Surface in chain when hovering strategy_match edge |
| Cross-source agreement | `signal_confluences` detects ≥2 source agreement | NEW: `signal_disagreements` for contradictions — equally important |
| Numeric claim provenance | Anti-hallucination rule enforced at PR review | Runtime integrity check `attribution.py:check_no_uncited_numerics` scans rendered API payloads |
| Stale facts | None | `is_stale` derived view: filing_date > 18mo old → warn |
| User correction | None | UI "👎 mark wrong" button on facts → record in `fact_corrections` table; flagged facts excluded from chain by default |

Specific schema: see §6.

---

### Pillar 3 — Information freshness

Goal: user never makes a decision on data older than the latency budget for that signal type.

**Latency budget per signal type**:

| Signal type | Acceptable latency | Current scanner | Gap action |
|---|---|---|---|
| Breaking news | < 30 min | `news` (every 20min) | ✓ within budget |
| Insider Form 4 | < 24h | `insider_form4` (hourly) | ✓ |
| Congressional STOCK Act | < 48h | `stock_act` (hourly) | ✓ |
| 13F whale moves | best effort (45-day SEC delay) | `whale_daily` | ✓ as good as possible |
| **Earnings calendar / surprises** | < 1h | partial via news | **NEW**: `earnings_calendar` scanner |
| **Analyst rating changes** | < 24h | partial via news | **NEW**: `analyst_ratings` scanner (Finnhub free tier or similar) |
| **SEC 8-K material events** | < 4h | partial via news | **NEW**: `sec_8k` scanner (RSS from SEC EDGAR filtered by tracked CIKs) |
| **Macro calendar (FOMC/CPI/NFP)** | < 30min | partial via `policy` | **NEW**: `macro_calendar` scanner (Trading Economics RSS) |
| Options flow / unusual options | < 24h | none | **DEFERRED**: needs paid data; retail latency disadvantage means low ROI |
| Short interest | < 1 week | none | **DEFERRED**: low actionable value for retail |
| ETF flows / sector rotation | < 24h | none | **DEFERRED** |

**UI requirements**:
- Every node shows "last fresh signal age" (color: green <7d, amber 7-30d, red >30d)
- New `/api/freshness/scanner_health` endpoint: returns last-success time per scanner;
  if any > 2× expected interval, dashboard header shows alert badge
- Push notifications via existing `NeoMindLiveStream` for severity=high signals on Core+
  Adjacent tickers
- Macro calendar widget on dashboard top: next 7d events highlighted

---

### Pillar 4 — Decision feedback loop

Goal: capture WHY behind every user action; auto-detect when the why no longer holds.

| Mechanism | Schema | UI |
|---|---|---|
| Note ↔ trigger linkage | `stock_notes.trigger_signal_id` (FK), `trigger_fact_id` (FK), `trigger_thesis_id` (FK) | When user adds note in drawer, dropdown of recent triggers (last 30d signals + active theses) |
| Watchlist action audit | `watchlist_audit (audit_id, ticker, action, from_tier, to_tier, trigger_kind, trigger_ref_id, ts, note)` | When user promotes/demotes, modal asks "trigger?" — fact / signal / thesis / manual |
| Investment thesis | `investment_theses (thesis_id, ticker, created_at, body_md, supporting_fact_ids, supporting_signal_types, status, invalidated_at, invalidated_reason)`. Body MD MUST have sections: `## Bull case`, `## Bear case`, `## Exit triggers`, `## Horizon` | "Add thesis" form with template; OPTIONAL on promote (not gate) |
| Thesis health auto-check | Daily job: for each active thesis, check supporting_fact_ids still exist + not stale, and supporting_signal_types had signals in last 30d. If not, mark `requires_review` | Watchlist top: "Thesis review needed: NVDA (3 supporting signals went silent)" |

**Critical**: thesis is OPTIONAL. User can promote without thesis (chain shows "⚠ no thesis"
but allows action). Per Pillar 2 philosophy: information, not gate.

---

### Pillar 5 — Decision Context Dimensions (renamed from "Decision Discipline" in v1)

Goal: surface 7 decision-relevant data dimensions IN THE CHAIN when user clicks a ticker.
NOT standalone widgets. NOT gates.

Each dimension is computed automatically and rendered as a node in the chain panel:

| Dimension | Source | Compute |
|---|---|---|
| Portfolio weight % | `tax_lots` summed by ticker, divided by portfolio value | Real-time on chain open |
| User max-weight preference | New `user_preferences.max_position_pct` (default 15) | Read |
| Sector concentration | tax_lots × yfinance.sector → grouped sums | Real-time |
| User sector-concentration preference | New `user_preferences.max_sector_pct` (default 50) | Read |
| Thesis health | active `investment_theses` for this ticker → check supporting evidence freshness | Daily job (Pillar 4) |
| Exit triggers status | parsed from `investment_theses.body_md` `## Exit triggers` section → check current state against trigger condition | Real-time |
| Tax-lot details | `tax_lots` for this ticker → cost basis / age / ST vs LT / unrealized P&L | Real-time |
| vs Benchmark | (current ticker price / 90d-ago price) vs (SPY price / 90d-ago) | Daily |

**Display priority**: position weight → thesis health → exit triggers → tax → vs benchmark.
This ordering puts the most decision-relevant first.

**No alerts unless user requests**: e.g. system computes "you exceed sector cap" and shows
in chain when relevant ticker is clicked. Does NOT push alert. Does NOT block buy.

---

### Pillar 6 (NEW) — Information Dimension Coverage

Goal: close the 6 information gaps identified during v2 review.

| Dimension | Current state | Source | Phase |
|---|---|---|---|
| Technical chart (price + volume + RSI + MA) | None in dashboard | yfinance daily + ta-lib | Phase 5 |
| Position state (cost basis, P&L, weight) | DB has tax_lots; not surfaced | Already collected | Phase 1 (easy) |
| Portfolio vs benchmark | None | Calc from positions vs SPY | Phase 1 (easy) |
| Sector concentration metric | None | Calc from positions + yfinance.sector | Phase 1 (easy) |
| Macro calendar | partial via policy | Trading Economics RSS (Pillar 3 also covers) | Phase 3 |
| Historical earnings beat/miss | yfinance has `earnings_history` | Just surface | Phase 4 |
| Analyst ratings & price targets | None | Finnhub free tier | Phase 3 |
| 13F holder concentration trend | partial in Smart Money tab | Already collected, surface trend | Phase 5 |

The first 3 are surface-existing-data work — fast wins, ship in Phase 1.

---

## §6. Data model changes (consolidated)

```sql
-- Pillar 4 — Decision feedback
ALTER TABLE stock_notes ADD COLUMN trigger_signal_id TEXT;
ALTER TABLE stock_notes ADD COLUMN trigger_fact_id INTEGER;
ALTER TABLE stock_notes ADD COLUMN trigger_thesis_id TEXT;

CREATE TABLE investment_theses (
    thesis_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body_md TEXT NOT NULL,        -- MUST contain ## Bull case, ## Bear case, ## Exit triggers, ## Horizon sections
    supporting_fact_ids TEXT,     -- JSON array of stock_anchored_facts.id
    supporting_signal_types TEXT, -- JSON array of signal_type strings to monitor
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','invalidated','realized','requires_review')),
    invalidated_at TEXT,
    invalidated_reason TEXT,
    last_health_check_at TEXT
);
CREATE INDEX idx_th_ticker ON investment_theses(ticker, status);

CREATE TABLE watchlist_audit (
    audit_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('promote','demote','drop','review','note','thesis_create','thesis_invalidate')),
    from_tier TEXT,
    to_tier TEXT,
    trigger_kind TEXT,           -- 'fact' | 'signal' | 'thesis' | 'manual'
    trigger_ref_id TEXT,
    ts TEXT NOT NULL,
    note TEXT
);
CREATE INDEX idx_wa_ticker ON watchlist_audit(ticker, ts DESC);

-- Pillar 2 — Algorithm correctness
ALTER TABLE stock_anchored_facts ADD COLUMN confidence REAL;
ALTER TABLE stock_anchored_facts ADD COLUMN polarity TEXT
    CHECK (polarity IN ('pro','contra','neutral'));
ALTER TABLE stock_anchored_facts ADD COLUMN requires_reextract INTEGER NOT NULL DEFAULT 0;

CREATE TABLE signal_disagreements (
    disagreement_id TEXT PRIMARY KEY,
    ticker TEXT,
    theme TEXT,
    headline TEXT NOT NULL,
    sources_json TEXT NOT NULL,  -- [{scanner, signal_type, position}, ...]
    detected_at TEXT NOT NULL,
    resolved_at TEXT,            -- nullable; set when user marks resolved or new evidence resolves
    resolution_note TEXT
);

CREATE TABLE fact_corrections (
    correction_id TEXT PRIMARY KEY,
    fact_id INTEGER NOT NULL,
    user_action TEXT NOT NULL CHECK (user_action IN ('mark_wrong','suggest_polarity','suggest_value')),
    user_note TEXT,
    ts TEXT NOT NULL
);

-- Pillar 5 — Decision Context Dimensions
CREATE TABLE user_preferences (
    pref_key TEXT PRIMARY KEY,
    pref_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- Seeded with: max_position_pct=15, max_sector_pct=50, default_review_window_core=14, etc.

-- Pillar 6 — Information Dimension Coverage (mostly leverages existing tables)
-- positions surfaced via tax_lots (existing)
-- benchmark via market_data_daily (existing) — query SPY for comparison
-- earnings_history: yfinance has it; cache in new table:
CREATE TABLE earnings_history (
    ticker TEXT NOT NULL,
    earnings_date TEXT NOT NULL,
    eps_est REAL,
    eps_actual REAL,
    surprise_pct REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, earnings_date)
);
```

All migrations idempotent via `_ensure_column` pattern (see `agent/finance/persistence/db.py`).

---

## §7. Implementation phases

User said phase order doesn't matter as long as final result is correct. Plan still proposes
an order based on data-dependency. Each phase is independently shippable + testable.

### Phase 1 — Foundation: easy data surfacing + decision feedback schema (~12h)

**Why first**: smallest unit, highest immediate visibility gain, no UI dependencies.

- Schema migrations (all of §6)
- UI: surface position state in StockResearchDrawer (cost basis / weight % / unrealized P&L from existing tax_lots)
- UI: portfolio summary widget on dashboard top (total value / 30/90/365 vs SPY / sector mix bar)
- UI: drawer note adds optional trigger_signal_id dropdown
- API: `POST /api/watchlist/promote` records to `watchlist_audit`
- API: `POST /api/theses` CRUD for investment_theses
- Daily job: thesis health check (mark requires_review when supporting evidence stale)

**Done**: user can answer "why did I promote ARM?" by querying watchlist_audit; can see
NVDA portfolio weight in chain; thesis health auto-monitored.

### Phase 2 — Pillar 2 algorithm correctness (~10h)

- `confidence` + `polarity` columns + extractor self-report
- `requires_reextract` flag + UI surface
- `is_stale` derived flag (filing_date > 18mo)
- `signal_disagreements` table + detector
- `fact_corrections` table + UI 👎 button
- `attribution.py:check_no_uncited_numerics` integrity check
- UI: render confidence as opacity, stale facts get warning icon, conflicts get red banner

**Done**: every dashboard number is provenance-traceable; user-flagged wrong facts excluded.

### Phase 3 — Pillar 3 freshness scanners + Pillar 6 info dimensions (~20h)

Adds 4 missing high-impact scanners:
- `scheduler/jobs/earnings_calendar.py` — daily yfinance fetch, emit on earnings within 14d
- `scheduler/jobs/analyst_ratings.py` — Finnhub free tier; emit on Core+Adjacent tickers
- `scheduler/jobs/sec_8k.py` — RSS from SEC EDGAR for material events, filtered by tracked CIKs
- `scheduler/jobs/macro_calendar.py` — Trading Economics RSS

Plus:
- `/api/freshness/scanner_health` endpoint
- Earnings history cache + UI on stock drawer (beat/miss bar chart)
- Analyst ratings panel in stock drawer

**Done**: NVDA earnings on T → signal by T+1h; AAPL analyst downgrade visible within 24h;
macro calendar widget on dashboard top.

### Phase 4 — Pillar 5 Decision Context Dimensions surfacing (~10h)

- Sector concentration computation (positions × yfinance.sector)
- vs Benchmark widget computation
- Exit-triggers parser (extract `## Exit triggers` from thesis body_md, evaluate state)
- Drawer chain panel: render all 7 dimensions

**Done**: clicking NVDA shows full chain INCLUDING Decision Context section.

### Phase 5 — Pillar 1 Visualization (THE onion + chain viz) — defer ≥4 weeks (~30h)

**Defer trigger**: only build when Adjacent ring has ≥15 populated tickers AND Phase 1-4
have shipped + been used for 2+ weeks. Otherwise viz renders empty space + low-fidelity
data.

- Add cytoscape.js + cytoscape-fcose + cytoscape-popper dependencies (~80KB gzipped)
- New backend endpoint `/api/lattice/portfolio_view` returning unified graph payload
- New frontend component `<PortfolioOnionView>`:
  - 4 concentric rings (Core/Adjacent/Watching/Outside)
  - Visual encoding per node (color/size/border/pulse/stale dot/conflict ring)
  - Side panel with 4 sections (INCOMING / OUTGOING / DECISION CONTEXT / PRO vs CONTRA)
  - Multi-hop expand (1-3 hops)
  - Time-travel `as_of` picker
  - Click empty space → reset to onion default
- Replace current Watchlist grid with toggle: [List view | Onion view]

**Done**: full onion+chain workflow as designed in §5 Pillar 1.

### Phase 6 — Lattice integration (after Phase 5 settles)

Once onion view is in production: fold the existing 5-layer Lattice into it. L3 calls
become arrows entering the onion from the top; L2 themes become clickable badges that
highlight all tickers they affect. Standalone Lattice column view becomes a secondary
"audit drill-down" view, not the primary surface.

---

## §8. Honest limitations — what this dashboard CANNOT do

This section exists so 5 years from now we don't blame the tool for problems it never
claimed to solve.

**The dashboard cannot**:

1. **Predict the future**. Past evidence — no matter how complete and verified — does not
   reliably predict future returns. NVDA chain all green ≠ NVDA up next quarter.

2. **Make you a better decision-maker**. The dashboard surfaces information; the decision
   is yours. If you have judgment biases, comprehensive information may amplify rather
   than reduce them. The PRO/CONTRA forced display is a *partial* counter-bias mechanism,
   not a cure.

3. **Beat the market**. Even with perfect information, retail investors with concentrated
   stock picks underperform SPY ~85-95% of the time over 20+ years (SPIVA). Dashboard
   gives you *understanding alpha*, which is valuable in itself, but not necessarily
   *return alpha*.

4. **Solve confirmation bias completely**. PRO/CONTRA forced display is necessary but not
   sufficient. Knowing the bear case ≠ acting on it. The system can show contradicting
   evidence; it cannot make you reconsider.

5. **Substitute for original thinking**. LLM-extracted facts capture what's IN the source
   text. They do not capture what's *missing* from the source text, what management chose
   not to disclose, or what only first-hand industry knowledge would reveal.

6. **Replace position sizing judgment**. Pillar 5 surfaces "you're at 8% NVDA, max 15%"
   but does not tell you what max should be. The 15% is your guess at your own risk
   tolerance. Wrong guess → wrong outcome regardless of the dashboard.

7. **Catch black swans**. By definition, signals you didn't subscribe to scanners for go
   undetected. Outside Ring partially counters but is itself bounded by what scanners exist.

8. **Replace tax/legal advice**. Tax-lot harvest hints are calculated; actual tax decisions
   need a CPA. Wash sale detection is best-effort.

What the dashboard *can* do, that justifies it:

✅ Make every visible piece of information clickable-to-source
✅ Make causal chains explicit so you don't reason in your head only
✅ Force the bear case in front of your eyes when reviewing the bull case
✅ Track what you used to believe vs. what's true now
✅ Surface freshness staleness so you don't act on rotten data
✅ Audit your own past decisions (why did you promote X 6 months ago)

---

## §9. Failure modes + recovery

| Failure | Manifests as | Detection | Recovery |
|---|---|---|---|
| LLM extracts wrong fact (NVDA "supplier" actually customer) | Wrong relationship type in chain | User flags via 👎 button | Excluded from chain; trigger re-extract |
| 10-K stale (filed >18mo) | Adjacent ring populated from outdated relations | `is_stale` flag (Phase 2) | UI shows stale badge; suggests re-extract |
| Scanner silently dies (cron OK, 0 events) | Freshness goes red without obvious cause | `/api/freshness/scanner_health` (Phase 3) | Dashboard alert; manual restart |
| Thesis-tracker false negative (says OK when broken) | User holds position whose thesis broke | Cross-validation: red confluence on a thesis-supported ticker auto-demotes thesis to "review" | Manual review |
| Onion becomes hairball (Adjacent > 50) | Visualization unusable | UI counts; warns at 40 | Force user to demote some before adding |
| Cytoscape mobile rendering broken | Phone users see garbage | Resize listener + viewport check | Auto-fall back to list view (don't render below 768px) |
| User ignores PRO/CONTRA contra column | Contra column sits unread, confirmation bias unchecked | Cannot detect from dashboard alone | Quarterly journal prompt "did you re-examine bear case for X?" — soft, not enforced |
| Migration breaks existing watchlist | 9 cores disappear | Pre-migration backup + post-migration row-count check | Rollback script |

---

## §10. Triggers to revisit this plan

Re-read this doc when ANY of these happen:

- Adjacent ring grows past 30 (active promote flow → may need ranking within tier)
- A scanner produces > 50 events/week (might dominate chain → need filter)
- A scanner repeatedly contradicts another (signal_disagreements catches pattern → maybe drop noisier scanner)
- A thesis is invalidated and user disagrees with auto-detection (algorithm needs tuning)
- LLM model upgrades (e.g. DeepSeek v5 or new model) — re-run extracts, compare confidence
- User starts paper-trading or live-trading actively (Pillar 5 dimensions become more critical)
- 6 months pass without revisiting (default freshness)
- User notices PRO/CONTRA column is consistently empty for some tickers (LLM not finding contra; algorithm needs adjusting OR genuinely no contra exists)

Every 4 weeks: read §7 phase status, check whether "Done = success criterion" is being
EXERCISED by the user (not just passing tests). If shipped but not used, that's a UX
problem, not a "build more" problem.

---

## §11. Open questions to resolve before each phase begins

### Before Phase 1 (Foundation)
- [ ] Position state: pull from `tax_lots` only, or also from a future "manual position entry" UI? (Recommend: tax_lots only initially; manual entry later if tax_lots doesn't capture all positions)
- [ ] Portfolio benchmark: SPY vs VOO vs QQQ vs custom user choice? (Recommend: SPY default, settable in user_preferences)
- [ ] thesis body_md template — markdown skeleton with `## Bull case` / `## Bear case` / `## Exit triggers` / `## Horizon` sections — single template or multiple by horizon?

### Before Phase 2 (Algorithm correctness)
- [ ] Does deepseek-v4-flash support self-reported confidence scores natively? If not, use substring-match-strength as proxy
- [ ] Disagreement detection: simple severity-vs-severity contradiction first; refine with LLM only if needed
- [ ] `polarity` for facts: extracted by LLM at extraction time (re-run extract), or by separate post-processing pass? (Recommend: re-run with extended prompt — single source of truth)

### Before Phase 3 (Freshness)
- [ ] Earnings: yfinance free, rate-limited; fallback to Finnhub free tier if hit limits
- [ ] Analyst ratings: Finnhub free tier covers most. Backup: scrape Benzinga (gray-area)
- [ ] SEC 8-K: filter to Core+Adjacent CIKs (not Watching, too noisy)
- [ ] Macro calendar: Trading Economics RSS is reliable; FRED is alternative

### Before Phase 4 (Decision Context surfacing)
- [ ] Exit triggers parser: regex on markdown sections, or LLM-extract structured triggers? (Recommend: regex on standard checkboxes `- [ ]` first; LLM later if needed)
- [ ] vs Benchmark periods: 30/90/365 default; user-configurable?

### Before Phase 5 (Visualization)
- [ ] Cytoscape vs d3-force vs sigma.js — final lib choice (Recommend cytoscape + fcose; reasons in §4)
- [ ] Multi-parent Adjacent (a ticker that's adjacent to multiple Cores): allow? Render thinner spokes to all parents? (Recommend: allow, render all)
- [ ] Onion view default vs current List view default in Strategies tab? (Recommend: List remains default; Onion is opt-in until proven)
- [ ] Mobile fallback: list view exact layout?

### Before Phase 6 (Lattice integration)
- [ ] How to render L3 calls flowing into the onion: arrows from top? floating cards above? (Decide when arrived)

---

## §12. Decision rationale (why these choices)

**Why Design B (me-centric onion + chain on demand) over A (lattice-as-radial) or C (separate views with shared selection)**:

- **Design A** rejected: ignores user_watchlist entirely. The onion view must reflect [关注点 + 持仓 + 投资架构] — none of which are in the strategy lattice.
- **Design C** rejected: user said "零零散散的不好集中看" — two separate views IS the problem, not the solution. Even with shared selection, requires switching mental models.
- **Design B** chosen because:
  1. Single workspace satisfies "集中" requirement
  2. Progressive disclosure controls hairball risk (Shneiderman's "details on demand")
  3. Reuses ALL existing data: user_watchlist (rings), stock_anchored_facts (edges), signal_events (animations), decision_traces (provenance)
  4. Tooling (cytoscape.js + fcose) is mature
  5. Buffett's circle of competence validates conceptual model

**Why 6 pillars (information-first) over 5 pillars (with discipline gate)**:

User correction (2026-05-10): individual investor + small capital + agile → wants information
amplifier, not advisor with gates. Discipline data still computed and displayed (Pillar 5),
but as INFORMATION not as ENFORCEMENT.

**Why PRO/CONTRA forced display**:

Confirmation bias is the most-cited single behavioral failure of retail investors.
PRO/CONTRA visual symmetry is the cheapest mechanism to counter it: forces the eye to see
contra evidence even if user doesn't want to. Doesn't fully solve bias (user can still
ignore the contra column) but raises the cost of ignoring from "naturally invisible" to
"actively avoided".

**Why phase 5 viz deferred**:

Adjacent ring is currently empty (0 tickers). Building viz on empty data shows empty rings.
The viz adds value when there are inter-ticker EDGES to display. Until user exercises
SuggestionsPanel to populate Adjacent, viz is rendering air. NOT a prioritization issue
— a data-existence prerequisite.

**Why no decision-discipline gates**:

User explicit philosophy: information ≫ discipline at individual-investor scale. Gates would
slow agility for marginal correctness gain. Information visibility allows focused attention
without slowing agility.

---

## §13. What I almost got wrong (lessons preserved)

For 6-months-from-now Claude / the repo owner who looks back at this plan and asks "why
this way?":

1. **v1 proposed Design B as a single-pillar viz solution.** User correctly pointed out
   visualization is one of several pillars. Without algorithm correctness + freshness +
   decision feedback, a pretty graph just makes wrong data more believable.

2. **v1 suggested "use existing watchlist for 2 weeks before building viz"** as scope
   control. User overrode with "不要考虑工作量". v2 still defers viz but for the right
   reason: no Adjacent data → nothing to visualize.

3. **v1 picked d3-force initially.** d3 is fine for force layouts but constraint-based
   concentric requires hand-rolling what fcose does for free. Use the right tool.

4. **v1 made decision feedback Phase 1.** Correct on importance, wrong on sequencing —
   easy data surfacing (position state, vs benchmark) is even smaller and more visible.
   v2 puts both in Phase 1.

5. **v1 missed entire pillar (information dimension coverage).** Position state, vs benchmark,
   sector concentration, technical chart, analyst ratings, earnings history all missing.
   Surface area for what "全面信息" means was too narrow.

6. **v1 framed Pillar 5 as "Decision Discipline" with gates.** User: information > gates.
   Discipline data exists but as chain nodes, not blocks. v2 renames to "Decision Context
   Dimensions" and removes all gate behavior.

7. **v1 missed PRO/CONTRA forced display entirely.** Anti-confirmation-bias is one of
   the highest-leverage information-design choices possible. Should have been there from v1.

8. **Almost shipped without §8 honest limitations.** Without explicitly stating what the
   dashboard CANNOT do, future-self would blame the tool for unsolvable problems. §8 is
   load-bearing.
