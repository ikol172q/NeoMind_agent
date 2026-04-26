# NeoMind Fin — Information-Distillation Architecture (V1)

**Author**: Claude (cowork session 2026-04-25)
**Status**: Design — captures the 6 user requirements raised after Phase 5 V4
plus the theoretical and market context. Implementation order follows.

## TL;DR

The Fin platform is doing three things at once, not one:

1. **Provenance-preserving causal distillation** — every conclusion keeps
   its derivation chain (Toulmin: claim / grounds / warrant / qualifier /
   rebuttal), so the user can audit "where did this come from?" all the
   way back to a SQLite row.
2. **Multi-resolution navigation** — overview → zoom → detail, classical
   Shneiderman info-vis pattern. User hover/clicks instead of reading
   instructions.
3. **Bidirectional knowledge-graph traceability** — strategy → lattice
   nodes (forward); lattice nodes → strategies (reverse). Every
   non-correspondence is an explicit gap (data widget missing OR
   strategy never grounded in current data).

A precise one-liner: **"provenance-preserving distillation with
multi-resolution drill-down over a bidirectional knowledge graph."**

No competitor (AlphaSense, Sentieo, Bloomberg, Koyfin, OpenBB,
FinChat, Stockpedia, Validea, Argdown, Kialo, Neo4j Bloom, PitchBook,
FactSet, Refinitiv) does all three for a personal investor.

---

## 1. Theoretical anchors

