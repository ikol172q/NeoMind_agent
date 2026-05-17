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
import { useState, useEffect } from 'react'
import { useStockResearch } from './StockResearchContext'
import { ChatPanel } from '@/components/chat/ChatPanel'
import {
  useStockProfile, useStockExposure, useStockNotes,
  useRegenStockProfile, useUpdateStockStatus, useAppendStockNote,
  useLiveQuote, useNextEarnings, useAnchoredFacts, useRegenAnchored,
  useTickerNews, useChatSessions,
  useWatchlistTiers, useWatchlistPromote, useWatchlistTouch,
  useWatchlistRemoveTier, useWatchlistSuggestions,
  // Phase W (2026-05-10): theses + audit
  useTheses, useThesisTemplate, useCreateThesis, useInvalidateThesis,
  useWatchlistAudit,
  // Phase 4: exit triggers eval
  useExitTriggers,
  // Phase 1B (2026-05-10): position state surfacing
  usePositionByTicker, usePortfolioSummary,
  // Lot management (2026-05-16): wire the existing delete/close mutations
  // — they had been in api.ts for a while but nothing in the UI called
  // them, leaving users with no way to remove a position.
  useDeleteLot, useCloseLot,
  // 2026-05-16: delta-since-review banner at drawer top
  useDeltaSinceReview,
  // 2026-05-16: user_decisions audit log
  useDecisions, useRecordDecision, useDecisionOutcome, type DecisionKind,
  // 2026-05-16: smart-money cross-cut per ticker
  useTickerSignalsByScanner,
  type StockExposureEvent, type AnchoredFacts, type NextEarnings,
  type StockProfile, type WatchlistTier,
  type InvestmentThesis, type EnrichedLot,
} from '@/lib/api'
import {
  X, ExternalLink, Sparkles, BarChart3, Network, Newspaper,
  NotebookPen, MessagesSquare, Building2, Loader2, ShieldCheck,
  Star, CircleDot, Eye, Lightbulb, History, AlertTriangle, Briefcase,
  Trash2,
} from 'lucide-react'
import { AnchoredFactsPanel } from './AnchoredFactsPanel'
import { EarningsHistoryMini } from '@/components/widgets/EarningsHistoryMini'

type Status = 'researching' | 'watching' | 'pass' | 'own'
type TabKey = 'overview' | 'smart_money' | 'supply_chain' | 'news' | 'notes' | 'chat'


