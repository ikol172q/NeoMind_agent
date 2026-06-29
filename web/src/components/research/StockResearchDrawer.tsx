/**
 * Stock Research Drawer — REAL backend wired (Phase R1).
 *
 * Data sources (all hit /api/stock/{ticker}/...):
 *   - useStockProfile:   GET cached LLM profile (404 if not yet generated)
 *   - useRegenStockProfile: POST forces NeoMind LLM regen (~$0.01, 15-30s)
 *   - useStockExposure:  GET signal_events join, real Smart Money events
 *   - useStockNotes:     GET user notes timeline
 *   - useAppendStockNote: POST append note
 *   - useUpdateStockStatus: PATCH user_status + reason (persisted to DB)
 *
 * Fallback: when GET /profile returns 404 (no cached row), the Overview
 * tab shows an empty state inviting the user to click ✨ regenerate.
 * Other tabs (Smart Money / Notes / Chat) work independently — they
 * don't need the LLM profile to render.
 */
import { useState, useEffect, useRef } from 'react'
import { useStockResearch } from './StockResearchContext'
import {
  useStockProfile, useStockExposure, useStockNotes,
  useRegenStockProfile, useUpdateStockStatus, useAppendStockNote,
  useLiveQuote, useNextEarnings, useAnchoredFacts, useRegenAnchored,
  useTickerNews, useOfficialNews, useRefreshOfficialNews, useHolders, useRecentFilings,
  useFundamentals, useMetricsAsof, type Fundamentals, type LiveQuote,
  useWatchlistTiers, useWatchlistPromote, useWatchlistTouch,
  useWatchlistRemoveTier, useWatchlistSuggestions,
  // Phase W (2026-05-10): theses + audit
  useTheses, useThesisTemplate, useCreateThesis, useInvalidateThesis,
  useWatchlistAudit,
  // Phase 4: exit triggers eval
  useExitTriggers,
  // Phase 1B (2026-05-10): position state surfacing
  usePositionByTicker, usePortfolioSummary,
  // smart-money cross-cut per ticker
  useTickerSignalsByScanner,
  type StockExposureEvent, type AnchoredFacts, type NextEarnings,
  type StockProfile, type WatchlistTier,
  type InvestmentThesis,
} from '@/lib/api'
import {
  X, ExternalLink, Sparkles, BarChart3, Newspaper,
  NotebookPen, Building2, Loader2, ShieldCheck,
  Star, CircleDot, Eye, Lightbulb, History, AlertTriangle, Briefcase,
  RotateCw,
} from 'lucide-react'
import { AnchoredFactsPanel } from './AnchoredFactsPanel'
import { AgentSummary } from './AgentSummary'
import { ThesisReviewBanner } from './ThesisReviewBanner'

type Status = 'researching' | 'watching' | 'pass' | 'own'
type TabKey = 'overview' | 'smart_money' | 'notes'


// ── Metric definitions (中英释义) — click any header metric to review ──
const METRIC_DEFS: Record<string, {
  zh: string; en: string; desc: string; band?: string; why?: string; next?: string
}> = {
  cap: { zh: '市值', en: 'Market cap',
    desc: '股价 × 总股数 = 公司当前总市值，衡量规模。它是“市场给的价”，不是公司“值多少”。',
    band: '大盘 >$200B · 中盘 $10–200B · 小盘 <$10B',
    why: '规模越大越稳但越难高增长；小盘弹性大也更脆。',
    next: '增速 / 估值 —— 判断还有多少成长空间' },
  pe: { zh: '市盈率(静态)', en: 'Trailing P/E',
    desc: '股价 ÷ 过去 12 月 EPS。≈ 按当前盈利多少年回本。',
    band: '<15 偏低 · 15–30 常见 · >30 高(要增长撑) · <0 亏损则作废',
    why: 'PE 不含“增长”这一维 —— 单看会把高增长股误判成“贵”，所以它只是入口。',
    next: 'PEG(=PE÷增速)；亏损股 → 改用 P/S' },
  fwd: { zh: '前瞻市盈率', en: 'Forward P/E',
    desc: '股价 ÷ 未来 12 月预测 EPS。比静态更看未来，但依赖分析师预测。',
    band: 'fwd < 静态PE = 预期盈利在涨(好) · fwd 仍极高 = 增长也难撑',
    why: '前瞻能修正“静态 PE 高”，但分析师预测常偏乐观，别全信。',
    next: '增速 / PEG —— 验证预测合不合理' },
  year1: { zh: '近一年涨跌', en: '1-year return',
    desc: '过去一年总涨跌幅(情绪 + 基本面混合)。',
    band: '强势 ≠ 便宜；大涨后更要回头看估值',
    why: '价格是结果不是原因；高涨幅常已 price-in 好消息。',
    next: '估值链(PE/PEG) —— 涨完还贵不贵' },
  range52: { zh: '52 周区间', en: '52-week range',
    desc: '过去一年最低 ~ 最高。现价位置 = 技术强弱。',
    band: '靠高点(>80%) 强势/可能贵 · 靠低点(<20%) 价值/可能接飞刀',
    why: '只是技术位置，辅助“时机”，不决定“做不做”。',
    next: '财报日 —— 避开 / 利用催化剂' },
  earnings: { zh: '下次财报', en: 'Next earnings',
    desc: '下次季报/年报日 —— 最大短期催化剂，常伴大波动。括号是预测 EPS。',
    band: '临近(<2 周) = 波动放大，仓位 / 时机留意',
    why: '财报是基本面被重新定价的时点。',
    next: 'fwd vs 静态PE —— 看市场预期方向' },
}

// 其他对“单个公司”重要、但本表暂无实时数据的指标 —— 当速查卡, 帮你扩展看公司的维度。
// Generic click-popover (touch-friendly): click the trigger → small
// definition card; click outside / Esc closes.
function InfoPop({ children, className, title, body }: {
  children: React.ReactNode; className?: string; title: React.ReactNode; body: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown); document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <span ref={ref} className="relative inline-block">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o) }}
        className={'underline decoration-dotted decoration-[var(--color-dim)]/60 underline-offset-2 hover:text-[var(--color-text)] cursor-help ' + (className ?? '')}
      >
        {children}
      </button>
      {open && (
        <div className="absolute z-50 mt-1 left-0 top-full w-[270px] max-w-[78vw] px-3 py-2 rounded-md bg-[#0e1219] border border-[var(--color-accent)]/40 shadow-lg shadow-black/40 text-[11px] leading-[1.55] text-[var(--color-text)] font-normal text-left normal-case">
          <div className="font-semibold mb-0.5">{title}</div>
          <div className="text-[10.5px] text-[var(--color-text)]/85">{body}</div>
        </div>
      )}
    </span>
  )
}

// A header metric whose value is clickable → 释义 + 阈值 + 当前值落档 +
// 为什么这个阈值 + 接着看哪个指标 (the diagnostic chain, per metric).
// "📐 还看啥" — reference card of the other important per-company metrics.

// Universal "怎么读这些指标" reading flow — identical for every company.
// Click 🩺 to scan the whole chain at a glance.
// Bucket a live metric value against its threshold → short "当前档" label.

