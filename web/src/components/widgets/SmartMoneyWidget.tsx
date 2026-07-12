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
import { useRecentSignals, useSignalsByWhale, type SignalEvent } from '@/lib/api'
import { useStockResearch } from '@/components/research/StockResearchContext'
import { useWhaleResearch } from '@/components/research/WhaleResearchContext'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useCollapsed } from '@/lib/useCollapsed'


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
  cathie:        { cn: '凯瑟琳·伍德 (ARK)',
                   intro: '颠覆性创新派 · ARKK/ARKQ/ARKG 等 · 重仓 TSLA/COIN/PLTR · 高 beta 高波动' },
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
  cathie:  'innovation',
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


// Click ticker → opens Stock Research Drawer (in-app, deep dive on
// company / smart money exposure / supply chain / news / your notes).
// TradingView is reachable from inside the drawer Overview tab as a
// secondary link. Cmd/Ctrl-click bypasses to TradingView for users
// who just want a quick chart.
function TickerLink({
  ticker, className,
}: { ticker?: string | null; className?: string }) {
  const { openTicker } = useStockResearch()
  if (!ticker) return <span className={className}>—</span>
  return (
    <button
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey) {
          window.open(`https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`, '_blank')
        } else {
          openTicker(ticker)
        }
      }}
      className={`${className ?? ''} text-left hover:text-[var(--color-accent)] hover:underline`}
      title={`点开 ${ticker} 深度研究 · ⌘ 点击直接去 TradingView`}
    >
      {ticker}
    </button>
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
  // Per-scanner pagination — default 100, click "load 100 more" to
  // bump. Single state per scanner so each tab's pagination is
  // independent and survives tab switches.
  const limit13f = 100  // legacy firehose query kept for n_stale calc in non-whale tabs; not user-adjustable anymore
  const [collapsed, toggle] = useCollapsed('smart-money')
  const [limitStockAct, setLimitStockAct] = useState(100)
  const [limitHouseClerk, setLimitHouseClerk] = useState(100)
  const [limitInsider, setLimitInsider] = useState(100)

  const q13f = useRecentSignals({ scanner: '13f', limit: limit13f })
  // Two scanner sources cover Congress: Quiver feed (most reps, free,
  // ~1000 records) + House Clerk PDF parser (text-PDF reps that Quiver
  // gates behind paid tier — currently just Pelosi). Merge in widget.
  const qStockAct = useRecentSignals({ scanner: 'stock_act', limit: limitStockAct })
  const qHouseClerk = useRecentSignals({ scanner: 'house_clerk_pdf', limit: limitHouseClerk })
  // ARK tab is a filtered view of the 13F whales — ark-funds.com daily
  // CSV is Cloudflare-walled (HTTP 403) so we use Cathie Wood's
  // quarterly 13F filing via the same whale_scanner pipeline.
  const qInsider = useRecentSignals({ scanner: 'insider_form4', limit: limitInsider })
  const [expanded, setExpanded] = useState(false)
  const [expandedCongress, setExpandedCongress] = useState(false)
  // 2026-05-19: 13F tab view mode + per-whale expand state.
  // - 'by_whale' (default): each whale collapsed showing action chips;
  //   click to expand the per-event detail rows. Lets user scan all
  //   30 whales at once.
  // - 'by_time': flat firehose across all whales sorted by source_timestamp
  //   desc — for "what's the latest news from any smart-money source".
  type WhaleView = 'by_whale' | 'by_time'
  const [whaleView, setWhaleView] = useState<WhaleView>('by_whale')
  const [openWhales, setOpenWhales] = useState<Set<string>>(new Set())
  const toggleWhale = (key: string) => setOpenWhales(prev => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })
  // 2026-05-19: per-whale event count selector — solves the "load more
  // only loads one whale" bug. Backend returns top-N per whale via
  // SQLite window function, so every whale is represented even when
  // a few have hundreds of filings.
  const [perWhaleLimit, setPerWhaleLimit] = useState<5 | 10 | 20 | 50>(5)
  const qByWhale = useSignalsByWhale({ scanner: '13f', limit_per_whale: perWhaleLimit })
  // Tabs replace the old stacked sections so the widget doesn't grow
  // taller as we add data sources. Default = whales (Buffett etc) since
  // that's the section users came here for originally.
  type Tab = 'whales' | 'congress' | 'ark' | 'insider'
  const [tab, setTab] = useState<Tab>('whales')
  // Help panel toggle — explains what each tab means + auto-refresh
  // behavior + staleness policy.
  const [showHelp, setShowHelp] = useState(false)
  // Per-tab max-age in days — events older than this are hidden by
  // default. User can toggle "show stale" to reveal. Different cadence
  // = different sensible windows. Form 4 is meant to be fresh.
  const MAX_AGE_DAYS: Record<Tab, number> = {
    insider:  14,   // 2-day disclosure window, anything > 2w is past acting on
    congress: 60,   // 45-day window + a couple weeks of post-publish action time
    ark:      120,  // quarterly cadence + 45-day SEC delay = ~135 days max useful
    whales:   120,
  }
  const [showStale, setShowStale] = useState<Record<Tab, boolean>>({
    whales: false, congress: false, ark: false, insider: false,
  })

  // Filter helper: keep events whose source_timestamp (real trade date)
  // or detected_at falls within the tab's window. Falls back to
  // detected_at when source_timestamp is missing/parse-fails.
  const ageMs = MAX_AGE_DAYS[tab] * 86_400_000
  const cutoff = Date.now() - ageMs
  function isFresh(e: SignalEvent): boolean {
    const ts = e.source_timestamp || e.detected_at
    if (!ts) return false
    const t = new Date(ts).getTime()
    return isFinite(t) && t >= cutoff
  }

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
  // (congressGroups removed — Congress tab now re-groups inside the
  // tab body using the age-filtered congressEvents_fresh.)

  // ARK = Cathie Wood subset of 13F whales (whale_key='cathie'),
  // shown as its own tab so user can drill in without scrolling
  // past 10 other funds.
  const arkGroups = groups.filter(
    (g) => String((g.events[0]?.body as Record<string, unknown> | undefined)?.whale_key ?? '') === 'cathie',
  )
  const arkEvents = arkGroups.flatMap((g) => g.events)
  const insiderEvents = (qInsider.data?.events ?? []) as SignalEvent[]

  // Followed anchors (Pelosi/Tina Smith/Cleo Fields, plus the
  // ARK/Cathie Wood case) are explicitly pinned — they bypass the
  // age filter unconditionally. The whole reason the user picked
  // them is to keep watching regardless of when they last traded.
  function congressBypassAge(e: SignalEvent): boolean {
    const b = (e.body ?? {}) as Record<string, unknown>
    const rep = String(b.representative ?? b.senator ?? '')
    return isFollowedRep(rep) !== null
  }
  function whaleBypassAge(e: SignalEvent): boolean {
    // ARK = Cathie Wood is an explicit anchor (own tab). All other
    // whales follow the standard window.
    const wk = String((e.body as Record<string, unknown> | undefined)?.whale_key ?? '')
    return wk === 'cathie'
  }

  // Apply per-tab age filter unless user toggled "show stale" OR the
  // event belongs to a followed anchor.
  const events_fresh = showStale.whales
    ? events
    : events.filter((e) => isFresh(e) || whaleBypassAge(e))
  const congressEvents_fresh = showStale.congress
    ? congressEvents
    : congressEvents.filter((e) => isFresh(e) || congressBypassAge(e))
  // ARK tab = Cathie Wood subset. Source from the per-whale endpoint
  // (qByWhale) so we get her full ~25-50 quarter moves; the legacy
  // firehose query was capped at 200 events sorted by detected_at and
  // would miss Cathie entirely when Norges+Rentech monopolized the slots.
  // ARK is an anchor (whaleBypassAge('cathie') === true) so no age filter.
  const arkGroupsFromByWhale: { whale: string; events: SignalEvent[] }[] =
    ((qByWhale.data?.whales ?? []).filter(g => g.whale_key === 'cathie'))
      .map(g => ({ whale: g.whale, events: g.events }))
  const arkGroups_fresh = arkGroupsFromByWhale.filter(g => g.events.length > 0)
  const arkEvents_fresh = arkGroups_fresh.flatMap((g) => g.events)
  const insiderEvents_fresh = showStale.insider ? insiderEvents : insiderEvents.filter(isFresh)

  const n_stale = {
    whales:   events.length - events_fresh.length,
    congress: congressEvents.length - congressEvents_fresh.length,
    ark:      arkEvents.length - arkEvents_fresh.length,
    insider:  insiderEvents.length - insiderEvents_fresh.length,
  }

  // 13F tab count comes from the new per-whale endpoint (qByWhale)
  // — events_fresh from the legacy firehose query is biased by 2-3
  // busy whales monopolizing the slots and badly under-counts the
  // actual recent activity across all 30 whales.
  const whales13fCount = ((qByWhale.data?.whales ?? []) as Array<{ events: SignalEvent[]; whale_key: string }>)
    .reduce((s, g) => s + g.events.filter(e => showStale.whales || isFresh(e) || g.whale_key === 'cathie').length, 0)

  const tabs: Array<{ k: Tab; label: string; count: number; subtitle: string }> = [
    { k: 'whales',   label: '🐋 13F 机构',     count: whales13fCount,
      subtitle: `SEC 45 天延迟 · 仅多头 · 11 funds · 仅显示 ${MAX_AGE_DAYS.whales}d 内` },
    { k: 'congress', label: '🏛 国会议员',     count: congressEvents_fresh.length,
      subtitle: `45 天披露窗口 · 金额是区间 · 仅显示 ${MAX_AGE_DAYS.congress}d 内` },
    { k: 'ark',      label: '🔵 ARK 创新',     count: arkEvents_fresh.length,
      subtitle: `Cathie Wood · 13F 季度 · 仅显示 ${MAX_AGE_DAYS.ark}d 内` },
    { k: 'insider',  label: '⚪ 内部 (Form 4)', count: insiderEvents_fresh.length,
      subtitle: `CEO/CFO 自掏腰包 · 2 天披露 · 最快 · 仅显示 ${MAX_AGE_DAYS.insider}d 内` },
  ]
  const activeTab = tabs.find((t) => t.k === tab)!

  return (
    <div
      data-testid="smart-money-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5"
    >
      {/* === Tab bar === */}
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)] flex-wrap">
        <button
          onClick={toggle}
          title={collapsed ? '展开' : '折叠'}
          className="flex items-center gap-1 font-semibold text-[var(--color-text)] hover:opacity-80"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          Smart Money
        </button>
        <button
          onClick={() => setShowHelp((v) => !v)}
          className="text-[10px] w-4 h-4 rounded-full border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-dim)] hover:text-[var(--color-text)] flex items-center justify-center"
          title="什么是 Smart Money / 各 tab 含义 / 刷新机制"
        >
          ?
        </button>
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

      {!collapsed && (<>
      {/* === Help panel (toggle via ?) === */}
      {showHelp && (
        <div className="mb-2 rounded border border-[var(--color-border)] bg-[var(--color-panel)]/40 p-2 text-[9.5px] leading-[1.55] text-[var(--color-dim)]">
          <div className="font-semibold text-[var(--color-text)] mb-1">📚 Smart Money 是什么</div>
          <p className="mb-1.5">
            汇总市场中"信息更靠前"的几类投资者最近在买卖什么. 不是抄作业 — 是<b>看他们看到了什么你还没看到</b>, 把<b>他们的高 conviction signal</b> 跟你自己的 thesis 交叉验证.
          </p>
          <ul className="ml-3 list-disc space-y-0.5 mb-1.5">
            <li><b>🐋 13F 机构</b> — 大型对冲基金 (Buffett/Bridgewater/Druckenmiller 等 11 家) 的季度持仓变化. SEC 强制 45 天内披露. <i>慢但 conviction 高</i>.</li>
            <li><b>🏛 国会议员</b> — Pelosi 等参/众议员买卖股票的强制披露 (STOCK Act). 最长 45 天延迟. ⭐ 标记的是你 follow 的 anchor.</li>
            <li><b>🔵 ARK 创新</b> — Cathie Wood 颠覆性创新主题 ETF (ARKK 等). 重仓 AI / 生物科技 / fintech. 跟 Buffett 派完全相反, 高波动.</li>
            <li><b>⚪ 内部 Form 4</b> — 公司高管 (CEO/CFO/董事) 用自己的钱买自家股票, SEC 强制 <b>2 天</b>披露 — <b>最快</b>的信号. 只显示买入 (卖出常是套现/期权计划, 信号弱).</li>
          </ul>
          <div className="font-semibold text-[var(--color-text)] mt-1.5 mb-0.5">🔄 刷新 + 过期</div>
          <ul className="ml-3 list-disc space-y-0.5">
            <li>本 tab 上方 <b>Today's Signals</b> widget 的 "↻ 拉取全部数据源" → 跑全部 7 个 scanner → 新数据 30s 内自动出现, <b>不用 page reload</b>.</li>
            <li>想只刷某个 scanner: 顶栏 <b>scanners</b> 徽章 → dropdown 每行有 ↻ 按钮.</li>
            <li>每 30s 自动 background poll + scheduler 每小时 fire 一次, 你不用管.</li>
            <li>各 tab <b>自动隐藏过期 events</b>: Form 4 {MAX_AGE_DAYS.insider}d / 国会 {MAX_AGE_DAYS.congress}d / 13F + ARK {MAX_AGE_DAYS.whales}d. 想看更老的, 点下面 "show {n_stale[tab]} stale" 按钮.</li>
          </ul>
        </div>
      )}

      {/* === Show-stale toggle for current tab ===
         Hidden for `whales` and `ark` tabs because those now use the
         per-whale endpoint (qByWhale) and have their own accurate stale
         counter rendered inside the tab body. Showing both was confusing
         and the numbers were inconsistent (legacy firehose vs new query). */}
      {n_stale[tab] > 0 && tab !== 'whales' && tab !== 'ark' && (
        <div className="mb-2 text-[9px] text-[var(--color-dim)] flex items-center gap-2">
          <span>🕐 {n_stale[tab]} 条事件超过 {MAX_AGE_DAYS[tab]} 天 (已隐藏)</span>
          <button
            onClick={() => setShowStale((s) => ({ ...s, [tab]: !s[tab] }))}
            className="text-[9px] underline hover:text-[var(--color-text)]"
          >
            {showStale[tab] ? '隐藏 stale' : '显示 stale'}
          </button>
        </div>
      )}

      {/* === Tab content: 13F whales === */}
      {tab === 'whales' && (() => {
        // Build the per-whale groups from the new endpoint. Falls back to
        // the legacy `groups_fresh` shape so WhaleGroup component works
        // unchanged. The new endpoint guarantees every whale that has
        // any history shows up — no more "load more" hunting.
        const byWhaleData = qByWhale.data
        const byWhaleGroups: { whale: string; events: SignalEvent[]; whaleKey: string; nTotalEvents: number }[] =
          (byWhaleData?.whales ?? []).map(g => ({
            whale: g.whale,
            events: g.events,
            whaleKey: g.whale_key,
            nTotalEvents: g.n_events,
          }))
        // Apply freshness filter only if the user hasn't toggled "show stale".
        // ALWAYS drop 0-event whales (the backend returns placeholders for
        // whales that exist in the WHALES registry but have no history yet —
        // useful for the count badge but useless to render as empty cards).
        const byWhaleGroupsFresh = (showStale.whales
          ? byWhaleGroups
          : byWhaleGroups.map(g => ({
              ...g,
              events: g.events.filter(e => isFresh(e) || g.whaleKey === 'cathie'),
            }))
        ).filter(g => g.events.length > 0)
        const totalEventsByWhale = byWhaleGroups.reduce((s, g) => s + g.events.length, 0)
        const totalEventsByWhaleFresh = byWhaleGroupsFresh.reduce((s, g) => s + g.events.length, 0)
        const nStaleByWhale = totalEventsByWhale - totalEventsByWhaleFresh
        // 0-event whales — separate so the user can still open their drawer
        // (some are curated, e.g. Cascade/Gates). Rendered as a subtle
        // "无最近活动" footer link list, name-only, click → drawer.
        const noEventWhales = byWhaleGroups.filter(g => g.events.length === 0)

        return (
          <>
            {qByWhale.isLoading && (
              <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
            )}

            {/* Stale toggle specific to by-whale view — always available if any stale exist */}
            {!qByWhale.isLoading && nStaleByWhale > 0 && (
              <div className="mb-2 text-[9px] text-[var(--color-dim)] flex items-center gap-2">
                <span>🕐 {nStaleByWhale} 条事件 &gt; {MAX_AGE_DAYS.whales} 天</span>
                <button
                  onClick={() => setShowStale(s => ({ ...s, whales: !s.whales }))}
                  className="text-[9px] underline hover:text-[var(--color-text)]"
                >
                  {showStale.whales ? '隐藏 stale' : `显示 ${nStaleByWhale} 条 stale`}
                </button>
              </div>
            )}

            {!qByWhale.isLoading && byWhaleGroupsFresh.length === 0 && (
              <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
                没有 fresh 13F 数据 (过去 {MAX_AGE_DAYS.whales} 天内). 上面"显示 stale"看历史数据.
              </div>
            )}

            {!qByWhale.isLoading && byWhaleData && (
              <>
                {/* View mode + per-whale limit controls */}
                <div className="flex items-center gap-2 mb-2 text-[9.5px] flex-wrap">
                  <span className="text-[var(--color-dim)]">视图:</span>
                  <button
                    onClick={() => setWhaleView('by_whale')}
                    className={'px-1.5 py-0.5 rounded border font-mono ' +
                      (whaleView === 'by_whale'
                        ? 'border-[var(--color-accent)] text-[var(--color-text)] bg-[var(--color-accent)]/10'
                        : 'border-[var(--color-border)]/60 text-[var(--color-dim)] hover:border-[var(--color-accent)]/60')}
                    title="每个机构一个卡片, 默认收起. 点击展开看具体动作"
                  >
                    📚 按机构 ({byWhaleGroupsFresh.length}/{byWhaleData.n_whales_total})
                  </button>
                  <button
                    onClick={() => setWhaleView('by_time')}
                    className={'px-1.5 py-0.5 rounded border font-mono ' +
                      (whaleView === 'by_time'
                        ? 'border-[var(--color-accent)] text-[var(--color-text)] bg-[var(--color-accent)]/10'
                        : 'border-[var(--color-border)]/60 text-[var(--color-dim)] hover:border-[var(--color-accent)]/60')}
                    title="跨机构最新动作时间线, 不分组"
                  >
                    ⏱ 最新时间线 ({totalEventsByWhaleFresh})
                  </button>

                  <span className="text-[var(--color-dim)] ml-2">每 whale:</span>
                  {([5, 10, 20, 50] as const).map(n => (
                    <button
                      key={n}
                      onClick={() => setPerWhaleLimit(n)}
                      className={'px-1.5 py-0.5 rounded border font-mono ' +
                        (perWhaleLimit === n
                          ? 'border-[var(--color-accent)] text-[var(--color-text)] bg-[var(--color-accent)]/10'
                          : 'border-[var(--color-border)]/60 text-[var(--color-dim)] hover:border-[var(--color-accent)]/60')}
                      title={`每个机构最多显示 ${n} 条最近事件`}
                    >
                      {n}
                    </button>
                  ))}

                  {whaleView === 'by_whale' && (
                    <>
                      <button
                        onClick={() => setOpenWhales(new Set(byWhaleGroupsFresh.map(g => g.whale)))}
                        className="ml-auto text-[9px] text-[var(--color-dim)] hover:text-[var(--color-text)] underline"
                      >
                        全部展开
                      </button>
                      <button
                        onClick={() => setOpenWhales(new Set())}
                        className="text-[9px] text-[var(--color-dim)] hover:text-[var(--color-text)] underline"
                      >
                        全部收起
                      </button>
                    </>
                  )}
                </div>

                {whaleView === 'by_whale' && (
                  <div className="space-y-1.5">
                    {byWhaleGroupsFresh.map((g) => (
                      <WhaleGroup
                        key={g.whale}
                        group={{ whale: g.whale, events: g.events }}
                        isOpen={openWhales.has(g.whale)}
                        onToggle={() => toggleWhale(g.whale)}
                      />
                    ))}
                    {noEventWhales.length > 0 && (
                      <NoEventWhalesFooter whales={noEventWhales} />
                    )}
                  </div>
                )}

                {whaleView === 'by_time' && (
                  <WhaleTimeline
                    events={byWhaleGroupsFresh.flatMap(g => g.events)
                      .sort((a, b) => {
                        const ta = new Date(a.source_timestamp || a.detected_at || 0).getTime()
                        const tb = new Date(b.source_timestamp || b.detected_at || 0).getTime()
                        return tb - ta
                      })
                      .slice(0, expanded ? totalEventsByWhaleFresh : 40)}
                  />
                )}
                {whaleView === 'by_time' && totalEventsByWhaleFresh > 40 && (
                  <button
                    onClick={() => setExpanded((v) => !v)}
                    className="text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] mt-1"
                  >
                    {expanded ? '▴ 仅显示前 40 条' : `▾ 显示全部 ${totalEventsByWhaleFresh} 条`}
                  </button>
                )}
              </>
            )}
          </>
        )
      })()}

      {/* === Tab content: Congress === */}
      {tab === 'congress' && (
        <>
          {congressLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!congressLoading && congressEvents_fresh.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No recent congressional trades in the last {MAX_AGE_DAYS.congress}
              days. Source: Quiver Quant live feed + House Clerk PTR PDFs.
            </div>
          )}
          {!congressLoading && congressEvents_fresh.length > 0 && (() => {
            // Re-group filtered events by rep so the per-rep cards
            // reflect only the fresh window.
            const byRepFresh = new Map<string, { rep: string; chamber: string; party: string; events: SignalEvent[] }>()
            for (const e of congressEvents_fresh) {
              const b = (e.body ?? {}) as Record<string, unknown>
              const rep = String(b.representative ?? b.senator ?? 'Unknown')
              const chamber = String(b.chamber ?? '')
              const party = String(b.party ?? '')
              if (!byRepFresh.has(rep)) byRepFresh.set(rep, { rep, chamber, party, events: [] })
              byRepFresh.get(rep)!.events.push(e)
            }
            // Sort each rep's events by actual transaction_date desc.
            // house_clerk_pdf scanner emits in PDF iteration order, NOT
            // by date, so without this sort Pelosi's rows render in
            // arbitrary order. stock_act (Quiver) backend already
            // sorts, but applying the same sort here is idempotent and
            // future-proof.
            for (const g of byRepFresh.values()) {
              g.events.sort((a, b) => {
                const ta = String((a.body as Record<string, unknown> | undefined)?.transaction_date ?? a.source_timestamp ?? '')
                const tb = String((b.body as Record<string, unknown> | undefined)?.transaction_date ?? b.source_timestamp ?? '')
                if (ta < tb) return 1
                if (ta > tb) return -1
                return 0
              })
            }
            const congressGroupsFresh = Array.from(byRepFresh.values()).sort((a, b) => {
              const fa = isFollowedRep(a.rep) ? 0 : 1
              const fb = isFollowedRep(b.rep) ? 0 : 1
              if (fa !== fb) return fa - fb
              return new Date(b.events[0]?.detected_at ?? 0).getTime()
                   - new Date(a.events[0]?.detected_at ?? 0).getTime()
            })
            return (
              <div className="space-y-2">
                {congressGroupsFresh.slice(0, expandedCongress ? congressGroupsFresh.length : 5).map((g) => (
                  <CongressGroup key={g.rep} group={g} />
                ))}
                {congressGroupsFresh.length > 5 && (
                  <button
                    onClick={() => setExpandedCongress((v) => !v)}
                    className="text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] mt-1"
                  >
                    {expandedCongress
                      ? `▴ collapse`
                      : `▾ show ${congressGroupsFresh.length - 5} more members`}
                  </button>
                )}
              </div>
            )
          })()}
          <LoadMoreButton
            currentLimit={limitStockAct + limitHouseClerk}
            currentCount={congressEvents.length}
            onLoadMore={() => {
              setLimitStockAct((l) => l + 100)
              setLimitHouseClerk((l) => l + 100)
            }}
            label="Congress"
          />
        </>
      )}

      {/* === Tab content: ARK = Cathie Wood subset of 13F === */}
      {tab === 'ark' && (
        <>
          <div className="text-[9px] italic text-[var(--color-dim)] mb-2 leading-[1.5]">
            🔵 <b>ARK Innovation (Cathie Wood)</b> — quarterly 13F filing.
            ark-funds.com daily CSV is Cloudflare-walled (HTTP 403); we use
            the SEC 13F instead, which gives the same holdings at quarterly
            cadence with 45-day delay. Future: add a daily scanner if we
            find a stable scrape path.
          </div>
          {qByWhale.isLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!qByWhale.isLoading && arkGroups_fresh.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No ARK 13F holdings in the last {MAX_AGE_DAYS.ark} days.
              Trigger "↻ 拉取全部数据源" in the Today's Signals widget
              above (or 顶栏 scanners 徽章 → 13F 行 ↻) to fetch SEC filings.
            </div>
          )}
          {!qByWhale.isLoading && arkGroups_fresh.length > 0 && (
            <div className="space-y-2">
              {arkGroups_fresh.map((g) => (
                <WhaleGroup
                  key={g.whale}
                  group={g}
                  isOpen={openWhales.has(g.whale)}
                  onToggle={() => toggleWhale(g.whale)}
                />
              ))}
            </div>
          )}
          {/* LoadMoreButton removed — ARK now uses the per-whale endpoint
              which loads top-N per whale based on the per-whale limit
              selector, not a global firehose pagination. */}
        </>
      )}

      {/* === Tab content: Insider Form 4 === */}
      {tab === 'insider' && (
        <InsiderTabBody
          isLoading={qInsider.isLoading}
          events={insiderEvents_fresh}
          totalRaw={insiderEvents.length}
          maxAge={MAX_AGE_DAYS.insider}
          onLoadMore={() => setLimitInsider((l) => l + 100)}
          currentLimit={limitInsider}
        />
      )}
      </>)}
    </div>
  )
}


