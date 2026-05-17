/**
 * NewsFlowWidget — anchor-first news/event traversal.
 *
 * Maps to the user's actual workflow: "我平时就是会关注特定的几个
 * 股票和消息，然后从中出发关注对应的公司和股票以及上下游".
 *
 * Surfaces recent signal_events (news, 13F, congress, insider,
 * policy, earnings) prominently at the top of Strategies tab so the
 * news flow IS the entry point — not buried in NeoMindLive
 * collapsed panel.
 *
 * Three filter modes:
 *   - 'anchor' (default): only events whose ticker is in user's
 *     watchlist tiers OR an open position. This is "my world".
 *   - 'anchor+adjacent': anchor set + their 10-K adjacent tickers
 *     (one hop out). Catches "AAPL's supplier had news".
 *   - 'all': raw firehose for market-wide context.
 *
 * Each event row has:
 *   - clickable ticker → opens drawer (the "walk" entry point)
 *   - source URL inline → primary source for "有根有据"
 *   - severity color + timestamp
 *   - 1-click "→ propagates to" expander that shows the ticker's
 *     10-K downstream (chain-propagation).
 */
import { useMemo, useState } from 'react'
import { useStockResearch } from '@/components/research/StockResearchContext'
import {
  useRecentSignals, useUserWatchlist, useAnchoredFacts,
  type SignalEvent,
} from '@/lib/api'
import { Newspaper, GitBranch, Globe, Filter } from 'lucide-react'


function relTime(iso: string): string {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return iso
  const secs = (Date.now() - dt.getTime()) / 1000
  if (secs < 60) return `${Math.floor(secs)}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h`
  return `${Math.floor(secs / 86400)}d`
}


const SCANNER_ICON: Record<string, string> = {
  watchlist:        '📊',
  news:             '📰',
  '13f':            '🐋',
  stock_act:        '🏛️',
  earnings:         '💰',
  earnings_calendar: '📅',
  insider_form4:    '⚪',
  house_clerk_pdf:  '🏛',
  policy:           '🌐',
}


type FilterMode = 'anchor' | 'anchor_plus_adjacent' | 'all'

const FILTER_META: Record<FilterMode, { label: string; icon: typeof Filter; help: string }> = {
  anchor:               { label: '🎯 my anchors',  icon: Filter,    help: '只看 watchlist + 持仓 ticker 的事件' },
  anchor_plus_adjacent: { label: '🔗 + adjacent',  icon: GitBranch, help: 'anchors + 它们 10-K 里的供应链邻居' },
  all:                  { label: '🌐 all market',  icon: Globe,     help: '全市场原始流 (噪音多, 用于 discovery)' },
}