export function StockResearchDrawer() {
  const { ticker, closeTicker, openTicker, navStack, back } = useStockResearch()
  const [tab, setTab] = useState<TabKey>('overview')
  const [statusEditing, setStatusEditing] = useState<Status | null>(null)
  const [statusReasonDraft, setStatusReasonDraft] = useState('')
  const [noteDraft, setNoteDraft] = useState('')
  // Phase W: trigger linkage for the note being composed.
  // Either 'thesis:<id>' or 'signal:<id>' format. UI translates back
  // to backend's two separate fields. Empty = no trigger.
  const [noteTriggerSelection, setNoteTriggerSelection] = useState<string>('')

  const profileQ = useStockProfile(ticker)
  const exposureQ = useStockExposure(ticker)
  const notesQ = useStockNotes(ticker)
  const regenMu = useRegenStockProfile()
  const statusMu = useUpdateStockStatus()
  const noteMu = useAppendStockNote()
  const liveQuoteQ = useLiveQuote(ticker)
  const earningsQ = useNextEarnings(ticker)
  const anchoredQ = useAnchoredFacts(ticker)
  const regenAnchoredMu = useRegenAnchored()
  const isRegenAnchoredForThis = regenAnchoredMu.isPending && regenAnchoredMu.variables === ticker

  // Watchlist tier state — read current tier so we can show
  // Core/Adjacent/Watching badge + tier-change buttons.
  const tiersQ = useWatchlistTiers()
  const promoteMu = useWatchlistPromote()
  const touchMu = useWatchlistTouch()
  const removeTierMu = useWatchlistRemoveTier()
  const currentEntry = ticker
    ? Object.values(tiersQ.data?.tiers ?? {})
        .flat()
        .find(e => e.ticker === ticker.toUpperCase())
    : undefined
  const [showSuggestions, setShowSuggestions] = useState(false)

  useEffect(() => {
    if (!ticker) return
    setTab('overview')
    setStatusEditing(null)
    setStatusReasonDraft('')
    setNoteDraft('')
    setShowSuggestions(false)
    // Bump last_reviewed_at — opening the drawer counts as a thesis
    // touch. Server returns ok even if ticker not in watchlist.
    touchMu.mutate(ticker)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  // 2026-05-16: ESC closes the drawer (UX expectation). Without this,
  // the backdrop overlay (z-40) lingers and intercepts ALL clicks on
  // the rest of the page — including top-nav tab buttons — leaving
  // the app feeling frozen until the user notices the dimmed overlay.
  useEffect(() => {
    if (!ticker) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeTicker()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ticker, closeTicker])

  if (!ticker) return null

  const profile = profileQ.data
  const hasProfile = !!profile?.summary
  const effectiveStatus = profile?.user_status as Status | undefined
  const exposureEvents: StockExposureEvent[] = exposureQ.data?.events ?? []
  const notes = notesQ.data?.notes ?? []
  // The drawer doesn't unmount on ticker switch (it's a single instance
  // mounted at App root), so the regen/status/note mutations are
  // shared across all tickers viewed in this session. Gate any
  // pending/error UI on `mutation.variables === ticker` so an
  // in-flight call for AAPL doesn't render as "生成中…" on GOOGL's
  // drawer when the user clicks through.
  const isRegenForThisTicker = regenMu.isPending && regenMu.variables === ticker
  const regenErrorForThisTicker = regenMu.error && regenMu.variables === ticker
    ? regenMu.error
    : null

  function commitStatus(skipReason: boolean) {
    if (!ticker || !statusEditing) return
    const reason = skipReason ? '(no reason given)' : statusReasonDraft.trim()
    if (!skipReason && !reason) return
    statusMu.mutate({ ticker, status: statusEditing, reason: reason || '(empty)' })
    setStatusEditing(null)
    setStatusReasonDraft('')
  }

  function commitNote() {
    if (!ticker || !noteDraft.trim()) return
    // Phase W: parse trigger selection to backend fields. Format is
    // 'thesis:<uuid>' or 'signal:<uuid>'. Empty = no trigger linkage.
    const args: {
      ticker: string; body: string
      trigger_thesis_id?: string; trigger_signal_id?: string
    } = { ticker, body: noteDraft.trim() }
    if (noteTriggerSelection.startsWith('thesis:')) {
      args.trigger_thesis_id = noteTriggerSelection.slice(7)
    } else if (noteTriggerSelection.startsWith('signal:')) {
      args.trigger_signal_id = noteTriggerSelection.slice(7)
    }
    noteMu.mutate(args)
    setNoteDraft('')
    setNoteTriggerSelection('')
  }

  function regenerate() {
    if (!ticker) return
    regenMu.mutate(ticker)
  }

  const tabs: Array<{ k: TabKey; label: string; icon: typeof BarChart3; badge?: number }> = [
    { k: 'overview',     label: 'Overview · 全貌',  icon: Building2 },
    { k: 'smart_money',  label: 'Smart Money 接触', icon: BarChart3, badge: exposureEvents.length },
    { k: 'notes',        label: '我的笔记',          icon: NotebookPen, badge: notes.length },
  ]

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={closeTicker} />
      <div className="fixed top-0 right-0 h-full w-[820px] max-w-[90vw] bg-[var(--color-bg)] border-l border-[var(--color-border)] z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-start gap-3 px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/60">
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xl font-bold text-[var(--color-text)] font-mono">{ticker}</span>
              <span className="text-sm text-[var(--color-text)]">
                {liveQuoteQ.data?.name
                  ?? (liveQuoteQ.isLoading ? 'loading…' : '—')}
              </span>
              <StatusPillSelector
                current={effectiveStatus}
                userStatusReason={profile?.user_status_reason ?? null}
                userStatusTs={profile?.user_status_ts ?? null}
                onPick={(s) => { setStatusEditing(s); setStatusReasonDraft('') }}
              />
            </div>
            <div className="text-[10px] text-[var(--color-dim)] mt-1 flex items-center gap-3 flex-wrap">
              {/* Sector — yfinance live only. We deliberately do NOT
                  fall back to LLM profile.sector because the user
                  can't tell the source from the rendered chip. If
                  yfinance has no sector for this ticker, show
                  nothing (chip omitted). */}
              {liveQuoteQ.data?.sector && (
                <span>
                  {liveQuoteQ.data.sector}
                  {liveQuoteQ.data.industry && ` · ${liveQuoteQ.data.industry}`}
                </span>
              )}
              {/* quick stats — yfinance live, with day-change ▲▼ */}
              {liveQuoteQ.data?.price != null && (
                <span data-testid="live-price">
                  · ${liveQuoteQ.data.price.toFixed(2)}
                  {liveQuoteQ.data.day_change_pct != null && (
                    <span className={liveQuoteQ.data.day_change_pct >= 0 ? 'text-emerald-400 ml-1' : 'text-red-400 ml-1'}>
                      {liveQuoteQ.data.day_change_pct >= 0 ? '▲' : '▼'}
                      {Math.abs(liveQuoteQ.data.day_change_pct).toFixed(2)}%
                    </span>
                  )}
                </span>
              )}
              {/* Metric brief removed (2026-06-27): cap/PE/fwd/1y/52w/earnings
                  + 🩺诊断链 + 📐还看啥 都折叠进 Overview 的「📊 基本面 · 诊断链」
                  (每个 chip 带 中文 + EN + 定义 + 阈值)。顶部只留价格/当日涨跌锚点。
                  下次财报见 Overview 的「📅 Next catalyst」。 */}
              {/* Old LLM-only profile.style_verdict deliberately
                  removed from header — the SEC-anchored verdict is
                  now displayed in the Overview tab body (emerald
                  box) where it has proper provenance. Showing two
                  competing verdicts in different places would be
                  confusing, and the unmarked LLM one in the header
                  blended into the live yfinance data. */}
            </div>
          </div>
          {/* Walk breadcrumb — supports the user's "from news/anchor →
              up/down chain" workflow. Each ticker click pushes a
              frame; ← back pops one. Empty stack hides the button. */}
          {navStack.length > 0 && (
            <button
              onClick={back}
              title={`back to ${navStack[navStack.length - 1]} (walk history: ${navStack.join(' → ')})`}
              className="text-[10px] px-2 py-1 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-dim)] hover:text-[var(--color-text)] mr-1 flex items-center gap-1"
            >
              ← {navStack[navStack.length - 1]}
              {navStack.length > 1 && (
                <span className="text-[8.5px] italic">({navStack.length})</span>
              )}
            </button>
          )}
          <button
            onClick={closeTicker}
            className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1 rounded"
            title="ESC to close (clears walk history)"
          >
            <X size={16} />
          </button>
        </div>

        {/* Status reason editor */}
        {statusEditing && (
          <div className="flex items-center gap-2 px-4 py-2 bg-[var(--color-accent)]/10 border-b border-[var(--color-accent)]/40">
            <span className="text-[10px] text-[var(--color-text)] font-semibold">
              {STATUS_LABEL[statusEditing]}
            </span>
            <span className="text-[10px] text-[var(--color-dim)]">理由 (一句话):</span>
            <input
              type="text"
              autoFocus
              value={statusReasonDraft}
              onChange={(e) => setStatusReasonDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitStatus(false)
                if (e.key === 'Escape') setStatusEditing(null)
              }}
              placeholder="e.g. PE 太高 + 等中国出口管制明朗 (Enter 保存, Esc 取消)"
              className="flex-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-2 py-0.5 text-[10px] outline-none"
            />
            <button
              onClick={() => commitStatus(false)}
              disabled={!statusReasonDraft.trim() || statusMu.isPending}
              className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-accent)] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-40"
            >
              {statusMu.isPending ? '保存中…' : '保存'}
            </button>
            <button
              onClick={() => commitStatus(true)}
              className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
              title="跳过 (不推荐, 半年后会忘理由)"
            >
              跳过
            </button>
          </div>
        )}

        {/* Tier strip — Core/Adjacent/Watching badge + change buttons.
            Bumps the user's last_reviewed_at on every drawer open
            (touchMu in useEffect above) so the Watchlist tab "stale
            thesis" review prompts stay accurate. */}
        <TierStrip
          ticker={ticker}
          currentTier={currentEntry?.tier ?? null}
          parentTicker={currentEntry?.parent_ticker ?? null}
          onPromote={(tier, parent) => {
            promoteMu.mutate(
              { ticker, tier, parent_ticker: parent ?? undefined },
              { onError: (err) => alert(`promote failed: ${err.message}`) },
            )
          }}
          onRemove={() => {
            if (confirm(`从 watchlist 移除 ${ticker}?`)) {
              removeTierMu.mutate(ticker)
            }
          }}
          showSuggestions={showSuggestions}
          onToggleSuggestions={() => setShowSuggestions(s => !s)}
          coreTickers={(tiersQ.data?.tiers.core ?? []).map(e => e.ticker)}
        />

        {/* Suggestions panel — opens when user clicks ✨ Expand on a
            ticker that has anchored facts. Lists competitor / customer /
            supplier names extracted from the 10-K, each with verbatim
            quote, and lets the user one-click promote any to Adjacent
            (with this ticker as parent). */}
        {showSuggestions && (
          <SuggestionsPanel
            ticker={ticker}
            existingTickers={new Set([
              ...(tiersQ.data?.tiers.core ?? []),
              ...(tiersQ.data?.tiers.adjacent ?? []),
              ...(tiersQ.data?.tiers.watching ?? []),
            ].map(e => e.ticker))}
            onPromote={(s) => {
              // Pre-fill prompt with the extractor-recorded ticker if
              // present (e.g. ROKU's competitor row has ticker="AMZN"
              // for Amazon). For NVDA's supplier rows the ticker is
              // null (TSMC has no US listing), so user enters manually.
              const guess = s.ticker
                || s.name.split(/[\s,.]/)[0].toUpperCase()
              const symbol = (prompt(
                `把 "${s.name}" 加为 ${ticker} 的 Adjacent。\n请输入 trading symbol (跳过则不添加):`,
                guess,
              ) || '').trim().toUpperCase()
              if (!symbol) return
              promoteMu.mutate(
                { ticker: symbol, tier: 'adjacent', parent_ticker: ticker, note: `from ${ticker} 10-K: ${s.name}` },
                { onError: (err) => alert(`promote failed: ${err.message}`) },
              )
            }}
          />
        )}

        {/* Smart-money cross-cut (13F / insider / congress, 90d) — the
            quick-glance "who's trading this" block. */}
        <SmartMoneyCrossCutPanel ticker={ticker} />

        {/* Position panel — your lots for this ticker (cost / P&L /
            weight). Hidden if you don't own it. */}
        <PositionPanel ticker={ticker} />

        {/* Tab strip — overflow-x-auto so 6 tabs can scroll
            horizontally on mobile (otherwise they wrap or get
            clipped); flex-shrink-0 + whitespace-nowrap on buttons so
            each label stays on one line and isn't compressed.
            -webkit-overflow-scrolling for iOS momentum. */}
        <div
          className="flex border-b border-[var(--color-border)] bg-[var(--color-bg)] overflow-x-auto overscroll-x-contain"
          style={{ WebkitOverflowScrolling: 'touch' }}
        >
          {tabs.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={
                'flex-shrink-0 flex items-center gap-1.5 px-3 py-2 text-[11px] border-b-2 transition whitespace-nowrap ' +
                (tab === t.k
                  ? 'border-[var(--color-accent)] text-[var(--color-text)]'
                  : 'border-transparent text-[var(--color-dim)] hover:text-[var(--color-text)]')
              }
            >
              <t.icon size={11} />
              {t.label}
              {typeof t.badge === 'number' && t.badge > 0 && (
                <span className="text-[8.5px] text-[var(--color-dim)] font-mono ml-0.5">{t.badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto p-4 text-[var(--color-text)] text-[12px] leading-[1.6]">
          {tab === 'overview' && (
            <>
              <OverviewTabBody
                ticker={ticker}
                anchoredFacts={anchoredQ.data}
                anchoredLoading={anchoredQ.isLoading}
                earnings={earningsQ.data}
                regenAnchored={() => regenAnchoredMu.mutate(ticker)}
                isRegenAnchored={isRegenAnchoredForThis}
                regenAnchoredError={regenAnchoredMu.error && regenAnchoredMu.variables === ticker
                  ? regenAnchoredMu.error : null}
                legacyProfile={profile}
                legacyHasProfile={hasProfile}
                legacyRegenerate={regenerate}
                isLegacyRegen={isRegenForThisTicker}
                legacyRegenError={regenErrorForThisTicker}
                onEditThesis={() => setTab('notes')}
              />

              {/* 上下游 (SEC-anchored 竞品/客户/供应商) — folded in from the
                  old 上下游 tab so Overview is the single full picture of
                  everything we know about this name. */}
              <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
                <AnchoredFactsPanel ticker={ticker} onTickerClick={openTicker} />
              </div>

              {/* 持股结构 · 谁在买卖 — universal ownership from data
                  (institution/insider %, 锁定%/供给悬顶, top holders + Δ买卖). */}
              <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
                <HoldersSection ticker={ticker} />
              </div>

              {/* 最新 SEC 备案/事件 — freshness layer: 8-K(US)/6-K(foreign)
                  material events, dated + event-typed, authoritative + universal */}
              <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
                <RecentFilingsSection ticker={ticker} />
              </div>

              {/* 官方新闻 — primary-source PRs straight from the company
                  newsroom RSS (high signal; works even when miniflux is down). */}
              <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
                <OfficialNews ticker={ticker} />
              </div>

              {/* 近期新闻 — folded in from the old News tab (miniflux/RSS). */}
              <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
                <NewsTabBody ticker={ticker} />
              </div>
            </>
          )}

          {tab === 'smart_money' && (
            <SmartMoneyTabBody
              isLoading={exposureQ.isLoading}
              events={exposureEvents}
              ticker={ticker}
            />
          )}

          {tab === 'notes' && (
            <>
              {/* Phase W (2026-05-10): theses panel — your hypotheses
                  about this ticker. OPTIONAL; if no thesis exists, UI
                  invites you to add one but never blocks anything. */}
              <ThesesPanel
                ticker={ticker}
                exposureEvents={exposureEvents}
              />

              {/* Phase W: audit history — "why is this ticker on my
                  radar". Auto-populated from promote/demote/drop +
                  thesis create/invalidate events. */}
              <WatchlistAuditPanel ticker={ticker} />

              <div className="mb-2 mt-4 text-[10px] text-[var(--color-dim)] flex items-center gap-1">
                <NotebookPen size={11} /> 你的笔记 (DB 持久化)
              </div>
              <div className="space-y-2 mb-4">
                {notes.length === 0 && (
                  <div className="text-[10px] italic text-[var(--color-dim)] py-1">No notes yet — 写下你对这只股的想法.</div>
                )}
                {notes.map((n) => (
                  <div key={n.id} className="border border-[var(--color-border)]/40 rounded p-2">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-[9px] font-mono text-[var(--color-dim)]">{new Date(n.ts).toLocaleString()}</span>
                      {n.tag && (
                        <span className="text-[9px] font-mono px-1.5 py-0 rounded border border-amber-500/40 text-amber-300">
                          {n.tag}
                        </span>
                      )}
                      {n.source === 'llm-extract' && (
                        <span className="text-[8.5px] text-[var(--color-dim)] italic">(LLM)</span>
                      )}
                      {n.trigger_thesis_id && (
                        <span className="text-[8.5px] text-emerald-300/80 italic">
                          ↳ thesis-triggered
                        </span>
                      )}
                      {n.trigger_signal_id && (
                        <span className="text-[8.5px] text-blue-300/80 italic">
                          ↳ signal-triggered
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] whitespace-pre-wrap">{n.body}</p>
                  </div>
                ))}
              </div>
              <div className="border border-dashed border-[var(--color-border)] rounded p-2">
                <textarea
                  className="w-full bg-transparent text-[11px] outline-none resize-none"
                  rows={3}
                  placeholder="写一条笔记… (Cmd/Ctrl+Enter 保存)"
                  value={noteDraft}
                  onChange={(e) => setNoteDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) commitNote() }}
                />
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  {/* Phase W: optional trigger linkage. Pulls active
                      theses + recent signal_events for this ticker so
                      user can pick "this note was prompted by X" */}
                  <NoteTriggerSelector
                    ticker={ticker}
                    exposureEvents={exposureEvents}
                    value={noteTriggerSelection}
                    onChange={setNoteTriggerSelection}
                  />
                  <button
                    onClick={commitNote}
                    disabled={!noteDraft.trim() || noteMu.isPending}
                    className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-accent)] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-40"
                  >
                    {noteMu.isPending ? '保存中…' : 'add note'}
                  </button>
                  {noteMu.error && <span className="text-[9px] text-red-400">err: {noteMu.error.message}</span>}
                </div>
              </div>
            </>
          )}

        </div>
      </div>
    </>
  )
}


// ─── Smart Money exposure tab body — sort + filter ───────────────

const SOURCE_LABEL: Record<string, string> = {
  '13f':              '13F',
  'stock_act':        'Congress',
  'house_clerk_pdf':  'PDF',
  'insider_form4':    'Form 4',
  'news':             'News',
  'watchlist':        'Watchlist',
  'policy':           'Policy',
}

type ExposureSort = 'date_desc' | 'date_asc' | 'severity' | 'source'