| Theory | Source | Used where |
|---|---|---|
| **Toulmin argument structure** | Stephen Toulmin (1958) *The Uses of Argument* | L3 call's 6-tuple |
| **Visual Information-Seeking Mantra** ("overview first, zoom and filter, then details on demand") | Ben Shneiderman (1996) *The Eyes Have It: A Task by Data Type Taxonomy for Information Visualizations*, IEEE | hover/click drill-down (req #6) |
| **Causal DAG / do-calculus** | Judea Pearl (2009) *Causality* | lattice DAG, counterfactual reasoning ("if MSFT didn't have wash sale, would call still fire?") |
| **Pyramid Principle / MECE** | Barbara Minto (1987) | strategy classification — currently horizon × difficulty; aspire to MECE-complete |
| **Data-ink ratio + small multiples + evidence-and-explanation** | Edward Tufte (1983-2006) | UI density, comparison patterns |
| **Ladder of Abstraction** | Bret Victor (2011) blog | hover-summary / scrub-detail / cross-layer navigation |

These six pieces form the implementation grammar. Choices that contradict
them ("just give the user a list", "wall-of-text reasoning") are explicit
regressions and must be flagged.

---

## 2. Market analogs (and why none fully fit)

| Category | Examples | What they solve | What they miss |
|---|---|---|---|
| Research search | AlphaSense, Sentieo, Visible Alpha | citations + filings full-text | no Toulmin lattice, no strategy taxonomy |
| Data dashboard | Bloomberg Terminal, Refinitiv Workspace, Koyfin | wide data | weak reasoning, no audit |
| Open-source data | OpenBB Terminal | modular data ingest | no strategy library, no bidirectional graph |
| AI Q&A | FinChat (Stratosphere), Public Premium | LLM Q&A on filings | black-box, conclusion-only |
| Scorecard | Stockpedia, SimplyWall.st, Validea | factor visualization | one-way, no strategy ↔ data reverse trace |
| Knowledge graph (general) | PitchBook, FactSet, Neo4j Bloom | entity links | not finance-causal, no Toulmin |
| Argumentation | Argdown.org, Kialo, Reasonable.land | argument graphs | no finance integration |
| Generic viz | Tableau, Apache Superset | dashboard tooling | no finance semantic layer |

NeoMind's specific combination — finance-specific Toulmin lattice +
strategy catalog + bidirectional widget audit + multi-resolution
drill-down — is **not currently shipped by any vendor**. The USP is real.

---

## 3. The six user requirements (verbatim, then expanded)

### Req #1 — "past dropdown should be more detailed; every run logged + queryable"

**Current state**: `agent/finance/lattice/snapshots.py` (Phase 8) writes
one snapshot per fresh build. UI dropdown shows distinct dates only.

**Target**:
- snapshot granularity per-run, not per-day (one day can have many
  manual force-reruns)
- each entry shows: timestamp · trigger (cron / manual / data-change)
  · #themes · #calls · diff-vs-prev (added themes, removed obs, etc.)
- click an entry → entire dashboard snapshots into that state, not
  just the lattice
- search/filter ("show all runs that included a wash-sale obs")

**Difficulty**: medium. Snapshot infrastructure exists.

---

### Req #2 — "Strategies tab needs a date selector — but explore first"

**Trap**: a strategy itself is time-invariant (`covered_call_etf` is
always `covered_call_etf`). What is time-varying is its
**relevance-to-today's-data** score, i.e. the strategy_match score
the matcher computes against current themes.

**Correct framing**: don't add time to strategies. Add time to
strategy_match scores. Per-snapshot fit-history.

**Schema**:
```sql
CREATE TABLE strategy_fit_history (
  snapshot_date  TEXT NOT NULL,
  run_id         TEXT NOT NULL,
  strategy_id    TEXT NOT NULL,
  score          REAL NOT NULL,
  score_breakdown_json TEXT NOT NULL,
  PRIMARY KEY (run_id, strategy_id)
);
```

**UI**: each strategy card gets a 30/90/365-day mini sparkline of
its fit score (e.g., `covered_call_etf` peaks at 8 during earnings
season, sits at 2-3 otherwise).

**LLM role**: NOT for selection (audit-breaking). LLM is the
**natural-language translator of score_breakdown** into prose. Input:
lattice snapshot (structured). Output: "Why this fits today" paragraph
that the user reads. The score itself stays deterministic.

**Difficulty**: medium. Requires #5 (controlled-vocab data_requirements)
to be sound first.

---

### Req #3 — "Bilingual UI; DB has both versions; one-button switch"

**Current**: `lattice_taxonomy.yaml` has `output_language: en | zh-CN-mixed`
but it's set at generation time. No runtime switch.

**Three paths**:
| Approach | Cost | Result |
|---|---|---|
| (a) Generate twice (every LLM call runs in both langs) | 2× tokens | Always-fresh both versions |
| (b) Single source + on-demand translation | Cheap | Slight lag on first switch |
| (c) Hybrid: structured fields double-written; long LLM output translated | Medium | Tight integration |

**Recommendation**: (c). `strategies.yaml` already has `name_en` /
`name_zh`. Extend the same dual-write to `starter_step_zh`,
`key_risks_zh`, etc. (subagent re-run can do this). For dynamic LLM
output (lattice claims/warrants), build a translation cache keyed on
content hash.

**UI**: top header `EN | 中` toggle, persists per-user via localStorage.

**Difficulty**: medium for strategies (a few hours), medium-large for
lattice dynamic translation.

---

### Req #4 — "Hyperlinks + reasoning so I can trust conclusions"

**Diagnosis**: it's not info-poverty. It's that:
- the matcher's reason ("score 8 because horizon_match + options +
  earnings + low_difficulty") is in tooltip-only as numbers, not prose
- the strategy card never says **"this is relevant today because
  MSFT 3 days from earnings + your $10k account + no naked options →
  cash_secured_put"**

**Build**:
1. Per-strategy "Why this fits today" auto-generated paragraph from
   `score_breakdown` (no LLM needed; simple template). Each scoring
   factor becomes a sentence with link.
2. Every reasoning chip is clickable → jumps to Research tab focused
   on the underlying L1 obs / L0 widget.
3. `key_risks` formatted as paragraph + sidenote ("此风险来自 lattice
   widget X 的 obs Y") with hyperlink.

**Difficulty**: medium. Templates + chip-routing. No new ML.

---

### Req #5 — "Strategies ↔ Research must be 1:1 and 100% comprehensive + correct"

**Core ask**. The infrastructure-defining one.

**Current shortcoming**: `strategies.yaml.data_requirements` is
free-text (`"options chain"`, `"IV rank"`, `"support levels"`). No
validation, no reverse index, no gap visibility.

**Build (the real work)**:

**Step A — controlled vocabulary**: enumerate every L0 widget id the
lattice currently produces (or could plausibly produce). Live in
`agent/finance/lattice/widget_registry.py`. Each widget is:
```python
{
    "id": "fin_db.wash_sale_detector",
    "label_en": "Wash Sale Detector",
    "label_zh": "Wash Sale 检测器",
    "status": "available",          # available | planned | deprecated
    "produces": ["risk:wash_sale", "compliance:tax_inefficiency"],
    "source_module": "agent.finance.compliance.wash_sale",
    "description": "...",
}
```

**Step B — enforce on strategies**: every entry in
`strategies.yaml.data_requirements` must reference a registered widget
id. Loader validates at boot; CI fails on dangling refs.

**Step C — backend endpoints**:
- `GET /api/strategies/{id}/widget-status` → `[{widget_id, status,
  description}, ...]` — forward map
- `GET /api/lattice/widgets/{widget_id}/strategies` → `[{strategy_id,
  name_zh, ...}]` — reverse map
- `GET /api/lattice/widget-coverage` → coverage matrix (every widget
  × every strategy) for audit

**Step D — UI forward**: strategy card shows requirements as widget
chips with ✓ / ⚠ / planned status. Click chip → lattice graph viewer
focused on that widget.

**Step E — UI reverse**: lattice graph node inspector (right panel)
adds a "Powered by N strategies" section listing every strategy that
declares this widget as a requirement. Click → Strategies tab focus
on that card.

**Difficulty**: highest of the six. **Highest value too** — this
operationalises the user's "100% comprehensive + correct" goal.

---

### Req #6 — "Hover/click instead of instructions; cursor reveals what to drill"

**Direct match**: Shneiderman's "details on demand". UX pattern is
known and stable.

**Build**:
- every primary element (strategy card, L0 widget node, theme node,
  call) has a 1-line hover tooltip
- click → right-side inspector panel (lattice graph viewer already
  has this; needs to be promoted to a global pattern)
- cross-tab: clicking a chip in any tab can pin the inspector to its
  context (strategy card while in Research tab, lattice node while in
  Strategies tab)

**Difficulty**: medium. UX work, no new ML.

---

## 4. Recommended implementation order

Optimised for **value / difficulty ratio**, **building on prior
foundation**, and **breaking nothing**:

1. **Req #5** — controlled vocab + bidirectional index. Foundation for #4 / #2.
2. **Req #4** — Why-this-fits-today + reasoning chips. Now has structured fields to reference.
3. **Req #1** — past run-level snapshot list + diff. Snapshot infra ready.
4. **Req #6** — hover-to-drill / inspector panel promoted to global pattern.
5. **Req #2** — strategy_fit_history table + sparkline. Needs #5.
6. **Req #3** — bilingual switch (catalog static first, lattice dynamic V2).

Each step is verified end-to-end against host browser at `127.0.0.1:8003`
before moving on. Build failures must surface (no `--silent`).

---

## 5. Non-goals for this phase

- Real-money trading execution. NeoMind stays advisory.
- Real-time streaming quotes. Daily / 5-min cadence is enough for the
  user's mid-term-leaning stance.
- Multi-user / RBAC. Single-user assumption holds.
- Mobile / tablet layout. Desktop dashboard is the primary surface.

---

## 6. Open questions

1. **MECE-completeness of strategy taxonomy**: 35 strategies is a good
   start, but is it MECE? Is there overlap (covered_call_etf vs
   poor_mans_covered_call) we should explicitly tag as "alternatives
   to each other"?
2. **Widget evolution**: when a new L0 widget gets added, what
   strategies should auto-update their requirements? Probably manual.
3. **Counterfactual queries** (Pearl): "if I had no MSFT position
   today, what would the lattice look like?" — this is research-grade
   and out of scope for now, but worth noting as a future direction.
4. **Hover latency budget**: target <100ms for tooltip render. May
   require pre-computed indexes (especially for reverse map at scale).

---

## 7. References

- Toulmin, S. (1958). *The Uses of Argument*. Cambridge University Press.
- Shneiderman, B. (1996). The Eyes Have It: A Task by Data Type Taxonomy
  for Information Visualizations. *Proceedings 1996 IEEE Symposium on
  Visual Languages*, pp. 336–343.
- Pearl, J. (2009). *Causality: Models, Reasoning, and Inference* (2nd ed.).
  Cambridge University Press.
- Minto, B. (1987). *The Pyramid Principle*. Pearson Education.
- Tufte, E. (2001). *The Visual Display of Quantitative Information* (2nd ed.).
  Graphics Press.
- Victor, B. (2011). [Up and Down the Ladder of Abstraction](http://worrydream.com/LadderOfAbstraction/).

Vendor product pages (accessed 2026-04-25):

- AlphaSense — https://www.alpha-sense.com
- Sentieo (now part of AlphaSense) — https://sentieo.com
- Bloomberg Terminal — https://www.bloomberg.com/professional/solution/bloomberg-terminal/
- Koyfin — https://www.koyfin.com
- OpenBB Terminal — https://openbb.co
- FinChat / Stratosphere — https://finchat.io
- Stockpedia — https://www.stockopedia.com
- SimplyWall.st — https://simplywall.st
- Validea — https://www.validea.com
- Argdown — https://argdown.org
- Kialo — https://www.kialo.com
- Neo4j Bloom — https://neo4j.com/product/bloom/