export function StockResearchDrawer() {
  const { ticker, projectId, closeTicker, openTicker, navStack, back } = useStockResearch()
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
    { k: 'overview',     label: 'Overview',         icon: Building2 },
    { k: 'smart_money',  label: 'Smart Money 接触', icon: BarChart3, badge: exposureEvents.length },
    { k: 'supply_chain', label: '上下游',            icon: Network },
    { k: 'news',         label: 'News',              icon: Newspaper },
    { k: 'notes',        label: '我的笔记',          icon: NotebookPen, badge: notes.length },
    { k: 'chat',         label: 'Chat',              icon: MessagesSquare },
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
              {liveQuoteQ.data?.market_cap != null && (
                <span>· cap {fmtCap(liveQuoteQ.data.market_cap)}</span>
              )}
              {liveQuoteQ.data?.trailing_pe != null && (
                <span>· PE {liveQuoteQ.data.trailing_pe.toFixed(1)}</span>
              )}
              {liveQuoteQ.data?.forward_pe != null && (
                <span>· fwd {liveQuoteQ.data.forward_pe.toFixed(1)}</span>
              )}
              {/* Year change + 52w range when yfinance has them */}
              {liveQuoteQ.data?.year_change_pct != null && (
                <span className={liveQuoteQ.data.year_change_pct >= 0 ? 'text-emerald-400/80' : 'text-red-400/80'}>
                  · 1y {liveQuoteQ.data.year_change_pct >= 0 ? '+' : ''}
                  {liveQuoteQ.data.year_change_pct.toFixed(0)}%
                </span>
              )}
              {/* Next earnings */}
              {earningsQ.data?.next_date && earningsQ.data.days_until != null && (
                <span data-testid="next-earnings" className="text-amber-300/80">
                  · earnings {earningsQ.data.days_until > 0
                    ? `in ${earningsQ.data.days_until}d`
                    : `${Math.abs(earningsQ.data.days_until)}d ago`}
                  {' '}
                  <span className="text-[var(--color-dim)]">({earningsQ.data.next_date})</span>
                </span>
              )}
              {/* Live data attribution */}
              {liveQuoteQ.data && (
                <span className="text-[9px] italic text-[var(--color-dim)]/60 ml-1">
                  live · yfinance
                </span>
              )}
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

        {/* 2026-05-16: Delta-since-review banner — "what changed since
            you last opened this ticker". Compresses signals + thesis
            state + price move + closed lots into one row so the user
            doesn't re-scan the whole drawer every visit. */}
        <DeltaSinceReviewBanner ticker={ticker} />

        {/* 2026-05-16: DecisionAuditPanel — record + replay decisions
            with explicit basis. Closes the audit loop: "why did I
            hold AAPL on 2026-05-10" becomes answerable. */}
        <DecisionAuditPanel ticker={ticker} />

        {/* 2026-05-16: SmartMoneyCrossCut — per-ticker view of 13F /
            insider / congress actions in the last 90d. Co-located so
            user doesn't have to switch to Smart Money tab + filter.
            Need #3 closure. */}
        <SmartMoneyCrossCutPanel ticker={ticker} />

        {/* Phase 1B (2026-05-10): Position panel — your actual lots
            for this ticker, with cost basis / P&L / weight / ST-vs-LT.
            Per plan §5 Pillar 5: information surfaced in chain context,
            NEVER a gate. If you don't own this ticker, panel hides
            (no-position state). */}
        <PositionPanel ticker={ticker} />

        {/* Phase 3 (2026-05-10): EarningsHistoryMini — last 8 quarter
            beat/miss bar chart. Decision context for thesis health.
            Per plan §5 Pillar 6 (information dimension coverage). */}
        <div className="px-4 pb-1 bg-[var(--color-bg)]">
          <EarningsHistoryMini ticker={ticker} />
        </div>

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
            />
          )}

          {tab === 'smart_money' && (
            <SmartMoneyTabBody
              isLoading={exposureQ.isLoading}
              events={exposureEvents}
              ticker={ticker}
            />
          )}

          {tab === 'supply_chain' && (
            <>
              {/* Phase B: SEC-anchored facts. Top panel is the trust
                  source. Legacy LLM-only section is below for
                  comparison so user can see what each layer adds. */}
              <AnchoredFactsPanel ticker={ticker} onTickerClick={openTicker} />

              <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
                <div className="mb-3 text-[10px] text-[var(--color-dim)] flex items-center gap-2">
                  <span>⚠️ 下方为 legacy LLM-only 输出（无 SEC 验证）—— 仅作对比保留</span>
                </div>
                {!hasProfile && (
                  <div className="text-[11px] italic text-[var(--color-dim)]">
                    Legacy LLM profile 未生成. 切到 Overview tab 点 ✨ generate.
                  </div>
                )}
                {hasProfile && (
                  <div className="opacity-60">
                    <h3 className="text-[11px] font-semibold mb-1.5 text-green-300">⬆ Upstream (供应商) · LLM</h3>
                    <div className="space-y-1 mb-3">
                      {profile!.upstream.length === 0 && <div className="text-[10px] italic text-[var(--color-dim)]">LLM 未列出</div>}
                      {profile!.upstream.map((u) => (
                        <SupplyRow key={u.ticker} ticker={u.ticker} name={u.name} note={u.role} onClick={openTicker} />
                      ))}
                    </div>

                    <h3 className="text-[11px] font-semibold mb-1.5 text-blue-300">⬇ Downstream (大客户) · LLM</h3>
                    <div className="space-y-1 mb-3">
                      {profile!.downstream.length === 0 && <div className="text-[10px] italic text-[var(--color-dim)]">LLM 未列出</div>}
                      {profile!.downstream.map((d) => (
                        <SupplyRow key={d.ticker} ticker={d.ticker} name={d.name} note={d.role} onClick={openTicker} />
                      ))}
                    </div>

                    <h3 className="text-[11px] font-semibold mb-1.5 text-amber-300">⚔ Competitors · LLM</h3>
                    <div className="space-y-1">
                      {profile!.competitors.length === 0 && <div className="text-[10px] italic text-[var(--color-dim)]">LLM 未列出</div>}
                      {profile!.competitors.map((c) => (
                        <SupplyRow key={c.ticker} ticker={c.ticker} name={c.name} note={c.note ?? ''} onClick={openTicker} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {tab === 'news' && <NewsTabBody ticker={ticker} />}

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

          {tab === 'chat' && (
            <DrawerChatTab ticker={ticker} projectId={projectId} />
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

function SupplyRow({
  ticker, name, note, onClick,
}: { ticker: string; name: string; note: string; onClick: (t: string) => void }) {
  return (
    <div className="flex items-start gap-2 text-[11px] py-1 px-2 border border-[var(--color-border)]/40 rounded">
      <button
        onClick={() => onClick(ticker)}
        className="font-mono w-20 flex-shrink-0 text-[var(--color-accent)] hover:underline text-left"
      >
        {ticker}
      </button>
      <span className="w-44 flex-shrink-0 truncate">{name}</span>
      <span className="text-[10px] text-[var(--color-dim)] flex-1">{note}</span>
    </div>
  )
}


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

function DrawerChatTab({ ticker, projectId }: { ticker: string; projectId: string }) {
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null)
  const [pendingContext, setPendingContext] = useState<{ symbol?: string } | null>(null)
  // Per-ticker session picker — sessionsBumpKey forces a remount of
  // ChatPanel when user clicks "+ new", which is the simplest way to
  // reset its internal sessionId state without exposing more props.
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null)
  const [sessionsBumpKey, setSessionsBumpKey] = useState(0)

  useEffect(() => { setPendingContext({ symbol: ticker }) }, [ticker])

  return (
    <div className="flex flex-col h-full -m-4">
      <DrawerSessionsBar
        ticker={ticker}
        projectId={projectId}
        onPickSession={(sid) => setPendingSessionId(sid)}
        onNewChat={() => {
          // Force ChatPanel remount: cleared internal state →
          // next user message creates a fresh session, tagged with
          // this ticker via the tickerTag prop below.
          setSessionsBumpKey(k => k + 1)
          setPendingSessionId(null)
        }}
      />
      <div className="flex-1 min-h-0">
        <ChatPanel
          key={`drawer-${ticker}-${sessionsBumpKey}`}
          projectId={projectId}
          pendingPrompt={pendingPrompt}
          pendingContext={pendingContext}
          onConsumePendingPrompt={() => setPendingPrompt(null)}
          hideSessions={true}
          tickerTag={ticker}
          pendingSessionId={pendingSessionId}
          onConsumePendingSession={() => setPendingSessionId(null)}
        />
      </div>
      <div className="px-3 py-2 border-t border-[var(--color-border)] bg-[var(--color-panel)]/20">
        <div className="text-[9px] text-[var(--color-dim)] mb-1">建议问 (点击发送):</div>
        <div className="flex flex-wrap gap-1">
          {[
            `${ticker} 估值合理吗? PE/PS/现金流`,
            `${ticker} 上下游受制于谁? 风险节点?`,
            `${ticker} vs 竞争对手谁的护城河更深?`,
            `如果 AI capex 见顶, ${ticker} 估值压缩多少?`,
          ].map((p) => (
            <button
              key={p}
              onClick={() => setPendingPrompt(p)}
              className="text-[9px] px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-dim)] hover:text-[var(--color-text)]"
            >
              {p.slice(0, 30)}…
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}


// ── Drawer per-ticker session picker (collapsible, with search) ──
function DrawerSessionsBar({
  ticker, projectId, onPickSession, onNewChat,
}: {
  ticker: string
  projectId: string
  onPickSession: (sessionId: string) => void
  onNewChat: () => void
}) {
  // Lazy-load: only fetch when user expands. Avoids one extra
  // network round-trip on every drawer open for users who never
  // care about past sessions.
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const sessionsQ = useChatSessions(open ? projectId : '', open ? ticker : null)
  const all = sessionsQ.data?.sessions ?? []
  const filtered = search.trim()
    ? all.filter(s => (s.title || '').toLowerCase().includes(search.trim().toLowerCase()))
    : all

  return (
    <div
      data-testid="drawer-sessions-bar"
      className="px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-panel)]/30 text-[10px]"
    >
      <div className="flex items-center gap-2">
        <button
          onClick={() => setOpen(o => !o)}
          className="text-[var(--color-dim)] hover:text-[var(--color-text)] flex items-center gap-1"
          title="过去对这个 ticker 的所有 chat sessions"
        >
          <MessagesSquare size={11} />
          <span>{open ? '▾' : '▸'} past {ticker} sessions{open ? ` (${all.length})` : ''}</span>
        </button>
        <button
          data-testid="drawer-chat-new"
          onClick={onNewChat}
          className="ml-auto text-[var(--color-dim)] hover:text-[var(--color-accent)] flex items-center gap-0.5"
          title="开新 session (会带 ticker_tag 标记)"
        >
          + new chat
        </button>
      </div>
      {open && (
        <div className="mt-1.5 space-y-1">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={`搜索 ${ticker} 历史 sessions…`}
            className="w-full px-2 py-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded text-[10px] outline-none focus:border-[var(--color-accent)]"
          />
          {sessionsQ.isLoading && <div className="italic text-[var(--color-dim)]">loading…</div>}
          {!sessionsQ.isLoading && filtered.length === 0 && (
            <div className="italic text-[var(--color-dim)] py-1">
              {all.length === 0
                ? `没有过去对 ${ticker} 的 chat. 点 "+ new chat" 开始第一个.`
                : `搜不到 "${search}".`}
            </div>
          )}
          <div className="max-h-32 overflow-y-auto">
            {filtered.map(s => (
              <button
                key={s.session_id}
                data-testid={`drawer-session-${s.session_id.slice(0, 8)}`}
                onClick={() => onPickSession(s.session_id)}
                className="w-full text-left px-2 py-1 rounded hover:bg-[var(--color-border)]/40 flex items-center gap-2"
              >
                <span className="flex-1 truncate text-[10px]">{s.title || '(empty)'}</span>
                <span className="text-[8.5px] text-[var(--color-dim)]">{s.message_count} msg</span>
                <span className="text-[8.5px] text-[var(--color-dim)] font-mono">
                  {(s.updated_at || s.created_at).slice(0, 10)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


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
function NewsTabBody({ ticker }: { ticker: string }) {
  const newsQ = useTickerNews(ticker)
  const data = newsQ.data
  const entries = data?.entries ?? []

  return (
    <div data-testid="news-tab-body">
      <div className="mb-3 text-[10px] text-[var(--color-dim)] flex items-center gap-2">
        <Newspaper size={11} />
        <span>{data ? `${data.count} items mentioning ${ticker}` : 'loading…'}</span>
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
        <div className="p-2 rounded border border-red-500/40 bg-red-500/10 text-[10px] text-red-300 mb-2">
          news fetch failed: {(newsQ.error as Error).message}
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
          —— 你对这只股的核心假设 (含 Bull / Bear / Exit triggers)
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
          No active thesis yet. Theses are <b>OPTIONAL</b>; if you have a clear bull case
          + bear case + exit triggers, write them down — chain panel will show them as your
          decision context.
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
              建议保留所有 4 节 (Bull / Bear / Exit triggers / Horizon) — Bear case
              是反 confirmation bias 的关键
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

      {/* Always-show: Bull / Bear side by side (PRO/CONTRA forced
          display per plan §5 Pillar 1 chain enhancement #3) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-1">
        <div className="border border-emerald-500/30 rounded p-1.5">
          <div className="text-[9px] uppercase tracking-wider text-emerald-300 mb-1">
            ✅ Bull case
          </div>
          <div className="text-[10.5px] leading-snug whitespace-pre-wrap">
            {t.sections.bull_case || (
              <span className="italic text-[var(--color-dim)]">(empty — 写一些)</span>
            )}
          </div>
        </div>
        <div className="border border-red-500/30 rounded p-1.5">
          <div className="text-[9px] uppercase tracking-wider text-red-300 mb-1">
            ❌ Bear case
          </div>
          <div className="text-[10.5px] leading-snug whitespace-pre-wrap">
            {t.sections.bear_case || (
              <span className="italic text-amber-300">
                ⚠ NO bear case recorded — 反 confirmation bias 用, 必须强迫自己写
              </span>
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
function DecisionHistoryRow({
  ticker,
  d,
}: {
  ticker: string
  d: { decision_id: string; kind: string; note: string; decided_at: string }
}) {
  const [open, setOpen] = useState(false)
  const outQ = useDecisionOutcome(open ? ticker : null, open ? d.decision_id : null)
  const o = outQ.data?.outcome
  const kindColor = {
    hold: 'text-emerald-300', add: 'text-emerald-300',
    trim: 'text-amber-300', sell: 'text-red-300',
    watch_only: 'text-[var(--color-dim)]', pass: 'text-[var(--color-dim)]',
  }[d.kind] ?? 'text-[var(--color-dim)]'
  const pctColor = (p: number) =>
    p > 0 ? 'text-emerald-300' : p < 0 ? 'text-red-300' : 'text-[var(--color-dim)]'
  return (
    <div className="text-[10px] leading-tight pl-1 border-l-2 border-[var(--color-border)]/30">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-baseline gap-2 text-left flex-wrap hover:bg-[var(--color-panel)]/30 px-1 py-0.5 rounded"
      >
        <span className="text-[var(--color-dim)] font-mono w-20 flex-shrink-0">
          {d.decided_at.slice(0, 16).replace('T', ' ')}
        </span>
        <span className={`${kindColor} font-semibold uppercase w-16 flex-shrink-0`}>
          {d.kind}
        </span>
        {d.note && (
          <span className="text-[var(--color-text)]/80 truncate flex-1 min-w-0">
            {d.note}
          </span>
        )}
        <span className="text-[9px] text-[var(--color-dim)] italic">
          {open ? '▾' : '→ outcome'}
        </span>
      </button>
      {open && (
        <div className="ml-3 mt-1 mb-1 pl-2 border-l-2 border-[var(--color-accent)]/30 text-[9.5px] space-y-0.5">
          {outQ.isLoading && (
            <div className="italic text-[var(--color-dim)]">loading outcome…</div>
          )}
          {o && o.price_move && (
            <div>
              <span className="text-[var(--color-dim)]">📈 price since: </span>
              <span className="font-mono">${o.price_move.start_close.toFixed(2)} → ${o.price_move.end_close.toFixed(2)}</span>
              <span className={`ml-1 font-mono font-semibold ${pctColor(o.price_move.pct)}`}>
                {o.price_move.pct > 0 ? '+' : ''}{o.price_move.pct.toFixed(2)}%
              </span>
              <span className="ml-1 text-[var(--color-dim)]">over {o.price_move.days}d</span>
            </div>
          )}
          {o && o.price_move == null && (
            <div className="italic text-[var(--color-dim)]">📈 price: no daily bars cached for this window — run daily_market_pull</div>
          )}
          {o && o.thesis_changes.length > 0 && (
            <div>
              <span className="text-[var(--color-dim)]">🧪 thesis changes ({o.thesis_changes.length}): </span>
              {o.thesis_changes.map((tc, i) => (
                <span key={i} className="mr-1">
                  <span className={tc.change === 'invalidated' ? 'text-red-300' : 'text-amber-300'}>
                    {tc.change}
                  </span>
                  {i < o.thesis_changes.length - 1 && <span className="text-[var(--color-dim)]"> · </span>}
                </span>
              ))}
            </div>
          )}
          {o && o.subsequent.length > 0 && (
            <div>
              <span className="text-[var(--color-dim)]">📡 subsequent ({o.subsequent.length} 高严重事件):</span>
              {o.subsequent.slice(0, 3).map((s, i) => (
                <div key={i} className="pl-2 leading-tight">
                  <span className="text-[var(--color-dim)] font-mono mr-1">{s.ts.slice(0, 10)}</span>
                  <span className={
                    s.severity === 'high' ? 'text-red-300' : 'text-amber-300'
                  }>[{s.severity}]</span>
                  <span className="ml-1">{s.scanner}/{s.type}</span>
                  {s.source_url && (
                    <a href={s.source_url} target="_blank" rel="noopener noreferrer"
                       className="text-[9px] text-[var(--color-accent)] hover:underline ml-1">↗</a>
                  )}
                </div>
              ))}
            </div>
          )}
          {o && o.closes.length > 0 && (
            <div>
              <span className="text-[var(--color-dim)]">📕 lots closed after: </span>
              {o.closes.map((c, i) => (
                <span key={i} className="mr-1">
                  {c.close_date.slice(0, 10)} <span className={pctColor(c.realized_pnl)}>{c.realized_pnl >= 0 ? '+' : ''}${c.realized_pnl.toFixed(0)}</span>
                  {i < o.closes.length - 1 && <span className="text-[var(--color-dim)]"> · </span>}
                </span>
              ))}
            </div>
          )}
          {o && !o.price_move && o.thesis_changes.length === 0 && o.subsequent.length === 0 && o.closes.length === 0 && (
            <div className="italic text-[var(--color-dim)]">
              still too early — no measurable outcome data yet
            </div>
          )}
        </div>
      )}
    </div>
  )
}


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
function DecisionAuditPanel({ ticker }: { ticker: string }) {
  const histQ = useDecisions(ticker)
  const recordMu = useRecordDecision()
  const [kind, setKind] = useState<DecisionKind | null>(null)
  const [note, setNote] = useState('')
  const items = histQ.data?.items ?? []

  function submit() {
    if (!kind) return
    recordMu.mutate(
      { ticker, kind, note: note.trim() || undefined },
      {
        onSuccess: () => { setKind(null); setNote('') },
      },
    )
  }

  return (
    <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[10.5px]">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="font-semibold text-[var(--color-text)] text-[11px]">📝 决策记录</span>
        <span className="text-[var(--color-dim)] italic text-[9.5px]">
          · 记录这次 review 的决定; 复盘时回放
        </span>
        {items.length > 0 && (
          <span className="ml-auto text-[9.5px] font-mono text-[var(--color-dim)]">
            {items.length} past
          </span>
        )}
      </div>

      {/* Record form */}
      <div className="flex flex-wrap items-center gap-1 mb-1">
        {(['hold', 'add', 'trim', 'sell', 'watch_only', 'pass'] as const).map(k => {
          const isActive = kind === k
          const colorCls = {
            hold:       'border-emerald-500/40 text-emerald-300',
            add:        'border-emerald-500/40 text-emerald-300',
            trim:       'border-amber-500/40 text-amber-300',
            sell:       'border-red-500/40 text-red-300',
            watch_only: 'border-[var(--color-border)] text-[var(--color-dim)]',
            pass:       'border-[var(--color-border)] text-[var(--color-dim)]',
          }[k]
          return (
            <button
              key={k}
              onClick={() => setKind(isActive ? null : k)}
              disabled={recordMu.isPending}
              className={`text-[10px] px-2 py-0.5 rounded border ${colorCls} ${
                isActive ? 'bg-[var(--color-accent)]/15' : 'hover:bg-[var(--color-panel)]/50'
              }`}
            >
              {k}
            </button>
          )
        })}
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="rationale (optional, recommended)"
          className="flex-1 min-w-[120px] text-[10px] px-2 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)]"
        />
        <button
          onClick={submit}
          disabled={!kind || recordMu.isPending}
          className="text-[10px] px-2 py-0.5 rounded border border-[var(--color-accent)] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {recordMu.isPending ? 'recording…' : 'record'}
        </button>
      </div>
      {recordMu.isError && (
        <div className="text-[9.5px] text-red-300 mb-1">
          ✗ {String((recordMu.error as Error)?.message).slice(0, 100)}
        </div>
      )}

      {/* History list */}
      {items.length === 0 ? (
        <div className="text-[10px] italic text-[var(--color-dim)] mt-1">
          — no decisions recorded yet; first record creates audit trail
        </div>
      ) : (
        <details className="mt-1">
          <summary className="text-[9.5px] text-[var(--color-dim)] cursor-pointer hover:text-[var(--color-text)]">
            ▸ history ({items.length})
          </summary>
          <div className="mt-1 space-y-0.5">
            {items.slice(0, 8).map(d => (
              <DecisionHistoryRow key={d.decision_id} ticker={ticker} d={d} />
            ))}
          </div>
        </details>
      )}
    </div>
  )
}


// ── DeltaSinceReviewBanner ───────────────────────────────────
// Compressed "what changed since last_reviewed_at" panel at top of
// drawer. Renders nothing when there are 0 changes — avoids noise
// for first-time opens with no signal flow.
function DeltaSinceReviewBanner({ ticker }: { ticker: string }) {
  const q = useDeltaSinceReview(ticker)
  if (q.isLoading || !q.data) return null
  const d = q.data
  if (d.total_changes === 0) {
    // First-time/quiet state: still render a thin "no changes" line so
    // user understands the system DID check, didn't fail.
    return (
      <div className="px-4 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[10px] text-[var(--color-dim)] italic">
        ✓ 自 {d.anchor_source === 'last_reviewed_at'
          ? `${d.days_since.toFixed(0)} 天前你上次复盘`
          : `${Math.round(d.days_since)} 天回溯窗口`} 没有 signal / thesis / 价格 / 业绩变化
      </div>
    )
  }
  const sevColor = (s: string) =>
    s === 'high' ? 'text-red-300' : s === 'med' ? 'text-amber-300' : 'text-[var(--color-dim)]'
  const pctColor = (p: number) =>
    p > 0 ? 'text-emerald-300' : p < 0 ? 'text-red-300' : 'text-[var(--color-dim)]'
  return (
    <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)] text-[10.5px] space-y-1">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-semibold text-[var(--color-accent)] text-[11px]">
          📊 自 {d.anchor_source === 'last_reviewed_at'
            ? `上次复盘 (${d.days_since.toFixed(0)}d 前)`
            : `${Math.round(d.days_since)}d 前 (从未复盘)`}
        </span>
        <span className="text-[var(--color-dim)] italic">
          · {d.total_changes} 处变化
        </span>
        {/* Scanner tally */}
        {Object.keys(d.scanner_tally).length > 0 && (
          <span className="text-[var(--color-dim)] font-mono">
            {Object.entries(d.scanner_tally).map(([k, v]) => `${k}=${v}`).join(' · ')}
          </span>
        )}
      </div>

      {/* Price move */}
      {d.price_delta && (
        <div className="text-[10px] pl-2">
          <span className="text-[var(--color-dim)]">💹 期间价格 </span>
          <span className="text-[var(--color-text)] font-mono">
            ${d.price_delta.start_close.toFixed(2)} → ${d.price_delta.end_close.toFixed(2)}
          </span>
          <span className={`ml-1.5 font-mono ${pctColor(d.price_delta.pct)}`}>
            {d.price_delta.pct > 0 ? '+' : ''}{d.price_delta.pct.toFixed(2)}%
          </span>
        </div>
      )}

      {/* Thesis changes */}
      {d.thesis_changes.length > 0 && (
        <div className="text-[10px] pl-2">
          <span className="text-[var(--color-dim)]">🧪 thesis: </span>
          {d.thesis_changes.map((tc, i) => (
            <span key={tc.thesis_id} className="mr-2">
              <span className={
                tc.change === 'invalidated' ? 'text-red-300' :
                tc.change === 'flagged_review' ? 'text-amber-300' :
                'text-emerald-300'
              }>
                {tc.change === 'created' ? '+ 新建' :
                 tc.change === 'invalidated' ? '× 失效' :
                 '⚠ 待 review'}
              </span>
              {i < d.thesis_changes.length - 1 && <span className="text-[var(--color-dim)]"> · </span>}
            </span>
          ))}
        </div>
      )}

      {/* Top signals — up to 4, severity-colored */}
      {d.signals.length > 0 && (
        <div className="text-[10px] pl-2 space-y-0.5">
          <span className="text-[var(--color-dim)]">📡 scanner events ({d.signals.length}):</span>
          {d.signals.slice(0, 4).map((s, i) => (
            <div key={i} className="pl-2 leading-snug">
              <span className={sevColor(s.severity)}>[{s.severity}]</span>{' '}
              <span className="text-[var(--color-text)] font-mono">{s.scanner}/{s.type}</span>
              <span className="text-[var(--color-dim)] ml-1">— {s.title}</span>
            </div>
          ))}
          {d.signals.length > 4 && (
            <div className="text-[9.5px] italic text-[var(--color-dim)] pl-2">
              + {d.signals.length - 4} more — 看 News / Smart Money / Live tabs 全部
            </div>
          )}
        </div>
      )}

      {/* New facts tally */}
      {Object.keys(d.new_facts_by_type).length > 0 && (
        <div className="text-[10px] pl-2">
          <span className="text-[var(--color-dim)]">📄 新 10-K facts: </span>
          <span className="text-[var(--color-text)] font-mono">
            {Object.entries(d.new_facts_by_type).map(([k, v]) => `${k}=${v}`).join(' · ')}
          </span>
        </div>
      )}

      {/* Closed lots in window */}
      {d.closed_lots.length > 0 && (
        <div className="text-[10px] pl-2">
          <span className="text-[var(--color-dim)]">📕 期间卖出 ({d.closed_lots.length}): </span>
          {d.closed_lots.map((cl, i) => (
            <span key={i} className="mr-2">
              <span className="font-mono">{cl.close_date.slice(0, 10)}</span>{' '}
              <span className={pctColor(cl.realized_pnl)}>
                {cl.realized_pnl >= 0 ? '+' : ''}${cl.realized_pnl.toFixed(0)}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}


function PositionPanel({ ticker }: { ticker: string }) {
  const posQ = usePositionByTicker(ticker)
  const sumQ = usePortfolioSummary('SPY')
  // Active lot being managed (delete / close modal target). null = no modal.
  const [managingLot, setManagingLot] = useState<EnrichedLot | null>(null)
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
        <span className="font-semibold text-[var(--color-text)]">我的持仓</span>
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

      {/* Per-lot detail — collapsible if many */}
      {d.lots.length > 0 && (
        <details className="mt-1.5">
          <summary className="text-[9.5px] text-[var(--color-dim)] cursor-pointer hover:text-[var(--color-text)]">
            ▸ 单笔 lot 明细 ({d.lots.length})
          </summary>
          <div className="mt-1 space-y-0.5 font-mono text-[10px]">
            {d.lots.map(l => (
              <div key={l.lot_id} className="flex items-center gap-2 text-[var(--color-dim)]">
                <span>{l.open_date}</span>
                <span className="text-[var(--color-text)]">
                  {l.open_quantity.toFixed(0)}sh @ ${l.open_price.toFixed(2)}
                </span>
                <span className="text-[var(--color-dim)]">
                  · {l.days_held}d ({l.is_long_term ? 'LT' : `ST, ${l.days_until_lt}d to LT`})
                </span>
                <span className={(l.lot_unrealized ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300'}>
                  {fmtMoney(l.lot_unrealized)}
                </span>
                {l.account_id && l.account_id !== 'main' && (
                  <span className="text-[var(--color-dim)] italic">[{l.account_id}]</span>
                )}
                {l.notes && (
                  <span className="text-[var(--color-dim)] italic truncate">— {l.notes}</span>
                )}
                <button
                  onClick={() => setManagingLot(l)}
                  title={`管理 lot #${l.lot_id} — 删除 (录入错) / 卖出 (close)`}
                  className="ml-auto w-5 h-5 rounded border border-[var(--color-border)]/60 hover:border-[var(--color-red,#e07070)] hover:text-[var(--color-red,#e07070)] text-[var(--color-dim)] flex items-center justify-center flex-shrink-0"
                >
                  <Trash2 size={9} />
                </button>
              </div>
            ))}
          </div>
        </details>
      )}

      {managingLot && (
        <ManageLotModal
          lot={managingLot}
          ticker={ticker}
          currentPrice={d.summary.current_price ?? managingLot.open_price}
          onClose={() => setManagingLot(null)}
        />
      )}
    </div>
  )
}


function ManageLotModal({
  lot, ticker, currentPrice, onClose,
}: {
  lot: EnrichedLot
  ticker: string
  currentPrice: number
  onClose: () => void
}) {
  // Two modes: 'choose' = pick delete vs close; 'close-form' = fill close
  // details. Delete confirms inline in 'choose' mode.
  const [mode, setMode] = useState<'choose' | 'close-form'>('choose')
  const [closeDate, setCloseDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [closePrice, setClosePrice] = useState(String(currentPrice.toFixed(2)))
  const [closeQty, setCloseQty] = useState(String(lot.open_quantity))
  const [closeFees, setCloseFees] = useState('0')
  const deleteMu = useDeleteLot()
  const closeMu = useCloseLot()

  const isPending = deleteMu.isPending || closeMu.isPending

  function onDelete() {
    deleteMu.mutate(
      { lot_id: lot.lot_id, ticker },
      { onSuccess: onClose },
    )
  }
  function onSubmitClose() {
    const price = Number(closePrice)
    const qty   = Number(closeQty)
    const fees  = Number(closeFees) || 0
    if (!isFinite(price) || price <= 0) return alert('卖出价必须是正数')
    if (!isFinite(qty) || qty <= 0 || qty > lot.open_quantity) {
      return alert(`卖出股数必须在 1 到 ${lot.open_quantity} 之间`)
    }
    closeMu.mutate(
      { lot_id: lot.lot_id, ticker, close_date: closeDate, close_price: price,
        close_quantity: qty, close_fees: fees },
      { onSuccess: onClose },
    )
  }

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded shadow-2xl w-[440px] max-w-[90vw] p-4 text-[11px]"
      >
        <div className="flex items-center gap-2 mb-2">
          <span className="font-semibold text-[var(--color-text)]">管理 lot #{lot.lot_id}</span>
          <span className="text-[var(--color-dim)]">·</span>
          <span className="font-mono text-[var(--color-text)]">{ticker}</span>
          <span className="text-[var(--color-dim)]">·</span>
          <span className="font-mono text-[var(--color-dim)]">
            {lot.open_quantity.toFixed(0)}sh @ ${lot.open_price.toFixed(2)} (opened {lot.open_date})
          </span>
          <button
            onClick={onClose}
            className="ml-auto text-[var(--color-dim)] hover:text-[var(--color-text)]"
          ><X size={12} /></button>
        </div>

        {mode === 'choose' && (
          <>
            <div className="space-y-2">
              <button
                onClick={() => setMode('close-form')}
                disabled={isPending}
                className="w-full text-left p-2.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent)]/5 disabled:opacity-50"
              >
                <div className="font-semibold text-[var(--color-text)]">📤 卖出 (close lot)</div>
                <div className="text-[var(--color-dim)] mt-0.5">
                  真实卖出，记录 P&amp;L、close_date、close_price，留在 paper trades 历史里。需要填卖出价格 / 日期 / 股数。
                </div>
              </button>

              <button
                onClick={onDelete}
                disabled={isPending}
                className="w-full text-left p-2.5 rounded border border-[var(--color-border)] hover:border-[var(--color-red,#e07070)] hover:bg-[var(--color-red,#e07070)]/5 disabled:opacity-50"
              >
                <div className="font-semibold text-[var(--color-red,#e07070)] flex items-center gap-1">
                  {deleteMu.isPending
                    ? <Loader2 size={11} className="animate-spin" />
                    : <Trash2 size={11} />}
                  删除 (录入错误)
                </div>
                <div className="text-[var(--color-dim)] mt-0.5">
                  整笔 lot 从 DB 抹除，不留任何痕迹。<b>只用在录入错误</b> (打错 ticker / 数量)。
                  真卖了请用上面"卖出"，否则 P&amp;L 历史就丢了。
                </div>
              </button>
            </div>

            {deleteMu.isError && (
              <div className="mt-2 text-[var(--color-red,#e07070)] text-[10px]">
                删除失败: {String((deleteMu.error as Error)?.message)}
              </div>
            )}
          </>
        )}

        {mode === 'close-form' && (
          <>
            <div className="grid grid-cols-2 gap-2 mt-1">
              <label className="text-[var(--color-dim)]">
                <div className="mb-0.5">卖出日期</div>
                <input
                  type="date"
                  value={closeDate}
                  onChange={(e) => setCloseDate(e.target.value)}
                  className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-1 text-[var(--color-text)] font-mono"
                />
              </label>
              <label className="text-[var(--color-dim)]">
                <div className="mb-0.5">
                  卖出价 <span className="italic">(now ${currentPrice.toFixed(2)})</span>
                </div>
                <input
                  type="number"
                  step="0.01"
                  value={closePrice}
                  onChange={(e) => setClosePrice(e.target.value)}
                  className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-1 text-[var(--color-text)] font-mono"
                />
              </label>
              <label className="text-[var(--color-dim)]">
                <div className="mb-0.5">
                  股数 <span className="italic">(max {lot.open_quantity})</span>
                </div>
                <input
                  type="number"
                  step="1"
                  min="1"
                  max={lot.open_quantity}
                  value={closeQty}
                  onChange={(e) => setCloseQty(e.target.value)}
                  className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-1 text-[var(--color-text)] font-mono"
                />
              </label>
              <label className="text-[var(--color-dim)]">
                <div className="mb-0.5">手续费</div>
                <input
                  type="number"
                  step="0.01"
                  value={closeFees}
                  onChange={(e) => setCloseFees(e.target.value)}
                  className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded px-1.5 py-1 text-[var(--color-text)] font-mono"
                />
              </label>
            </div>

            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() => setMode('choose')}
                disabled={isPending}
                className="px-2 py-1 text-[var(--color-dim)] hover:text-[var(--color-text)] disabled:opacity-50"
              >
                ← 返回
              </button>
              <button
                onClick={onSubmitClose}
                disabled={isPending}
                className="ml-auto px-3 py-1 rounded border border-[var(--color-accent)] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/10 disabled:opacity-50 flex items-center gap-1"
              >
                {closeMu.isPending && <Loader2 size={10} className="animate-spin" />}
                确认卖出
              </button>
            </div>

            {closeMu.isError && (
              <div className="mt-2 text-[var(--color-red,#e07070)] text-[10px]">
                卖出失败: {String((closeMu.error as Error)?.message)}
              </div>
            )}
          </>
        )}
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
