/**
 * PriorityListWidget — "今日 priority" Top-N.
 *
 * Single ranked inbox surfacing what to look at first across 5
 * decision-relevant signal streams. Held tickers boosted 2×.
 *
 * Each row shows: ticker (click → drawer) + score + stream badges +
 * reason chips. Reads from /api/dashboard/priority_list which does
 * the aggregation server-side.
 *
 * Sits at the top of Strategies tab — supplants the user's manual
 * scan across Today's Signals + 待复盘 banner + Outside ring + Smart
 * Money + earnings calendar.
 */
import { useState } from 'react'
import { Compass, AlertTriangle, Calendar, Clock, Zap, Briefcase, BookOpen, Target, ChevronDown, ChevronRight } from 'lucide-react'
import { usePriorityList, type PriorityListItem } from '@/lib/api'
import { useStockResearch } from '@/components/research/StockResearchContext'
import { useCollapsed } from '@/lib/useCollapsed'


// Per-stream icon + color. Mapped so a row's "streams" array becomes
// visual tags without dragging in stream-specific labels.
const STREAM_META: Record<string, { icon: typeof Zap; color: string; label: string }> = {
  confluence:    { icon: Zap,            color: 'text-amber-300',   label: 'confluence' },
  thesis_review: { icon: AlertTriangle,  color: 'text-red-300',     label: 'thesis review' },
  outside:       { icon: Compass,        color: 'text-violet-300',  label: 'outside ring' },
  earnings:      { icon: Calendar,       color: 'text-blue-300',    label: 'earnings' },
  stale_core:    { icon: Clock,          color: 'text-emerald-300', label: 'stale core' },
  closed_lot:    { icon: BookOpen,       color: 'text-cyan-300',    label: 'post-mortem' },
  held_earnings: { icon: Target,         color: 'text-red-300',     label: 'held catalyst' },
}


function fmtMoney(n: number | null): string {
  if (n == null) return ''
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}


export function PriorityListWidget() {
  const q = usePriorityList(5)
  const { openTicker } = useStockResearch()
  const [collapsed, toggle] = useCollapsed('priority-list')

  // Show even on loading so the slot doesn't jump in once data arrives.
  return (
    <div
      data-testid="priority-list-widget"
      className="mb-3 rounded border border-[var(--color-accent)]/40 bg-gradient-to-r from-[var(--color-accent)]/[0.04] to-transparent p-2.5"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <button
          onClick={toggle}
          title={collapsed ? '展开' : '折叠'}
          className="flex items-center gap-1 text-[var(--color-accent)] font-semibold text-[11px] hover:opacity-80"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          📌 今日 priority
        </button>
        <span className="italic">
          · 跨 5 个信号源合并的"今天先看这几个"
        </span>
        {q.data && (
          <span className="ml-auto font-mono text-[9.5px]">
            {q.data.n_total_candidates} 个候选 → top {q.data.items.length}
          </span>
        )}
      </div>

      {!collapsed && (<>
      {q.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">computing…</div>
      )}

      {!q.isLoading && q.data && q.data.items.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1.5 leading-snug">
          ✓ 风平浪静 — 当前没有 confluence / 待 review thesis / 临近 earnings / outside-ring 的强候选。
          可以利用空闲时间补复盘 stale 的 watchlist 项。
        </div>
      )}

      {!q.isLoading && q.data && q.data.items.length > 0 && (
        <div className="space-y-1">
          {q.data.items.map((it, i) => (
            <PriorityRow key={it.ticker} item={it} rank={i + 1} onOpen={openTicker} />
          ))}
        </div>
      )}
      </>)}
    </div>
  )
}


function PriorityRow({
  item, rank, onOpen,
}: {
  item: PriorityListItem
  rank: number
  onOpen: (t: string) => void
}) {
  const [scoreOpen, setScoreOpen] = useState(false)
  return (
    <div className="w-full px-2 py-1.5 rounded border border-[var(--color-border)]/40 bg-[var(--color-panel)]/30 hover:bg-[var(--color-accent)]/[0.05] transition group flex items-start gap-2">
      <span className="font-mono text-[9.5px] text-[var(--color-dim)] w-4 flex-shrink-0 mt-0.5">
        #{rank}
      </span>
      <button
        onClick={() => onOpen(item.ticker)}
        title={`点击打开 ${item.ticker} 详细分析`}
        className="flex flex-col flex-1 min-w-0 text-left"
      >
        <span className="flex items-center gap-2 flex-wrap">
          <span className="font-mono font-bold text-[12px] text-[var(--color-text)] group-hover:text-[var(--color-accent)] underline decoration-dotted underline-offset-2">
            {item.ticker}
          </span>
          {item.is_core && (
            <span className="text-[8.5px] px-1 rounded border border-amber-500/40 text-amber-300">core</span>
          )}
          {item.held && item.held_cost != null && (
            <span className="text-[8.5px] text-[var(--color-text)]/80 font-mono flex items-center gap-0.5">
              <Briefcase size={9} />{fmtMoney(item.held_cost)}
            </span>
          )}
          {!item.held && (
            <span className="text-[8.5px] italic text-[var(--color-dim)]">not held</span>
          )}
          {/* Score is now a separate button to expose the math */}
          <span
            onClick={(e) => { e.stopPropagation(); setScoreOpen(o => !o) }}
            role="button"
            tabIndex={0}
            title="点 score 看 stream-by-stream 算法分解 (transparency)"
            className="ml-auto text-[9.5px] font-mono text-[var(--color-dim)] hover:text-[var(--color-accent)] cursor-pointer underline decoration-dotted decoration-[var(--color-dim)]/40 underline-offset-2"
          >
            score {item.score.toFixed(1)} ▾
          </span>
        </span>

        {/* Score breakdown — only when expanded */}
        {scoreOpen && (
          <span className="block mt-1 mb-1 ml-2 pl-2 border-l border-[var(--color-accent)]/40 text-[9.5px] text-[var(--color-dim)] leading-snug font-mono">
            <span className="text-[var(--color-text)] font-semibold not-italic">score breakdown:</span>
            {item.reasons.map((r, i) => (
              <span key={i} className="block">
                <span className="text-[var(--color-accent)]">+{r.score.toFixed(2)}</span>
                {' '}
                <span className="text-[var(--color-dim)] not-italic">[{r.stream}]</span>
              </span>
            ))}
            <span className="block mt-0.5 text-[var(--color-text)]">
              ── total: <b>{item.score.toFixed(2)}</b>
            </span>
          </span>
        )}

        {/* Reasons — one chip per reason. {stream,text,score} paired
            server-side so the icon always matches the reason. */}
        <span className="flex flex-wrap gap-1 mt-0.5">
          {item.reasons.map((r, ri) => {
            const meta = STREAM_META[r.stream]
            const Icon = meta?.icon
            return (
              <span
                key={ri}
                title={`stream: ${r.stream} · contributes ${r.score.toFixed(2)} to total score`}
                className={`text-[9.5px] px-1.5 py-0.5 rounded border border-[var(--color-border)]/50 leading-tight flex items-center gap-1 ${
                  meta?.color ?? 'text-[var(--color-dim)]'
                }`}
              >
                {Icon && <Icon size={9} />}
                <span>{r.text}</span>
              </span>
            )
          })}
        </span>
      </button>
    </div>
  )
}