export function NewsFlowWidget() {
  const [mode, setMode] = useState<FilterMode>('anchor')
  const [limit, setLimit] = useState(40)
  const { openTicker } = useStockResearch()
  const wlQ = useUserWatchlist()
  const sigsQ = useRecentSignals({ limit })

  // Anchor set: watchlist + supply chain (depending on mode)
  const anchorSet = useMemo(() => {
    const set = new Set<string>()
    for (const e of wlQ.data?.user_watchlist ?? []) {
      if (e?.ticker) set.add(e.ticker.toUpperCase())
    }
    return set
  }, [wlQ.data])
  const adjacentSet = useMemo(() => {
    const set = new Set<string>()
    for (const t of wlQ.data?.supply_chain ?? []) set.add(t.toUpperCase())
    return set
  }, [wlQ.data])

  const allEvents = sigsQ.data?.events ?? []
  const filtered = useMemo(() => {
    if (mode === 'all') return allEvents
    return allEvents.filter(e => {
      if (!e.ticker) return false
      const tk = e.ticker.toUpperCase()
      if (anchorSet.has(tk)) return true
      if (mode === 'anchor_plus_adjacent' && adjacentSet.has(tk)) return true
      return false
    })
  }, [allEvents, mode, anchorSet, adjacentSet])

  // Group by ticker so a single ticker with 5 news items doesn't crowd out others.
  const byTicker = useMemo(() => {
    const map = new Map<string, SignalEvent[]>()
    for (const e of filtered) {
      const tk = e.ticker || '(theme)'
      if (!map.has(tk)) map.set(tk, [])
      map.get(tk)!.push(e)
    }
    return Array.from(map.entries())
      .sort((a, b) => {
        const ta = a[1][0]?.detected_at ?? ''
        const tb = b[1][0]?.detected_at ?? ''
        return tb.localeCompare(ta)
      })
  }, [filtered])

  return (
    <div
      data-testid="news-flow-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-panel)]/40 p-2.5"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] flex-wrap">
        <span className="text-[var(--color-text)] font-semibold flex items-center gap-1 text-[11px]">
          <Newspaper size={12} /> 消息流
        </span>
        <span className="italic text-[var(--color-dim)]">
          · 从这里 click ticker walk 到 chain
        </span>
        {/* Mode selector */}
        <div className="flex gap-0.5 ml-2">
          {(['anchor', 'anchor_plus_adjacent', 'all'] as FilterMode[]).map(m => {
            const meta = FILTER_META[m]
            const active = m === mode
            return (
              <button
                key={m}
                onClick={() => setMode(m)}
                title={meta.help}
                className={`text-[9.5px] px-2 py-0.5 rounded border ${
                  active
                    ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                    : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]'
                }`}
              >
                {meta.label}
              </button>
            )
          })}
        </div>
        <span className="ml-auto text-[9px] font-mono text-[var(--color-dim)]">
          {filtered.length} / {allEvents.length} events
        </span>
      </div>

      {sigsQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
      )}

      {!sigsQ.isLoading && filtered.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1.5 leading-snug">
          {mode === 'anchor'
            ? '✓ 当前 watchlist 内的 ticker 暂无新事件; 切到 "+ adjacent" 看上下游, 或 "all" 看全市场'
            : '无事件 - scanner 还没产出新数据, 可点顶栏 ↻ 强制刷'}
        </div>
      )}

      {byTicker.length > 0 && (
        <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
          {byTicker.slice(0, 20).map(([tk, events]) => (
            <TickerEventGroup
              key={tk}
              ticker={tk}
              events={events}
              isAnchor={anchorSet.has(tk)}
              isAdjacent={adjacentSet.has(tk)}
              onWalk={openTicker}
            />
          ))}
          {byTicker.length > 20 && (
            <button
              onClick={() => setLimit(l => l + 40)}
              className="w-full text-[9px] text-[var(--color-dim)] hover:text-[var(--color-text)] italic py-1"
            >
              + {byTicker.length - 20} more tickers; 加载更多 events…
            </button>
          )}
        </div>
      )}
    </div>
  )
}


