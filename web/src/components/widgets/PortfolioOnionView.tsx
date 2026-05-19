/**
 * PortfolioOnionView — Phase 5 viz.
 *
 * Concentric rings (onion) for tier hierarchy + edges for relations:
 *   Center  ⊙ ME node
 *   Ring 1  Core (≤10), large gold-bordered
 *   Ring 2  Adjacent (10-50), medium emerald, with always-visible
 *           spoke line back to parent_ticker
 *   Ring 3  Watching (50+), small dim
 *
 * Relation edges (10-K competitor / customer / supplier) are
 * default-HIDDEN to avoid hairball. Click a node → its incoming +
 * outgoing relations highlight, all other nodes dim. Click empty → reset.
 *
 * Per plan §5 Pillar 1 progressive-disclosure design.
 *
 * Built on react-force-graph-2d (already in deps) with custom
 * radial force per tier — d3.forceRadial pulls each node to its
 * tier's target radius, charge force keeps them spread, link force
 * is muted because spokes are already implied by ring placement.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import { useStockResearch } from '@/components/research/StockResearchContext'
import { usePortfolioView, useLatticeCalls, usePortfolioSummary, useChain, type PortfolioGraphNode, type PortfolioGraphEdge, type LatticeTheme } from '@/lib/api'
import { Loader2, Eye, EyeOff, Clock, Layers } from 'lucide-react'
import { NodeChainPanel } from '@/components/widgets/NodeChainPanel'

/**
 * Common 2-5 letter UPPERCASE English tokens that aren't tickers.
 * The regex `[A-Z]{2,5}` matches these and would false-positive without
 * the watchlist intersect — but even with the intersect we can still
 * hit edge cases where a real ticker like CEO (a tiny Chinese ADR) is
 * in the watchlist AND the claim text contains "CEO" as an English
 * abbreviation. This blacklist filters tokens that almost certainly
 * mean the English meaning when found in financial-analyst prose.
 *
 * If you add a ticker that's also in this list, prefer the more
 * specific theme-tag path (`symbol:CEO`) for the arrow instead.
 */
const TICKER_FP_BLACKLIST = new Set([
  // Pronouns / connectors / units
  'US', 'EU', 'UK', 'JP', 'CN', 'USD', 'EUR', 'CNY', 'JPY', 'GDP', 'YOY', 'YTD',
  // Tech / business jargon
  'AI', 'API', 'CEO', 'CFO', 'CTO', 'CIO', 'COO', 'EPS', 'PE', 'EBIT', 'EBT',
  'IPO', 'IPO', 'M&A', 'KPI', 'ROI', 'ROE', 'ROA', 'TAM', 'SAM', 'SOM',
  'B2B', 'B2C', 'SaaS', 'LLM', 'CPU', 'GPU', 'GHG', 'ESG', 'FX',
  // SEC / accounting
  'SEC', 'FED', 'IRS', 'GAAP', 'IFRS', 'PCAOB', 'FASB', 'CAPEX', 'OPEX',
  // Common headline words
  'NEW', 'OLD', 'TOP', 'BOT', 'BIG', 'CAP', 'GAP', 'WIN', 'LOSS', 'BUY', 'SELL',
  'HOLD', 'PASS', 'FAIL', 'PRO', 'CON', 'YES', 'NO', 'OK', 'AM', 'PM', 'ET',
])

/**
 * Extract tickers a given L3 call refers to. Strategy:
 *   1. theme-tag path (highest precedence) — `symbol:XXX` tags upstream
 *      are explicit, never false-positive.
 *   2. claim regex (fallback) — 2-5 letter UPPERCASE tokens, intersected
 *      with watchlist AND filtered against the FP blacklist.
 * Returns the matched tickers from the supplied watchlist set so we
 * only point arrows at nodes that exist in the onion.
 */
function extractCallTickers(
  call: { claim: string; grounds: string[] },
  themesById: Map<string, { tags: string[] }>,
  watchlist: Set<string>,
): string[] {
  const found = new Set<string>()
  // 1. theme symbol tags first — these are explicit and trusted
  for (const themeId of call.grounds) {
    const t = themesById.get(themeId)
    if (!t) continue
    for (const tag of t.tags ?? []) {
      if (tag.startsWith('symbol:')) {
        const tk = tag.slice(7).toUpperCase().trim()
        if (watchlist.has(tk)) found.add(tk)
      }
    }
  }
  // 2. claim regex, blacklist-filtered
  const re = /\b[A-Z]{2,5}\b/g
  for (const m of call.claim.matchAll(re)) {
    const tk = m[0]
    if (TICKER_FP_BLACKLIST.has(tk)) continue
    if (watchlist.has(tk)) found.add(tk)
  }
  return Array.from(found)
}

/**
 * Extract per-theme tickers from a LatticePayload by reading
 * `symbol:XXX` tags off each theme. Returns { themeId → Set<ticker> }.
 * Also produces tickerThemes (ticker → themeIds) for the inverse lookup
 * used by the chain panel.
 */
function buildThemeIndex(themes: LatticeTheme[]) {
  const themeTickers = new Map<string, Set<string>>()
  const tickerThemes = new Map<string, string[]>()
  for (const t of themes) {
    const tks = new Set<string>()
    for (const tag of t.tags ?? []) {
      if (tag.startsWith('symbol:')) {
        const tk = tag.slice(7).toUpperCase().trim()
        if (tk) tks.add(tk)
      }
    }
    themeTickers.set(t.id, tks)
    for (const tk of tks) {
      if (!tickerThemes.has(tk)) tickerThemes.set(tk, [])
      tickerThemes.get(tk)!.push(t.id)
    }
  }
  return { themeTickers, tickerThemes }
}

const THEME_SEVERITY_COLOR: Record<LatticeTheme['severity'], string> = {
  alert: 'text-red-300 border-red-500/40 bg-red-500/10',
  warn:  'text-amber-300 border-amber-500/40 bg-amber-500/10',
  info:  'text-[var(--color-dim)] border-[var(--color-border)] hover:border-[var(--color-text)]',
}

