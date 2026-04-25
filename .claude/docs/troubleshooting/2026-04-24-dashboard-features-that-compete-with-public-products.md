# Dashboard features that duplicate public products are dead weight

**Session:** 2026-04-24, Insight Lattice Research-tab cleanup

## The principle

For an opinionated product (NeoMind = "lattice / information
distillation"), every UI surface earns its pixels by doing something
the user can't get from authoritative public products. If a tile
exists only to "show a chart" or "show a heatmap" or "show a quote",
**it competes with TradingView, Yahoo Finance, Koyfin, Finviz, 雪球
on their home turf** — and loses, because:

- They have 10x your engineering budget aimed at exactly that surface
- They have realtime feeds you'd have to license to match
- They have keyboard shortcuts, themes, drawing tools, alerts you
  don't have time to build
- They are *what the user reaches for habitually anyway*

The product question isn't "can I build a chart tile?" It's
"why would the user ever look at my chart tile instead of
TradingView in their other browser tab?" If you can't answer in
one short sentence, the tile is a tax on the rest of the product.

## What the L0 layer ACTUALLY needs to be

For NeoMind specifically: L0 is the layer that **tags + snapshots**
the data feeding L1+. It must:

1. Run as a backend pipeline that produces structured observations
2. Stamp each observation with `source.widget` + `source.generator`
   so self-check can audit "did this number actually come from this
   widget?"
3. Produce a snapshotable JSON (so today's lattice can be reproduced
   tomorrow for audit / regression)

It MUST NOT:

1. Try to be a viewing UI for the user. The user views data on
   TradingView/Yahoo/Finviz — not in your tile.
2. Have its own real-time refresh loop fighting public products
   for the user's attention.
3. Duplicate domain-specialist features (orderbook, drawing,
   technical indicators) because "every dashboard has them".

## WRONG

```tsx
// Research tab: 16-widget grid where DigestView (the actual
// product value) is just one row at the top.
const DEFAULT_LAYOUT = [
  { i: 'brief',     w: 12, h: 9 },          // ← lattice (the value)
  { i: 'news',      w: 9,  h: 12 },
  { i: 'sentiment', w: 3,  h: 12 },
  { i: 'watchlist', w: 5,  h: 10 },
  { i: 'us_quote',  w: 4,  h: 5 },
  { i: 'cn_quote',  w: 4,  h: 5 },
  { i: 'portfolio', w: 3,  h: 10 },
  { i: 'earnings',  w: 6,  h: 9 },
  { i: 'rs_grid',   w: 6,  h: 9 },
  { i: 'correlation', w: 6, h: 9 },
  { i: 'sectors',   w: 6,  h: 9 },
  { i: 'chart',     w: 6,  h: 10 },
  // ... 11 more tiles
]
```

The user lands on the page, sees 16 tiles, and the lattice — the
*one thing the product is for* — is one row out of 70. They
unconsciously categorise the page as "yet another dashboard"
and lose the affordance of the unique feature.

## RIGHT

```tsx
// Research = lattice, full-page, no competing surfaces.
// Watchlist + portfolio config (the inputs L0 needs) are
// reachable via a small `config` button → drawer; no permanent
// pixels.
export function ResearchTab(props) {
  const [configOpen, setConfigOpen] = useState(false)
  return (
    <div className="h-full overflow-y-auto p-3 relative">
      <button onClick={() => setConfigOpen(true)}> config </button>
      <DigestView {...props} />
      <ResearchConfigDrawer open={configOpen} onClose={...} {...props} />
    </div>
  )
}
```

Every L0 node in the lattice gets per-widget outbound links to the
authoritative public products. You don't compete; you point at
the better tool with a one-click jump.

```tsx
const WIDGET_EXTERNAL_LINKS = {
  chart:    [TradingView, Yahoo Finance, 雪球],
  earnings: [Yahoo Earnings, Earnings Whispers],
  sectors:  [Finviz Map, 雪球 行业, OpenBB sectors],
  sentiment:[CNN Fear & Greed, AAII Sentiment],
  // ...
}
```

This is honest and durable: your product owns the unique value
(tagging, snapshot, distillation, audit), and outsources every
"viewing data" need to the products that already won that fight.

## What you DON'T have to do (= "Path A")

You don't have to delete the old code. Move the dashboard grid to
a `LegacyTab` reachable only via Settings or `?legacy=1`, mark it
LEGACY in the header, and leave it. Cost: ~50 lines + one new tab.
Benefits:

- Reversible: if the user actually misses a tile, they have it
- Saved layouts (`localStorage`) survive untouched
- The product surface that drives the experience is single-purpose

You can delete the legacy grid weeks later if the user never
opens it. Don't burn the bridge on day 1.

## Tell — are you doing this?

Walk through your top-level UI surfaces. For each surface, ask:

1. **Does this exist primarily because every product in the space
   has one?** (e.g., "well, all dashboards have a quote tile")
   → Almost certainly dead weight. Link out.
2. **What does this do that a domain-specialist product doesn't
   do better?** If the answer is empty or "it's right here" or
   "it matches our colour scheme" → dead weight.
3. **Is the user reaching for this, or for the external product
   in another tab?** If the latter, you're paying engineering tax
   to replicate something the user *isn't even looking at*.

Surfaces that survive this audit:

- The features that uniquely belong to your product (lattice,
  Toulmin calls, integrity self-check)
- Configuration surfaces for **your** unique features (watchlist,
  portfolio — but as drawers, not permanent tiles)
- Audit / trace / debug surfaces (irreplaceable: external products
  can't audit your output)

## This codebase

- `web/src/tabs/Research.tsx` — lattice-only after V11
- `web/src/tabs/Legacy.tsx` — preserved old grid, hidden from main nav
- `web/src/components/widgets/ResearchConfigDrawer.tsx` — gear-button
  drawer; no permanent pixels for config
- `web/src/components/widgets/LatticeTracePanel.tsx::WIDGET_EXTERNAL_LINKS`
  — curated outbound links, one section per L0 widget node

## Related entries

- `2026-04-23-validate-then-ship-llm-pattern.md` —
  the *content* layer of the same idea: ship LLM output only after
  a validator passes; this entry is the *surface* layer of the
  same idea: ship UI only when it earns its pixels.