function InsiderRow({ event }: { event: SignalEvent }) {
  const body = (event.body ?? {}) as Record<string, unknown>
  const company = String(body.company ?? '')
  const industry = String(body.industry ?? '')
  const nIns = Number(body.n_insiders ?? 1)
  const valueUsd = Number(body.value_usd ?? 0)
  const tradeDate = String(body.trade_date ?? '')
  const price = Number(body.price ?? 0)
  const qty = Number(body.qty ?? 0)
  const return1w = String(body.return_1w ?? '').trim()
  const return1d = String(body.return_1d ?? '').trim()
  const isCluster = nIns >= 2
  const valueDisplay =
    valueUsd >= 1_000_000 ? `$${(valueUsd / 1_000_000).toFixed(1)}M` :
    valueUsd >= 1_000     ? `$${Math.round(valueUsd / 1_000)}K` :
                            `$${Math.round(valueUsd)}`
  const qtyDisplay = qty >= 1_000_000 ? `${(qty / 1_000_000).toFixed(1)}M sh` :
                     qty >= 1_000     ? `${(qty / 1_000).toFixed(0)}K sh` :
                     qty > 0          ? `${qty} sh` : ''
  const sevClass = event.severity === 'high'
    ? 'text-[var(--color-green,#7ed98c)] border-[var(--color-green,#7ed98c)]/40'
    : 'text-[var(--color-amber,#e5a200)] border-[var(--color-amber,#e5a200)]/40'

  // Color the post-trade returns: green = stock went up (signal paid),
  // red = stock went down. Empty string = no data yet (very recent buy).
  function returnClass(s: string) {
    if (!s || s === 'N/A') return 'text-[var(--color-dim)]'
    if (s.startsWith('+')) return 'text-[var(--color-green,#7ed98c)]'
    if (s.startsWith('-')) return 'text-[var(--color-red,#e07070)]'
    return 'text-[var(--color-dim)]'
  }

  return (
    <div className="rounded border border-[var(--color-border)]/40 bg-[var(--color-panel)]/20 px-1.5 py-1">
      {/* Top row: badge + ticker + company + value + 🔗 + date */}
      <div className="flex items-center gap-2 text-[10px]">
        <span className={`px-1 py-0 rounded border text-[8.5px] font-mono flex-shrink-0 ${sevClass}`}>
          {isCluster ? `${nIns}人买` : '买'}
        </span>
        <TickerLink
          ticker={event.ticker}
          className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0"
        />
        <span className="text-[9px] text-[var(--color-text)] truncate flex-1">
          {company}
        </span>
        <span className="text-[9.5px] text-[var(--color-text)] font-mono flex-shrink-0">
          {valueDisplay}
        </span>
        {event.source_url && (
          <a
            href={event.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[8.5px] text-[var(--color-accent)] hover:underline flex-shrink-0"
            title="点击看该股全部内部交易历史 (openinsider.com)"
          >
            🔗
          </a>
        )}
        <span className="text-[8.5px] text-[var(--color-dim)] font-mono w-16 text-right flex-shrink-0">
          {tradeDate}
        </span>
      </div>
      {/* Bottom row: detail line — price / qty / industry / post-trade returns */}
      <div className="flex items-center gap-2 text-[8.5px] text-[var(--color-dim)] font-mono mt-0.5 ml-[3.5rem]">
        {price > 0 && <span>@${price.toFixed(2)}</span>}
        {qtyDisplay && <span>· {qtyDisplay}</span>}
        {industry && <span className="truncate">· {industry}</span>}
        {(return1d || return1w) && (
          <span className="ml-auto flex-shrink-0">
            {return1d && (
              <span className="mr-1">
                1d <span className={returnClass(return1d)}>{return1d}</span>
              </span>
            )}
            {return1w && (
              <span>
                1w <span className={returnClass(return1w)}>{return1w}</span>
              </span>
            )}
          </span>
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
      <TickerLink
        ticker={event.ticker}
        className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0"
      />
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


function WhaleGroup({
  group, isOpen, onToggle,
}: {
  group: { whale: string; events: SignalEvent[] }
  isOpen: boolean
  onToggle: () => void
}) {
  const latest = group.events[0]
  const whaleKey = String(
    (latest?.body as Record<string, unknown> | undefined)?.whale_key ?? '',
  )
  const filingDate = String(
    (latest?.body as Record<string, unknown> | undefined)?.filing_date ?? '',
  )
  const cn = WHALE_CN[whaleKey]
  const styleKey = WHALE_STYLE[whaleKey]
  const { openWhale } = useWhaleResearch()

  // Tally moves by action_type so the collapsed header shows e.g. "新建 1 · 加仓 4 · 减仓 8 · 清仓 2"
  const tally = { new: 0, increase: 0, decrease: 0, exit: 0 }
  for (const e of group.events) {
    const ct = String((e.body as Record<string, unknown> | undefined)?.change_type ?? '')
    if (ct in tally) (tally as Record<string, number>)[ct]++
  }

  return (
    <div className="rounded border border-[var(--color-border)]/60 bg-[var(--color-panel)]/30">
      {/* Header — always visible, click anywhere to toggle */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-[10px] hover:bg-[var(--color-border)]/10 text-left"
      >
        <span className="text-[10px] text-[var(--color-dim)] w-3 flex-shrink-0">
          {isOpen ? '▾' : '▸'}
        </span>
        <span
          onClick={(ev) => {
            if (whaleKey) {
              ev.stopPropagation()
              openWhale(whaleKey)
            }
          }}
          role="link"
          tabIndex={0}
          className="font-semibold text-[var(--color-text)] hover:text-[var(--color-accent,#7ed9d9)] hover:underline cursor-pointer"
          title={whaleKey ? `Open ${group.whale} encyclopedia · ${cn?.intro ?? ''}` : (cn?.intro ?? '')}
        >
          {group.whale}
        </span>
        {cn && (
          <span className="text-[9.5px] text-[var(--color-dim)] font-normal">
            · {cn.cn}
          </span>
        )}
        <StyleTag k={styleKey} />
        {/* Action chips — color-coded so user sees activity profile at a glance */}
        <div className="flex items-center gap-1 flex-wrap">
          {tally.new > 0 && (
            <span className="text-[8.5px] px-1 rounded border border-[var(--color-green,#7ed98c)]/40 text-[var(--color-green,#7ed98c)] font-mono">
              新建 {tally.new}
            </span>
          )}
          {tally.increase > 0 && (
            <span className="text-[8.5px] px-1 rounded border border-[var(--color-green,#7ed98c)]/40 text-[var(--color-green,#7ed98c)] font-mono">
              加仓 {tally.increase}
            </span>
          )}
          {tally.decrease > 0 && (
            <span className="text-[8.5px] px-1 rounded border border-[var(--color-amber,#e5a200)]/40 text-[var(--color-amber,#e5a200)] font-mono">
              减仓 {tally.decrease}
            </span>
          )}
          {tally.exit > 0 && (
            <span className="text-[8.5px] px-1 rounded border border-[var(--color-red,#e07070)]/40 text-[var(--color-red,#e07070)] font-mono">
              清仓 {tally.exit}
            </span>
          )}
        </div>
        {filingDate && (
          <span className="ml-auto text-[8.5px] text-[var(--color-dim)] font-mono">
            {filingDate}
          </span>
        )}
      </button>
      {/* Body — only when expanded */}
      {isOpen && (
        <div className="px-2 pb-2 pt-1 border-t border-[var(--color-border)]/30">
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
      )}
    </div>
  )
}


// Flat firehose: cross-whale chronological list. Each row tags which
// whale made the move so the user can spot patterns (e.g. multiple
// whales all buying NVDA in same week).
function WhaleTimeline({ events }: { events: SignalEvent[] }) {
  const { openWhale } = useWhaleResearch()
  // Sort by source_timestamp desc (most recent filing first) with
  // detected_at as fallback.
  const sorted = [...events].sort((a, b) => {
    const ta = new Date(a.source_timestamp || a.detected_at || 0).getTime()
    const tb = new Date(b.source_timestamp || b.detected_at || 0).getTime()
    return tb - ta
  })
  return (
    <div className="space-y-0.5">
      {sorted.map((e) => {
        const b = (e.body ?? {}) as Record<string, unknown>
        const whaleKey = String(b.whale_key ?? '')
        const whaleName = String(b.whale ?? 'Unknown')
        const filingDate = String(b.filing_date ?? e.source_timestamp ?? '').slice(0, 10)
        const badge = changeBadge(e.signal_type)
        const valueK = b.value_usd_k
        const name = b.name as string | undefined
        const badgeClass =
          badge.color === 'green' ? 'text-[var(--color-green,#7ed98c)] border-[var(--color-green,#7ed98c)]/40' :
          badge.color === 'red'   ? 'text-[var(--color-red,#e07070)] border-[var(--color-red,#e07070)]/40' :
                                    'text-[var(--color-amber,#e5a200)] border-[var(--color-amber,#e5a200)]/40'
        return (
          <div key={e.event_id} className="flex items-center gap-2 text-[10px] py-0.5">
            <span className="text-[8.5px] text-[var(--color-dim)] font-mono w-16 flex-shrink-0 truncate">
              {filingDate}
            </span>
            <button
              onClick={() => whaleKey && openWhale(whaleKey)}
              disabled={!whaleKey}
              className="text-[9.5px] text-[var(--color-text)] hover:text-[var(--color-accent,#7ed9d9)] hover:underline disabled:no-underline disabled:cursor-default font-semibold w-32 flex-shrink-0 truncate text-left"
              title={whaleKey ? `Open ${whaleName} encyclopedia` : ''}
            >
              {whaleName}
            </button>
            <span className={`px-1 rounded border text-[8.5px] font-mono flex-shrink-0 ${badgeClass}`}>
              {badge.label}
            </span>
            <TickerLink
              ticker={e.ticker}
              className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0"
            />
            {name && (
              <span className="text-[9px] text-[var(--color-dim)] truncate flex-1">{name}</span>
            )}
            <span className="text-[9.5px] text-[var(--color-dim)] font-mono flex-shrink-0">
              {formatValueUSD(valueK)}
            </span>
          </div>
        )
      })}
    </div>
  )
}


// Subtle footer listing whales with no recent 13F events. Some of these
// (Cascade/Marks/ValueAct etc) have curated bilingual profiles and the
// user might still want to open their drawer for learning. Without this
// they'd be completely inaccessible from the UI.
function NoEventWhalesFooter({
  whales,
}: { whales: { whale: string; whaleKey: string }[] }) {
  const { openWhale } = useWhaleResearch()
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2 pt-2 border-t border-[var(--color-border)]/30 text-[9px] text-[var(--color-dim)]">
      <button
        onClick={() => setOpen(v => !v)}
        className="hover:text-[var(--color-text)]"
      >
        {open ? '▴ 隐藏' : '▾ 展开'} {whales.length} 个无最近 13F 活动的 whale (可点开看 curated profile)
      </button>
      {open && (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
          {whales.map(w => (
            <button
              key={w.whaleKey}
              onClick={() => openWhale(w.whaleKey)}
              className="text-[10px] text-[var(--color-text)]/70 hover:text-[var(--color-accent,#7ed9d9)] hover:underline"
            >
              {w.whale}
            </button>
          ))}
        </div>
      )}
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
      <TickerLink
        ticker={event.ticker}
        className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0"
      />
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


function LoadMoreButton({
  currentLimit, currentCount, onLoadMore, label,
}: {
  currentLimit: number
  currentCount: number
  onLoadMore: () => void
  label: string
}) {
  // If the API returned fewer events than we asked for, the DB is
  // exhausted — hide the button so the user knows there's nothing
  // older to fetch.
  const exhausted = currentCount < currentLimit
  if (exhausted) {
    return (
      <div className="text-[8.5px] text-[var(--color-dim)] italic mt-2 text-center">
        — DB 已到底, {currentCount} 条全部加载 ({label}) —
      </div>
    )
  }
  return (
    <button
      onClick={onLoadMore}
      className="w-full mt-2 px-2 py-1 text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] border border-[var(--color-border)]/40 hover:border-[var(--color-accent)]/60 rounded font-mono"
      title={`Currently loaded: ${currentCount} / asked for ${currentLimit}. Click to fetch 100 more from DB.`}
    >
      ▾ 加载更早 100 条 ({label}, 当前 {currentCount})
    </button>
  )
}


type InsiderSort = 'value' | 'date' | 'cluster' | 'return_1w'

function InsiderTabBody({
  isLoading, events, totalRaw, maxAge, onLoadMore, currentLimit,
}: {
  isLoading: boolean
  events: SignalEvent[]
  totalRaw: number
  maxAge: number
  onLoadMore: () => void
  currentLimit: number
}) {
  // Form 4 is dense — without sort/filter it's hard to find the high-
  // signal trades. Defaults: sort by value desc (largest dollar
  // commitments first), min 2 insiders (real cluster), no value floor.
  const [sortBy, setSortBy] = useState<InsiderSort>('value')
  const [minIns, setMinIns] = useState(2)
  const [minVal, setMinVal] = useState(0)

  function valueOf(e: SignalEvent): number {
    return Number((e.body as Record<string, unknown> | undefined)?.value_usd ?? 0)
  }
  function clusterOf(e: SignalEvent): number {
    return Number((e.body as Record<string, unknown> | undefined)?.n_insiders ?? 1)
  }
  function dateOf(e: SignalEvent): number {
    const ts = e.source_timestamp || e.detected_at
    return ts ? new Date(ts).getTime() : 0
  }
  function returnOf(e: SignalEvent): number {
    // Parse '+12.3%' / '-5.4%' / '' → numeric (empty = 0).
    const r = String((e.body as Record<string, unknown> | undefined)?.return_1w ?? '').replace('%', '').trim()
    const n = parseFloat(r)
    return isFinite(n) ? n : -Infinity  // empty returns sort to bottom
  }

  // Filter
  const filtered = events.filter(
    (e) => clusterOf(e) >= minIns && valueOf(e) >= minVal,
  )

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'value')     return valueOf(b)   - valueOf(a)
    if (sortBy === 'date')      return dateOf(b)    - dateOf(a)
    if (sortBy === 'cluster')   return clusterOf(b) - clusterOf(a)
    if (sortBy === 'return_1w') return returnOf(b)  - returnOf(a)
    return 0
  })

  return (
    <>
      <div className="text-[9px] italic text-[var(--color-dim)] mb-2 leading-[1.5]">
        ⚪ <b>Insider Form 4</b> — SEC-mandated <b>2-day</b> disclosure
        (the freshest signal in this widget). Source: openinsider.com.
        Sells filtered out (often mechanical 10b5-1 exits). High =
        ≥$1M total OR ≥5 insiders. Click 🔗 to see full insider
        history for that ticker.
      </div>

      {/* === Sort + filter controls === */}
      <div className="flex flex-wrap items-center gap-2 mb-2 text-[9.5px] text-[var(--color-dim)] bg-[var(--color-panel)]/30 rounded p-1.5 border border-[var(--color-border)]/40">
        <span className="font-semibold">排序:</span>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as InsiderSort)}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[9.5px]"
        >
          <option value="value">金额 desc (default)</option>
          <option value="cluster">人数 desc (cluster size)</option>
          <option value="date">日期 desc (最新)</option>
          <option value="return_1w">1 周回报 desc</option>
        </select>

        <span className="font-semibold ml-2">人数 ≥</span>
        <select
          value={minIns}
          onChange={(e) => setMinIns(Number(e.target.value))}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[9.5px]"
        >
          <option value={1}>1 (含单笔)</option>
          <option value={2}>2 (cluster, default)</option>
          <option value={3}>3 (强 cluster)</option>
          <option value={5}>5 (集体压注)</option>
        </select>

        <span className="font-semibold ml-2">金额 ≥</span>
        <select
          value={minVal}
          onChange={(e) => setMinVal(Number(e.target.value))}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[9.5px]"
        >
          <option value={0}>$0 (default)</option>
          <option value={100_000}>$100K</option>
          <option value={1_000_000}>$1M</option>
          <option value={10_000_000}>$10M</option>
        </select>

        <span className="ml-auto text-[8.5px] font-mono">
          {sorted.length} / {events.length} fresh / {totalRaw} raw
        </span>
      </div>

      {isLoading && (
        <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
      )}
      {!isLoading && sorted.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
          {events.length === 0
            ? `No insider buys in the last ${maxAge} days. 点上面 Today's Signals 的 "↻ 拉取全部数据源", 或顶栏 scanners 徽章 → insider_form4 行的 ↻.`
            : `没有 event 满足 filter (人数 ≥ ${minIns}, 金额 ≥ $${minVal.toLocaleString()}). 放宽 filter 试试.`}
        </div>
      )}
      {!isLoading && sorted.length > 0 && (
        <div className="space-y-1">
          {sorted.slice(0, 50).map((e) => (
            <InsiderRow key={e.event_id} event={e} />
          ))}
          {sorted.length > 50 && (
            <div className="text-[9px] text-[var(--color-dim)] mt-1 text-center">
              + {sorted.length - 50} more — 收紧 filter 看 top hits
            </div>
          )}
        </div>
      )}
      <LoadMoreButton
        currentLimit={currentLimit}
        currentCount={totalRaw}
        onLoadMore={onLoadMore}
        label="Form 4"
      />
    </>
  )
}
