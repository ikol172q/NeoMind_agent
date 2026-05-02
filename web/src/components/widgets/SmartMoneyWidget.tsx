/**
 * SmartMoneyWidget — surfaces raw 13f whale activity (Buffett, Druckenmiller,
 * Tepper, Ackman, Klarman, Loeb, Marks) independent of the 24h confluence
 * TTL that hides things from TodaysSignalsWidget.
 *
 * 13F filings drop quarterly with a 45-day SEC delay, so most days there's
 * nothing new. When a filing lands, the user wants to see WHO bought/sold
 * WHAT — not wait for a separate scanner to also tag the ticker before it
 * shows up.
 *
 * Same shape as TodaysSignalsWidget — title bar, list of compact cards,
 * empty state — but reads `useRecentSignals({ scanner: '13f' })` instead
 * of confluences.
 */
import { useState } from 'react'
import { useRecentSignals, type SignalEvent } from '@/lib/api'


function relTime(iso: string): string {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return iso
  const secs = (Date.now() - dt.getTime()) / 1000
  if (secs < 60) return `${Math.floor(secs)}s 前`
  if (secs < 3600) return `${Math.floor(secs / 60)}m 前`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h 前`
  if (secs < 86400 * 14) return `${Math.floor(secs / 86400)}d 前`
  return `${Math.floor(secs / 86400 / 7)}w 前`
}


function formatValueUSD(k: unknown): string {
  const n = typeof k === 'string' ? Number(k) : (typeof k === 'number' ? k : NaN)
  if (!isFinite(n)) return ''
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}B`
  if (n >= 1_000)     return `$${(n / 1_000).toFixed(0)}M`
  return `$${Math.round(n)}K`
}


// 中文名字 + 一句话简介, 让不熟英文名的 user 立刻知道这是谁.
// Keyed by whale_key from agent/finance/regime/scanners/whale_scanner.py::WHALES.
const WHALE_CN: Record<string, { cn: string; intro: string }> = {
  buffett:       { cn: '巴菲特 (伯克希尔)',
                   intro: '价值投资之王 · 长期持有可口可乐/苹果, 95岁仍在管 $300B+' },
  druckenmiller: { cn: '德鲁肯米勒 (杜肯家族办公室)',
                   intro: '索罗斯前合伙人 · 30 年从无年度亏损 · 宏观 + 选股双修' },
  tepper:        { cn: '特珀 (阿帕卢萨)',
                   intro: '困境投资 + 宏观 trader · NFL 球队老板 · 2020 抄底美股的人' },
  ackman:        { cn: '阿克曼 (潘兴广场)',
                   intro: '激进维权派 · Chipotle 翻盘成名 · 集中持仓 ~10 只股' },
  klarman:       { cn: '克拉曼 (鲍波斯特)',
                   intro: '安全边际派 · 巴菲特同辈 · 现金可达 30%, 不便宜不出手' },
  loeb:          { cn: '罗伯 (第三点)',
                   intro: '激进维权 + 事件驱动 · 写公开信批管理层风格' },
  marks:         { cn: '马克斯 (橡树资本)',
                   intro: '困境债权之王 · 《周期》作者 · 备忘录全华尔街必读' },
}


// Map 13f signal_type → short Chinese label + color hint.
function changeBadge(signal_type: string): { label: string; color: string } {
  if (signal_type === '13f_new')      return { label: '新建仓', color: 'green' }
  if (signal_type === '13f_increase') return { label: '加仓',   color: 'green' }
  if (signal_type === '13f_decrease') return { label: '减仓',   color: 'amber' }
  if (signal_type === '13f_exit')     return { label: '清仓',   color: 'red'   }
  return { label: signal_type, color: 'amber' }
}


