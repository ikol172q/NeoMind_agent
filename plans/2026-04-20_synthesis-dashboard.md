# Synthesis Dashboard — from grid-of-widgets to agent-first analysis

**Status**: active (phased implementation, 6 phases)
**Scope**: Research tab UX + inline-agent architecture + advanced analytical layer
**Motivation**: Widgets ≠ decisions. Chat tab as separate destination = copy/paste friction.
The dashboard should read the data *with* the user, not wait to be asked.

---

## Problem

The current dashboard separates **data display** (Research tab, 14 widgets) from
**analysis** (Chat tab). The user has to:

1. See something interesting on Research.
2. Switch to Chat.
3. Retype or click ask-agent buttons that inject synthesis.
4. Read the agent's answer.
5. Switch back to Research.

Even with the context-injection shipped in steps 1-5 of the prior arc
(`a4c918a`, `f6b47ff`), this round-trip remains. The research survey of
10+ production tools (Perplexity Finance, Robinhood Cortex, Bloomberg
ASKB, Seeking Alpha Quant, FinChat, etc.) labels the "drawer chat"
pattern I almost shipped as **fake sophistication** — it's a thinner
costume on the same mode-switching problem.

Two more user-reported gaps:

- **No widget-to-widget relationships**. Why is AAPL flat while Tech is
  green? The user infers this. Research finds that the top tools
  (Bloomberg ASKB, Robinhood Cortex) compute relationships and write
  them as prose or citation links.
- **No density tiers** (初级 / 中级 / 高级). Every widget is at the
  same altitude. Seeking Alpha Quant's hard-tiered factor drill is the
  cleanest "10k-ft → datapoint" pattern in the survey.

## Design (decided, not optional)

Three patterns, composited, in priority order:

1. **Narrative hero** at top of Research — agent-authored 3-4 sentence
   story refreshed every 5 min. Reuses `/brief` synthesis.
2. **Hover-synthesis tooltips** on every hot row (watchlist, portfolio,
   RS grid, sector tiles). Zero-click interpretation, cached by
   (widget, symbol, 5min bucket).
3. **3-tier factor drill** per stock: letter grade → 5 factor pills
   → raw + agent narrative. Tiers 1 and 2 are local math, tier 3 hits
   the LLM.

Rejected:
- Right-side chat drawer (the thing I almost shipped). Research-labelled
  fake sophistication.
- Continuous density slider. Hard-tiered (3 fixed levels) beats it for
  cognitive clarity.

## Phases

### Phase 1 — Narrative hero on Research (~1 commit)

- `GET /api/research_brief?project_id=X` — backend. Calls synthesis
  (project), feeds it + a fixed brief prompt to DeepSeek, returns 200-
  word agent read. 5-min in-memory cache.
- `<ResearchBrief>` component at top of Research (full-width, fixed
  height ~120px). Auto-refresh every 5 min. Manual refresh button.
- Tests: endpoint returns text with the key sections; widget renders
  non-empty text on first paint.
- Commit when green.

### Phase 2 — Hover-synthesis on hot rows (~1 commit)

- `GET /api/insight/symbol/{sym}?project_id=X` — returns a 1-sentence
  interpretation pulled from synthesis + a tight prompt. Cached by
  (symbol, 5-min bucket).
- `<InsightHover>` React component: wraps a target, on hover shows a
  floating tooltip that fetches the insight lazily.
- Integrate into: WatchlistWidget rows, PortfolioHeatmapWidget rows,
  RSGridWidget rows, SectorHeatmapWidget treemap cells.
- Tests: tooltip appears on hover, contains non-empty text, doesn't
  double-fetch within the cache window.
- Commit when green.

### Phase 3 — 3-tier factor drill on stock widgets (~1-2 commits)

- `GET /api/factors/{sym}` — returns `{momentum, value, quality,
  growth, revisions}` each as `{grade: 'A'..'F', value, percentile}`.
  Computed locally from yfinance fundamentals + our RS module.
- Each stock-level widget row grows a 3-state expansion:
  - Tier 1 (default): one-line summary — price + day % + overall grade.
  - Tier 2: factor pills row (M·V·Q·G·R with colour-coded letters).
  - Tier 3: raw numbers + peer median + agent narrative (hits LLM,
    cached 10 min).
