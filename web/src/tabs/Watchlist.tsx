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
  type WatchlistEntry,
  type WatchlistTier,
  type OutsideRingCandidate,
} from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { PortfolioOnionView } from '@/components/widgets/PortfolioOnionView'
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
export function WatchlistSection() {
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
      {/* Section header — clickable to collapse/expand */}
      <button
        onClick={toggle}
        className="w-full flex items-center gap-2 px-3 py-2 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 bg-[var(--color-panel)]/60 text-left group"
        title={collapsed ? '展开 watchlist' : '折叠 watchlist'}
      >
        {collapsed
          ? <ChevronRight size={14} className="text-[var(--color-dim)] group-hover:text-[var(--color-accent)] flex-shrink-0" />
          : <ChevronDown size={14} className="text-[var(--color-dim)] group-hover:text-[var(--color-accent)] flex-shrink-0" />}
        <Star size={14} className="text-amber-300 flex-shrink-0" />
        <span className="text-[12px] font-semibold text-[var(--color-text)] flex-shrink-0">我的 watchlist</span>
        <span className="text-[10px] italic text-[var(--color-dim)] flex-shrink-0">
          · 点 ticker 打开详细分析
        </span>
        <span className="ml-auto">{summaryChip}</span>
      </button>

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
                · 点节点高亮关系链, 双击打开详细分析
              </span>
            )}
          </div>

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
