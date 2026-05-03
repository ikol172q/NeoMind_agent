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
  // ARK tab is a filtered view of the 13F whales — ark-funds.com daily
  // CSV is Cloudflare-walled (HTTP 403) so we use Cathie Wood's
  // quarterly 13F filing via the same whale_scanner pipeline.
  const qInsider = useRecentSignals({ scanner: 'insider_form4', limit: 100 })
  const [expanded, setExpanded] = useState(false)
  const [expandedCongress, setExpandedCongress] = useState(false)
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
  const groups_fresh = showStale.whales ? groups : groups.map((g) => ({
    ...g,
    events: g.events.filter((e) => isFresh(e) || whaleBypassAge(e)),
  })).filter((g) => g.events.length > 0)
  const congressEvents_fresh = showStale.congress
    ? congressEvents
    : congressEvents.filter((e) => isFresh(e) || congressBypassAge(e))
  const arkGroups_fresh = showStale.ark ? arkGroups : arkGroups.map((g) => ({
    ...g,
    // ARK tab IS the Cathie Wood anchor — bypass age unconditionally,
    // user explicitly opened her tab.
    events: g.events,
  })).filter((g) => g.events.length > 0)
  const arkEvents_fresh = arkGroups_fresh.flatMap((g) => g.events)
  const insiderEvents_fresh = showStale.insider ? insiderEvents : insiderEvents.filter(isFresh)

  const n_stale = {
    whales:   events.length - events_fresh.length,
    congress: congressEvents.length - congressEvents_fresh.length,
    ark:      arkEvents.length - arkEvents_fresh.length,
    insider:  insiderEvents.length - insiderEvents_fresh.length,
  }

  const tabs: Array<{ k: Tab; label: string; count: number; subtitle: string }> = [
    { k: 'whales',   label: '🐋 13F 机构',     count: events_fresh.length,
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
        <span className="font-semibold text-[var(--color-text)]">Smart Money</span>
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
            <li>顶部 "↻ 立即扫描" → 跑所有 scanner → 新数据 30s 内自动出现, <b>不用 page reload</b>.</li>
            <li>每 30s 自动 background poll, 你不用管.</li>
            <li>各 tab <b>自动隐藏过期 events</b>: Form 4 {MAX_AGE_DAYS.insider}d / 国会 {MAX_AGE_DAYS.congress}d / 13F + ARK {MAX_AGE_DAYS.whales}d. 想看更老的, 点下面 "show {n_stale[tab]} stale" 按钮.</li>
          </ul>
        </div>
      )}

      {/* === Show-stale toggle for current tab === */}
      {n_stale[tab] > 0 && (
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
      {tab === 'whales' && (
        <>
          {q13f.isLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!q13f.isLoading && groups_fresh.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No recent 13F filings in the last {MAX_AGE_DAYS.whales} days.
              Whale scanner runs daily; events appear within 1-2 days of SEC
              publication.
            </div>
          )}
          {!q13f.isLoading && groups_fresh.length > 0 && (
            <div className="space-y-2">
              {groups_fresh.slice(0, expanded ? groups_fresh.length : 3).map((g) => (
                <WhaleGroup key={g.whale} group={g} />
              ))}
              {groups_fresh.length > 3 && (
                <button
                  onClick={() => setExpanded((v) => !v)}
                  className="text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] mt-1"
                >
                  {expanded ? `▴ collapse` : `▾ show ${groups_fresh.length - 3} more whales`}
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
          {q13f.isLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!q13f.isLoading && arkGroups_fresh.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No ARK 13F holdings in the last {MAX_AGE_DAYS.ark} days.
              Trigger ↻ 立即扫描 (in Today's Signals widget above) to
              fetch SEC filings.
            </div>
          )}
          {!q13f.isLoading && arkGroups_fresh.length > 0 && (
            <div className="space-y-2">
              {arkGroups_fresh.map((g) => (
                <WhaleGroup key={g.whale} group={g} />
              ))}
            </div>
          )}
        </>
      )}

      {/* === Tab content: Insider Form 4 === */}
      {tab === 'insider' && (
        <>
          <div className="text-[9px] italic text-[var(--color-dim)] mb-2 leading-[1.5]">
            ⚪ <b>Insider Form 4</b> — SEC-mandated <b>2-day</b> disclosure
            (the freshest signal in this widget). Source: openinsider.com.
            Sells filtered out (often mechanical 10b5-1 exits). High =
            ≥$1M total OR ≥5 insiders. Click 🔗 to see full insider
            history for that ticker.
          </div>
          {qInsider.isLoading && (
            <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
          )}
          {!qInsider.isLoading && insiderEvents_fresh.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
              No insider buys in the last {MAX_AGE_DAYS.insider} days.
              Trigger ↻ 立即扫描 to fetch latest cluster buys + large CEO
              open-market purchases.
            </div>
          )}
          {!qInsider.isLoading && insiderEvents_fresh.length > 0 && (
            <div className="space-y-1">
              {insiderEvents_fresh.slice(0, 30).map((e) => (
                <InsiderRow key={e.event_id} event={e} />
              ))}
              {insiderEvents_fresh.length > 30 && (
                <div className="text-[9px] text-[var(--color-dim)] mt-1">
                  + {insiderEvents_fresh.length - 30} more — refine via openinsider.com
                </div>
              )}
            </div>
          )}
        </>
      )}
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
        <span className="font-medium text-[var(--color-text)] font-mono w-14 flex-shrink-0">
          {event.ticker}
        </span>
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