- First integration: WatchlistWidget. Then USQuoteCard. Then
  PortfolioHeatmapWidget rows.
- Tests: factors endpoint returns all 5 grades, expansion toggles
  tier, agent narrative appears only at tier 3.
- Commit when green.

### Phase 4 — Citation-linked claims (~1 commit)

- Extend the workflow-slash commands (`/brief`, `/prep`, `/check`) so
  the LLM is instructed to emit claims in JSON with
  `{"text": "...", "cites": [{"widget": "portfolio", "row": "AAPL"}]}`.
- Chat panel parses citations, renders claim sentences with a hover
  highlight that flashes the cited widget row.
- Narrative hero uses the same citation channel.
- Tests: parser handles both citation-JSON responses and plain-prose
  fallbacks gracefully.
- Commit when green.

### Phase 5 — Command palette + anomaly flags (~1 commit)

- Global ⌘K / Ctrl+K handler → modal palette listing slash commands.
  Types → fuzzy filter → Enter invokes, routes to the chat with context.
- Anomaly flag bar on narrative hero: flags computed locally, e.g.
  *"AAPL at 52w high + earnings 10d (rare combo this year)"*, *"NVDA
  IV > 1.5× historical move (option market pricing a big event)"*.
- Tests: ⌘K opens palette, typing filters, Enter dispatches. Anomaly
  endpoint produces >=1 flag when seeded data has a matching condition.
- Commit when green.

### Phase 6 — Advanced analytical components (~2-3 commits)

Each slots into an existing widget's tier-3 expansion. Priority order:

1. **Factor grades** — already computed in Phase 3. Just surface more.
2. **Peer comparison table** — sector-median P/E / growth / margin /
   debt for a stock, from yfinance `info`. Slots under tier-3 of the
   quote card.
3. **Portfolio attribution** — today's PnL split by position and by
   sector. Slots under PortfolioHeatmapWidget tier-2.
4. **Correlation matrix** — across watchlist, 90d returns. New widget
   or slots under WatchlistWidget tier-3.
5. **Economic calendar** — from BLS/BEA/Fed RSS already in Miniflux
   seed. Slots as a header strip above news.
6. **Options skew / term structure** — for each symbol with options,
   IV curve across expiries. Extends the earnings widget's tier-3.

Deferred (out of scope v1): insider/13F from SEC EDGAR, live
volatility surface, Wall-Street-consensus roll-up. These are 1-2
commits each and should be their own mini-plans.

## Implementation rules

- **Reuse over rebuild**. The synthesis endpoints (`synth_symbol_data`,
  `synth_project_data`) are the data bus. New widgets consume the same
  object. Don't re-fetch from yfinance/akshare inside widgets.
- **Cache aggressively**. Hover synthesis uses 5-min buckets. Factor
  grades 10 min. Brief 5 min. Anomaly flags 2 min. If the user clicks
  "refresh" on a widget, cache-busts only that widget's layer.
- **Graceful degradation**. A missing data field renders as "—", not
  an error. A failed LLM call renders the pre-computed pills tier
  without narrative. Never 502 the whole page because one
  sub-fetch choked.
- **Tests at every phase boundary**. Full suite stays green. New
  Playwright tests per phase. Regression tests capture the
  design intent, not just the implementation.

## Non-goals

- Persistent right-side drawer chat. Rejected above. Chat tab stays as
  the deep-conversation workshop; Research becomes the synthesis stage.
- Continuous density slider. Use fixed 3-tier.
- Paid data feeds. Everything via yfinance / akshare / Miniflux / SEC
  EDGAR. If a pattern requires paid data, we skip it.
- Mobile responsive. Dashboard is a desktop-first tool for
  user's workflow.

## Success criteria

- Zero copy/paste from Research to Chat for the common questions.
- User can get a 3-sentence read of "what matters today" without
  clicking anything.
- Any ticker on any widget shows the agent's take on hover.
- 3 clicks deep: ticker → factor grid → raw numbers + narrative.
- All 14 widgets' data now reaches the agent via synthesis; no widget
  is an island.

## Rollback plan

If a phase regresses worse than it improves, revert the commit and
ship only the phases that net-positive. Each phase is designed to be
independently revertible.
