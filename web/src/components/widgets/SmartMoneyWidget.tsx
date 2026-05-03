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


// Followed reps the user wants pinned to the top of the Congress section
// regardless of when they last traded — they're "anchors" not just feed
// noise. Keys are case-insensitive substring matches against the rep's
// display name as stored in body_json.representative / body_json.senator.
const FOLLOWED_CONGRESS = {
  pelosi:    { cn: '佩洛西',     intro: '众议院前议长 · ETF NANC 跟踪她 · 2024 年回报 +38% 跑赢 SPY · 低频高信念' },
  tina:      { cn: '蒂娜·史密斯', intro: '参议院 D-MN · Senate Finance 委员 · 现 feed 中披露最快 (中位 3 天) · 稳健分散' },
  cleo:      { cn: '克里奥·菲尔兹', intro: '众议院 D-LA · 2025 回报 +44.8% 跑赢 SPY 16.8% · 重仓 GOOGL/MSFT/NVDA' },
} as const

function isFollowedRep(name: string): keyof typeof FOLLOWED_CONGRESS | null {
  const n = name.toLowerCase()
  if (n.includes('pelosi')) return 'pelosi'
  if (n.includes('tina') && n.includes('smith')) return 'tina'
  if (n.includes('cleo') && n.includes('fields')) return 'cleo'
  return null
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
  dalio:         { cn: '达里奥 (桥水)',
                   intro: '全天候投资派 · 2025 Pure Alpha +34% 史上最佳 · All Weather +20%' },
  griffin:       { cn: '格里芬 (Citadel)',
                   intro: '多策略量化 · 2025 +10.2% · $570B 管理 · 高频做市起家' },
  deshaw:        { cn: 'D.E. Shaw',
                   intro: '量化对冲先驱 · 2025 Composite +18.5% / Oculus +28.2% · 数学博士驱动' },
}


// Investment-style tags so the user can pattern-match risk profile at a
// glance without reading every intro. Single-character emoji + short
// label; rendered in the rep/whale header. Adjust as you learn more
// about each entity's actual style.
const STYLE_TAG = {
  conservative: { emoji: '🟢', label: '稳健',   cls: 'text-[var(--color-green,#7ed98c)]' },
  balanced:     { emoji: '🟠', label: '平衡',   cls: 'text-[var(--color-amber,#e5a200)]' },
  aggressive:   { emoji: '🔴', label: '激进',   cls: 'text-[var(--color-red,#e07070)]' },
  quant:        { emoji: '🟣', label: '量化',   cls: 'text-purple-400' },
  innovation:   { emoji: '🔵', label: '创新',   cls: 'text-blue-400' },
  insider:      { emoji: '⚪', label: '内部',   cls: 'text-[var(--color-dim)]' },
} as const
type StyleKey = keyof typeof STYLE_TAG

const WHALE_STYLE: Record<string, StyleKey> = {
  buffett: 'conservative', klarman: 'conservative', marks: 'conservative',
  dalio:   'conservative',
  griffin: 'quant',        deshaw:  'quant',
  druckenmiller: 'aggressive', tepper: 'aggressive',
  ackman:  'aggressive',   loeb:    'aggressive',
}

const CONGRESS_STYLE: Partial<Record<keyof typeof FOLLOWED_CONGRESS, StyleKey>> = {
  pelosi: 'conservative', tina: 'conservative', cleo: 'balanced',
}

