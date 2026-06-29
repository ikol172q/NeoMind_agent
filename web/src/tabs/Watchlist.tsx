/**
 * Watchlist — hub-and-spoke fundamental research.
 *
 * As of 2026-05-08 this is no longer a top-level tab; it lives at the
 * top of the Strategies tab via <WatchlistSection> so the user has a
 * single workspace ("零零散散的不好集中看" — user feedback).
 * The legacy <WatchlistTab> wrapper is kept for any deep-link bookmark
 * that may still hit it, but is removed from App.tsx's nav array.
 *
 * Three concentric tiers:
 *   ★ Core      ≤10 names, weekly review prompted (red badge if
 *                last_reviewed_at older than 14 days)
 *   ◐ Adjacent  10-50 names reached via a core's competitor /
 *                customer / supplier from stock_anchored_facts.
 *                Linked back to parent_ticker.
 *   · Watching  50-200 names, alerts only.
 *
 * Plus an "outside-ring" anti-anchoring section: high-confluence
 * scanner signals (≥2 sources, last 14d) that are NOT in any tier —
 * counter-current to confirmation bias.
 *
 * UI is intentionally read-heavy: clicking a ticker opens the
 * existing StockResearchDrawer, where the full "promote / demote /
 * expand from 10-K" actions live. This component shows STATE
 * (what's in each tier, what's stale, what needs review); the drawer
 * shows ACTIONS (open one ticker, edit it, expand it).
 */