function TickerEventGroup({
  ticker, events, isAnchor, isAdjacent, onWalk,
}: {
  ticker: string
  events: SignalEvent[]
  isAnchor: boolean
  isAdjacent: boolean
  onWalk: (t: string) => void
}) {
  const [showProp, setShowProp] = useState(false)
  // Only fetch propagation data when user expands — saves bandwidth.
  // Chain propagation = ticker's 10-K customers + suppliers (upstream + downstream).
  const factsQ = useAnchoredFacts(showProp ? ticker : null)
  const customers = factsQ.data?.facts?.customer ?? []
  const suppliers = factsQ.data?.facts?.supplier ?? []
  const propTickers = useMemo(() => {
    const set = new Set<string>()
    for (const c of customers) if (c.ticker) set.add(c.ticker)
    for (const s of suppliers) if (s.ticker) set.add(s.ticker)
    return Array.from(set)
  }, [customers, suppliers])

  return (
    <div className="border-l-2 border-[var(--color-border)] pl-2">
      <div className="flex items-baseline gap-2 mb-0.5">
        {ticker !== '(theme)' ? (
          <button
            onClick={() => onWalk(ticker)}
            title={`walk to ${ticker} chain (drawer)`}
            className="font-mono font-bold text-[var(--color-text)] hover:text-[var(--color-accent)] underline decoration-dotted underline-offset-2 text-[12px]"
          >
            {ticker}
          </button>
        ) : (
          <span className="font-mono text-[var(--color-dim)] italic text-[11px]">(theme)</span>
        )}
        {isAnchor && (
          <span className="text-[8.5px] px-1 rounded border border-amber-500/40 text-amber-300">anchor</span>
        )}
        {isAdjacent && !isAnchor && (
          <span className="text-[8.5px] px-1 rounded border border-emerald-500/40 text-emerald-300">adjacent</span>
        )}
        <span className="text-[9.5px] text-[var(--color-dim)] font-mono">
          {events.length} event{events.length > 1 ? 's' : ''}
        </span>
        {ticker !== '(theme)' && (
          <button
            onClick={() => setShowProp(o => !o)}
            title="show 10-K downstream (suppliers + customers) — chain propagation"
            className="text-[9px] text-[var(--color-dim)] hover:text-[var(--color-accent)] underline decoration-dotted underline-offset-2 ml-1"
          >
            {showProp ? '▾ propagation' : '→ propagates to?'}
          </button>
        )}
      </div>

      {/* Event list (compact, source URL inline) */}
      <div className="space-y-0.5">
        {events.slice(0, 5).map(e => (
          <div key={e.event_id} className="text-[10px] flex items-baseline gap-1.5 flex-wrap pl-1">
            <span className="flex-shrink-0">{SCANNER_ICON[e.scanner_name] ?? '·'}</span>
            <span className="text-[var(--color-dim)] font-mono w-[60px] truncate flex-shrink-0">
              {e.scanner_name}
            </span>
            <span className={
              e.severity === 'high' ? 'text-red-300' :
              e.severity === 'med'  ? 'text-amber-300' :
              'text-[var(--color-dim)]'
            }>[{e.severity}]</span>
            <span className="text-[var(--color-text)]/85 truncate flex-1 min-w-0">
              {e.title}
            </span>
            {e.source_url && (
              <a
                href={e.source_url}
                target="_blank"
                rel="noopener noreferrer"
                title={`source: ${e.source_url}`}
                className="text-[9px] text-[var(--color-accent)] hover:underline flex-shrink-0"
              >↗</a>
            )}
            <span className="text-[8.5px] text-[var(--color-dim)] font-mono flex-shrink-0">
              {relTime(e.detected_at)}
            </span>
          </div>
        ))}
        {events.length > 5 && (
          <div className="text-[8.5px] italic text-[var(--color-dim)] pl-1">
            + {events.length - 5} more — open {ticker} drawer to see full feed
          </div>
        )}
      </div>

      {/* Chain propagation — opt-in expand */}
      {showProp && (
        <div className="mt-1.5 mb-0.5 pl-2 border-l border-[var(--color-accent)]/40">
          {factsQ.isLoading ? (
            <div className="text-[9px] italic text-[var(--color-dim)]">loading 10-K chain…</div>
          ) : propTickers.length === 0 ? (
            <div className="text-[9px] italic text-[var(--color-dim)]">
              no 10-K supply chain extracted yet — run anchored_quarterly cron or click drawer ↻
            </div>
          ) : (
            <div className="text-[9.5px] flex items-baseline gap-1 flex-wrap">
              <span className="text-[var(--color-dim)]">→ propagates to:</span>
              {propTickers.slice(0, 10).map(t => (
                <button
                  key={t}
                  onClick={() => onWalk(t)}
                  title={`walk to ${t}`}
                  className="px-1 py-0 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] hover:text-[var(--color-accent)] font-mono"
                >
                  {t}
                </button>
              ))}
              {propTickers.length > 10 && (
                <span className="text-[8.5px] italic text-[var(--color-dim)]">+ {propTickers.length - 10}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