// Format market cap to human-readable: $18.3B / $1.2T / $543M
function fmtCap(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(0)}M`
  return `$${n.toLocaleString()}`
}

function SmartMoneyTabBody({
  isLoading, events, ticker,
}: { isLoading: boolean; events: StockExposureEvent[]; ticker: string }) {
  // Default: most-recent first across all sources. Form-4 / News tend
  // to drown out 13F / Congress when sorted purely by date, so the
  // source filter is the main escape hatch when a user wants to
  // focus on "what funds did with this ticker".
  const [sortBy, setSortBy] = useState<ExposureSort>('date_desc')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [sevFilter, setSevFilter] = useState<string>('all')

  // Distinct sources actually present in the data — drives the
  // dropdown so we don't show options that have 0 events.
  const sources = Array.from(new Set(events.map((e) => e.scanner)))

  function dateOf(e: StockExposureEvent): number {
    const ts = e.source_timestamp || e.detected_at
    return ts ? new Date(ts).getTime() : 0
  }
  function sevRank(e: StockExposureEvent): number {
    return e.severity === 'high' ? 3 : e.severity === 'med' ? 2 : 1
  }

  const filtered = events.filter((e) => {
    if (sourceFilter !== 'all' && e.scanner !== sourceFilter) return false
    if (sevFilter    !== 'all' && e.severity !== sevFilter)    return false
    return true
  })

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'date_desc') return dateOf(b) - dateOf(a)
    if (sortBy === 'date_asc')  return dateOf(a) - dateOf(b)
    if (sortBy === 'severity')  return sevRank(b) - sevRank(a)
    if (sortBy === 'source')    return (SOURCE_LABEL[a.scanner] ?? a.scanner)
                                       .localeCompare(SOURCE_LABEL[b.scanner] ?? b.scanner)
    return 0
  })

  return (
    <>
      <div className="mb-2 text-[10px] text-[var(--color-dim)]">
        {ticker} 的 Smart Money 接触 (跨 13F / Congress / House Clerk PDF / Form 4 / News / Watchlist).
        实时 join signal_events, 60 秒自动 refetch.
      </div>

      {/* Sort + filter controls */}
      <div className="flex flex-wrap items-center gap-2 mb-2 text-[9.5px] text-[var(--color-dim)] bg-[var(--color-panel)]/30 rounded p-1.5 border border-[var(--color-border)]/40">
        <span className="font-semibold">排序:</span>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as ExposureSort)}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[9.5px]"
        >
          <option value="date_desc">日期 desc (最新)</option>
          <option value="date_asc">日期 asc (最早)</option>
          <option value="severity">severity desc</option>
          <option value="source">来源 a-z</option>
        </select>

        <span className="font-semibold ml-2">来源:</span>
        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[9.5px]"
        >
          <option value="all">All ({events.length})</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {SOURCE_LABEL[s] ?? s} ({events.filter((e) => e.scanner === s).length})
            </option>
          ))}
        </select>

        <span className="font-semibold ml-2">severity:</span>
        <select
          value={sevFilter}
          onChange={(e) => setSevFilter(e.target.value)}
          className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1 py-0.5 text-[9.5px]"
        >
          <option value="all">All</option>
          <option value="high">high only</option>
          <option value="med">med only</option>
          <option value="low">low only</option>
        </select>

        <span className="ml-auto text-[8.5px] font-mono">
          {sorted.length} / {events.length}
        </span>
      </div>

      {isLoading && <div className="text-[10px] text-[var(--color-dim)]">loading…</div>}
      {!isLoading && sorted.length === 0 && (
        <div className="text-[11px] italic text-[var(--color-dim)]">
          {events.length === 0
            ? `无 Smart Money 接触. 让 scanner 跑一轮: Today's Signals widget 点 ↻ 立即扫描.`
            : `没有 event 满足 filter. 放宽 filter 试试.`}
        </div>
      )}
      {!isLoading && sorted.length > 0 && (
        <div className="space-y-1">
          {sorted.map((e, i) => {
            const sourceLabel = SOURCE_LABEL[e.scanner] ?? e.scanner
            const sevClass = e.severity === 'high' ? 'text-[var(--color-green,#7ed98c)]' :
                             e.severity === 'med'  ? 'text-[var(--color-amber,#e5a200)]' : 'text-[var(--color-dim)]'
            const date = (e.source_timestamp || e.detected_at || '').slice(0, 10)
            return (
              <div key={i} className="flex items-start gap-2 text-[11px] py-1 px-2 border border-[var(--color-border)]/40 rounded">
                <span className={`text-[9px] font-mono w-16 flex-shrink-0 ${sevClass}`}>{sourceLabel}</span>
                <span className="flex-1">{e.title}</span>
                {e.source_url && (
                  <a href={e.source_url} target="_blank" rel="noopener noreferrer"
                     className="text-[9px] text-[var(--color-accent)] hover:underline flex-shrink-0">🔗</a>
                )}
                <span className="text-[8.5px] text-[var(--color-dim)] font-mono w-20 text-right flex-shrink-0">
                  {date}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}


// ─── helpers ──────────────────────────────────────────────────────


// ─── Status pill ──────────────────────────────────────────────────

const STATUS_LABEL: Record<Status, string> = {
  researching: '🔍 researching',
  watching:    '👀 watching',
  pass:        '✕ pass',
  own:         '✓ own',
}
const STATUS_COLOR: Record<Status, string> = {
  researching: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  watching:    'bg-blue-500/20 text-blue-300 border-blue-500/40',
  pass:        'bg-red-500/20 text-red-300 border-red-500/40',
  own:         'bg-green-500/20 text-green-300 border-green-500/40',
}

function StatusPillSelector({
  current, userStatusReason, userStatusTs, onPick,
}: {
  current?: Status
  userStatusReason: string | null
  userStatusTs: string | null
  onPick: (s: Status) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={`text-[10px] font-mono px-1.5 py-0.5 rounded border hover:brightness-125 ${
          current ? STATUS_COLOR[current] : 'border-[var(--color-border)] text-[var(--color-dim)]'
        }`}
        title={
          userStatusReason
            ? `状态: ${current ? STATUS_LABEL[current] : ''}\n理由: ${userStatusReason}\n更新: ${userStatusTs ? new Date(userStatusTs).toLocaleString() : ''}\n\n点击改变`
            : '点击设置状态 — 强制要求一句话理由, 6 个月后回看时知道为啥'
        }
      >
        {current ? STATUS_LABEL[current] : '⊕ set status'}
        <span className="ml-1 text-[8px]">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-50" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded shadow-lg z-50 w-44">
            {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
              <button
                key={s}
                onClick={() => { onPick(s); setOpen(false) }}
                className={`block w-full text-left px-2 py-1 text-[10px] hover:bg-[var(--color-panel)] ${
                  s === current ? 'bg-[var(--color-panel)]/50' : ''
                }`}
              >
                {STATUS_LABEL[s]}
                <span className="text-[8px] text-[var(--color-dim)] ml-1">
                  {s === 'researching' && '研究中, 未决定'}
                  {s === 'watching'    && '看好, 等 timing'}
                  {s === 'pass'        && '决定不买'}
                  {s === 'own'         && '已持有'}
                </span>
              </button>
            ))}
            {userStatusReason && (
              <div className="border-t border-[var(--color-border)] px-2 py-1.5 text-[8.5px] text-[var(--color-dim)] italic">
                上次理由: {userStatusReason}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}


// ─── Chat tab ─────────────────────────────────────────────────────


// ── Drawer per-ticker session picker (collapsible, with search) ──

// ── Overview tab body — anchored-first, legacy LLM in collapsed footer ──
interface OverviewBodyProps {
  ticker: string
  anchoredFacts: AnchoredFacts | undefined
  anchoredLoading: boolean
  earnings: NextEarnings | undefined
  regenAnchored: () => void
  isRegenAnchored: boolean
  regenAnchoredError: Error | null
  legacyProfile: StockProfile | null | undefined
  legacyHasProfile: boolean
  legacyRegenerate: () => void
  isLegacyRegen: boolean
  legacyRegenError: Error | null
  onEditThesis: () => void
}


// ── 我的认知 (共识 + 推断) — surfaced at the TOP of Overview ──────
// Reads the active thesis (the single per-ticker knowledge store) and
// renders its 共识 / 推断 sections as bullets, with inline [label](url)
// source links made clickable. Editing happens in the 我的笔记 tab.
function renderInlineLinks(text: string) {
  const parts = text.split(/(\[[^\]]+\]\([^)]+\))/g)
  return parts.map((part, i) => {
    const m = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
    if (m) {
      return (
        <a key={i} href={m[2]} target="_blank" rel="noopener noreferrer"
           className="text-[var(--color-accent)] hover:underline">
          {m[1]}<ExternalLink size={8} className="inline ml-0.5 -mt-0.5" />
        </a>
      )
    }
    return <span key={i}>{part}</span>
  })
}

// ── 认知维度标签 — categorize bullets so it's extensible across names.
// A bullet may start with [标签]; we render it as a colored chip and use
// the set of tags to show a "维度覆盖" checklist (what's still blank).
const COGNITION_TAGS: Record<string, string> = {
  业务:   'text-sky-300 border-sky-500/40',
  护城河: 'text-emerald-300 border-emerald-500/40',
  财务:   'text-teal-300 border-teal-500/40',
  估值:   'text-violet-300 border-violet-500/40',
  风险:   'text-red-300 border-red-500/40',
  管理层: 'text-amber-300 border-amber-500/40',
  股东:   'text-orange-300 border-orange-500/40',
  竞争:   'text-pink-300 border-pink-500/40',
  催化剂: 'text-lime-300 border-lime-500/40',
  技术:   'text-cyan-300 border-cyan-500/40',
  组合:   'text-fuchsia-300 border-fuchsia-500/40',
}
const STANDARD_DIMENSIONS = Object.keys(COGNITION_TAGS)

function parseTag(line: string): { tag: string | null; rest: string } {
  const m = line.match(/^\[([^\]]+)\]\s*/)
  if (m && COGNITION_TAGS[m[1]]) return { tag: m[1], rest: line.slice(m[0].length) }
  return { tag: null, rest: line }
}

function CognitionBullets({ md }: { md: string }) {
  const lines = md.split('\n')
    .map(l => l.replace(/^[-•·]\s*/, '').trim())
    .filter(l => l && l !== '-')
  if (lines.length === 0) {
    return <span className="text-[10px] italic text-[var(--color-dim)]">(空)</span>
  }
  return (
    <ul className="space-y-1">
      {lines.map((l, i) => {
        const { tag, rest } = parseTag(l)
        return (
          <li key={i} className="flex gap-1.5 text-[11px] leading-snug">
            <span className="text-[var(--color-dim)] flex-shrink-0">·</span>
            <span>
              {tag && (
                <span className={'text-[8.5px] px-1 rounded border mr-1 ' + COGNITION_TAGS[tag]}>
                  {tag}
                </span>
              )}
              {renderInlineLinks(rest)}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

// Which standard dimensions the thesis covers (any [tag] used) + which
// are still blank — a checklist that nudges filling the gaps, reusable
// across every ticker.
function DimensionCoverage({ text }: { text: string }) {
  const covered = new Set(STANDARD_DIMENSIONS.filter(t => text.includes(`[${t}]`)))
  return (
    <div className="mt-2 pt-2 border-t border-[var(--color-border)]/30">
      <div className="text-[9px] text-[var(--color-dim)] mb-1">
        维度覆盖 {covered.size}/{STANDARD_DIMENSIONS.length} · 灰色 = 还没写, 可补
      </div>
      <div className="flex flex-wrap gap-1">
        {STANDARD_DIMENSIONS.map(t => (
          <span key={t}
            className={'text-[8.5px] px-1 rounded border ' + (covered.has(t)
              ? COGNITION_TAGS[t]
              : 'text-[var(--color-dim)]/50 border-[var(--color-border)]/40 line-through')}>
            {t}
          </span>
        ))}
      </div>
    </div>
  )
}

function MyCognition({ ticker, onEdit }: { ticker: string; onEdit: () => void }) {
  const thesesQ = useTheses(ticker, 'active')
  const t = thesesQ.data?.theses?.[0]
  const consensus = t?.sections.consensus ?? ''
  const inference = t?.sections.inference ?? ''
  const hasAny = !!(consensus.trim() || inference.trim())
  return (
    <div className="mb-4 rounded border border-[var(--color-accent)]/30 bg-[var(--color-accent)]/[0.05] p-2.5">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Lightbulb size={12} className="text-[var(--color-accent)]" />
        <span className="text-[11px] font-semibold text-[var(--color-text)]">🧠 我的认知</span>
        <span className="text-[9px] italic text-[var(--color-dim)]">
          · 共识 = 已确认(附 source) · 推断 = 待验证
        </span>
        <button
          onClick={onEdit}
          className="ml-auto text-[9px] px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="去『我的笔记』tab 编辑/添加 共识 & 推断"
        >
          ✎ 编辑（我的笔记）
        </button>
      </div>
      {!hasAny && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1 leading-[1.6]">
          还没记录认知。去『我的笔记』tab 写下 <b className="not-italic text-sky-300">共识</b>
          （已查证的事实 + source）和 <b className="not-italic text-amber-300">推断</b>
          （你的前瞻判断）—— 这里会同步显示, 是把"未知"压成 conviction 的地方。
        </div>
      )}
      {hasAny && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="text-[9px] uppercase tracking-wider text-sky-300 mb-1">🔒 共识（已确认）</div>
              <CognitionBullets md={consensus} />
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-amber-300 mb-1">🔮 推断（待验证）</div>
              <CognitionBullets md={inference} />
            </div>
          </div>
          <DimensionCoverage text={consensus + '\n' + inference} />
        </>
      )}
    </div>
  )
}

function OverviewTabBody(p: OverviewBodyProps) {
  const facts = p.anchoredFacts?.facts ?? {}
  const meta = p.anchoredFacts?.meta
  const summary = facts.business_summary ?? []
  const segments = facts.segment ?? []
  const risks = facts.risk ?? []
  const verdict = (facts as any).style_verdict?.[0] as
    { tag?: string; paragraph?: string; evidence_quote?: string; source_url?: string } | undefined
  const totalAnchored = summary.length + segments.length + risks.length
  const hasAnchored = totalAnchored > 0

  return (
    <>
      {/* ⚠️ Goal 2 — evidence-driven review trigger: do NEW SEC events since
          your last review confirm / weaken / break this thesis? Reporter only. */}
      <ThesisReviewBanner ticker={p.ticker} />

      {/* 🤖 NeoMind 速读 — grounded 3-sentence read (优势/劣势/综合) over the
          whole verified picture; the exec summary above the detailed sections */}
      <AgentSummary ticker={p.ticker} />

      {/* 我的认知 — 共识 + 推断, front and center (the conviction loop) */}
      <MyCognition ticker={p.ticker} onEdit={p.onEditThesis} />

      {/* 基本面 · Tier-1 quality/valuation — closes the 🩺 诊断链 */}
      <FundamentalsSection ticker={p.ticker} />

      {/* Top action bar — anchored regen + external links */}
      <div className="mb-3 flex items-center gap-2 text-[10px] text-[var(--color-dim)] flex-wrap">
        <ShieldCheck size={11} className="text-emerald-400" />
        {meta?.source_filing_date
          ? <>SEC-anchored from 10-K filed {new Date(meta.source_filing_date).toLocaleDateString()}</>
          : 'No SEC-anchored data yet'}
        <button
          data-testid="overview-regen-anchored"
          onClick={p.regenAnchored}
          disabled={p.isRegenAnchored}
          className="ml-auto px-2 py-0.5 rounded border border-emerald-500/40 hover:border-emerald-300 text-emerald-300 flex items-center gap-1 disabled:opacity-50"
          title="Fetch latest 10-K from SEC EDGAR + extract all 6 fact types with verbatim-quote validation. ~60-90s."
        >
          {p.isRegenAnchored
            ? <><Loader2 size={10} className="animate-spin" /> 抽取中…</>
            : <><Sparkles size={10} /> {hasAnchored ? 're-extract from SEC' : 'extract from SEC 10-K'}</>}
        </button>
        <a
          href={`https://www.tradingview.com/symbols/${encodeURIComponent(p.ticker)}/`}
          target="_blank" rel="noopener noreferrer"
          className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1"
        >
          TradingView <ExternalLink size={9} />
        </a>
      </div>

      {p.regenAnchoredError && (
        <div className="mb-2 p-2 rounded border border-red-500/40 bg-red-500/10 text-[10px] text-red-300">
          抽取失败: {p.regenAnchoredError.message}
        </div>
      )}

      {!hasAnchored && !p.isRegenAnchored && !p.anchoredLoading && (
        <div className="text-[11px] italic text-[var(--color-dim)] py-3 leading-[1.6]">
          {p.ticker} 没 SEC-anchored data。点上面 ✨ extract — NeoMind 会从 SEC EDGAR
          拉最新 10-K，抽取 business summary / segments / risks / competitors / customers
          / suppliers / style verdict，每条带 verbatim quote。约 60-90 秒。
        </div>
      )}

      {/* Style verdict — most prominent when present */}
      {verdict && (
        <div data-testid="overview-style-verdict"
             className="mb-3 p-2.5 rounded border border-emerald-500/30 bg-emerald-500/5">
          <div className="text-[12px] font-semibold mb-1">{verdict.tag}</div>
          {verdict.paragraph && (
            <div className="text-[11px] leading-[1.6] text-[var(--color-text)]/90">{verdict.paragraph}</div>
          )}
          {verdict.evidence_quote && (
            <div className="mt-1.5 text-[9px] text-[var(--color-dim)] italic">
              ⛓ derived from anchored facts: <code>{verdict.evidence_quote.slice(0, 120)}{verdict.evidence_quote.length > 120 ? '…' : ''}</code>
            </div>
          )}
        </div>
      )}

      {/* Anchored business summary */}
      {summary.length > 0 && (
        <>
          <h3 className="text-[12px] font-semibold mb-1.5 flex items-center gap-1">
            <ShieldCheck size={11} className="text-emerald-400" /> 业务概览
            <span className="text-[9px] font-normal text-[var(--color-dim)]">· anchored to 10-K Item 1</span>
          </h3>
          <div className="mb-3 space-y-1.5">
            {summary.map((s, i) => (
              <div key={i} className="text-[11px] leading-[1.65]" title={s.evidence_quote}>
                {s.sentence}
                <span className="text-[9px] text-[var(--color-dim)] ml-1.5">⛓</span>
              </div>
            ))}
            {meta?.source_url && (
              <a href={meta.source_url} target="_blank" rel="noopener noreferrer"
                 className="text-[9px] text-emerald-400/70 hover:text-emerald-300 inline-flex items-center gap-0.5">
                view source 10-K <ExternalLink size={8} />
              </a>
            )}
          </div>
        </>
      )}

      {/* Anchored segments */}
      {segments.length > 0 && (
        <>
          <h3 className="text-[12px] font-semibold mb-1.5 flex items-center gap-1">
            <ShieldCheck size={11} className="text-emerald-400" /> 业务分段
            <span className="text-[9px] font-normal text-[var(--color-dim)]">· anchored to 10-K Item 7 MD&amp;A</span>
          </h3>
          <div className="space-y-1 mb-3">
            {segments.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-[11px]" title={s.evidence_quote}>
                <div className="w-24 flex-shrink-0">{s.name}</div>
                {s.revenue_pct != null && (
                  <>
                    <div className="flex-1 h-1.5 bg-[var(--color-panel)] rounded">
                      <div className="h-full bg-emerald-500/70 rounded" style={{ width: `${s.revenue_pct}%` }} />
                    </div>
                    <span className="text-[10px] text-[var(--color-dim)] font-mono w-10 text-right">{s.revenue_pct}%</span>
                  </>
                )}
                {s.period && <span className="text-[9.5px] text-[var(--color-dim)]">{s.period}</span>}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Real catalyst — next earnings date from yfinance */}
      {p.earnings?.next_date && p.earnings.days_until != null && (
        <>
          <h3 className="text-[12px] font-semibold mb-1.5 flex items-center gap-1">
            📅 Next catalyst
            <span className="text-[9px] font-normal text-[var(--color-dim)]">· yfinance live</span>
          </h3>
          <div className="mb-3 text-[11px]">
            <span className="text-amber-300 font-mono">{p.earnings.next_date}</span>
            <span className="ml-2">
              {p.earnings.days_until > 0
                ? `Earnings in ${p.earnings.days_until} days`
                : `Earnings ${Math.abs(p.earnings.days_until)} days ago`}
            </span>
            {p.earnings.eps_estimate_avg != null && (
              <span className="ml-2 text-[var(--color-dim)]">
                · EPS est ${p.earnings.eps_estimate_avg.toFixed(2)}
                {p.earnings.eps_estimate_low != null && p.earnings.eps_estimate_high != null &&
                  ` (${p.earnings.eps_estimate_low.toFixed(2)} – ${p.earnings.eps_estimate_high.toFixed(2)})`}
              </span>
            )}
          </div>
        </>
      )}

      {/* Anchored risks */}
      {risks.length > 0 && (
        <>
          <h3 className="text-[12px] font-semibold mb-1.5 text-red-300 flex items-center gap-1">
            <ShieldCheck size={11} className="text-emerald-400" /> 主要风险
            <span className="text-[9px] font-normal text-[var(--color-dim)]">· anchored to 10-K Item 1A</span>
          </h3>
          <ul className="space-y-1.5 mb-3">
            {risks.map((r, i) => (
              <li key={i} className="text-[11px] flex items-start gap-2" title={r.evidence_quote}>
                <span className={`text-[8px] mt-0.5 px-1 rounded border flex-shrink-0 ${
                  r.severity_signal === 'high' ? 'text-red-400 border-red-500/40' :
                  'text-[var(--color-dim)] border-[var(--color-border)]'}`}>
                  {r.category || 'risk'}
                </span>
                <span className="leading-snug">{r.headline}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Legacy LLM section — collapsed by default, shown for comparison */}
      {p.legacyHasProfile && (
        <details className="mt-4 pt-3 border-t border-[var(--color-border)]/50">
          <summary className="text-[10px] text-[var(--color-dim)] cursor-pointer hover:text-[var(--color-text)]">
            ▸ Legacy LLM-only output (no SEC verification) — click to expand
          </summary>
          <div className="opacity-60 mt-2">
            <div className="mb-3 flex items-center gap-2 text-[9px] text-[var(--color-dim)] flex-wrap">
              <Sparkles size={9} className="text-[var(--color-accent)]" />
              {p.legacyProfile?.generated_at &&
                `LLM generated · ${new Date(p.legacyProfile.generated_at).toLocaleString()}`}
              <button
                onClick={p.legacyRegenerate}
                disabled={p.isLegacyRegen}
                className="ml-auto px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1 disabled:opacity-50"
              >
                {p.isLegacyRegen
                  ? <><Loader2 size={9} className="animate-spin" /> regen</>
                  : <>✨ legacy regen</>}
              </button>
            </div>
            {p.legacyRegenError && (
              <div className="mb-2 p-1.5 rounded border border-red-500/40 bg-red-500/10 text-[9px] text-red-300">
                LLM 失败: {p.legacyRegenError.message}
              </div>
            )}
            {p.legacyProfile?.summary && (
              <p className="mb-2 text-[10px] leading-[1.6]">{p.legacyProfile.summary}</p>
            )}
            {p.legacyProfile?.style_verdict && (
              <div className="mb-2 text-[10px] italic">{p.legacyProfile.style_verdict}</div>
            )}
            {p.legacyProfile?.catalysts.length ? (
              <>
                <h4 className="text-[10px] font-semibold mb-1">LLM-guessed catalysts</h4>
                <ul className="space-y-0.5 mb-2">
                  {p.legacyProfile.catalysts.map((c, i) => (
                    <li key={i} className="text-[10px]">
                      <span className="font-mono text-[9px] text-[var(--color-dim)] mr-2">{c.when}</span>
                      {c.what}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        </details>
      )}
    </>
  )
}


// ── News tab body — miniflux per-ticker search ──
// ── 基本面 · Tier-1 quality/valuation metrics (closes the 诊断链) ──
type FundTone = 'good' | 'warn' | 'bad' | ''
const _pct = (v: number) => `${(v * 100).toFixed(1)}%`
const _money = (v: number) =>
  Math.abs(v) >= 1e9 ? `${v < 0 ? '-' : ''}$${(Math.abs(v) / 1e9).toFixed(1)}B`
  : Math.abs(v) >= 1e6 ? `${v < 0 ? '-' : ''}$${(Math.abs(v) / 1e6).toFixed(0)}M`
  : `$${v.toFixed(0)}`
const _ratio = (v: number) => v.toFixed(1)

const FUND_ROWS: Array<{
  key: keyof Fundamentals; zh: string; en: string; desc: string;
  fmt: (v: number) => string; band: string; why: string; tone: (v: number) => FundTone
}> = [
  { key: 'peg', zh: 'PEG', en: 'PEG ratio', desc: 'PE ÷ 盈利增速 —— 把估值用增长校正。',
    fmt: _ratio, band: '<1 便宜 · ~1 合理 · >2 贵', why: '把"高 PE"用增速校正; >2 = 即使算上增长也贵。',
    tone: v => v < 1 ? 'good' : v <= 2 ? 'warn' : 'bad' },
  { key: 'revenue_growth', zh: '营收增速', en: 'Revenue growth', desc: '营收同比增长率(近一年)。',
    fmt: _pct, band: '>20% 高 · 10–20% 稳 · <5% 成熟', why: '增长是高估值唯一的 justify。',
    tone: v => v > 0.2 ? 'good' : v > 0.05 ? 'warn' : 'bad' },
  { key: 'gross_margin', zh: '毛利率', en: 'Gross margin', desc: '(营收 − 成本) ÷ 营收, 反映定价权。',
    fmt: _pct, band: '>60% 类软件护城河 · <30% 商品化', why: '定价权/护城河强弱(行业相对)。',
    tone: v => v > 0.6 ? 'good' : v > 0.3 ? 'warn' : 'bad' },
  { key: 'profit_margin', zh: '净利率', en: 'Net margin', desc: '净利润 ÷ 营收, 综合盈利能力。',
    fmt: _pct, band: '越高越好(行业相对)', why: '综合盈利能力。',
    tone: v => v > 0.2 ? 'good' : v > 0.05 ? 'warn' : 'bad' },
  { key: 'roe', zh: 'ROE', en: 'Return on equity', desc: '净利润 ÷ 净资产 —— 资本回报效率(ROIC 代理)。',
    fmt: _pct, band: '>15% 好 · <8%(≈资金成本) 偏弱', why: '每 1 块净资产创造多少回报; ROIC yfinance 无, 用 ROE 代理。',
    tone: v => v > 0.15 ? 'good' : v > 0.08 ? 'warn' : 'bad' },
  { key: 'fcf', zh: '自由现金流', en: 'Free cash flow', desc: '经营现金流 − 资本支出 —— 可自由支配的现金。',
    fmt: _money, band: '正且增长 = 能自己造血', why: '真能拿来分红/回购/再投的钱, 比净利难粉饰。',
    tone: v => v > 0 ? 'good' : 'bad' },
  { key: 'net_debt', zh: '净负债', en: 'Net debt', desc: '有息负债 − 现金; 负数 = 净现金。',
    fmt: _money, band: '<0 = 净现金(稳) · 高 = 利率敏感', why: '抗风险/杠杆; 负数 = 现金多于有息负债。',
    tone: v => v < 0 ? 'good' : 'warn' },
  { key: 'price_to_sales', zh: '市销率', en: 'P/S', desc: '市值 ÷ 营收 —— 没正 PE 时的估值锚。',
    fmt: _ratio, band: '同业对比才有意义(亏损股用)', why: '没正 PE 时的估值锚。', tone: () => '' },
  { key: 'price_to_book', zh: '市净率', en: 'P/B', desc: '市值 ÷ 净资产。',
    fmt: _ratio, band: '重资产/金融更看', why: '轻资产科技参考性低。', tone: () => '' },
  { key: 'dividend_yield', zh: '股息率', en: 'Dividend yield', desc: '年股息 ÷ 股价; 成长股通常 ≈ 0。',
    fmt: _pct, band: '成长股≈0 · 价值/公用事业较高', why: '看分红回报; 对成长股意义小。', tone: () => '' },
  { key: 'beta', zh: 'Beta', en: 'Beta', desc: '相对大盘的波动系数。',
    fmt: _ratio, band: '~1 随大盘 · >1.5 高波动', why: '相对大盘的波动性。',
    tone: v => v > 1.5 ? 'warn' : '' },
  { key: 'ev_ebitda', zh: 'EV/EBITDA', en: 'EV/EBITDA', desc: '企业价值 ÷ EBITDA —— 含债的估值。EBITDA 为负时该比率无意义。',
    // EBITDA<0 → ratio is mathematically defined but financially meaningless
    // (a precise-looking negative number misleads). Show "n/m" instead, like
    // trailing P/E is nulled for unprofitable names.
    fmt: (v: number) => v <= 0 ? 'n/m' : _ratio(v), band: '越高越贵(含债的估值) · EBITDA<0 显示 n/m',
    why: '比 PE 更看企业价值(算上债)。',
    tone: v => v <= 0 ? '' : v > 30 ? 'bad' : v > 15 ? 'warn' : 'good' },
]

// Chip color by tone.
const CHIP_CLS: Record<FundTone, string> = {
  good: 'border-emerald-500/40 text-emerald-300',
  warn: 'border-amber-500/40 text-amber-300',
  bad:  'border-red-500/40 text-red-300',
  '':   'border-[var(--color-border)] text-[var(--color-text)]',
}

// Resolve a flow node (from quote OR fundamentals) → chip label + value +
// tone + full def (中文全名/EN/定义/阈值/为什么) for the tooltip.
type FlowM = { label: string; zh: string; en: string; value: string; tone: FundTone; desc: string; band: string; why: string }
function flowMetric(src: 'q' | 'f', key: string, q?: LiveQuote, f?: Fundamentals): FlowM {
  if (src === 'f') {
    const row = FUND_ROWS.find(r => r.key === (key as keyof Fundamentals))
    const v = f ? (f[key as keyof Fundamentals] as number | null) : null
    if (!row) return { label: key, zh: key, en: '', value: '—', tone: '', desc: '', band: '', why: '' }
    return { label: row.zh, zh: row.zh, en: row.en, value: v == null ? '—' : row.fmt(v),
             tone: v == null ? '' : row.tone(v), desc: row.desc, band: row.band, why: row.why }
  }
  const D = METRIC_DEFS
  const wrap = (dk: string, label: string, value: string, tone: FundTone): FlowM =>
    ({ label, zh: D[dk].zh, en: D[dk].en, value, tone, desc: D[dk].desc ?? '', band: D[dk].band ?? '', why: D[dk].why ?? '' })
  if (key === 'pe') {
    const v = q?.trailing_pe ?? null
    return wrap('pe', 'PE', v == null ? '—' : v.toFixed(0), v == null ? '' : (v < 0 ? 'bad' : v > 30 ? 'warn' : ''))
  }
  if (key === 'fwd') {
    const v = q?.forward_pe ?? null, t = q?.trailing_pe ?? null
    return wrap('fwd', 'fwd', v == null ? '—' : v.toFixed(0), (v != null && t != null && v < t) ? 'good' : '')
  }
  if (key === 'range52') {
    const p = q?.price ?? null, lo = q?.fifty_two_week_low ?? null, hi = q?.fifty_two_week_high ?? null
    const pct = (p != null && lo != null && hi != null && hi > lo) ? ((p - lo) / (hi - lo)) * 100 : null
    return wrap('range52', '52w位置', pct == null ? '—' : `${pct.toFixed(0)}%`, pct == null ? '' : (pct > 80 ? 'warn' : ''))
  }
  if (key === 'cap') {
    const v = q?.market_cap ?? null
    return wrap('cap', '市值', v == null ? '—' : fmtCap(v), '')
  }
  if (key === 'year1') {
    const v = q?.year_change_pct ?? null
    return wrap('year1', '近一年', v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`, '')
  }
  return { label: key, zh: key, en: '', value: '—', tone: '', desc: '', band: '', why: '' }
}

function MetricChip({ m }: { m: FlowM }) {
  return (
    <InfoPop
      className={'px-1.5 py-0 rounded border text-[10px] ' + CHIP_CLS[m.tone]}
      title={<>{m.zh} <span className="text-[9px] font-normal text-[var(--color-dim)]">{m.en}</span></>}
      body={
        <div className="space-y-1">
          {m.desc && <div>{m.desc}</div>}
          {m.band && <div><span className="text-[var(--color-dim)]">阈值:</span> {m.band}</div>}
          {m.why && <div className="text-[9.5px] text-[var(--color-dim)] italic">{m.why}</div>}
        </div>
      }
    >
      {m.label} <b>{m.value}</b>
    </InfoPop>
  )
}

// Capex gets a richer chip: value = intensity (capex/营收, asset-light vs
// heavy), tooltip breaks down the *kinds* (总 / 维护≈D&A / 成长=总−维护) +
// the FCF bridge + the D&A-proxy caveat (acquisition-heavy names like AMD).
function CapexChip({ f }: { f?: Fundamentals }) {
  const capex = f?.capex ?? null
  const intensity = f?.capex_intensity ?? null
  const da = f?.dep_amort ?? null
  const growth = (capex != null && da != null) ? capex - da : null
  const tone: FundTone = intensity == null ? '' : intensity < 0.05 ? 'good' : intensity <= 0.15 ? 'warn' : 'bad'
  return (
    <InfoPop
      className={'px-1.5 py-0 rounded border text-[10px] ' + CHIP_CLS[tone]}
      title="资本支出 Capex（有好几种）"
      body={
        <div className="space-y-1">
          <div>总 capex(gross): <b>{capex == null ? '—' : _money(capex)}</b>（占营收 {intensity == null ? '—' : _pct(intensity)}）</div>
          <div>维护性 (≈ 折旧摊销 D&A): {da == null ? '—' : _money(da)}</div>
          <div>成长性 (≈ 总 − 维护): {growth == null ? '—' : _money(growth)}</div>
          <div className="text-[var(--color-dim)]">FCF = 经营现金流 − capex；强度 = capex/营收（越低越轻资产, 越能把利润转成现金）。</div>
          <div className="text-[9.5px] text-amber-300/80 italic">⚠️ 维护≈D&A 只是代理；收购多的公司(如 AMD, capex 低于 D&A)D&A 被无形资产摊销抬高, 会高估维护性。</div>
        </div>
      }
    >
      资本支出 {intensity == null ? '—' : _pct(intensity)}
    </InfoPop>
  )
}

// The diagnostic reading order as a top-down flow (→ = "牵出下一个" chain,
// + = "一起看" combine). Each step: question → its metric chips → takeaway.
const DIAG_FLOW: Array<{
  q: string; connector: string;
  nodes: Array<{ src: 'q' | 'f'; key: string }>;
  take: (q?: LiveQuote, f?: Fundamentals) => string;
}> = [
  { q: '① 贵不贵?', connector: '→',
    nodes: [{ src: 'q', key: 'pe' }, { src: 'f', key: 'peg' }, { src: 'f', key: 'revenue_growth' }],
    take: (_q, f) => f?.peg == null ? '' : f.peg < 1 ? 'PEG<1, 偏便宜' : f.peg <= 2 ? 'PEG 中性, 增长基本撑得起' : 'PEG>2, 算上增长仍偏贵' },
  { q: '② 贵得值不值?(质量配得上估值吗)', connector: '+',
    nodes: [{ src: 'f', key: 'gross_margin' }, { src: 'f', key: 'profit_margin' }, { src: 'f', key: 'roe' }],
    take: (_q, f) => (f?.gross_margin ?? 0) > 0.6 ? '毛利极高 = 护城河强, 高估值有支撑' : '毛利一般, 高估值要打问号' },
  { q: '③ 护城河深不深?', connector: '+',
    nodes: [{ src: 'f', key: 'gross_margin' }, { src: 'f', key: 'roe' }, { src: 'f', key: 'ev_ebitda' }],
    take: (_q, f) => (f?.roe ?? 0) > 0.15 ? 'ROE 强(≈ROIC)' : 'ROE 一般(≈ROIC代理), 护城河主要看毛利' },
  { q: '④ 扛不扛得住?(风险/下行)', connector: '+',
    nodes: [{ src: 'f', key: 'fcf' }, { src: 'f', key: 'capex' }, { src: 'f', key: 'net_debt' }, { src: 'f', key: 'beta' }],
    take: (_q, f) => {
      const cash = (f?.net_debt ?? 0) < 0 && (f?.fcf ?? 0) > 0
      const volat = (f?.beta ?? 0) > 1.5
      return (cash ? '净现金 + 正 FCF, 财务稳健' : '盯现金流 / 负债') + (volat ? '; 但波动很大' : '')
    } },
  { q: '⑤ 什么时候?(只定时机, 不定做不做)', connector: '+',
    nodes: [{ src: 'q', key: 'range52' }, { src: 'q', key: 'year1' }, { src: 'q', key: 'fwd' }],
    take: (q) => (q?.forward_pe != null && q?.trailing_pe != null && q.forward_pe < q.trailing_pe) ? 'fwd<静态, 市场预期盈利在涨' : '' },
]

function FundamentalsSection({ ticker }: { ticker: string }) {
  const fq = useFundamentals(ticker)
  const qq = useLiveQuote(ticker)
  const histQ = useMetricsAsof(ticker)
  const f = fq.data, q = qq.data
  const nDays = histQ.data?.dates?.length ?? 0
  if (f && !f.supported) return null
  return (
    <div data-testid="fundamentals-section" className="mb-4">
      <div className="mb-2 text-[10px] text-[var(--color-dim)] flex items-center gap-2 flex-wrap">
        <BarChart3 size={11} className="text-emerald-300" />
        <span className="font-semibold text-[var(--color-text)]">📊 基本面 · 诊断链</span>
        <span className="text-[9px]">· 从上往下读 · → 牵出下一个 / + 一起看 · 点指标看释义+阈值</span>
        {nDays > 0 && <span className="ml-auto text-[9px]">📅 {nDays} 天快照</span>}
      </div>
      {fq.isLoading && <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>}
      {fq.error && <div className="text-[10px] italic text-[var(--color-dim)]">基本面暂不可用</div>}
      {f?.supported && (
        <div className="space-y-2">
          {/* 概况 — 规模 / 其它估值, folded from the old header metric strip */}
          <div className="flex items-center gap-1 flex-wrap pb-2 border-b border-[var(--color-border)]/20">
            <span className="text-[9px] text-[var(--color-dim)] mr-0.5">概况</span>
            {([['q', 'cap'], ['f', 'price_to_sales'], ['f', 'price_to_book'], ['f', 'dividend_yield']] as const).map(([s, k], i) => (
              <MetricChip key={i} m={flowMetric(s, k, q, f)} />
            ))}
          </div>
          {DIAG_FLOW.map((step, si) => {
            const take = step.take(q, f)
            return (
              <div key={si} className="pl-2.5 border-l-2 border-[var(--color-accent)]/40">
                <div className="text-[10.5px] font-semibold text-[var(--color-text)]">{step.q}</div>
                <div className="flex items-center gap-1 flex-wrap mt-1">
                  {step.nodes.map((n, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-[var(--color-dim)] text-[11px]">{step.connector}</span>}
                      {n.key === 'capex'
                        ? <CapexChip f={f} />
                        : <MetricChip m={flowMetric(n.src, n.key, q, f)} />}
                    </span>
                  ))}
                </div>
                {take && <div className="text-[9.5px] text-[var(--color-accent)]/90 mt-1">⮑ {take}</div>}
              </div>
            )
          })}
          {/* ⑥ 市场预期 / 卖方共识 (Goal-1 dim #8, borrowed from TOPS) —
              what's priced-in; the thing your thesis bets against */}
          {(f.target_mean != null || f.analyst_rating != null) && (
            <div className="pl-2.5 border-l-2 border-cyan-500/40">
              <div className="text-[10.5px] font-semibold text-[var(--color-text)]">⑥ 市场怎么看?(卖方共识)</div>
              <div className="text-[10px] mt-1 flex items-center gap-x-3 gap-y-1 flex-wrap">
                {f.analyst_rating != null && (
                  <span>评级 <b className="text-[var(--color-text)]">{f.analyst_rating_key ?? '—'}</b>
                    <span className="text-[var(--color-dim)]"> ({f.analyst_rating.toFixed(1)}/5{f.analyst_count != null ? ` · ${f.analyst_count} 家` : ''})</span>
                  </span>
                )}
                {f.target_mean != null && (
                  <span>目标价 <b className="text-[var(--color-text)]">${f.target_mean.toFixed(0)}</b>
                    {q?.price != null && (
                      <span className={f.target_mean >= q.price ? 'text-emerald-400' : 'text-red-400'}>
                        {' '}({f.target_mean >= q.price ? '+' : ''}{((f.target_mean / q.price - 1) * 100).toFixed(0)}% vs 现价)
                      </span>
                    )}
                    {f.target_low != null && f.target_high != null && (
                      <span className="text-[var(--color-dim)]"> · 区间 ${f.target_low.toFixed(0)}–${f.target_high.toFixed(0)}</span>
                    )}
                  </span>
                )}
              </div>
              <div className="text-[9.5px] text-cyan-300/80 mt-1">⮑ 这是市场已 priced-in 的预期 —— 你的赌注是它对不对,不是跟随它</div>
            </div>
          )}
        </div>
      )}
      <div className="mt-2 text-[9px] text-[var(--color-dim)] italic">
        ⚠️ 阈值是起点不是规则(看行业/阶段) · 现价/当日涨跌见抽屉顶部 · 点任一指标看 中文 + EN + 定义 · yfinance 单源{f?.fetched_at ? ` · 截至 ${f.fetched_at.slice(0, 10)}` : ''}
      </div>
    </div>
  )
}


// Universal ownership / who's-holding section. Shows institution / insider
// %, float-vs-locked (供给悬顶), and the top institutional holders WITH
// their recent buy/sell direction (pct_change). Works for any ticker from
// one data source — no per-company card. Hidden if unsupported.
function HoldersSection({ ticker }: { ticker: string }) {
  const q = useHolders(ticker)
  const d = q.data
  if (d && !d.supported) return null
  const pctH = (v?: number | null, dp = 2) => v == null ? '—' : `${(v * 100).toFixed(dp)}%`
  const locked = d?.pct_locked ?? null
  const lockedHigh = locked != null && locked > 0.3
  return (
    <div data-testid="holders-section">
      <div className="mb-2 text-[10px] text-[var(--color-dim)] flex items-center gap-2 flex-wrap">
        <Building2 size={11} className="text-emerald-300" />
        <span className="font-semibold text-[var(--color-text)]">🏛 持股结构 · 谁在持有 / 买卖</span>
        {d?.supported && <span className="text-[9px]">· yfinance · 机构截至 {d.top_holders?.[0]?.date_reported || '—'}</span>}
      </div>
      {q.isLoading && <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>}
      {q.error && <div className="text-[10px] italic text-[var(--color-dim)]">持股数据暂不可用</div>}
      {d?.supported && (
        <>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] mb-2">
            <span>机构 <b className="text-[var(--color-text)]">{pctH(d.pct_institutions, 0)}</b></span>
            <span>内部人 <b className="text-[var(--color-text)]">{pctH(d.pct_insiders, 2)}</b></span>
            <span>流通盘 <b className="text-[var(--color-text)]">{pctH(d.pct_float, 0)}</b></span>
            {lockedHigh && (
              <span className="text-amber-300">锁定 <b>{pctH(locked, 0)}</b> ⚠️ 供给悬顶(大股东锁仓)</span>
            )}
            {d.institutions_count != null && <span className="text-[var(--color-dim)]">· {d.institutions_count} 家机构</span>}
          </div>
          {/* 13F-vs-aggregate reconciliation. The top-holders list is 13F
              PUBLIC filers; for locked-up / fresh-IPO names the aggregate 机构%
              includes pre-IPO / locked institutions NOT in any 13F, so the two
              do NOT reconcile (e.g. CBRS: 16% aggregate vs 0.8% 13F). Surface
              this instead of letting it read as broken data. */}
          {(() => {
            const top = d.top_holders ?? []
            const topSum = top.reduce((a, h) => a + (h.pct_held ?? 0), 0)
            const inst = d.pct_institutions ?? null
            const flt = d.pct_float ?? null
            if (inst == null || top.length === 0) return null
            const lowCoverage = topSum < inst * 0.25
            const overFloat = flt != null && inst > flt + 0.01
            if (!lowCoverage && !overFloat) return null
            return (
              <div className="text-[10px] text-amber-300/90 bg-amber-500/5 border border-amber-500/20 rounded px-2 py-1 mb-2 leading-snug">
                ⚠️ 下方前 {top.length} 大是 <b>13F 公开持仓</b>(合计 {pctH(topSum, 1)}),远低于上面「机构 {pctH(inst, 0)}」。
                {overFloat
                  ? ' 机构% > 流通盘% → 大头是锁定 / pre-IPO 机构股(VC 等),不进公开 13F。'
                  : ' 差额是未进前列的长尾 13F + 锁定持仓。'}
                {' '}两数来自 yfinance 不同口径(聚合估算 vs 13F 申报),不能直接相加对账。
              </div>
            )
          })()}
          {(d.top_holders ?? []).length > 0 && (
            <div className="space-y-0.5">
              <div className="text-[9px] text-[var(--color-dim)]">前 {d.top_holders.length} 大机构(13F 公开持仓) · Δ = 季度增减(▲在买 / ▼在卖)</div>
              {d.top_holders.map((h, i) => {
                const ch = h.pct_change
                return (
                  <div key={i} className="flex items-center gap-2 text-[11px] py-0.5 border-b border-[var(--color-border)]/20">
                    <span className="flex-1 truncate">{h.holder}</span>
                    <span className="font-mono text-[10px] w-14 text-right">{pctH(h.pct_held, 2)}</span>
                    {ch != null && (
                      <span className={'font-mono text-[10px] w-16 text-right ' + (ch >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                        {ch >= 0 ? '▲' : '▼'}{Math.abs(ch * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          <div className="mt-1.5 text-[9px] text-[var(--color-dim)] italic">
            Δ = 机构季度持仓变化(在买/在卖)。内部人 / 国会 / 举牌(13D) 等具体交易 → 见 Smart Money tab。yfinance 单源, 参考。
          </div>
        </>
      )}
    </div>
  )
}

// Human-readable "how old is this" for the freshness badge.
function fmtAge(s?: number | null): string {
  if (s == null) return ''
  if (s < 90) return '刚刚'
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`
  if (s < 86400) return `${Math.round(s / 3600)} 小时前`
  return `${Math.round(s / 86400)} 天前`
}

// Official company-newsroom PRs (primary source, RSS-backed, DB-stored,
// kept fresh hourly by the official_news_pull scheduler job). Shows a
// freshness badge (最新 vs 可能过时) + a 立刻刷新 button. Hidden for
// tickers with no mapped feed.
// 最新 SEC 备案/事件 — the freshness layer (Goal-1 dim #3). 8-K(US)/6-K(foreign)
// material events, dated + event-typed, straight from SEC EDGAR (authoritative).
function RecentFilingsSection({ ticker }: { ticker: string }) {
  const q = useRecentFilings(ticker)
  const d = q.data
  const filings = d?.filings ?? []
  return (
    <div data-testid="recent-filings">
      <div className="mb-2 text-[10px] text-[var(--color-dim)] flex items-center gap-2 flex-wrap">
        <History size={11} className="text-amber-300" />
        <span className="font-semibold text-[var(--color-text)]">📅 最新 SEC 备案 / 事件</span>
        <span className="text-[9px]">· 8-K/6-K 重大事件 · SEC EDGAR{d?.fetched_at ? ` · 截至 ${d.fetched_at.slice(0, 10)}` : ''}</span>
      </div>
      {q.isLoading && <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>}
      {!q.isLoading && filings.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)]">近 5 个月无 8-K/6-K 备案</div>
      )}
      <div className="space-y-0.5">
        {filings.map((f, i) => (
          <a key={i} href={f.url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 text-[11px] py-0.5 px-1 rounded hover:bg-[var(--color-panel)]/40">
            <span className="font-mono text-[9px] text-[var(--color-dim)] w-[68px] flex-shrink-0">{f.date}</span>
            <span className="text-[9px] px-1 rounded border border-[var(--color-border)] text-[var(--color-dim)] flex-shrink-0">{f.form}</span>
            <span className="flex-1 truncate text-[var(--color-text)]">{f.event}</span>
            <ExternalLink size={9} className="text-[var(--color-dim)] flex-shrink-0" />
          </a>
        ))}
      </div>
    </div>
  )
}

function OfficialNews({ ticker }: { ticker: string }) {
  const q = useOfficialNews(ticker)
  const refreshMu = useRefreshOfficialNews()
  const data = q.data
  if (data && !data.supported) return null   // no feed mapped → no clutter
  const age = data?.age_seconds
  const fresh = age != null && age < 3600 && !data?.stale
  return (
    <div data-testid="official-news">
      <div className="mb-2 text-[10px] text-[var(--color-dim)] flex items-center gap-2 flex-wrap">
        <Newspaper size={11} className="text-emerald-300" />
        <span className="font-semibold text-[var(--color-text)]">📰 官方新闻 · {ticker} newsroom</span>
        {data?.fetched_at && (
          <span
            className={'px-1.5 py-0 rounded border ' + (fresh
              ? 'border-emerald-500/40 text-emerald-300'
              : 'border-amber-500/40 text-amber-300')}
            title={`上次抓取: ${data.fetched_at}`}
          >
            {fresh ? '🟢 最新' : '🕒 可能过时'} · {fmtAge(age)}
          </span>
        )}
        <span className="text-[9px]">· 每小时自动刷新</span>
        <span className="ml-auto flex items-center gap-2">
          <button
            onClick={() => refreshMu.mutate(ticker)}
            disabled={refreshMu.isPending}
            className="text-[9px] px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-dim)] hover:text-[var(--color-text)] flex items-center gap-1 disabled:opacity-50"
            title="立刻从 newsroom 重新抓取"
          >
            <RotateCw size={9} className={refreshMu.isPending ? 'animate-spin' : ''} /> 刷新
          </button>
          {data?.feed_url && (
            <a href={data.feed_url} target="_blank" rel="noopener noreferrer"
               className="text-[9px] text-[var(--color-accent)] hover:underline">RSS ↗</a>
          )}
        </span>
      </div>
      {(q.isLoading || refreshMu.isPending) && <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>}
      {q.error && <div className="text-[10px] italic text-[var(--color-dim)]">官方新闻暂不可用</div>}
      {data?.supported && !q.isLoading && data.items.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)]">newsroom 暂无条目</div>
      )}
      <ul className="space-y-2">
        {(data?.items ?? []).map((e, i) => (
          <li key={i} className="border border-[var(--color-border)]/40 rounded p-2">
            <a href={e.url} target="_blank" rel="noopener noreferrer"
               className="text-[12px] font-semibold text-[var(--color-text)] hover:text-[var(--color-accent)]">
              {e.title}
            </a>
            <div className="text-[9px] text-[var(--color-dim)] mt-0.5 flex items-center gap-2">
              <span>{e.published_at?.slice(0, 16)}</span>
              <ExternalLink size={9} />
            </div>
            {e.snippet && (
              <p className="text-[10.5px] text-[var(--color-text)]/75 mt-1.5 leading-snug">{e.snippet}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}


function NewsTabBody({ ticker }: { ticker: string }) {
  const newsQ = useTickerNews(ticker)
  const data = newsQ.data
  const entries = data?.entries ?? []

  return (
    <div data-testid="news-tab-body">
      <div className="mb-3 text-[10px] text-[var(--color-dim)] flex items-center gap-2">
        <Newspaper size={11} />
        <span>{newsQ.error ? `${ticker} 新闻` : data ? `${data.count} items mentioning ${ticker}` : 'loading…'}</span>
        <span className="text-[9px]">· miniflux RSS (title + content match)</span>
        {data?.fallback_search_url && (
          <a
            href={data.fallback_search_url}
            target="_blank" rel="noopener noreferrer"
            className="ml-auto px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] text-[9px] flex items-center gap-1"
            title="Search Google News for this ticker (opens in new tab)"
          >
            Google News <ExternalLink size={9} />
          </a>
        )}
      </div>
      {newsQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
      )}
      {newsQ.error && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2 flex items-center gap-2 flex-wrap">
          📰 新闻源暂不可用（RSS 未配置或离线）
          <a
            href={`https://news.google.com/search?q=${encodeURIComponent(ticker)}%20stock`}
            target="_blank" rel="noopener noreferrer"
            className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] text-[9px] not-italic"
          >
            Google News ↗
          </a>
        </div>
      )}
      {!newsQ.isLoading && entries.length === 0 && (
        <div className="text-[11px] italic text-[var(--color-dim)] py-3 leading-[1.6]">
          没有 miniflux 订阅源最近提到 {ticker}. 你可以:
          <br />· 加更多财经 RSS 到 miniflux (Settings → Backend health → Miniflux)
          <br />· 用上面 "Google News" 按钮去外部查
        </div>
      )}
      <ul className="space-y-2">
        {entries.map((e) => (
          <li key={e.id} className="border border-[var(--color-border)]/40 rounded p-2">
            <a
              href={e.url}
              target="_blank" rel="noopener noreferrer"
              className="text-[12px] font-semibold text-[var(--color-text)] hover:text-[var(--color-accent)]"
            >
              {e.title}
            </a>
            <div className="text-[9px] text-[var(--color-dim)] mt-0.5 flex items-center gap-2">
              <span>{e.published_at?.slice(0, 10)}</span>
              <span>·</span>
              <span>{e.feed_title}</span>
              <ExternalLink size={9} className="ml-1" />
            </div>
            {e.snippet && (
              <p className="text-[10.5px] text-[var(--color-text)]/75 mt-1.5 leading-snug">
                {e.snippet}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}


// ── Tier strip — current tier badge + change buttons ──
//
// Renders the strip just below the status reason editor. Three
// click targets per tier (→ Core / → Adjacent / → Watching) plus a
// drop button. Adjacent tier requires choosing a parent_ticker
// from existing core tickers (otherwise the spoke graph is broken).
function TierStrip({
  currentTier, parentTicker,
  onPromote, onRemove,
  showSuggestions, onToggleSuggestions,
  coreTickers,
}: {
  ticker: string  // unused but kept in API for future per-tier copy
  currentTier: WatchlistTier | null
  parentTicker: string | null
  onPromote: (tier: WatchlistTier, parent?: string | null) => void
  onRemove: () => void
  showSuggestions: boolean
  onToggleSuggestions: () => void
  coreTickers: string[]
}) {
  const TierIcon = currentTier === 'core' ? Star
    : currentTier === 'adjacent' ? CircleDot
    : currentTier === 'watching' ? Eye : null
  const tierLabel = currentTier
    ? { core: 'Core', adjacent: 'Adjacent', watching: 'Watching' }[currentTier]
    : '—'
  const tierColor = {
    core:     'text-amber-300 border-amber-500/40 bg-amber-500/10',
    adjacent: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10',
    watching: 'text-[var(--color-dim)] border-[var(--color-border)]',
  }
  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[10px] flex-wrap">
      {/* Current state */}
      {currentTier ? (
        <span className={`px-1.5 py-0.5 rounded border flex items-center gap-1 ${tierColor[currentTier]}`}>
          {TierIcon && <TierIcon size={11} />} {tierLabel}
          {parentTicker && (
            <span className="text-[9px] opacity-75">↳ {parentTicker}</span>
          )}
        </span>
      ) : (
        <span className="px-1.5 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)]">
          unwatched
        </span>
      )}

      {/* Change-tier buttons. Skip the one matching current tier. */}
      <div className="flex items-center gap-1 ml-auto flex-wrap">
        {currentTier !== 'core' && (
          <button
            onClick={() => onPromote('core')}
            className="px-2 py-0.5 rounded border border-amber-500/40 hover:bg-amber-500/10 text-amber-300"
            title="Promote to Core (≤10, weekly review)"
          >
            <Star size={9} className="inline mr-1" />→ Core
          </button>
        )}
        {currentTier !== 'adjacent' && (
          <button
            onClick={() => {
              if (coreTickers.length === 0) {
                alert('需要先有 Core ticker 作为 parent。先把一个 ticker 升到 Core 再试。')
                return
              }
              const parent = (prompt(
                `Adjacent 是 spoke — 选一个 Core ticker 作为它的 parent (来源):\n\nCore tickers: ${coreTickers.join(', ')}`,
                coreTickers[0],
              ) || '').trim().toUpperCase()
              if (!parent) return
              if (!coreTickers.includes(parent)) {
                alert(`${parent} 不在 Core 里 — parent 必须是 Core ticker`)
                return
              }
              onPromote('adjacent', parent)
            }}
            className="px-2 py-0.5 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300"
            title="Adjacent — 链到一个 Core ticker"
          >
            <CircleDot size={9} className="inline mr-1" />→ Adjacent
          </button>
        )}
        {currentTier !== 'watching' && (
          <button
            onClick={() => {
              if (coreTickers.length === 0) {
                alert('Watching 也需要 parent ticker (来源 Core)')
                return
              }
              const parent = (prompt(
                `Watching 是远观察 — 选一个 Core ticker 作为来源:`,
                coreTickers[0],
              ) || '').trim().toUpperCase()
              if (!parent) return
              if (!coreTickers.includes(parent)) {
                alert(`${parent} 不在 Core 里`)
                return
              }
              onPromote('watching', parent)
            }}
            className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-text)] text-[var(--color-dim)]"
            title="Watching — alert only"
          >
            <Eye size={9} className="inline mr-1" />→ Watching
          </button>
        )}
        {currentTier && (
          <button
            onClick={onRemove}
            className="px-2 py-0.5 rounded border border-red-500/40 hover:bg-red-500/10 text-red-300"
            title="从 watchlist 移除"
          >
            ✕ drop
          </button>
        )}

        {/* Expand from 10-K — opens the suggestions panel below */}
        <button
          onClick={onToggleSuggestions}
          className={`px-2 py-0.5 rounded border flex items-center gap-1 ${
            showSuggestions
              ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
              : 'border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)]'
          }`}
          title="从 10-K 抽出的 competitor / customer / supplier 一键加为 Adjacent"
        >
          <Sparkles size={9} /> 从 10-K 扩 ring
        </button>
      </div>
    </div>
  )
}


// ── Suggestions panel — expand ring from anchored facts ──
function SuggestionsPanel({
  ticker, existingTickers, onPromote,
}: {
  ticker: string
  existingTickers: Set<string>
  onPromote: (suggestion: { name: string; ticker: string }) => void
}) {
  const sugQ = useWatchlistSuggestions(ticker)
  const sugs = sugQ.data?.suggestions
  const total = sugs
    ? sugs.competitor.length + sugs.customer.length + sugs.supplier.length
    : 0

  return (
    <div className="px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-panel)]/30 text-[11px]">
      <div className="text-[10px] text-[var(--color-dim)] mb-2">
        从 {ticker} 的 10-K SEC-anchored facts 抽出的 related companies — 点 + 加为 Adjacent (parent={ticker})。
        每条都有 verbatim quote 在 hover title 里。
      </div>
      {sugQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
      )}
      {!sugQ.isLoading && total === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">
          {ticker} 还没抽过 10-K (或抽出但 0 条 competitor/customer/supplier)。
          先去 Overview tab 点 ✨ extract from SEC 10-K。
        </div>
      )}
      {!sugQ.isLoading && total > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(['competitor', 'customer', 'supplier'] as const).map(kind => {
            const list = sugs?.[kind] ?? []
            if (list.length === 0) return null
            const label = { competitor: '竞品', customer: '客户', supplier: '供应商' }[kind]
            return (
              <div key={kind}>
                <div className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
                  {label} ({list.length})
                </div>
                <ul className="space-y-1">
                  {list.map((s, i) => {
                    // Use extractor-recorded ticker if present;
                    // otherwise fall back to company-name first word
                    // (catches "Apple Inc." → AAPL but not multi-word
                    // companies like "Walmart Stores" → would need a
                    // resolver; user is prompted in that case).
                    const guess = s.ticker || s.name.split(/[\s,.]/)[0].toUpperCase()
                    const alreadyIn = existingTickers.has(guess)
                    return (
                      <li key={i} className="flex items-start gap-1">
                        <button
                          onClick={() => onPromote({ name: s.name, ticker: s.ticker })}
                          disabled={alreadyIn}
                          title={s.evidence_quote || s.name}
                          className={`flex-1 text-left px-1.5 py-0.5 rounded border text-[10.5px] ${
                            alreadyIn
                              ? 'border-[var(--color-border)] text-[var(--color-dim)] cursor-default opacity-60'
                              : 'border-[var(--color-border)] hover:border-emerald-500/40 hover:bg-emerald-500/10 text-[var(--color-text)]'
                          }`}
                        >
                          {alreadyIn ? '✓ ' : '+ '}{s.name}
                          {s.ticker && (
                            <span className="ml-1 opacity-60 text-[9px] font-mono">({s.ticker})</span>
                          )}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}


// ── Phase W: Theses panel ──
//
// Shows active theses for this ticker, plus an "Add thesis" button
// that opens a markdown form pre-filled with the template. Per plan
// §2 philosophy: information not gates — having NO thesis is fine,
// we just label the ticker as "no thesis recorded" so the chain
// panel can be honest about it.
function ThesesPanel({
  ticker, exposureEvents,
}: {
  ticker: string
  exposureEvents: StockExposureEvent[]
}) {
  const thesesQ = useTheses(ticker, 'active')
  const templateQ = useThesisTemplate()
  const createMu = useCreateThesis()
  const invalidateMu = useInvalidateThesis()

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  function openCreate() {
    setDraft(templateQ.data?.body_md ?? '')
    setEditing(true)
  }

  function commitCreate() {
    if (!draft.trim()) return
    createMu.mutate(
      { ticker, body_md: draft.trim() },
      {
        onSuccess: () => { setEditing(false); setDraft('') },
        onError: (err) => alert(`create failed: ${err.message}`),
      },
    )
  }

  const theses = thesesQ.data?.theses ?? []
  // exposureEvents kept in props for future use (citing signals as
  // supporting evidence when thesis is created); not used yet.
  void exposureEvents

  return (
    <div className="mb-4 border border-emerald-500/30 rounded p-2 bg-emerald-500/[0.04]">
      <div className="flex items-center gap-2 mb-2">
        <Lightbulb size={12} className="text-emerald-300" />
        <span className="text-[11px] font-semibold text-emerald-300">投资 Theses</span>
        <span className="text-[9px] italic text-[var(--color-dim)]">
          —— 共识(已确认) + 推断(待验证) + Exit triggers
        </span>
        <button
          onClick={openCreate}
          disabled={editing || templateQ.isLoading}
          className="ml-auto text-[10px] px-2 py-0.5 rounded border border-emerald-500/40 hover:bg-emerald-500/10 text-emerald-300 disabled:opacity-40"
        >
          + Add thesis
        </button>
      </div>

      {thesesQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
      )}

      {!thesesQ.isLoading && theses.length === 0 && !editing && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">
          还没有 active thesis。写下 <b>共识</b>（已查证的事实 + source）和 <b>推断</b>（前瞻判断）
          + exit triggers —— Overview 顶部「我的认知」会同步显示, 把未知压成 conviction。
        </div>
      )}

      {/* Existing theses */}
      <div className="space-y-2">
        {theses.map(t => (
          <ThesisCard
            key={t.thesis_id}
            t={t}
            onInvalidate={(reason) => invalidateMu.mutate(
              { thesis_id: t.thesis_id, ticker, reason },
              { onError: (err) => alert(`invalidate failed: ${err.message}`) },
            )}
          />
        ))}
      </div>

      {/* Create form */}
      {editing && (
        <div className="mt-2 border border-dashed border-emerald-500/40 rounded p-2">
          <textarea
            className="w-full bg-[var(--color-bg)] text-[10.5px] font-mono outline-none resize-y leading-snug p-2 rounded border border-[var(--color-border)]"
            rows={14}
            placeholder="thesis 模板加载中..."
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <button
              onClick={commitCreate}
              disabled={!draft.trim() || createMu.isPending}
              className="text-[10px] px-2 py-0.5 rounded border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40"
            >
              {createMu.isPending ? '保存中…' : 'create thesis'}
            </button>
            <button
              onClick={() => { setEditing(false); setDraft('') }}
              className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            >
              cancel
            </button>
            <span className="text-[9px] italic text-[var(--color-dim)]">
              保留 共识 / 推断 / Exit triggers / Horizon — 推断里写清『若错会怎样』
            </span>
          </div>
        </div>
      )}
    </div>
  )
}


function ThesisCard({
  t, onInvalidate,
}: {
  t: InvestmentThesis
  onInvalidate: (reason: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const hasMissing = t.missing_sections.length > 0

  function handleInvalidate() {
    const reason = prompt(
      `失效 thesis "${t.ticker}"?\n请简要说明原因 (会记录在 audit log):`,
      '',
    )
    if (reason && reason.trim()) {
      onInvalidate(reason.trim())
    }
  }

  return (
    <div className="border border-emerald-500/40 rounded p-2 bg-[var(--color-panel)]/50">
      <div className="flex items-start gap-2 mb-1">
        <span className="text-[10px] font-mono text-emerald-300">
          thesis · created {new Date(t.created_at).toLocaleDateString()}
        </span>
        {hasMissing && (
          <span
            className="text-[8.5px] text-amber-300 flex items-center gap-1"
            title={`Missing sections: ${t.missing_sections.join(', ')}`}
          >
            <AlertTriangle size={9} /> incomplete
          </span>
        )}
        <button
          onClick={() => setExpanded(e => !e)}
          className="ml-auto text-[10px] px-1.5 py-0 text-[var(--color-dim)] hover:text-[var(--color-text)]"
        >
          {expanded ? '−' : '+'}
        </button>
        <button
          onClick={handleInvalidate}
          className="text-[9px] px-1.5 py-0 rounded border border-red-500/40 hover:bg-red-500/10 text-red-300"
          title="标记 thesis 已失效 (移到 audit log, 不删除)"
        >
          ✕ invalidate
        </button>
      </div>

      {/* 共识 (grounded, sourced facts) + 推断 (forward bets) side by side.
          Falls back to legacy bull_case/bear_case for old theses. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-1">
        <div className="border border-sky-500/30 rounded p-1.5">
          <div className="text-[9px] uppercase tracking-wider text-sky-300 mb-1">
            🔒 共识（已确认）
          </div>
          <div className="text-[10.5px] leading-snug whitespace-pre-wrap">
            {t.sections.consensus || t.sections.bull_case || (
              <span className="italic text-[var(--color-dim)]">(empty — 写已查证的事实 + source)</span>
            )}
          </div>
        </div>
        <div className="border border-amber-500/30 rounded p-1.5">
          <div className="text-[9px] uppercase tracking-wider text-amber-300 mb-1">
            🔮 推断（待验证）
          </div>
          <div className="text-[10.5px] leading-snug whitespace-pre-wrap">
            {t.sections.inference || t.sections.bear_case || (
              <span className="italic text-[var(--color-dim)]">(empty — 写前瞻判断/赌注, 标明若错会怎样)</span>
            )}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
          <div className="border border-[var(--color-border)]/50 rounded p-1.5">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
              Exit triggers (evaluated)
            </div>
            {/* Phase 4: replace raw markdown with parsed + evaluated
                triggers showing CURRENT state. Per plan §5 Pillar 5. */}
            <ExitTriggersStatus thesisId={t.thesis_id} fallbackMd={t.sections.exit_triggers} />
          </div>
          <div className="border border-[var(--color-border)]/50 rounded p-1.5">
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
              Horizon
            </div>
            <div className="text-[10.5px] leading-snug whitespace-pre-wrap">
              {t.sections.horizon || (
                <span className="italic text-[var(--color-dim)]">(empty)</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


// ── Phase W: Watchlist audit history (chain panel INCOMING) ──
function WatchlistAuditPanel({ ticker }: { ticker: string }) {
  const auditQ = useWatchlistAudit(ticker)
  const events = auditQ.data?.events ?? []

  const ACTION_COLOR: Record<string, string> = {
    promote:           'border-emerald-500/40 text-emerald-300',
    demote:            'border-amber-500/40 text-amber-300',
    drop:              'border-red-500/40 text-red-300',
    review:            'border-[var(--color-border)] text-[var(--color-dim)]',
    note:              'border-blue-500/40 text-blue-300',
    thesis_create:    'border-emerald-500/40 text-emerald-300',
    thesis_invalidate:'border-red-500/40 text-red-300',
  }

  return (
    <div className="mb-4 border border-[var(--color-border)]/50 rounded p-2">
      <div className="flex items-center gap-2 mb-2">
        <History size={12} className="text-[var(--color-dim)]" />
        <span className="text-[11px] font-semibold text-[var(--color-text)]">
          为什么这只在你 radar 上
        </span>
        <span className="text-[9px] italic text-[var(--color-dim)]">
          —— promote / demote / thesis 历史 (Phase W audit)
        </span>
      </div>

      {auditQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
      )}

      {!auditQ.isLoading && events.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1">
          没有 audit 事件 — 该 ticker 是早期手动加进 watchlist 的, 没记录 trigger.
          以后的 promote / drop / thesis 会自动记录到这里.
        </div>
      )}

      <div className="space-y-1">
        {events.map(ev => (
          <div key={ev.audit_id} className="flex items-start gap-2 text-[10px]">
            <span
              className={`px-1.5 py-0 rounded border font-mono flex-shrink-0 ${
                ACTION_COLOR[ev.action] ?? 'border-[var(--color-border)] text-[var(--color-dim)]'
              }`}
            >
              {ev.action}
            </span>
            <span className="text-[var(--color-dim)] font-mono flex-shrink-0">
              {new Date(ev.ts).toLocaleString()}
            </span>
            <span className="flex-1">
              {ev.from_tier && ev.to_tier && `${ev.from_tier} → ${ev.to_tier}`}
              {ev.trigger_kind && ev.trigger_kind !== 'manual' && (
                <span className="ml-1 text-[var(--color-dim)] italic">
                  via {ev.trigger_kind}
                </span>
              )}
              {ev.note && <span className="ml-1 text-[var(--color-text)]/80"> · {ev.note}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}


// ── Phase W: Note trigger selector ──
//
// Dropdown shown beside the note textarea. Lets the user link the
// note to: (a) one of their active theses for this ticker, (b) one
// of recent signal_events on this ticker. Empty option = no link
// (still allowed — note is fine without a trigger).
function NoteTriggerSelector({
  ticker, exposureEvents, value, onChange,
}: {
  ticker: string
  exposureEvents: StockExposureEvent[]
  value: string
  onChange: (v: string) => void
}) {
  const thesesQ = useTheses(ticker, 'active')
  const theses = thesesQ.data?.theses ?? []
  const recentSignals = exposureEvents.slice(0, 10)  // most recent 10

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      title="可选: 把笔记关联到一个 thesis 或 signal — 帮你 6 个月后回忆为何写下这个"
      className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
    >
      <option value="">trigger? (optional)</option>
      {theses.length > 0 && (
        <optgroup label="Active theses">
          {theses.map(t => (
            <option key={t.thesis_id} value={`thesis:${t.thesis_id}`}>
              💡 thesis · {new Date(t.created_at).toLocaleDateString()}
              {t.sections.bull_case
                ? ` · ${t.sections.bull_case.split('\n')[0].slice(0, 30)}`
                : ''}
            </option>
          ))}
        </optgroup>
      )}
      {recentSignals.length > 0 && (
        <optgroup label="Recent signals">
          {recentSignals
            .filter(s => s.event_id)   // skip events without real id (defensive)
            .map((s) => (
              <option
                key={s.event_id}
                value={`signal:${s.event_id}`}
              >
                📡 {s.scanner} · {s.signal_type} · {s.title?.slice(0, 30)}
              </option>
            ))}
        </optgroup>
      )}
    </select>
  )
}


// ── Phase 1B: Position panel — per-ticker decision context ──
//
// Renders just below TierStrip. Hidden when user owns 0 shares
// (no_position state). When holdings exist, shows:
//   • Total qty + avg cost + market value + unrealized P&L
//   • Weight in portfolio (vs user's max-position pref, info only)
//   • Each lot: open date / qty / cost / days-held / ST vs LT
//
// Per plan §2 philosophy: NO gates. Information only.
// ── DecisionHistoryRow ───────────────────────────────────────
// One row per past decision with click-to-expand outcome:
//   - price move % since decision date
//   - thesis state changes since decision
//   - subsequent high-severity events
//   - closed lots after decision
// Closes Need #5/#6: "did my last decision pan out?" auditable.

// ── DecisionScorecardPanel ───────────────────────────────────
// Synthesizes all signals into one clear lean: buy/add/hold/trim/sell/
// watch/pass + degree. The "看懂 → 行动" anchor. Signal summary, not advice.

// ── SmartMoneyCrossCutPanel ──────────────────────────────────
// Per-ticker view of smart-money actions in last 90d, co-located in
// the drawer so user doesn't have to leave to Smart Money tab.
// 4 scanners union: 13F (whales) / insider_form4 / stock_act / house_clerk_pdf.
function SmartMoneyCrossCutPanel({ ticker }: { ticker: string }) {
  const w13f = useTickerSignalsByScanner(ticker, '13f', 8)
  const wIns = useTickerSignalsByScanner(ticker, 'insider_form4', 8)
  const wAct = useTickerSignalsByScanner(ticker, 'stock_act', 8)
  const wPdf = useTickerSignalsByScanner(ticker, 'house_clerk_pdf', 8)
  const events13f = w13f.data?.events ?? []
  const eventsIns = wIns.data?.events ?? []
  const eventsAct = wAct.data?.events ?? []
  const eventsPdf = wPdf.data?.events ?? []
  const total = events13f.length + eventsIns.length + eventsAct.length + eventsPdf.length
  if (total === 0) return null
  return (
    <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[10.5px]">
      <div className="flex items-baseline gap-2 mb-1 flex-wrap">
        <span className="font-semibold text-[var(--color-text)] text-[11px]">
          💼 Smart money on {ticker}
        </span>
        <span className="text-[var(--color-dim)] italic text-[9.5px]">
          · 跨 4 类大户最近的动作 (90d 内)
        </span>
        <span className="ml-auto text-[9px] font-mono text-[var(--color-dim)]">
          {total} events
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-3 gap-y-0.5">
        {events13f.length > 0 && (
          <SmartMoneyBlock label="🐋 13F (institutions)" events={events13f} />
        )}
        {eventsIns.length > 0 && (
          <SmartMoneyBlock label="⚪ Insider Form 4" events={eventsIns} />
        )}
        {eventsAct.length > 0 && (
          <SmartMoneyBlock label="🏛 Congress (Quiver)" events={eventsAct} />
        )}
        {eventsPdf.length > 0 && (
          <SmartMoneyBlock label="📄 House Clerk PDF" events={eventsPdf} />
        )}
      </div>
    </div>
  )
}


function SmartMoneyBlock({
  label, events,
}: {
  label: string
  events: Array<{
    event_id: string; signal_type: string; severity: string;
    title: string; source_url?: string | null;
    detected_at: string; source_timestamp?: string | null;
  }>
}) {
  return (
    <div>
      <div className="text-[10px] text-[var(--color-dim)] mb-0.5">{label}</div>
      {events.slice(0, 4).map(e => {
        const ts = (e.source_timestamp || e.detected_at).slice(0, 10)
        return (
          <div key={e.event_id} className="text-[9.5px] pl-1 leading-tight flex items-baseline gap-1 flex-wrap">
            <span className="font-mono text-[var(--color-dim)] w-[60px] flex-shrink-0">{ts}</span>
            <span className={
              e.severity === 'high' ? 'text-red-300' :
              e.severity === 'med'  ? 'text-amber-300' :
              'text-[var(--color-dim)]'
            }>{e.signal_type}</span>
            <span className="text-[var(--color-text)]/80 truncate flex-1 min-w-0">{e.title}</span>
            {e.source_url && (
              <a href={e.source_url} target="_blank" rel="noopener noreferrer"
                 className="text-[9px] text-[var(--color-accent)] hover:underline">↗</a>
            )}
          </div>
        )
      })}
      {events.length > 4 && (
        <div className="text-[8.5px] italic text-[var(--color-dim)] pl-1">
          + {events.length - 4} more
        </div>
      )}
    </div>
  )
}


// ── DecisionAuditPanel ───────────────────────────────────────
// Record investment decisions (hold/trim/add/sell/watch_only/pass)
// + free-text note. Reads back the history below so user can compare
// today's decision to past ones. Closes "信息有根有据" by capturing
// user INTENT alongside data INPUTS.

// ── DeltaSinceReviewBanner ───────────────────────────────────
// Compressed "what changed since last_reviewed_at" panel at top of
// drawer. Renders nothing when there are 0 changes — avoids noise
// for first-time opens with no signal flow.

function PositionPanel({ ticker }: { ticker: string }) {
  const posQ = usePositionByTicker(ticker)
  const sumQ = usePortfolioSummary('SPY')
  const d = posQ.data
  // No-position state: hide entirely (don't clutter the drawer with
  // "you own 0 shares" — the absence speaks)
  if (posQ.isLoading) return null
  if (!d || d.lots.length === 0 || !d.summary) return null

  const totalPortfolio = sumQ.data?.total_value ?? 0
  const weight = (d.summary.market_value && totalPortfolio > 0)
    ? (d.summary.market_value / totalPortfolio) * 100
    : null

  const fmtMoney = (n: number | null | undefined) => {
    if (n == null) return '—'
    if (Math.abs(n) >= 1_000_000) return `$${(n/1_000_000).toFixed(2)}M`
    if (Math.abs(n) >= 1_000) return `$${(n/1_000).toFixed(1)}K`
    return `$${n.toFixed(0)}`
  }
  const fmtPct = (n: number | null | undefined) =>
    n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

  const pnlColor = (d.summary.unrealized ?? 0) >= 0
    ? 'text-emerald-300' : 'text-red-300'

  return (
    <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[10.5px]">
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <Briefcase size={11} className="text-[var(--color-accent)]" />
        <span className="font-semibold text-[var(--color-text)]">持仓</span>
        <span className="text-[var(--color-dim)] italic">
          {d.summary.n_lots} lot{d.summary.n_lots > 1 ? 's' : ''} · 总{d.summary.total_quantity.toFixed(0)}sh
        </span>
        {/* 2026-05-16: provenance — cost from tax_lots, live price from data_hub */}
        <span className="ml-auto text-[8.5px] italic text-[var(--color-dim)]">
          source: tax_lots + live quote
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-x-4 gap-y-1 text-[10.5px]">
        <KV label="avg cost" value={fmtMoney(d.summary.avg_cost)} mono />
        <KV label="now" value={fmtMoney(d.summary.current_price)} mono />
        <KV label="market value" value={fmtMoney(d.summary.market_value)} mono />
        <KV
          label="unrealized"
          value={`${fmtMoney(d.summary.unrealized)} (${fmtPct(d.summary.unrealized_pct)})`}
          mono
          colorClass={pnlColor}
        />
        <KV
          label="portfolio weight"
          value={weight != null ? `${weight.toFixed(1)}%` : '—'}
          mono
        />
      </div>

    </div>
  )
}



function KV({
  label, value, mono, colorClass,
}: {
  label: string
  value: string
  mono?: boolean
  colorClass?: string
}) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-[9px] text-[var(--color-dim)] uppercase tracking-wider">
        {label}
      </span>
      <span className={`${mono ? 'font-mono' : ''} ${colorClass || 'text-[var(--color-text)]'}`}>
        {value}
      </span>
    </div>
  )
}


// ── Phase 4: ExitTriggersStatus — parsed + evaluated exit triggers ──
//
// Replaces the raw markdown render of `## Exit triggers` with a
// per-trigger status: ☐ unfired (with current value vs threshold)
// or ☑ FIRED (red, alerting). Per plan §5 Pillar 5: information,
// not gate — we never auto-sell, just surface the firing state.
function ExitTriggersStatus({
  thesisId, fallbackMd,
}: {
  thesisId: string
  fallbackMd: string
}) {
  const q = useExitTriggers(thesisId)
  if (q.isLoading) {
    return (
      <div className="text-[9.5px] italic text-[var(--color-dim)]">
        evaluating triggers…
      </div>
    )
  }
  const triggers = q.data?.triggers ?? []
  if (triggers.length === 0) {
    // Fall back to raw markdown if parser found no checkboxes
    return fallbackMd
      ? <div className="text-[10.5px] leading-snug whitespace-pre-wrap font-mono">{fallbackMd}</div>
      : <div className="italic text-[var(--color-dim)]">(empty)</div>
  }
  const nFired = q.data?.n_fired ?? 0
  return (
    <div className="space-y-1">
      {nFired > 0 && (
        <div className="text-[10px] text-red-300 font-semibold mb-1.5 flex items-center gap-1">
          ⚠ {nFired} trigger{nFired > 1 ? 's' : ''} fired — review thesis
        </div>
      )}
      {triggers.map((tr, i) => {
        const fired = tr.fired === true
        const unfired = tr.fired === false
        const manual = tr.fired === null
        const icon = fired ? '☑' : '☐'
        const colorClass = fired
          ? 'text-red-300 bg-red-500/10 border-red-500/40'
          : unfired
            ? 'text-emerald-300/80 border-[var(--color-border)]/50'
            : 'text-[var(--color-dim)] border-[var(--color-border)]/40'
        return (
          <div
            key={i}
            className={`text-[10px] px-1.5 py-1 rounded border ${colorClass}`}
            title={tr.explanation}
          >
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono">{icon}</span>
              <span className="font-mono flex-1">{tr.text}</span>
              {fired && <span className="text-[8.5px] uppercase font-bold tracking-wider">FIRED</span>}
              {manual && <span className="text-[8.5px] italic">manual</span>}
            </div>
            <div className="text-[8.5px] text-[var(--color-dim)] mt-0.5 ml-3.5">
              {tr.explanation}
            </div>
          </div>
        )
      })}
    </div>
  )
}