function StyleTag({ k }: { k?: StyleKey | null }) {
  if (!k) return null
  const s = STYLE_TAG[k]
  return (
    <span className={`text-[8.5px] font-mono ${s.cls}`} title={`${s.label} 风格`}>
      {s.emoji}{s.label}
    </span>
  )
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
  // Two scanner sources cover Congress: Quiver feed (most reps, free,
  // ~1000 records) + House Clerk PDF parser (text-PDF reps that Quiver
  // gates behind paid tier — currently just Pelosi). Merge in widget.
  const qStockAct = useRecentSignals({ scanner: 'stock_act', limit: 100 })
  const qHouseClerk = useRecentSignals({ scanner: 'house_clerk_pdf', limit: 100 })
  // ARK + Form 4 are tab placeholders for now — scanners pending.
  const qArk = useRecentSignals({ scanner: 'ark_daily', limit: 100 })
  const qInsider = useRecentSignals({ scanner: 'insider_form4', limit: 100 })
  const [expanded, setExpanded] = useState(false)
  const [expandedCongress, setExpandedCongress] = useState(false)
  // Tabs replace the old stacked sections so the widget doesn't grow
  // taller as we add data sources. Default = whales (Buffett etc) since
  // that's the section users came here for originally.
  type Tab = 'whales' | 'congress' | 'ark' | 'insider'
  const [tab, setTab] = useState<Tab>('whales')

  const events = (q13f.data?.events ?? []) as SignalEvent[]
  const congressEvents = [
    ...((qStockAct.data?.events ?? []) as SignalEvent[]),
    ...((qHouseClerk.data?.events ?? []) as SignalEvent[]),
  ]
  const congressLoading = qStockAct.isLoading || qHouseClerk.isLoading

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

  // Group congress events by representative. Within each rep, sort
  // trades by actual transaction_date desc (most-recent trade first) —
  // detected_at is identical for the whole batch (we ingested all of
  // Pelosi's PTRs in one scan tick) so without per-rep sort the order
  // would be PDF iteration order, which has no relationship to recency.
  const byRep = new Map<string, { rep: string; chamber: string; party: string; events: SignalEvent[] }>()
  for (const e of congressEvents) {
    const b = (e.body ?? {}) as Record<string, unknown>
    const rep = String(b.representative ?? b.senator ?? 'Unknown')
    const chamber = String(b.chamber ?? '')
    const party = String(b.party ?? '')
    if (!byRep.has(rep)) byRep.set(rep, { rep, chamber, party, events: [] })
    byRep.get(rep)!.events.push(e)
  }
  // Sort each rep's events: most-recent trade first.
  for (const g of byRep.values()) {
    g.events.sort((a, b) => {
      const ta = String((a.body as Record<string, unknown> | undefined)?.transaction_date ?? a.source_timestamp ?? '')
      const tb = String((b.body as Record<string, unknown> | undefined)?.transaction_date ?? b.source_timestamp ?? '')
      // ISO date strings sort lexically — desc means b - a.
      if (ta < tb) return 1
      if (ta > tb) return -1
      return 0
    })
  }
  const congressGroups = Array.from(byRep.values()).sort((a, b) => {
    // Followed-rep anchors pinned first (Pelosi/Tina Smith/Cleo Fields),
    // then everyone else by latest detected_at desc.
    const fa = isFollowedRep(a.rep) ? 0 : 1
    const fb = isFollowedRep(b.rep) ? 0 : 1
    if (fa !== fb) return fa - fb
    const ta = new Date(a.events[0]?.detected_at ?? 0).getTime()
    const tb = new Date(b.events[0]?.detected_at ?? 0).getTime()
    return tb - ta
  })

  const arkEvents = (qArk.data?.events ?? []) as SignalEvent[]
  const insiderEvents = (qInsider.data?.events ?? []) as SignalEvent[]

  const tabs: Array<{ k: Tab; label: string; count: number; subtitle: string }> = [
    { k: 'whales',   label: '🐋 13F 机构',     count: events.length,
      subtitle: 'SEC 45 天延迟 · 仅多头' },
    { k: 'congress', label: '🏛 国会议员',     count: congressEvents.length,
      subtitle: '45 天披露窗口 · 金额是区间' },
    { k: 'ark',      label: '🔵 ARK 创新',     count: arkEvents.length,
      subtitle: 'Cathie Wood · 每日公开 · 创新型 long bet' },
    { k: 'insider',  label: '⚪ 内部 (Form 4)', count: insiderEvents.length,
      subtitle: 'CEO/CFO 自掏腰包 · 2 天披露 · 最快' },
  ]
  const activeTab = tabs.find((t) => t.k === tab)!

  return (
    <div
      data-testid="smart-money-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5"
    >
      {/* === Tab bar === */}
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)] flex-wrap">
        <span className="font-semibold text-[var(--color-text)]">Smart Money</span>
        <div className="flex gap-1 ml-1">
          {tabs.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={
                'px-2 py-0.5 rounded border text-[10px] font-mono ' +
                (t.k === tab
                  ? 'border-[var(--color-accent)] text-[var(--color-text)] bg-[var(--color-accent)]/10'
                  : 'border-[var(--color-border)]/60 hover:border-[var(--color-accent)]/60')
              }
              title={t.subtitle}
            >
              {t.label}
              {t.count > 0 && (
                <span className="ml-1 text-[8.5px] text-[var(--color-dim)]">
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[8.5px] italic">{activeTab.subtitle}</span>
      </div>

      {/* === Tab content: 13F whales === */}
      {tab === 'whales' && (
        <>
          {q13f.isLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!q13f.isLoading && events.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No recent 13F filings tracked. Whale scanner runs daily; events
              appear within 1-2 days of SEC publication.
            </div>
          )}
          {!q13f.isLoading && groups.length > 0 && (
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
        </>
      )}

      {/* === Tab content: Congress === */}
      {tab === 'congress' && (
        <>
          {congressLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!congressLoading && congressEvents.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No recent congressional trades tracked in your watchlist. Source:
              Quiver Quant live feed (1000 most-recent records, House + Senate
              combined) + House Clerk PTR PDFs for followed reps.
            </div>
          )}
          {!congressLoading && congressGroups.length > 0 && (
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
        </>
      )}

      {/* === Tab content: ARK (placeholder until scanner ships) === */}
      {tab === 'ark' && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.6]">
          🔵 <b>ARK Innovation</b> (Cathie Wood) — daily holdings disclosure
          from <code>ark-funds.com</code> covering ARKK / ARKQ / ARKG / ARKW /
          ARKF / ARKX. Scanner pending — once live this tab will show
          per-fund net buys/sells with 1-day latency (much fresher than 13F's
          quarterly cycle). Style: 创新 / disruptive long bets.
        </div>
      )}

      {/* === Tab content: Insider Form 4 (placeholder) === */}
      {tab === 'insider' && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.6]">
          ⚪ <b>Insider Form 4</b> — SEC-mandated <b>2-day</b> disclosure for
          corporate officers/directors. Scanner pending. Will surface:
          (1) <b>cluster buys</b> — ≥3 insiders buying same ticker in 30 days
          (strong bullish), (2) <b>CEO open-market buys ≥ $100k</b> —
          executive putting personal cash in. Sells filtered out (often
          mechanical 10b5-1 plans, low signal).
        </div>
      )}
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
  const followedKey = isFollowedRep(group.rep)
  const followed = followedKey ? FOLLOWED_CONGRESS[followedKey] : null
  const styleKey = followedKey ? CONGRESS_STYLE[followedKey] : null
  // Pinned anchors get a slightly stronger border + ⭐ marker so the
  // user can find them at a glance without reading every name.
  const containerClass = followed
    ? 'rounded border border-[var(--color-accent)]/60 bg-[var(--color-accent)]/[0.04] p-2'
    : 'rounded border border-[var(--color-border)]/60 bg-[var(--color-panel)]/30 p-2'
  return (
    <div className={containerClass}>
      <div className="flex items-center gap-2 mb-1.5 text-[10px]">
        {followed && <span className="text-[10px]" title="followed anchor">⭐</span>}
        <span className="font-semibold text-[var(--color-text)]" title={followed?.intro ?? ''}>
          {group.rep}
          {followed && (
            <span className="ml-1.5 text-[9.5px] text-[var(--color-dim)] font-normal">
              · {followed.cn}
            </span>
          )}
        </span>
        <StyleTag k={styleKey} />
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
      {followed && (
        <div className="text-[9px] italic text-[var(--color-dim)] mb-1.5 leading-[1.4]">
          {followed.intro}
        </div>
      )}
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
  const styleKey = WHALE_STYLE[whaleKey]
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
        <StyleTag k={styleKey} />
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
