# Insight Lattice — L0 → L1 → L2 → L3

**Status**: approved 2026-04-20 · D1 in progress; targeted research
round (news salience · call stability · theme-overlap viz) running
in parallel.
**Scope**: a layered, overlap-preserving distillation pipeline that
replaces the shallow "narrative hero" with a mathematically rooted
traceable structure from raw widget data up to actionable calls.

## Naming

**Insight Lattice**. The "lattice" name is borrowed from Formal
Concept Analysis — the only mathematically rigorous structure in the
literature that both layers and preserves overlap by construction
(the user's two hard requirements). UI component: `<LatticeView>`.
Layer roles: Raw / Observations / Clusters / Apex (apex because the
top can hold >1 call).

## Decisions locked on 2026-04-20

- **n=3**. CFA / inverted-pyramid / research-paper literature all
  converge on 3 as the scan-and-drill modal. n=4 stays possible via
  pipeline config but isn't built until a real information gap is
  observed in use.
- **L3 allows 0 calls**. Forced emission corrupts trust — better to
  say "no high-conviction action today" than invent one.
- **Tag taxonomy is versioned** (YAML with `version:` field).
- **Language of L3 claim**: bilingual switch deferred. v1 English;
  add `language:` knob if user asks for zh-CN later.
- **Call stability / persistence**: deferred past D6 pending the
  concurrent research round's recommendation.

## Why this exists

The current narrative hero is **compression, not distillation**: the
LLM sees DASHBOARD STATE and writes 3 sentences. No intermediate
structure, no traceability, no overlap. The user cannot ask "why
this conclusion?" and get back specific evidence. A real analyst's
workflow has visible intermediate layers that can be audited.

## Hard rules (non-negotiable)

1. **L0 and L_n are fixed, middle layers configurable.**
2. **Overlap must be preserved.** Same L1 fact legitimately supports
   multiple L2 themes; same theme supports multiple L3 calls. MECE
   (mutually exclusive) is rejected by design.
3. **Every upper-layer claim carries a `cites: [lower_layer_id]`
   array.** No claim exists without a reference chain down to L0.
4. **n=3 to start**, pipeline config makes n=4 a one-line change.

## Schemas

### L1 · Observation

```python
class Observation:
    id: str                         # "obs_001"
    kind: str                       # "52w_high" | "earnings_soon" | ...
    text: str                       # human-readable, ≤25 words
    numbers: dict[str, float]       # typed values
    tags: list[str]                 # multi-label taxonomy (see below)
    source: dict                    # {widget, field, symbol} — L0 pointer
    severity: Literal["info", "warn", "alert"]
    confidence: float               # 0-1
```

**Generation: deterministic, no LLM.** Scan synthesis + anomalies +
factors + sector + portfolio; emit 20-40 observations. Milliseconds.

### L2 · Theme

```python
class Theme:
    id: str                         # "theme_earnings_risk"
    title: str                      # ≤4 words
    narrative: str                  # 1-2 sentences, cites numbers
    members: list[dict]             # [{obs_id, weight: 0-1}]
    tags: list[str]                 # tag signature of the theme
    severity: Literal["info", "warn", "alert"]
```

**Generation: tag-based clustering + LLM naming.** Pure-compute L2 is:

```
for each theme_tag_signature T:
    members = [
        (obs.id, jaccard(obs.tags, T))
        for obs in L1
        if obs.tags ∩ T is non-empty
    ]
```

Observations can appear in multiple themes — **overlap preserved
exactly** by set intersection. Then one LLM call per theme just to
write the narrative string; it does not re-cluster.

Theme tag signatures are enumerated from a curated taxonomy (see
below). Typical count: 5-7 themes per refresh.

### L3 · Call (Toulmin-structured)

```python
class Call:
    id: str                         # "call_001"
    claim: str                      # "Hold AAPL through earnings"
    grounds: list[str]              # theme_ids that support this
    warrant: str                    # *why* grounds justify the claim
    qualifier: str                  # "if VIX < 20", "medium confidence"
    rebuttal: str                   # what would invalidate it
    confidence: Literal["high", "medium", "low"]
    time_horizon: str               # intraday | days | weeks | quarter
```

**Generation: LLM structured output + MMR.** One LLM pass returns
up to 5 candidate calls; MMR (Maximal Marginal Relevance) picks the
top-K (K≤3) most diverse. `grounds` must reference only existing
theme_ids; ungrounded calls are dropped in post-validation.

0 calls is a valid answer — "no high-conviction action today."

## Tag taxonomy (versioned)

The tag set is the **hidden source of truth** for L1→L2. It must be
explicit, versioned, and testable. v1 tags:

```
symbol:<TICKER>        # symbol:AAPL
sector:<NAME>          # sector:Technology
market:<US|CN|HK>
risk:<earnings|regulatory|liquidity|macro|political>
technical:<breakout|oversold|overbought|support|resistance>
pnl:<positive|negative|flat>
position:<TICKER>      # my paper book
timescale:<short|mid|long>
direction:<up|down|flat>
signal:<bullish|bearish|neutral>
regime:<vix|breadth|sentiment>
catalyst:<earnings|fed|data|product>
```

Theme tag signatures are human-curated combinations:
- `{risk:earnings}` → "Earnings risk cluster"
- `{technical:breakout, direction:up}` → "Breakout momentum"
- `{regime:*}` → "Macro regime"
- `{pnl:*, position:*}` → "Book performance"
- `{catalyst:earnings, timescale:short}` → "Near-term catalysts"

New themes = one YAML entry in `agent/config/digest_themes.yaml`.
No code change. Tests assert every observation lands in at least
one theme (completeness); zero themes being orphaned.

## Research results (2nd round, 2026-04-20)

Three gaps got targeted answers:

**A · News salience (which 3-8 headlines become L1 obs)**
Ship the pipeline **symbol+keyword+recency** → **TDT dedup** → **MMR pick**.
- Base score: `portfolio_weight × keyword_multiplier / (1 + log(age_min))` — this is what Bloomberg First Word actually does, and it's microseconds per headline with pure stdlib regex.
- Dedup via incremental clustering (TF-IDF or HashingVectorizer + cosine threshold) — classical TDT. sklearn, <50 ms at 100 headlines.
- MMR final pick of 3-8 with λ=0.7.
- **Skip** NER/spaCy (15MB model — violates "no heavy downloads") and embedding models entirely until >500 headlines/day.
- **LLM re-ranker** optional on top-15 only (latency budget permitting).

**B · Call stability (no flip-flop every 5 min)**
Ship **hysteresis bands on an EMA'd score** + **UX diff of prior call**.
- EMA the confidence score for each call over time (`α ≈ 0.3`).
- Schmitt-trigger thresholds: don't flip HOLD→TRIM until score > upper; don't flip back until score < lower.
- Always render the prior call + a one-line "changed because …" diff — Morningstar's actual trust mechanism.
- **Skip** Dempster-Shafer (mathematical cosplay for this data), Kalman filter (overkill for discrete calls), Bayesian belief update (needs real likelihoods we don't have).

**C · Overlap visualization**
Ship the **themes × observations biclique heatmap** as primary view + **Sankey** as secondary provenance tab + bipartite listing as text fallback.
- Heatmap: rows = themes (5-7), cols = observations (20-40), cell = membership weight. Shared observations show as vertical hot stripes — immediately legible. `plotly.express.imshow` or a React heatmap lib.
- Sankey (L1→L2→L3) for the "where does this call come from" narrative view.
- **Skip** force-directed (jitters), Hasse diagrams (too niche), Venn (breaks past 4 sets).
- **Always add** hover-highlight: hover a theme → any obs shared with it glows elsewhere in the UI.

## Methods picked (from the research)

- **L1 tagging**: pure Python rules. No LLM. No external model.
- **L1→L2 clustering**: **tag-based soft membership** (Jaccard over
  tag sets). Overlap: native. Deterministic: yes. Ref: research agent
  "Best bet #1".
- **L2 narrative**: one LLM call per theme (~5 calls). Cheap.
- **L3 argument structure**: **Toulmin model** (claim/grounds/warrant/
  qualifier/rebuttal). Ref: Toulmin + argmining-on-earnings-calls
  literature.
- **L3 selection**: **MMR** with λ=0.7 to pick diverse high-value
  calls from the LLM's candidate set.
- **Rejected**: BERTopic (boot-heavy ML), LDA (stochastic, drifts),
  MECE (overlap forbidden), FCA (mathematically cleaner but `concepts`
  PyPI library is unmaintained — revisit if tags taxonomy breaks down).

## Caching + refresh

| Layer | TTL | Trigger |
|---|---|---|
| L1 | 60s | Cheap, safe to rebuild often |
| L2 narratives | 5 min | LLM-generated, 5 calls |
| L3 calls | 15 min | LLM-generated, 1 call + MMR |

`?fresh=1` bypass on every layer for manual refresh.

## Endpoints

```
GET /api/distill/observations?project_id=X     → L1 list
GET /api/distill/themes?project_id=X           → L1+L2
GET /api/distill/calls?project_id=X            → L1+L2+L3
GET /api/digest?project_id=X                   → all three (one fetch)
```

Composition is linear. Upper endpoints include lower layers so the
UI can render the full traceability tree in one round-trip.

## UI · `<DigestView>` component

Replaces the current `<ResearchBriefWidget>` at the top of Research.

**Three render modes:**

1. **Summary** (default): L3 calls only, Toulmin chips (Claim ·
   Because · Unless). Each chip is clickable for drill-down.
2. **Drilldown**: L3 → L2 → L1 → L0. Each node is a collapsible
   accordion. Hover any L1 observation shows "appears in themes:
   X, Y" (demonstrating overlap both directions).
3. **Flat** (debug): all layers expanded at once.

**Interactions**:
- Click L3 claim's "Because" chip → expand cited L2 themes.
- Click L2 theme's "▸" → expand cited L1 observations with weights.
- Click L1 observation → highlight the source widget/cell in L0.
- Shift-click L1 obs → "explain why this is in theme Y" triggers an
  on-demand LLM call (not on every refresh — user-initiated).
- `cites` chips from chat messages (existing citation system) route
  back to this tree so chat answers land you in the evidence.

**Cognitive load rule**: ≤4 items visible per layer in summary mode.
If the LLM emits >4 themes/calls, MMR picks the top-4.

## Phases

| Phase | Deliverable | Validation gate |
|---|---|---|
| **D1** | `observations.py` + tag taxonomy + L1 endpoint | 20-40 obs on real data; every obs has ≥1 tag and valid `source`; invariant tests on taxonomy completeness |
| **D2** | `themes.py` (tag clustering + LLM narrative) + endpoint | 3-7 themes; **overlap proven** (some obs in ≥2 themes on real data); narrative cites specific numbers from members |
| **D3** | `calls.py` (Toulmin + MMR) + endpoint | 0-3 calls; every call's grounds reference existing theme_ids; diversity (no two calls with identical theme set) |
| **D4** | `<DigestView>` frontend (summary + drilldown) + replaces brief hero | Click-through from L3 to L0 works for real data; hover shows bidirectional membership |
| **D5** | Integrate existing citations + anomalies into the new tree | Existing `[[AAPL]]` tags in chat route to DigestView nodes |
| **D6** | Config for n=4 (add a sub-theme layer between L1 and L2) | YAML switch works without code change |

Each phase commits independently, behind a feature flag if needed so
we can roll back to the old narrative hero.

## Tests (each phase has Playwright + unit)

Unit (pytest):
- L1 taxonomy completeness: every observation has ≥1 tag
- L1→L2 overlap: at least one observation belongs to ≥2 themes on
  seeded data (regression against "hard clustering crept back in")
- L2→L3 traceability: every L3 call's `grounds` references existing
  theme_ids
- MMR diversity: no two returned calls share all theme_ids

Playwright:
- DigestView summary mode shows Toulmin chips
- Drill-down sequence: L3 → L2 → L1 → widget highlight
- Bidirectional: hover L1 obs shows theme memberships
- Empty-state (no data): shows the quickstart like the current hero
- Cache busts when `?fresh=1` requested

## Non-goals

- No BERTopic / LDA / embeddings: keep deterministic and dependency-
  light.
- No new data sources — L1 draws only from what synthesis already has.
- No chat-tab replacement — chat stays as deep conversation; DigestView
  is the inline distillation surface on Research.
- No retraction learning — we don't persist which calls turned out
  right/wrong in v1. Add later if useful.

## Rollback

Every phase commit is independently revertible. The feature flag
(`NEOMIND_DIGEST_ENABLED`, env var, default off) lets us keep the
old narrative hero as the production read while iterating the new
funnel in isolation.

## Open questions (flag for user at plan-approval time)

- Tag taxonomy v1 is author-specified. Should we plan a YAML migration
  when we need v2? (I say: yes, version field + upgrade script)
- Should L3 calls persist across refreshes so the user can see "this
  call has been consistent for 3 hours" vs "flip-flopping"? Adds
  storage + dedup logic. I'd defer to Phase D6+.
- Bilingual output? Current prompts are English; L3 claim in Chinese
  might land better for this user. Cheap change: add `language:
  zh-CN` switch to the calls prompt template.