export function SmartMoneyWidget() {
  // Two independent queries — 13F (institutional fund managers, quarterly
  // filings, 45-day SEC delay) and stock_act (Congress members, 30-45 day
  // STOCK Act disclosure window). Rendered as two sub-sections so user can
  // tell at a glance whose money is moving.
  const q13f = useRecentSignals({ scanner: '13f', limit: 100 })
  const qStockAct = useRecentSignals({ scanner: 'stock_act', limit: 100 })
  const [expanded, setExpanded] = useState(false)
  const [expandedCongress, setExpandedCongress] = useState(false)
  // Section-level fold (collapses entire section to its header).
  // Defaults open; user click toggles.
  const [collapsed13f, setCollapsed13f] = useState(false)
  const [collapsedCongress, setCollapsedCongress] = useState(false)

  const events = (q13f.data?.events ?? []) as SignalEvent[]
  const congressEvents = (qStockAct.data?.events ?? []) as SignalEvent[]

  // Group by whale_key so the user sees per-fund activity rather than a
  // flat firehose. Sort whales by latest activity desc, events within
  // each whale by detected_at desc (already from API).
  const byWhale = new Map<string, { whale: string; events: SignalEvent[] }>()
  for (const e of events) {
    const wk = String((e.body as Record<string, unknown> | undefined)?.whale_key ?? 'unknown')
    const wn = String((e.body as Record<string, unknown> | undefined)?.whale ?? 'Unknown whale')
    if (!byWhale.has(wk)) byWhale.set(wk, { whale: wn, events: [] })
    byWhale.get(wk)!.events.push(e)
  }
  const groups = Array.from(byWhale.values()).sort((a, b) => {
    const ta = new Date(a.events[0]?.detected_at ?? 0).getTime()
    const tb = new Date(b.events[0]?.detected_at ?? 0).getTime()
    return tb - ta
  })

  // Group congress events by representative.
  const byRep = new Map<string, { rep: string; chamber: string; party: string; events: SignalEvent[] }>()
  for (const e of congressEvents) {
    const b = (e.body ?? {}) as Record<string, unknown>
    const rep = String(b.representative ?? b.senator ?? 'Unknown')
    const chamber = String(b.chamber ?? '')
    const party = String(b.party ?? '')
    if (!byRep.has(rep)) byRep.set(rep, { rep, chamber, party, events: [] })
    byRep.get(rep)!.events.push(e)
  }
  const congressGroups = Array.from(byRep.values()).sort((a, b) => {
    const ta = new Date(a.events[0]?.detected_at ?? 0).getTime()
    const tb = new Date(b.events[0]?.detected_at ?? 0).getTime()
    return tb - ta
  })

  return (
    <div
      data-testid="smart-money-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5"
    >
      {/* === 13F whale section === */}
      <button
        onClick={() => setCollapsed13f((v) => !v)}
        className="w-full flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)] text-left"
      >
        <span className="text-[9px]">{collapsed13f ? '▸' : '▾'}</span>
        <span className="font-semibold text-[var(--color-text)]">
          🐋 Smart Money — 13F whale moves
        </span>
        {events.length > 0 && (
          <span className="font-mono">{events.length} events · {groups.length} funds</span>
        )}
        <span className="ml-auto text-[8.5px] italic">
          SEC 45-day delay · long positions only
        </span>
      </button>

      {!collapsed13f && q13f.isLoading && (
        <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
      )}

      {!collapsed13f && !q13f.isLoading && events.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
          No recent 13F filings tracked. Whale scanner runs daily; events
          appear within 1-2 days of SEC publication.
        </div>
      )}

      {!collapsed13f && !q13f.isLoading && groups.length > 0 && (
        <div className="space-y-2">
          {groups.slice(0, expanded ? groups.length : 3).map((g) => (
            <WhaleGroup key={g.whale} group={g} />
          ))}
          {groups.length > 3 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] mt-1"
            >
              {expanded ? `▴ collapse` : `▾ show ${groups.length - 3} more whales`}
            </button>
          )}
        </div>
      )}

      {/* === Congressional STOCK Act section === */}
      <div className="mt-3 pt-3 border-t border-[var(--color-border)]/40">
        <button
          onClick={() => setCollapsedCongress((v) => !v)}
          className="w-full flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)] text-left"
        >
          <span className="text-[9px]">{collapsedCongress ? '▸' : '▾'}</span>
          <span className="font-semibold text-[var(--color-text)]">
            🏛 Congress — STOCK Act trades (Pelosi, etc)
          </span>
          {congressEvents.length > 0 && (
            <span className="font-mono">
              {congressEvents.length} events · {congressGroups.length} members
            </span>
          )}
          <span className="ml-auto text-[8.5px] italic">
            45-day disclosure window · amounts are ranges, not exact
          </span>
        </button>

        {!collapsedCongress && qStockAct.isLoading && (
          <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
        )}

        {!collapsedCongress && !qStockAct.isLoading && congressEvents.length === 0 && (
          <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
            No recent congressional trades tracked in your watchlist. Source:
            Quiver Quant live feed (1000 most-recent records, House + Senate
            combined). Filtered to your watchlist + supply chain.
          </div>
        )}

        {!collapsedCongress && !qStockAct.isLoading && congressGroups.length > 0 && (
          <div className="space-y-2">
            {congressGroups.slice(0, expandedCongress ? congressGroups.length : 5).map((g) => (
              <CongressGroup key={g.rep} group={g} />
            ))}
            {congressGroups.length > 5 && (
              <button
                onClick={() => setExpandedCongress((v) => !v)}
                className="text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] mt-1"
              >
                {expandedCongress
                  ? `▴ collapse`
                  : `▾ show ${congressGroups.length - 5} more members`}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}


function CongressGroup({
  group,
}: {
  group: { rep: string; chamber: string; party: string; events: SignalEvent[] }
}) {
  const chamberLabel = group.chamber === 'senate' ? '参议院' : '众议院'
  const partyClass =
    group.party === 'D' ? 'text-blue-400' :
    group.party === 'R' ? 'text-red-400' : 'text-[var(--color-dim)]'
  return (
    <div className="rounded border border-[var(--color-border)]/60 bg-[var(--color-panel)]/30 p-2">
      <div className="flex items-center gap-2 mb-1.5 text-[10px]">
        <span className="font-semibold text-[var(--color-text)]">{group.rep}</span>
        {group.party && (
          <span className={`text-[8.5px] font-mono ${partyClass}`}>[{group.party}]</span>
        )}
        {group.chamber && (
          <span className="text-[8.5px] text-[var(--color-dim)]">{chamberLabel}</span>
        )}
        <span className="text-[8.5px] text-[var(--color-dim)] font-mono ml-auto">
          {group.events.length} 笔
        </span>
      </div>
      <div className="space-y-0.5">
        {group.events.map((e) => (
          <CongressRow key={e.event_id} event={e} />
        ))}
      </div>
    </div>
  )
}


function CongressRow({ event }: { event: SignalEvent }) {
  const body = (event.body ?? {}) as Record<string, unknown>
  const txType = String(body.transaction_type ?? '').toLowerCase()
  const isBuy = txType.includes('purchase')
  const action = isBuy ? '买入' : (txType.includes('sale') ? '卖出' : '换股')
  const actionClass = isBuy
    ? 'text-[var(--color-green,#7ed98c)] border-[var(--color-green,#7ed98c)]/40'
    : 'text-[var(--color-red,#e07070)] border-[var(--color-red,#e07070)]/40'
  const amount = String(body.amount_range ?? '')
  const txDate = String(body.transaction_date ?? '')
  return (
    <div className="flex items-center gap-2 text-[10px] py-0.5">
      <span className={`px-1 py-0 rounded border text-[8.5px] font-mono flex-shrink-0 ${actionClass}`}>
        {action}
      </span>
      <span className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0">
        {event.ticker ?? '—'}
      </span>
      <span className="text-[9.5px] text-[var(--color-dim)] font-mono">
        {amount}
      </span>
      {event.source_url && (
        <a
          href={event.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[8.5px] text-[var(--color-accent)] hover:underline ml-auto flex-shrink-0"
          title="View on Quiver Quant"
        >
          🔗
        </a>
      )}
      <span className="text-[8.5px] text-[var(--color-dim)] font-mono w-16 text-right flex-shrink-0">
        {txDate}
      </span>
    </div>
  )
}


function WhaleGroup({ group }: { group: { whale: string; events: SignalEvent[] } }) {
  const latest = group.events[0]
  const whaleKey = String(
    (latest?.body as Record<string, unknown> | undefined)?.whale_key ?? '',
  )
  const filingDate = String(
    (latest?.body as Record<string, unknown> | undefined)?.filing_date ?? '',
  )
  const cn = WHALE_CN[whaleKey]
  return (
    <div className="rounded border border-[var(--color-border)]/60 bg-[var(--color-panel)]/30 p-2">
      <div className="flex items-center gap-2 mb-1.5 text-[10px]">
        <span
          className="font-semibold text-[var(--color-text)]"
          title={cn?.intro ?? ''}
        >
          {group.whale}
          {cn && (
            <span className="ml-1.5 text-[9.5px] text-[var(--color-dim)] font-normal">
              · {cn.cn}
            </span>
          )}
        </span>
        <span className="text-[8.5px] text-[var(--color-dim)] font-mono">
          {group.events.length} moves
        </span>
        {filingDate && (
          <span className="ml-auto text-[8.5px] text-[var(--color-dim)] font-mono">
            13F filed {filingDate}
          </span>
        )}
      </div>
      {cn && (
        <div className="text-[9px] italic text-[var(--color-dim)] mb-1.5 leading-[1.4]">
          {cn.intro}
        </div>
      )}
      <div className="space-y-0.5">
        {group.events.map((e) => (
          <EventRow key={e.event_id} event={e} />
        ))}
      </div>
    </div>
  )
}


function EventRow({ event }: { event: SignalEvent }) {
  const body = (event.body ?? {}) as Record<string, unknown>
  const badge = changeBadge(event.signal_type)
  const valueK = body.value_usd_k
  const shares = body.shares
  const name = body.name as string | undefined

  const badgeClass =
    badge.color === 'green' ? 'text-[var(--color-green,#7ed98c)] border-[var(--color-green,#7ed98c)]/40' :
    badge.color === 'red'   ? 'text-[var(--color-red,#e07070)] border-[var(--color-red,#e07070)]/40' :
                              'text-[var(--color-amber,#e5a200)] border-[var(--color-amber,#e5a200)]/40'

  return (
    <div className="flex items-center gap-2 text-[10px] py-0.5">
      <span className={`px-1 py-0 rounded border text-[8.5px] font-mono flex-shrink-0 ${badgeClass}`}>
        {badge.label}
      </span>
      <span className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0">
        {event.ticker ?? '—'}
      </span>
      {name && (
        <span className="text-[9px] text-[var(--color-dim)] truncate flex-1">{name}</span>
      )}
      <span className="text-[9.5px] text-[var(--color-dim)] font-mono flex-shrink-0">
        {formatValueUSD(valueK)}
        {typeof shares === 'number' && shares > 0 && (
          <span className="ml-1 text-[8.5px]">
            ({(shares / 1000).toFixed(0)}k sh)
          </span>
        )}
      </span>
      {event.source_url && (
        <a
          href={event.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[8.5px] text-[var(--color-accent)] hover:underline flex-shrink-0"
          title="Open SEC filing"
        >
          🔗
        </a>
      )}
      <span className="text-[8.5px] text-[var(--color-dim)] font-mono w-10 text-right flex-shrink-0">
        {relTime(event.detected_at)}
      </span>
    </div>
  )
}