// 2026-05-19: 4 visual layers, indexed by render_tier (server-computed):
//   held          — innermost yellow (your real money)
//   buy_candidate — orange ring (strongly recommended add/init, signal > 0.40)
//   watchlist     — green ring (existing universe, not buy_candidate)
//   outside       — purple ring (anti-anchoring discovery)
//   external      — faintest, edge of graph (only via 10-K)
// Backward-compat: also accept old tier names (core/adjacent/...) so
// any pre-migration cached graph still renders sensibly.
const TIER_RADIUS: Record<string, number> = {
  // new render_tier values
  held:          90,
  buy_candidate: 180,
  watchlist:     280,
  outside:       340,
  external:      410,
  // legacy fallbacks (old `tier` field, in case render_tier missing)
  core:     90,
  adjacent: 280,
  watching: 280,
  held_unwatched: 310,
}

// Base radius per tier — floor when nothing else applies.
const TIER_NODE_BASE_RADIUS: Record<string, number> = {
  held:          10,
  buy_candidate: 8,
  watchlist:     5,
  outside:       5,
  external:      3,
  // legacy
  core:     8,
  adjacent: 5,
  watching: 4,
  held_unwatched: 7,
}
// Research-depth secondary bump per tier (multiplied by sqrt(n_facts)).
// Kept smaller than the exposure bump so research depth never
// out-shouts actual $ at stake.
const TIER_NODE_FACT_BUMP: Record<string, number> = {
  held:          1.5,
  buy_candidate: 1.5,
  watchlist:     0.8,
  outside:       0,
  external:      0,
  // legacy
  core:     1.5,
  adjacent: 1.0,
  watching: 0.5,
  held_unwatched: 0,
}

// 2026-05-16: SIZE NOW REFLECTS $ EXPOSURE, not research depth.
// Why: when you sit down to make a decision, the question is "where is
// my money?" — not "what have I researched the most?". A 40%-weight
// AAPL position should visually dwarf a deeply-researched but
// 0-position TSM. n_facts still contributes as a small secondary
// bump so tier nesting reads correctly even for unheld tickers.
//
// Formula:
//   exposure_px = sqrt(held_cost / 100) capped at +20px
//     (held_cost in dollars; sqrt softens so $1K → 3.2px and $40K → 20px)
//   facts_px = sqrt(n_facts) × tier_bump (research-depth nudge)
//   total = base[tier] + exposure_px + facts_px
// 2026-05-19: prefer server-computed render_tier; fall back to tier.
function effTier(n: PortfolioGraphNode): string {
  return (n as { render_tier?: string }).render_tier || n.tier
}

function nodeRadius(n: PortfolioGraphNode): number {
  const t = effTier(n)
  const base = TIER_NODE_BASE_RADIUS[t] ?? 6
  const factsBump = TIER_NODE_FACT_BUMP[t] ?? 0
  const factsPx = factsBump * Math.sqrt(Math.max(0, n.n_facts))
  const cost = Math.max(0, n.held_cost ?? 0)
  const exposurePx = Math.min(20, Math.sqrt(cost / 100))
  return base + exposurePx + factsPx
}

const TIER_COLOR: Record<string, string> = {
  // new render_tier values
  held:          '#fbbf24',  // amber-400 — your real money
  buy_candidate: '#fb923c',  // orange-400 — strongly recommended add/init
  watchlist:     '#10b981',  // emerald-500 — your universe
  outside:       '#a78bfa',  // violet-400 — anti-anchoring candidates
  external:      '#52525b',  // zinc-600 — discovery placeholder
  // legacy (fallback when render_tier missing)
  core:     '#fbbf24',
  adjacent: '#10b981',
  watching: '#71717a',
  held_unwatched: '#f87171',  // red-400 — "you own but haven't researched"
}

const EDGE_COLOR: Record<string, string> = {
  spoke:      'rgba(255,255,255,0.15)',
  competitor: 'rgba(248,113,113,0.55)',  // red-400
  customer:   'rgba(96,165,250,0.55)',   // blue-400
  supplier:   'rgba(167,139,250,0.55)',  // violet-400
}


// Quick-pick time-travel options (label → days-ago, null = today/no filter)
const AS_OF_PRESETS: Array<{ label: string; daysAgo: number | null }> = [
  { label: 'today',    daysAgo: null },
  { label: '7d ago',   daysAgo: 7 },
  { label: '30d ago',  daysAgo: 30 },
  { label: '90d ago',  daysAgo: 90 },
]
function daysAgoIso(d: number | null): string | null {
  if (d == null) return null
  const dt = new Date()
  dt.setDate(dt.getDate() - d)
  return dt.toISOString().slice(0, 10)
}