import { useEffect, useState } from 'react'
import { useStockResearch } from '@/components/research/StockResearchContext'
import {
  useWatchlistTiers,
  useWatchlistOutsideRing,
  useWatchlistRemoveTier,
  useCrossStructure,
  type WatchlistEntry,
  type WatchlistTier,
  type OutsideRingCandidate,
  type CrossStructure,
  type CrossEdge,
  type SharedEntity,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { PortfolioOnionView } from '@/components/widgets/PortfolioOnionView'
import { AgentPlaceholder } from '@/components/research/AgentSummary'
import { PriceMovesPanel } from '@/components/research/PriceMovesPanel'
import { useWhaleResearch } from '@/components/research/WhaleResearchContext'
import {
  AlertTriangle, Clock, Compass, Star, CircleDot, Eye, X, ChevronDown,
  ChevronRight, ArrowRight, List, Network,
} from 'lucide-react'

const TIER_META: Record<WatchlistTier, { label: string; icon: typeof Star; color: string; reviewWindowDays: number }> = {
  core:     { label: 'Core',     icon: Star,       color: 'text-amber-300 border-amber-500/40 bg-amber-500/10',     reviewWindowDays: 14 },
  adjacent: { label: 'Adjacent', icon: CircleDot,  color: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10', reviewWindowDays: 30 },
  watching: { label: 'Watching', icon: Eye,        color: 'text-[var(--color-dim)] border-[var(--color-border)]',     reviewWindowDays: 90 },
}

/**
 * WatchlistSection — embedded form, no outer scroll wrapper. Used at
 * the top of the Strategies tab. Defaults to expanded since this is
 * now the primary surface; user can collapse via the section header
 * to focus on the strategy catalog.
 */
export function WatchlistSection({ onAddLot }: { onAddLot?: () => void } = {}) {
  const tiersQ = useWatchlistTiers()
  const outsideQ = useWatchlistOutsideRing()
  const removeMu = useWatchlistRemoveTier()
  const { openTicker } = useStockResearch()

  // Persist collapse state — once a user manually collapses, we
  // remember that choice across page reloads.
  const [collapsed, setCollapsed] = useState<boolean>(() =>
    typeof window !== 'undefined'
      && localStorage.getItem('strategies.watchlist.collapsed') === '1'
  )
  // View mode: list (default, mobile-friendly) | onion (Phase 5 viz).
  // Force list mode below 768px (iPhone via Tailscale) — the onion
  // canvas is unusable on narrow viewports.
  const [isNarrow, setIsNarrow] = useState<boolean>(() =>
    typeof window !== 'undefined' && window.innerWidth < 768
  )
  useEffect(() => {
    const onResize = () => setIsNarrow(window.innerWidth < 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  const [savedViewMode, setSavedViewMode] = useState<'list' | 'onion'>(() => {
    if (typeof window === 'undefined') return 'list'
    return (localStorage.getItem('strategies.watchlist.view') as 'list' | 'onion') || 'list'
  })
  const viewMode: 'list' | 'onion' = isNarrow ? 'list' : savedViewMode
  function setView(m: 'list' | 'onion') {
    setSavedViewMode(m)
    try { localStorage.setItem('strategies.watchlist.view', m) } catch {}
  }
  function toggle() {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem('strategies.watchlist.collapsed', next ? '1' : '0') } catch {}
  }

  const tiers = tiersQ.data?.tiers
  const totals = tiersQ.data?.totals

  // Stale = core or adjacent ticker where days_since_review > tier review window
  const staleEntries = (tier: WatchlistTier): WatchlistEntry[] => {
    const win = TIER_META[tier].reviewWindowDays
    return (tiers?.[tier] ?? []).filter(e =>
      e.days_since_review === null || e.days_since_review > win)
  }

  // Compact summary line shown in the section header so collapsed
  // state still shows useful state-at-a-glance.
  const summaryChip = (
    <span className="text-[11px] text-[var(--color-dim)] flex items-center gap-2 flex-wrap">
      <span className="text-amber-300">★ {totals?.core ?? 0}</span>
      <span className="text-emerald-300">◐ {totals?.adjacent ?? 0}</span>
      <span className="text-[var(--color-dim)]">👁 {totals?.watching ?? 0}</span>
      {outsideQ.data?.candidates && outsideQ.data.candidates.length > 0 && (
        <span className="text-violet-300">🧭 {outsideQ.data.candidates.length}</span>
      )}
      {(staleEntries('core').length + staleEntries('adjacent').length) > 0 && (
        <span className="text-amber-300 flex items-center gap-1">
          <AlertTriangle size={10} />
          {staleEntries('core').length + staleEntries('adjacent').length} 待复盘
        </span>
      )}
    </span>
  )

  return (
    <div className="space-y-3 mb-3">
      {/* Section header — collapse toggle + add-position. This is the
          single unified "我的组合" workspace: holdings + watchlist in one
          onion (the separate "我的持仓" summary widget was removed). */}
      <div className="w-full flex items-center gap-2">
        <button
          onClick={toggle}
          className="flex-1 flex items-center gap-2 px-3 py-2 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 bg-[var(--color-panel)]/60 text-left group"
          title={collapsed ? '展开' : '折叠'}
        >
          {collapsed
            ? <ChevronRight size={14} className="text-[var(--color-dim)] group-hover:text-[var(--color-accent)] flex-shrink-0" />
            : <ChevronDown size={14} className="text-[var(--color-dim)] group-hover:text-[var(--color-accent)] flex-shrink-0" />}
          <Star size={14} className="text-amber-300 flex-shrink-0" />
          <span className="text-[12px] font-semibold text-[var(--color-text)] flex-shrink-0">我的组合 · 持仓 + watchlist</span>
          <span className="text-[10px] italic text-[var(--color-dim)] flex-shrink-0">
            · 点 ticker 打开详细分析
          </span>
          <span className="ml-auto">{summaryChip}</span>
        </button>
        {onAddLot && (
          <button
            onClick={onAddLot}
            className="flex-shrink-0 px-3 py-2 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-accent)]/60 text-[11px]"
            title="加一笔持仓"
          >
            + 持仓
          </button>
        )}
      </div>

      {!collapsed && (
        <>
          {/* Stale-thesis banner — only if any core/adjacent overdue */}
          {(staleEntries('core').length > 0 || staleEntries('adjacent').length > 0) && (
            <div className="rounded border border-amber-500/40 bg-amber-500/5 p-2.5 text-[12px]">
              <div className="flex items-center gap-1.5 text-amber-300 font-semibold mb-1">
                <AlertTriangle size={13} /> 待复盘 thesis
              </div>
              <div className="text-[11px] text-[var(--color-text)]/80">
                {staleEntries('core').length > 0 && (
                  <div>
                    Core 里 <b>{staleEntries('core').length}</b> 只 ≥ 14 天没复盘 ·{' '}
                    {staleEntries('core').map(e => (
                      <TickerChip key={e.ticker} ticker={e.ticker} onOpen={openTicker} variant="amber" />
                    ))}
                  </div>
                )}
                {staleEntries('adjacent').length > 0 && (
                  <div className="mt-1">
                    Adjacent 里 <b>{staleEntries('adjacent').length}</b> 只 ≥ 30 天没复盘 ·{' '}
                    {staleEntries('adjacent').slice(0, 8).map(e => (
                      <TickerChip key={e.ticker} ticker={e.ticker} onOpen={openTicker} variant="amber" />
                    ))}
                    {staleEntries('adjacent').length > 8 && (
                      <span className="italic"> + {staleEntries('adjacent').length - 8} 更多</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {tiersQ.isLoading && (
            <div className="text-[11px] italic text-[var(--color-dim)]">loading…</div>
          )}

          {/* View toggle: List (default) | Onion (Phase 5 viz) */}
          <div className="flex items-center gap-1 text-[10px]">
            <span className="text-[var(--color-dim)] mr-1">view:</span>
            <button
              onClick={() => setView('list')}
              className={`px-2 py-1 rounded border flex items-center gap-1 ${
                viewMode === 'list'
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                  : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]'
              }`}
              title="文字列表 — 每个 tier 一行排开 (适合 iPhone)"
            >
              <List size={11} /> list
            </button>
            <button
              onClick={() => setView('onion')}
              disabled={isNarrow}
              className={`px-2 py-1 rounded border flex items-center gap-1 disabled:opacity-40 disabled:cursor-not-allowed ${
                viewMode === 'onion'
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                  : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]'
              }`}
              title={isNarrow
                ? 'onion 视图需要 ≥768px 宽屏 (iPhone 强制 list)'
                : '同心环图 — Core 在内 / Adjacent 在外, 点节点看 10-K 关系链'}
            >
              <Network size={11} /> onion
            </button>
            {isNarrow && (
              <span className="text-[10px] text-[var(--color-dim)] italic ml-1">
                · 窄屏强制 list
              </span>
            )}
            {viewMode === 'onion' && (
              <span className="text-[10px] text-[var(--color-dim)] italic ml-2">
                · 点节点 = 高亮关系链 + 打开详细分析
              </span>
            )}
          </div>

          {/* 今日异动 — validated real-time price moves (Slice 1). Most
              time-sensitive glance, so above the (slower) cross-structure. */}
          <PriceMovesPanel onOpen={openTicker} />

          {/* Portfolio-level cross-structure: who's SHARED across holdings
              (chokepoint / correlation) — the thing per-stock metrics can't show */}
          <CrossStructurePanel onOpen={openTicker} />

          {viewMode === 'onion' ? (
            <Card>
              <CardBody>
                <PortfolioOnionView height={560} />
              </CardBody>
            </Card>
          ) : (
            <>
              {/* Core */}
              <TierSection
                tier="core"
                entries={tiers?.core ?? []}
                total={totals?.core ?? 0}
                subtitle={
                  <>
                    ≤10 只深研 · 每周复盘 ·
                    {' '}{(tiers?.core ?? []).reduce((s, e) => s + e.n_facts, 0)} 条 SEC fact 已抽
                  </>
                }
                onOpen={openTicker}
                onRemove={(t) => removeMu.mutate(t)}
              />

              {/* Adjacent */}
              <TierSection
                tier="adjacent"
                entries={tiers?.adjacent ?? []}
                total={totals?.adjacent ?? 0}
                subtitle={<>核心的上下游 / 竞品 / 客户 · 每月复盘 · 通过 drawer 的 ✨ Promote 添加</>}
                onOpen={openTicker}
                onRemove={(t) => removeMu.mutate(t)}
              />

              {/* Watching */}
              <TierSection
                tier="watching"
                entries={tiers?.watching ?? []}
                total={totals?.watching ?? 0}
                subtitle={<>较远观察 · 仅 alert · 50+ 容量</>}
                onOpen={openTicker}
                onRemove={(t) => removeMu.mutate(t)}
              />
            </>
          )}

          {/* Outside ring — anti-anchoring */}
          <Card>
            <CardHeader
              title={<span className="flex items-center gap-1.5"><Compass size={14} /> Outside ring</span>}
              subtitle={
                <>
                  {outsideQ.data?.candidates.length ?? 0} 只 multi-source 强信号但 <b>不在你任何 tier</b>{' '}
                  · 防 anchoring bias / sector 集中盲区 · 14 天回看
                </>
              }
            />
            <CardBody>
              {outsideQ.isLoading && (
                <div className="text-[11px] italic text-[var(--color-dim)]">loading…</div>
              )}
              {!outsideQ.isLoading && (outsideQ.data?.candidates.length ?? 0) === 0 && (
                <div className="text-[11px] text-[var(--color-dim)] italic py-2">
                  目前没有强信号在你的 ring 之外 — 要么 scanner 还没攒够多源 confluence,
                  要么你的 watchlist 已经覆盖了主要在跑的标的。下面的复盘 + Promote 流程
                  跑起来后, 这里逐渐有候选浮现。
                </div>
              )}
              {(outsideQ.data?.candidates ?? []).length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {(outsideQ.data?.candidates ?? []).map(c => (
                    <OutsideRingCard key={c.ticker} c={c} onOpen={openTicker} />
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  )
}


/**
 * WatchlistTab — legacy wrapper kept for any deep-link bookmarks.
 * Removed from App.tsx nav 2026-05-08; the section is now embedded
 * at the top of Strategies.
 */
export function WatchlistTab() {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-2 md:p-4 max-w-6xl mx-auto">
        <WatchlistSection />
      </div>
    </div>
  )
}


/**
 * CrossStructurePanel — portfolio-level shared edges. The per-stock drawer
 * shows what ONE company is; this shows who my holdings SHARE: institutional
 * owners (crowding), competitors (same arena), value-chain links between names
 * I hold both sides of. Suppliers/customers are sparse (10-Ks under-disclose)
 * so the gap is surfaced honestly. All DB-sourced (no yfinance throttle).
 */
function CrossStructurePanel({ onOpen }: { onOpen: (t: string) => void }) {
  const [open, setOpen] = useState(true)
  const [ownerExpanded, setOwnerExpanded] = useState(false)
  const { openWhale } = useWhaleResearch()
  const q = useCrossStructure()
  const d: CrossStructure | undefined = q.data
  if (!d || d.n_held === 0) return null
  const { shared, internal, coverage } = d

  // owner name → in-app whale profile (whale_key) or its SEC 13F filing (url)
  const ownerName = (s: SharedEntity) =>
    s.whale_key
      ? <button onClick={() => openWhale(s.whale_key!)}
          className="text-[var(--color-text)] hover:text-cyan-300 underline decoration-dotted">{s.entity}</button>
      : s.source_url
        ? <a href={s.source_url} target="_blank" rel="noopener noreferrer"
            className="text-[var(--color-text)] hover:text-cyan-300 underline decoration-dotted">{s.entity}</a>
        : <span className="text-[var(--color-text)]">{s.entity}</span>

  const chip = (t: string, key?: string | number) => (
    <button key={key ?? t} onClick={() => onOpen(t)}
      className="px-1 py-0.5 rounded bg-[var(--color-accent)]/10 border border-[var(--color-accent)]/30 text-[var(--color-accent)] font-mono text-[9px] hover:bg-[var(--color-accent)]/20">
      {t}
    </button>
  )
  // provenance-carrying chip for value-chain edges: tooltip = source filing +
  // date + verbatim quote; ↩ marks a reverse (derived-from-counterparty) edge
  const vcChip = (h: string, e: CrossEdge | undefined, key: string) => (
    <button key={key} onClick={() => onOpen(h)}
      title={e
        ? `${e.kind === 'reverse' ? '↩ 反向推导自 ' + (e.via ?? '?') + ' 的 10-K (关系已翻转)' : 'from ' + h + ' 10-K'} · filed ${e.filing_date ?? '—'}${e.stale ? ' ⚠️ stale' : ''}\n"${(e.quote || '').slice(0, 220)}"`
        : h}
      className="px-1 py-0.5 rounded bg-[var(--color-accent)]/10 border border-[var(--color-accent)]/30 text-[var(--color-accent)] font-mono text-[9px] hover:bg-[var(--color-accent)]/20 inline-flex items-center gap-0.5">
      {h}{e?.kind === 'reverse' && <span className="text-violet-300 text-[8px]">↩</span>}
    </button>
  )
  const arrow = (dir?: string | null) =>
    !dir ? null
    : /加|新建|建仓|increase|add/i.test(dir) ? <span className="text-emerald-400 text-[8px]">▲</span>
    : /减|清|exit|trim|reduce/i.test(dir)    ? <span className="text-red-400 text-[8px]">▼</span>
    : null

  const relIcon: Record<string, string> = { competitor: '⚔', supplier: '🏭→', customer: '→👥' }
  const supplierGap = Object.entries(coverage).filter(([, c]) => (c.supplier ?? 0) === 0).map(([t]) => t)
  const noChain = Object.entries(coverage)
    .filter(([, c]) => (c.competitor ?? 0) + (c.supplier ?? 0) + (c.customer ?? 0) === 0).map(([t]) => t)

  const Section = ({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) => (
    <div className="mb-2">
      <div className="text-[10px] font-semibold text-[var(--color-text)] mb-0.5">
        {title}{hint && <span className="font-normal text-[var(--color-dim)] ml-1">· {hint}</span>}
      </div>
      {children}
    </div>
  )

  return (
    <div className="rounded border border-violet-500/30 bg-violet-500/[0.04] p-2.5">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-1.5 text-left mb-1">
        {open ? <ChevronDown size={13} className="text-violet-300" /> : <ChevronRight size={13} className="text-violet-300" />}
        <Network size={13} className="text-violet-300" />
        <span className="text-[12px] font-semibold text-violet-200">组合交叉结构 · 谁被多只持仓共享</span>
        <span className="text-[10px] italic text-[var(--color-dim)]">(相关性 / chokepoint · 11 只)</span>
      </button>
      {open && (
        <div className="pl-1">
          {/* portfolio-level agent read — placeholder until the portfolio-context
              synthesis engine is wired (per-stock 3-sentence is already live) */}
          <AgentPlaceholder label="组合级速读 · 最大相关性 / chokepoint / crowding 综合" />
          {/* source + freshness — every edge is traceable to a dated SEC filing */}
          <div className="text-[9px] text-[var(--color-dim)] mb-1.5 leading-snug">
            来源: SEC 10-K {d.freshness.value_chain_oldest_filing ?? '—'} ~ {d.freshness.value_chain_newest_filing ?? '—'} · 机构 = {d.freshness.owner_source}
            {' · '}{d.freshness.n_edges} 边 ({d.freshness.n_reverse} 反向推导 ↩)
            {d.freshness.n_stale_edges > 0 && <span className="text-amber-400"> · ⚠️ {d.freshness.n_stale_edges} 过期</span>}
            <span className="block mt-0.5">↩ = 从对方 10-K 反向推导(同一条 verbatim 事实,关系已正确翻转) · 悬停 ticker 看来源原文</span>
          </div>
          {shared.owner.length > 0 && (
            <Section title="🏛 机构股东重叠" hint="同一只手押注你的多只 → 一起 de-risk 时同跌 (▲加仓 ▼减仓) · 点机构名看其档案">
              <div className="space-y-0.5">
                {(ownerExpanded ? shared.owner : shared.owner.slice(0, 6)).map(s => (
                  <div key={s.entity} className="flex items-start gap-1.5 flex-wrap text-[10px]">
                    {ownerName(s)}
                    <span className="text-[var(--color-dim)]">×{s.n}</span>
                    <span className="flex gap-1 flex-wrap items-center">
                      {s.holdings.map(h => <span key={h} className="inline-flex items-center">{chip(h, s.entity + h)}{arrow(s.edges[h]?.dir)}</span>)}
                    </span>
                  </div>
                ))}
                {shared.owner.length > 6 && (
                  <button onClick={() => setOwnerExpanded(v => !v)}
                    className="text-[9px] text-cyan-400 hover:text-cyan-300 italic">
                    {ownerExpanded ? '收起 ▲' : `展开全部 +${shared.owner.length - 6} 家共享机构 ▾`}
                  </button>
                )}
              </div>
            </Section>
          )}

          {shared.competitor.length > 0 && (
            <Section title="⚔ 同战场竞争对手" hint="多只持仓共同对手 → 同主题、易同向">
              <div className="space-y-0.5">
                {shared.competitor.slice(0, 6).map(s => (
                  <div key={s.entity} className="flex items-center gap-1.5 flex-wrap text-[10px]">
                    {s.entity_ticker ? chip(s.entity_ticker) : <span className="text-[var(--color-text)]">{s.entity}</span>}
                    <span className="text-[var(--color-dim)]">×{s.n} ←</span>
                    <span className="flex gap-1 flex-wrap">{s.holdings.map(h => vcChip(h, s.edges[h], s.entity + h))}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {internal.length > 0 && (
            <Section title="🔗 你同时持有、互为对手/上下游的" hint="你押了关系的两端">
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px]">
                {internal.map((x, i) => (
                  <span key={i} className="inline-flex items-center gap-1">
                    {chip(x.from, 'if' + i)}<span className="text-[var(--color-dim)]">{relIcon[x.rel] ?? x.rel}</span>{chip(x.to, 'it' + i)}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {(shared.supplier.length > 0 || shared.customer.length > 0) ? (
            <>
              {shared.supplier.length > 0 && (
                <Section title="🏭 共享供应商" hint="输入端 chokepoint / 单点故障">
                  <div className="space-y-0.5">{shared.supplier.slice(0, 6).map(s => (
                    <div key={s.entity} className="flex items-center gap-1.5 flex-wrap text-[10px]">
                      {s.entity_ticker ? chip(s.entity_ticker) : <span>{s.entity}</span>}
                      <span className="text-[var(--color-dim)]">×{s.n} ←</span>
                      <span className="flex gap-1 flex-wrap">{s.holdings.map(h => vcChip(h, s.edges[h], s.entity + h))}</span>
                    </div>))}</div>
                </Section>
              )}
              {shared.customer.length > 0 && (
                <Section title="👥 共享客户" hint="需求端相关">
                  <div className="space-y-0.5">{shared.customer.slice(0, 6).map(s => (
                    <div key={s.entity} className="flex items-center gap-1.5 flex-wrap text-[10px]">
                      {s.entity_ticker ? chip(s.entity_ticker) : <span>{s.entity}</span>}
                      <span className="text-[var(--color-dim)]">×{s.n} ←</span>
                      <span className="flex gap-1 flex-wrap">{s.holdings.map(h => vcChip(h, s.edges[h], s.entity + h))}</span>
                    </div>))}</div>
                </Section>
              )}
            </>
          ) : (
            <div className="text-[9.5px] text-amber-300/80 leading-snug mt-1">
              ⚠️ 共享供应商/客户暂为空 = 数据缺口,不是没有。10-K 基本不点名供应商、客户只在 ≥10% 时才披露;
              {supplierGap.length > 0 && <> 供应商顶点空的有 <b>{supplierGap.length}</b> 只</>}
              {noChain.length > 0 && <>;无任何 10-K 价值链数据(20-F/S-1 或抽取缺): {noChain.join(' ')}</>}。
              下一步需多源(供应链库/电话会/反向客户 10-K)才能补实。
            </div>
          )}
        </div>
      )}
    </div>
  )
}


/**
 * TickerChip — inline-flex compact ticker reference. Used in the
 * stale-thesis banner where we need a short row of "click these to
 * review" links. Strong hover affordance: underline, accent color,
 * arrow icon — fixes the "过于隐蔽" feedback.
 */
function TickerChip({
  ticker, onOpen, variant = 'default',
}: {
  ticker: string
  onOpen: (t: string) => void
  variant?: 'default' | 'amber'
}) {
  const baseColor = variant === 'amber'
    ? 'text-amber-300 hover:text-amber-200 hover:bg-amber-500/15'
    : 'text-[var(--color-accent)] hover:bg-[var(--color-accent)]/15'
  return (
    <button
      onClick={() => onOpen(ticker)}
      title={`点击打开 ${ticker} 详细分析 (drawer)`}
      className={`mx-1 px-1.5 py-0.5 rounded inline-flex items-center gap-0.5 underline decoration-dotted underline-offset-2 ${baseColor} font-mono`}
    >
      {ticker}
      <ArrowRight size={9} className="opacity-0 group-hover:opacity-100 transition-opacity" />
    </button>
  )
}


function TierSection({
  tier, entries, total, subtitle, onOpen, onRemove,
}: {
  tier: WatchlistTier
  entries: WatchlistEntry[]
  total: number
  subtitle: React.ReactNode
  onOpen: (t: string) => void
  onRemove: (t: string) => void
}) {
  const meta = TIER_META[tier]
  const Icon = meta.icon
  return (
    <Card>
      <CardHeader
        title={
          <span className={`flex items-center gap-1.5 ${meta.color.split(' ').filter(c => c.startsWith('text-')).join(' ')}`}>
            <Icon size={14} /> {meta.label} · {total}
          </span>
        }
        subtitle={subtitle}
      />
      <CardBody>
        {entries.length === 0 ? (
          <div className="text-[11px] text-[var(--color-dim)] italic py-1.5">
            {tier === 'core' && '没有 core 标的 · 通过 Settings 或股票 drawer 的 Promote to Core 添加'}
            {tier === 'adjacent' && '没有 adjacent 标的 · 在某个 core 的 drawer 里点 ✨ Expand 从 10-K 抽出竞品/客户/供应商'}
            {tier === 'watching' && '没有 watching 标的'}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {entries.map(e => (
              <TickerCard key={e.ticker} e={e} onOpen={onOpen} onRemove={onRemove} reviewWindow={meta.reviewWindowDays} />
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  )
}


function TickerCard({
  e, onOpen, onRemove, reviewWindow,
}: {
  e: WatchlistEntry
  onOpen: (t: string) => void
  onRemove: (t: string) => void
  reviewWindow: number
}) {
  const isStale = e.days_since_review === null || e.days_since_review > reviewWindow
  // Whole card is the click target — strong hover affordance via
  // border-accent + accent overlay so user sees it's interactive.
  // The X button stops propagation so it doesn't open the drawer.
  return (
    <div
      onClick={() => onOpen(e.ticker)}
      role="button"
      tabIndex={0}
      onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onOpen(e.ticker) } }}
      title={`点击打开 ${e.ticker} 详细分析 (drawer)`}
      className="group p-2.5 rounded border border-[var(--color-border)]/50 hover:border-[var(--color-accent)]/70 bg-[var(--color-panel)]/30 hover:bg-[var(--color-accent)]/10 cursor-pointer transition flex flex-col gap-1.5"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[14px] md:text-[13px] font-mono font-bold text-[var(--color-text)] group-hover:text-[var(--color-accent)] underline decoration-dotted decoration-[var(--color-dim)] underline-offset-2 group-hover:decoration-[var(--color-accent)]">
          {e.ticker}
          <ArrowRight size={11} className="opacity-0 group-hover:opacity-100 transition-opacity text-[var(--color-accent)]" />
        </span>
        <button
          onClick={(ev) => { ev.stopPropagation(); if (confirm(`从 watchlist 移除 ${e.ticker}?`)) onRemove(e.ticker) }}
          title="从 watchlist 移除"
          className="text-[var(--color-dim)] hover:text-red-300 p-0.5 -m-0.5 z-10"
        >
          <X size={11} />
        </button>
      </div>

      <div className="flex items-center gap-2 text-[10px] text-[var(--color-dim)] flex-wrap">
        {e.parent_ticker && (
          <span className="font-mono">↳ from {e.parent_ticker}</span>
        )}
        <span className="font-mono">{e.n_facts} facts</span>
        <span className={`flex items-center gap-0.5 ${isStale ? 'text-amber-300' : ''}`}>
          <Clock size={9} />
          {e.days_since_review === null ? '未复盘' : `${e.days_since_review}d`}
        </span>
        {isStale && (
          <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[9px]">
            待复盘
          </span>
        )}
      </div>

      {e.note && (
        <div className="text-[11px] text-[var(--color-text)]/70 leading-snug line-clamp-2">
          {e.note}
        </div>
      )}
    </div>
  )
}


function OutsideRingCard({
  c, onOpen,
}: { c: OutsideRingCandidate; onOpen: (t: string) => void }) {
  return (
    <div
      onClick={() => onOpen(c.ticker)}
      role="button"
      tabIndex={0}
      onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onOpen(c.ticker) } }}
      title={`点击打开 ${c.ticker} 详细分析`}
      className="group p-2.5 rounded border border-[var(--color-border)]/50 hover:border-violet-500/60 bg-[var(--color-panel)]/30 hover:bg-violet-500/10 cursor-pointer transition flex flex-col gap-1"
    >
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-[14px] md:text-[13px] font-mono font-bold text-[var(--color-text)] group-hover:text-violet-300 underline decoration-dotted decoration-[var(--color-dim)] underline-offset-2 group-hover:decoration-violet-300">
          {c.ticker}
          <ArrowRight size={11} className="opacity-0 group-hover:opacity-100 transition-opacity text-violet-300" />
        </span>
        {c.n_high > 0 && (
          <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/40 text-[9px] flex items-center gap-1">
            🔥 {c.n_high} high
          </span>
        )}
      </div>
      <div className="text-[10px] text-[var(--color-dim)] flex items-center gap-2 flex-wrap">
        <span>{c.n_events} events</span>
        <span>· {c.n_sources} 个 scanner 源</span>
        <span>· latest {new Date(c.latest_at).toLocaleDateString()}</span>
      </div>
    </div>
  )
}