export function PortfolioOnionView({ height = 540 }: { height?: number }) {
  const [asOf, setAsOf] = useState<string | null>(null)
  const [includeExternal, setIncludeExternal] = useState<boolean>(false)
  const q = usePortfolioView(asOf, includeExternal)
  const latticeQ = useLatticeCalls('fin-core')
  const portfolioQ = usePortfolioSummary()
  const { openTicker } = useStockResearch()
  const [selected, setSelected] = useState<string | null>(null)
  const [hopDepth, setHopDepth] = useState<1 | 2 | 3>(1)
  const [showRelations, setShowRelations] = useState<boolean>(false)
  // Lazy multi-hop: fetch chain (incl. non-watchlist neighbors) only
  // when user expands past 1 hop. hop=1 path is fully covered by
  // portfolio_view's edges so we don't refetch at depth 1.
  const chainQ = useChain(selected, hopDepth)
  const [themeFilter, setThemeFilter] = useState<string | null>(null)

  // Theme indexing for ticker-highlight on theme-chip click.
  const { themeTickers } = useMemo(
    () => buildThemeIndex(latticeQ.data?.themes ?? []),
    [latticeQ.data],
  )
  const themeFilterSet = themeFilter ? themeTickers.get(themeFilter) ?? null : null

  // Phase 6: L3 calls as arrows entering the onion. For each call,
  // figure out which watchlist tickers it points at (via claim text
  // or grounds → themes). When fires, frontend draws an arrow from a
  // ring outside `watching` to the ticker node with the call's
  // confidence color (high=emerald, med=amber, low=zinc).
  const callArrows = useMemo(() => {
    const calls = latticeQ.data?.calls ?? []
    const themes = latticeQ.data?.themes ?? []
    if (calls.length === 0) return []
    const watchlistSet = new Set((q.data?.nodes ?? []).map(n => n.id))
    const themesById = new Map(themes.map(t => [t.id, { tags: t.tags ?? [] }]))
    type Arrow = { ticker: string; claim: string; confidence: string; id: string }
    const out: Arrow[] = []
    for (const c of calls) {
      const tickers = extractCallTickers(c, themesById, watchlistSet)
      for (const t of tickers) {
        out.push({
          ticker:     t,
          claim:      c.claim,
          confidence: c.confidence,
          id:         `${c.id}-${t}`,
        })
      }
    }
    return out
  }, [latticeQ.data, q.data])
  const graphRef = useRef<ForceGraphMethods | undefined>(undefined)
  // Track container width. We render the graph only AFTER size is
  // measured (>0 width) to avoid ForceGraph2D's internal
  // translateBy((newW - oldW)/2) stacking up offsets across width
  // changes — that was the root cause of the off-center initial view.
  // Use a callback ref so we attach the observer the instant the div
  // mounts; with the loading-state early-return, a plain useRef +
  // useEffect doesn't see the div on the first effect pass and never
  // re-runs after data loads.
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const roRef = useRef<ResizeObserver | null>(null)
  const containerRef = useCallback((el: HTMLDivElement | null) => {
    roRef.current?.disconnect()
    roRef.current = null
    if (!el) return
    const measure = () => {
      const w = el.clientWidth
      if (w > 0) setSize(prev => (prev && prev.w === w && prev.h === height) ? prev : { w, h: height })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    roRef.current = ro
  }, [height])

  // Onion layout is structural — pin each node with fx/fy on its tier
  // ring. Origin is sim (0,0) which the ForceGraph2D default camera
  // centers on the canvas. We render the graph only after size is
  // measured (see render guard below), so width/height props stay
  // constant from first mount and translateBy stacking is avoided.
  // Adjacent nodes are angularly clustered near their parent_ticker
  // so each spoke reads as a coherent group.
  const graphData = useMemo(() => {
    if (!q.data) return { nodes: [], links: [] }
    // 2026-05-19: bucket by render_tier (server-computed). Falls back
    // to legacy tier so pre-migration cached data still renders.
    const byTier: Record<string, PortfolioGraphNode[]> = {
      held: [], buy_candidate: [], watchlist: [], outside: [], external: [],
    }
    for (const n of q.data.nodes) {
      const t = effTier(n)
      const bucket = t in byTier ? t : 'watchlist'
      byTier[bucket].push(n)
    }
    // Angle layout: held inside, distribute remaining around
    const placed: PortfolioGraphNode[] = []
    const pin = (n: PortfolioGraphNode, r: number, theta: number) => {
      const x = r * Math.cos(theta)
      const y = r * Math.sin(theta)
      placed.push({ ...n, x, y, fx: x, fy: y } as PortfolioGraphNode)
    }
    // Held — innermost, evenly spaced
    byTier.held.forEach((n, i) => {
      const theta = (2 * Math.PI * i) / Math.max(byTier.held.length, 1)
      pin(n, TIER_RADIUS.held, theta)
    })
    // Buy candidate — next ring
    byTier.buy_candidate.forEach((n, i) => {
      const theta = (2 * Math.PI * i) / Math.max(byTier.buy_candidate.length, 1)
      pin(n, TIER_RADIUS.buy_candidate, theta)
    })
    // Watchlist — third ring (consolidates former core/adjacent/watching not held)
    byTier.watchlist.forEach((n, i) => {
      const theta = (2 * Math.PI * i) / Math.max(byTier.watchlist.length, 1)
      pin(n, TIER_RADIUS.watchlist, theta)
    })
    // Outside ring — evenly spaced; no parent relationship, no spoke edge.
    byTier.outside.forEach((n, i) => {
      const theta = (2 * Math.PI * i) / Math.max(byTier.outside.length, 1)
      pin(n, TIER_RADIUS.outside, theta)
    })
    // External ring — only populated when include_external_edges=true.
    // Evenly distributed outside the outside ring; no spoke parent
    // because they're not in any watchlist tier.
    byTier.external.forEach((n, i) => {
      const t = (2 * Math.PI * i) / Math.max(byTier.external.length, 1)
      pin(n, TIER_RADIUS.external, t)
    })
    const links = q.data.edges.map(e => ({
      source: e.source, target: e.target, kind: e.kind, label: e.label,
    }))

    // Lazy multi-hop expansion: when chain endpoint returned external
    // (non-watchlist) entities, pin them just outside the outermost
    // ring and emit dotted edges to their origin. We attach a synthetic
    // tier 'external' so they get their own visual styling. Position
    // angularly clustered near the origin node's angle so the
    // discovery cluster reads as a satellite of the selected ticker.
    const placedIds = new Set(placed.map(n => n.id))
    if (chainQ.data && selected) {
      const origin = placed.find(p => p.id === selected)
      const originAngle = origin
        ? Math.atan2(origin.y ?? 0, origin.x ?? 0)
        : 0
      const externals = chainQ.data.nodes.filter(
        n => (n as { render_tier?: string; tier?: string }).render_tier === 'external'
          || (n as { tier?: string }).tier === 'external')
      const extRadius = TIER_RADIUS.outside + 70
      externals.forEach((n, i) => {
        if (placedIds.has(n.id)) return
        const spread = Math.PI / 8
        const theta = externals.length === 1
          ? originAngle
          : originAngle - spread + (2 * spread * i) / Math.max(externals.length - 1, 1)
        const x = extRadius * Math.cos(theta)
        const y = extRadius * Math.sin(theta)
        placed.push({
          id:               n.id,
          tier:             'external' as any,
          parent:           null,
          n_facts:          0,
          stale_days:       null,
          is_stale:         false,
          fresh_signal_24h: false,
          n_active_theses:  0,
          thesis_status:    null,
          n_unresolved_disagreements: 0,
          is_conflicted:    false,
          importance:       1,
          // Extra fields for label rendering
          x, y, fx: x, fy: y,
        } as PortfolioGraphNode & { x: number; y: number; fx: number; fy: number })
        placedIds.add(n.id)
      })
      // Edges from chain — only emit ones that touch externals (the
      // in-watchlist edges are already provided by portfolio_view).
      for (const e of chainQ.data.edges) {
        const srcExt = !placedIds.has(e.source)
        const tgtExt = chainQ.data.nodes.find(n => n.id === e.target)?.tier === 'external'
        if (tgtExt || srcExt) {
          links.push({
            source: e.source,
            target: e.target,
            kind:   e.kind,
            label:  `chain hop ${e.hop}: ${e.source} → ${e.target}`,
          })
        }
      }
    }

    return { nodes: placed, links }
  }, [q.data, chainQ.data, selected])

  // Nodes are pinned via fx/fy. Disable simulation forces so they
  // don't try to mutate fixed positions each tick.
  useEffect(() => {
    const g = graphRef.current
    if (!g) return
    const anyG: any = g
    anyG.d3Force?.('charge', null)
    anyG.d3Force?.('center', null)
    anyG.d3Force?.('link')?.strength(0)
  }, [graphData])

  // BFS the chain from `selected` up to `hopDepth` hops. Returns:
  //   linkedNodeIds  — set of nodes to keep bright (vs dim)
  //   hopOf          — origin = 0, direct neighbors = 1, etc.
  // Spoke edges are also walked since Adjacent ↔ parent is a real
  // relation; otherwise chain stops at the watchlist boundary.
  // When a theme filter is active AND no node is selected, the theme
  // set acts as the "linked" group (no chain edges, just dimming).
  const { linkedNodeIds, hopOf } = useMemo(() => {
    const emptyIds = new Set<string>()
    const emptyHop = new Map<string, number>()
    if (!selected && themeFilterSet) {
      return { linkedNodeIds: new Set(themeFilterSet), hopOf: emptyHop }
    }
    if (!selected || !q.data) return { linkedNodeIds: emptyIds, hopOf: emptyHop }
    // Build undirected adjacency from edges
    const adj = new Map<string, string[]>()
    const push = (a: string, b: string) => {
      if (!adj.has(a)) adj.set(a, [])
      adj.get(a)!.push(b)
    }
    for (const e of q.data.edges) { push(e.source, e.target); push(e.target, e.source) }
    // Also include chain endpoint edges (these touch externals and
    // shouldn't dim the discovery nodes)
    for (const e of chainQ.data?.edges ?? []) { push(e.source, e.target); push(e.target, e.source) }
    // BFS
    const hops = new Map<string, number>([[selected, 0]])
    const queue: string[] = [selected]
    while (queue.length) {
      const cur = queue.shift()!
      const d = hops.get(cur)!
      if (d >= hopDepth) continue
      for (const nb of adj.get(cur) ?? []) {
        if (!hops.has(nb)) {
          hops.set(nb, d + 1)
          queue.push(nb)
        }
      }
    }
    return { linkedNodeIds: new Set(hops.keys()), hopOf: hops }
  }, [selected, hopDepth, q.data, chainQ.data])

  if (q.isLoading) {
    return (
      <div className="flex items-center justify-center h-[200px] text-[var(--color-dim)] text-[12px]">
        <Loader2 size={16} className="animate-spin mr-2" /> loading portfolio graph…
      </div>
    )
  }
  if (!q.data || q.data.n_nodes === 0) {
    return (
      <div className="text-[12px] text-[var(--color-dim)] italic p-4">
        Watchlist 空 — 加 ticker 到 Core 后图才有内容。
      </div>
    )
  }

  // Chain panel pinned to right-0 width 380 (max 40%) when a node is
  // selected — push the top-right toolbar left by that amount so the
  // two don't collide on the same pixels. 8 px gap matches `right-2`.
  // 380 is the panel's hard width from line below; 40% covers narrower
  // viewports where it scales.
  const CHAIN_PANEL_W = 380
  const toolbarRightOffset = selected
    ? `calc(min(${CHAIN_PANEL_W}px, 40%) + 8px)`
    : '0.5rem' // = right-2

  return (
    <div ref={containerRef} className="relative" style={{ height }}>
      {/* Top-right controls (time-travel, edges toggle) */}
      <div
        className="absolute top-2 z-30 flex items-center gap-2"
        style={{ right: toolbarRightOffset }}
      >
        {/* Time-travel picker — per plan §5 Pillar 1 enhancement #2.
            Quick presets (today / 7d / 30d / 90d) + custom date input.
            Backend filters facts/signals/theses/disagreements/positions
            by timestamp ≤ as_of. Watchlist membership filtered by
            added_at ≤ as_of (drops/demotes not yet replayed). */}
        <div className="flex items-center gap-0.5 text-[10px] border border-[var(--color-border)] bg-[var(--color-bg)]/80 rounded overflow-hidden">
          <Clock size={11} className="ml-1 text-[var(--color-dim)]" />
          {AS_OF_PRESETS.map(p => {
            const iso = daysAgoIso(p.daysAgo)
            const isSelected = asOf === iso
            return (
              <button
                key={p.label}
                onClick={() => setAsOf(iso)}
                className={`px-1.5 py-1 ${
                  isSelected
                    ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                    : 'text-[var(--color-dim)] hover:text-[var(--color-text)]'
                }`}
                title={iso ? `Rewind to ${iso} end-of-day UTC` : 'Show current state'}
              >{p.label}</button>
            )
          })}
          {/* Custom date input — shown small after presets */}
          <input
            type="date"
            value={asOf ?? ''}
            onChange={e => setAsOf(e.target.value || null)}
            className="bg-transparent border-l border-[var(--color-border)] px-1 py-0.5 text-[10px] text-[var(--color-dim)] w-[110px]"
            title="Custom as_of date"
          />
        </div>
        <button
          onClick={() => setShowRelations(s => !s)}
          className={`text-[10px] px-2 py-1 rounded border flex items-center gap-1 ${
            showRelations
              ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
              : 'border-[var(--color-border)] hover:border-[var(--color-text)] text-[var(--color-dim)]'
          }`}
          title="Toggle 10-K relation edges (default hidden to avoid hairball)"
        >
          {showRelations ? <Eye size={11} /> : <EyeOff size={11} />}
          {showRelations ? 'edges shown' : 'edges hidden'}
        </button>
        {/* Include-external: show 10-K edges to entities OUTSIDE the
            user's watchlist (Skyworks, Foxconn et al). Default off
            because it expands the node count; on for discovery. */}
        <button
          onClick={() => setIncludeExternal(v => !v)}
          className={`text-[10px] px-2 py-1 rounded border flex items-center gap-1 ${
            includeExternal
              ? 'border-violet-500/60 bg-violet-500/10 text-violet-300'
              : 'border-[var(--color-border)] hover:border-[var(--color-text)] text-[var(--color-dim)]'
          }`}
          title={
            includeExternal
              ? '关：只显示 watchlist 内部边'
              : '开：把 10-K 提到的外部公司也画出来 (discovery 用，可能很乱)'
          }
        >
          {includeExternal ? '🌐 + external' : '🔒 internal only'}
        </button>
        {/* No separate deselect — panel's own ✕ in header dismisses selection */}
      </div>

      {/* Top-left hop controls — only visible when something is selected.
          Positioned away from the chain panel so they don't get covered. */}
      {selected && (
        <div className="absolute top-2 left-2 z-30 flex items-center gap-0.5 text-[10px] border border-[var(--color-border)] bg-[var(--color-bg)]/80 rounded">
          <button
            onClick={() => setHopDepth(d => Math.max(1, d - 1) as 1 | 2 | 3)}
            disabled={hopDepth === 1}
            className="px-2 py-1 hover:bg-[var(--color-panel)] disabled:opacity-30 disabled:cursor-not-allowed"
            title="Shrink chain by one hop"
          >−</button>
          <span className="px-1 text-[var(--color-dim)]">{hopDepth}-hop chain</span>
          <button
            onClick={() => setHopDepth(d => Math.min(3, d + 1) as 1 | 2 | 3)}
            disabled={hopDepth === 3}
            className="px-2 py-1 hover:bg-[var(--color-panel)] disabled:opacity-30 disabled:cursor-not-allowed"
            title="Extend chain by one hop (1=direct, 2=neighbors-of, 3=max)"
          >+</button>
        </div>
      )}

      {/* Lattice theme strip — Phase 6 integration. Hidden when a node
          is selected (selection's chain takes priority). Each chip
          shows L2 theme title + severity. Click → highlight tickers
          tagged with that theme; click active → clear. Themes with
          zero matched tickers are hidden (less noise). */}
      {!selected && (latticeQ.data?.themes ?? []).length > 0 && (
        <div className="absolute top-2 left-2 z-20 flex items-center gap-1 max-w-[55%] flex-wrap text-[10px]">
          <Layers size={11} className="text-[var(--color-dim)] flex-shrink-0" />
          <span className="text-[var(--color-dim)] mr-1 flex-shrink-0">L2 themes:</span>
          {(latticeQ.data?.themes ?? []).map(t => {
            const ntickers = (themeTickers.get(t.id) ?? new Set()).size
            if (ntickers === 0) return null
            const isActive = themeFilter === t.id
            return (
              <button
                key={t.id}
                onClick={() => setThemeFilter(isActive ? null : t.id)}
                className={`px-1.5 py-0.5 rounded border ${
                  isActive
                    ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                    : THEME_SEVERITY_COLOR[t.severity]
                }`}
                title={`${t.title} · ${ntickers} ticker${ntickers === 1 ? '' : 's'} tagged`}
              >
                {t.title}
                <span className="ml-1 opacity-60">{ntickers}</span>
              </button>
            )
          })}
          {themeFilter && (
            <button
              onClick={() => setThemeFilter(null)}
              className="text-[var(--color-dim)] hover:text-[var(--color-text)] ml-1"
              title="Clear theme filter"
            >✕</button>
          )}
        </div>
      )}

      {/* Historical mode banner — replaces nothing; sits below top toolbar */}
      {q.data?.is_historical && (
        <div className="absolute top-12 left-1/2 -translate-x-1/2 z-20 px-3 py-1 rounded border border-amber-500/50 bg-amber-500/10 text-amber-300 text-[11px] flex items-center gap-2">
          <Clock size={11} />
          <span>viewing as of <b>{q.data.as_of?.slice(0, 10)}</b> · tiers replayed from audit · facts/signals/theses filtered by timestamp</span>
        </div>
      )}

      {/* Bottom legend */}
      <div className="absolute bottom-2 left-2 z-10 text-[9px] text-[var(--color-dim)] space-y-0.5 bg-[var(--color-bg)]/80 px-2 py-1 rounded">
        {/* 2026-05-19: legend by render_tier (visual layer) */}
        <div className="flex items-center gap-1" title="你持有 — 真钱在里面">
          <span style={{color: TIER_COLOR.held}}>●</span> Held
          ({q.data.nodes.filter(n => effTier(n) === 'held').length})
        </div>
        {q.data.nodes.filter(n => effTier(n) === 'buy_candidate').length > 0 && (
          <div className="flex items-center gap-1" title="未持有但综合信号 > 0.40 — 强烈推荐增持/初仓">
            <span style={{color: TIER_COLOR.buy_candidate}}>●</span> 推荐增持
            ({q.data.nodes.filter(n => effTier(n) === 'buy_candidate').length})
          </div>
        )}
        <div className="flex items-center gap-1" title="你的 watchlist 但暂无强增持信号">
          <span style={{color: TIER_COLOR.watchlist}}>●</span> Watchlist
          ({q.data.nodes.filter(n => effTier(n) === 'watchlist').length})
        </div>
        {q.data.nodes.filter(n => effTier(n) === 'outside').length > 0 && (
          <div className="flex items-center gap-1" title="不在 watchlist 但近期信号密集 — anti-anchoring 发现">
            <span style={{color: TIER_COLOR.outside}}>●</span> Outside
            ({q.data.nodes.filter(n => effTier(n) === 'outside').length})
          </div>
        )}
        {q.data.nodes.some(n => n.is_conflicted) && (
          <div className="flex items-center gap-1 text-red-300">
            <span>◯</span> conflicted ({q.data.nodes.filter(n => n.is_conflicted).length})
          </div>
        )}
        {showRelations && (
          <>
            <div className="flex items-center gap-1"><span style={{color: EDGE_COLOR.competitor}}>—</span> competitor</div>
            <div className="flex items-center gap-1"><span style={{color: EDGE_COLOR.customer}}>—</span> customer</div>
            <div className="flex items-center gap-1"><span style={{color: EDGE_COLOR.supplier}}>—</span> supplier</div>
          </>
        )}
        <div className="pt-0.5 mt-0.5 border-t border-[var(--color-border)]/40 text-[8px] italic opacity-70">
          ⌘/Ctrl + scroll = zoom · drag = pan
        </div>
      </div>

      {size && <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        width={size.w}
        height={size.h}
        backgroundColor="transparent"
        nodeRelSize={1}
        cooldownTicks={150}
        d3VelocityDecay={0.4}
        // Interaction policy (per user 2026-05-11):
        // · plain wheel / trackpad scroll → page scroll, NOT zoom
        //   (otherwise trackpad滑动会被图抢走)
        // · ctrl/cmd + wheel → zoom the graph
        // · drag (no modifier) → pan
        enableZoomInteraction={(ev: MouseEvent) => ev.ctrlKey || ev.metaKey}
        // Ring guides + ME marker, drawn in sim coords so they always
        // align with node positions (regardless of zoom/pan).
        onRenderFramePre={(ctx, scale) => {
          ctx.save()
          for (const [tier, r] of Object.entries(TIER_RADIUS)) {
            ctx.beginPath()
            ctx.arc(0, 0, r, 0, 2 * Math.PI)
            ctx.strokeStyle = 'rgba(148,163,184,0.18)'
            ctx.lineWidth = 0.5 / scale
            ctx.setLineDash([2 / scale, 4 / scale])
            ctx.stroke()
            ctx.setLineDash([])
            ctx.fillStyle = 'rgba(148,163,184,0.55)'
            ctx.font = `${8 / scale}px ui-monospace,monospace`
            ctx.textAlign = 'left'
            ctx.textBaseline = 'middle'
            ctx.fillText(tier, r + 4 / scale, -3 / scale)
          }
          // ── L3 call arrows entering the onion ────────────────────
          // Each call's arrow originates from a point just outside the
          // outermost populated ring and points inward toward the
          // referenced ticker node. Color encodes confidence.
          if (callArrows.length > 0) {
            const outerR = (graphData.nodes as PortfolioGraphNode[]).some(n => effTier(n) === 'outside')
              ? TIER_RADIUS.outside + 30
              : TIER_RADIUS.adjacent + 30
            const nodeByTicker = new Map<string, PortfolioGraphNode & {x?:number; y?:number}>()
            for (const n of graphData.nodes as Array<PortfolioGraphNode & {x?:number;y?:number}>) {
              nodeByTicker.set(n.id, n)
            }
            for (const a of callArrows) {
              const target = nodeByTicker.get(a.ticker)
              if (!target || target.x == null || target.y == null) continue
              // Project from target outward to origin/2 radius source
              const len = Math.sqrt(target.x * target.x + target.y * target.y) || 1
              const sx = (target.x / len) * outerR
              const sy = (target.y / len) * outerR
              const color = a.confidence === 'high'   ? '#34d399'
                          : a.confidence === 'medium' ? '#fbbf24'
                          : '#94a3b8'
              ctx.strokeStyle = color
              ctx.fillStyle = color
              ctx.lineWidth = 1.2 / scale
              // Line from outer to a bit before node
              const stop = 0.85   // stop before node radius
              ctx.beginPath()
              ctx.moveTo(sx, sy)
              ctx.lineTo(sx + (target.x - sx) * stop, sy + (target.y - sy) * stop)
              ctx.stroke()
              // Arrowhead
              const tipX = sx + (target.x - sx) * stop
              const tipY = sy + (target.y - sy) * stop
              const ang = Math.atan2(target.y - sy, target.x - sx)
              const ah = 6 / scale
              ctx.beginPath()
              ctx.moveTo(tipX, tipY)
              ctx.lineTo(tipX - ah * Math.cos(ang - Math.PI / 6),
                         tipY - ah * Math.sin(ang - Math.PI / 6))
              ctx.lineTo(tipX - ah * Math.cos(ang + Math.PI / 6),
                         tipY - ah * Math.sin(ang + Math.PI / 6))
              ctx.closePath()
              ctx.fill()
              // Small "L3" tag near source
              ctx.font = `${7 / scale}px ui-monospace,monospace`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'middle'
              ctx.fillText('L3', sx, sy)
            }
          }

          // ── ME center node ───────────────────────────────────────
          // Per plan §5 Pillar 1: "Center ⊙ ME node showing portfolio
          // summary (total value / 90d vs SPY / sector mix)".
          // Renders as a small filled-circle anchor with multi-line
          // stats labeled below it. Each line falls back to a
          // placeholder when data isn't loaded or no positions exist.
          const p = portfolioQ.data
          const totalValStr = p && p.total_value > 0
            ? `$${(p.total_value / 1000).toFixed(1)}k`
            : 'no positions'
          const totalPnlStr = p && p.total_value > 0
            ? `${p.unrealized_pct >= 0 ? '+' : ''}${p.unrealized_pct.toFixed(1)}%`
            : null
          const vs90d = p?.vs_benchmark?.windows?.['90d']?.benchmark_pct ?? null
          const vsBenchStr = vs90d != null
            ? `SPY 90d: ${vs90d >= 0 ? '+' : ''}${vs90d.toFixed(1)}%`
            : null
          // Top 3 sectors stacked (plan says "sector mix", plural).
          // Each rendered on its own line so the user sees diversification.
          const topSectors = (p?.by_sector ?? []).slice(0, 3)

          // ME center scales with zoom like every other node — sizes
          // and positions live in SIM coords (no /scale division).
          // Border stroke + tiny anchor dot keep their /scale so they
          // stay crisp at high zoom; the disc + text scale with view.
          const nSectorLines = topSectors.length
          const baseR = 36
          const meR = baseR + Math.max(0, nSectorLines - 1) * 4
          ctx.beginPath()
          ctx.arc(0, 0, meR, 0, 2 * Math.PI)
          ctx.fillStyle = 'rgba(15,23,42,0.65)'   // slate-900 / 65%
          ctx.fill()
          ctx.strokeStyle = 'rgba(34,211,238,0.55)'
          ctx.lineWidth = 1 / scale
          ctx.stroke()

          // Small ME anchor dot at exact origin (stays crisp at any zoom)
          ctx.beginPath()
          ctx.arc(0, 0, 2.5 / scale, 0, 2 * Math.PI)
          ctx.fillStyle = 'rgba(34,211,238,0.95)'
          ctx.fill()

          // Stacked text — sim coords so the whole ME block scales with
          // the disc when user ⌘/Ctrl+scrolls in.
          ctx.fillStyle = 'rgba(34,211,238,1)'
          ctx.font = `bold 9px ui-monospace,monospace`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText('ME', 0, -18)

          ctx.font = `8px ui-monospace,monospace`
          ctx.fillStyle = 'rgba(245,245,245,0.95)'
          ctx.fillText(totalValStr, 0, -8)

          if (totalPnlStr) {
            ctx.fillStyle = p!.unrealized_pct >= 0 ? '#34d399' : '#f87171'
            ctx.fillText(totalPnlStr, 0, 0)
          }
          if (vsBenchStr) {
            ctx.fillStyle = 'rgba(148,163,184,0.9)'
            ctx.font = `7px ui-monospace,monospace`
            ctx.fillText(vsBenchStr, 0, 9)
          }
          // Top 3 sector mix lines
          ctx.fillStyle = 'rgba(148,163,184,0.9)'
          ctx.font = `7px ui-monospace,monospace`
          topSectors.forEach((s, i) => {
            const label = `${s.sector.slice(0, 12)}: ${s.pct.toFixed(0)}%`
            ctx.fillText(label, 0, 18 + i * 8)
          })
          ctx.restore()
        }}
        // Node rendering — radius by tier, dim if selection active and not in linked set
        nodeCanvasObject={(node, ctx, scale) => {
          const n = node as PortfolioGraphNode & { x?: number; y?: number }
          const r = nodeRadius(n)
          const hasFilter = !!(selected || themeFilterSet)
          const dim = hasFilter && !linkedNodeIds.has(n.id)
          ctx.globalAlpha = dim ? 0.18 : 1.0
          // Pulse ring for fresh signal
          if (n.fresh_signal_24h && !dim) {
            ctx.beginPath()
            ctx.arc(n.x ?? 0, n.y ?? 0, r + 4, 0, 2 * Math.PI)
            ctx.fillStyle = (TIER_COLOR[effTier(n)] || TIER_COLOR.watchlist) + '33'    // alpha 20%
            ctx.fill()
          }
          // Earnings catalyst glow — ticker reports within 5d. Drawn
          // BEFORE the main fill so the ring sits behind the dot and
          // doesn't clip the label. Cyan distinguishes from the
          // fresh-signal pulse (which uses the tier color).
          const ed = n.next_earnings_days
          if (typeof ed === 'number' && ed >= 0 && ed <= 5 && !dim) {
            const pulse = 5 + (5 - ed) * 0.8   // closer = thicker ring
            ctx.beginPath()
            ctx.arc(n.x ?? 0, n.y ?? 0, r + pulse, 0, 2 * Math.PI)
            ctx.strokeStyle = '#22d3ee'       // cyan-400
            ctx.lineWidth = 2 / scale
            ctx.globalAlpha = 0.7
            ctx.stroke()
            ctx.globalAlpha = dim ? 0.18 : 1.0
          }
          // Main circle
          ctx.beginPath()
          ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI)
          ctx.fillStyle = TIER_COLOR[effTier(n)] || TIER_COLOR.watchlist
          ctx.fill()
          // Border priority: selected (white) > conflicted (red) > stale (amber).
          // Conflict ring signals unresolved signal_disagreements per
          // plan §5 Pillar 1 enhancement #4.
          if (selected === n.id) {
            ctx.strokeStyle = '#fff'
            ctx.lineWidth = 2 / scale
            ctx.stroke()
          } else if (n.is_conflicted && !dim) {
            // Outer red ring; inner stale ring if also stale
            ctx.strokeStyle = '#ef4444'   // red-500
            ctx.lineWidth = 2 / scale
            ctx.stroke()
            if (n.is_stale) {
              ctx.beginPath()
              ctx.arc(n.x ?? 0, n.y ?? 0, r - 2.5 / scale, 0, 2 * Math.PI)
              ctx.strokeStyle = '#f59e0b'
              ctx.lineWidth = 1 / scale
              ctx.stroke()
            }
          } else if (n.is_stale && !dim) {
            ctx.strokeStyle = '#f59e0b'
            ctx.lineWidth = 1.5 / scale
            ctx.stroke()
          } else if (!dim && (n.importance ?? 1) >= 2) {
            // Priority watchlist entry — soft white outer ring drawn
            // just outside the fill so it visually separates from the
            // tier color (gold-on-gold would be invisible).
            ctx.beginPath()
            ctx.arc(n.x ?? 0, n.y ?? 0, r + 2 / scale, 0, 2 * Math.PI)
            ctx.strokeStyle = 'rgba(255,255,255,0.7)'
            ctx.lineWidth = 1.5 / scale
            ctx.stroke()
          }
          // Label — external nodes show the entity name (stripped of
          // the "name:" prefix). Watchlist nodes show ticker.
          const fontPx = Math.max(7 / scale, 4)
          ctx.font = `${fontPx}px ui-monospace,monospace`
          ctx.fillStyle = dim ? '#71717a' : '#f5f5f5'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          const label = n.id.startsWith('name:')
            ? n.id.slice(5).split(/[,\s]/)[0]   // first word of entity name
            : n.id
          ctx.fillText(label, n.x ?? 0, (n.y ?? 0) + r + 1)
          ctx.globalAlpha = 1.0
        }}
        // Hit detection — must paint an invisible hit-zone matching
        // the visible node radius (`r` from nodeRadius), otherwise
        // react-force-graph defaults to nodeRelSize × √nodeVal = 1 px
        // and clicks miss everything except the exact center pixel.
        nodePointerAreaPaint={(node, color, ctx) => {
          const n = node as PortfolioGraphNode & { x?: number; y?: number }
          const r = nodeRadius(n) + 4   // small pad for easier clicking
          ctx.fillStyle = color
          ctx.beginPath()
          ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, 2 * Math.PI)
          ctx.fill()
        }}
        // Link rendering — kind-specific color, hidden unless showRelations
        // or one of its endpoints is selected. Spoke always shown.
        linkCanvasObject={(link, ctx, scale) => {
          const l = link as PortfolioGraphEdge & {
            source: { x?: number; y?: number; id: string }
            target: { x?: number; y?: number; id: string }
          }
          const src = l.source
          const tgt = l.target
          if (src.x == null || tgt.x == null) return
          const isSpoke = l.kind === 'spoke'
          // Edge is "in chain" if BOTH endpoints are within hopDepth.
          // The hop level of the edge = max(hopOf src, hopOf tgt).
          const srcHop = hopOf.get(src.id)
          const tgtHop = hopOf.get(tgt.id)
          const inChain = selected != null
            && srcHop !== undefined && tgtHop !== undefined
          const edgeHop = inChain
            ? Math.max(srcHop!, tgtHop!)
            : undefined
          // Hide non-spoke unless toggled OR in chain.
          if (!isSpoke && !showRelations && !inChain) return
          // Dim if selection active and edge isn't in chain
          const dim = selected && !inChain
          ctx.globalAlpha = dim ? 0.08 : (inChain ? 0.95 : 0.6)
          ctx.beginPath()
          ctx.moveTo(src.x, src.y ?? 0)
          ctx.lineTo(tgt.x, tgt.y ?? 0)
          ctx.strokeStyle = EDGE_COLOR[l.kind] || EDGE_COLOR.spoke
          ctx.lineWidth = (inChain ? 1.5 : 0.5) / scale
          // Per plan §5 Pillar 1 enhancement #1: hop 1 solid, hop 2 dashed,
          // hop 3 dotted. edgeHop=1 means one endpoint is origin (hop 0)
          // and the other is at hop 1; that's the "direct" edge.
          if (edgeHop === 2) ctx.setLineDash([4 / scale, 3 / scale])
          else if (edgeHop === 3) ctx.setLineDash([1 / scale, 3 / scale])
          else ctx.setLineDash([])
          ctx.stroke()
          ctx.setLineDash([])
          ctx.globalAlpha = 1.0
        }}
        linkCanvasObjectMode={() => 'replace'}
        // Click handlers
        onNodeClick={(node) => {
          const n = node as PortfolioGraphNode
          if (selected === n.id) {
            // Second click — open drawer for full detail
            openTicker(n.id)
          } else {
            setSelected(n.id)
            setHopDepth(1)        // start fresh; user can expand via +/−
            setThemeFilter(null)  // selection supersedes theme filter
          }
        }}
        onBackgroundClick={() => { setSelected(null); setHopDepth(1) }}
        // Drag enabled by default; node fix on drag
        onNodeDragEnd={(node) => {
          const n = node as any
          n.fx = n.x
          n.fy = n.y
        }}
      />}

      {/* Chain panel — absolute overlay on the right when a node is
          selected. Doesn't resize the canvas (which would re-trigger
          ForceGraph2D's translateBy stale-state bug). User can dismiss
          via the X button or click empty canvas to deselect. */}
      {selected && (
        <div
          className="absolute top-0 right-0 bottom-0 z-20"
          style={{ width: 380, maxWidth: '40%' }}
        >
          <NodeChainPanel
            ticker={selected}
            onClose={() => { setSelected(null); setHopDepth(1) }}
            onOpenFullDetail={() => openTicker(selected)}
            asOf={asOf}
          />
        </div>
      )}
    </div>
  )
}
