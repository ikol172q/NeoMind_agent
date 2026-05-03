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
  useTickerNews,
  type StockExposureEvent, type AnchoredFacts, type NextEarnings,
  type StockProfile,
} from '@/lib/api'
import {
  X, ExternalLink, Sparkles, BarChart3, Network, Newspaper,
  NotebookPen, MessagesSquare, Building2, Loader2, ShieldCheck,
} from 'lucide-react'
import { AnchoredFactsPanel } from './AnchoredFactsPanel'

type Status = 'researching' | 'watching' | 'pass' | 'own'
type TabKey = 'overview' | 'smart_money' | 'supply_chain' | 'news' | 'notes' | 'chat'


export function StockResearchDrawer() {
  const { ticker, projectId, closeTicker, openTicker } = useStockResearch()
  const [tab, setTab] = useState<TabKey>('overview')
  const [statusEditing, setStatusEditing] = useState<Status | null>(null)
  const [statusReasonDraft, setStatusReasonDraft] = useState('')
  const [noteDraft, setNoteDraft] = useState('')

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

  useEffect(() => {
    if (!ticker) return
    setTab('overview')
    setStatusEditing(null)
    setStatusReasonDraft('')
    setNoteDraft('')
  }, [ticker])

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
    noteMu.mutate({ ticker, body: noteDraft.trim() })
    setNoteDraft('')
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
          <button
            onClick={closeTicker}
            className="text-[var(--color-dim)] hover:text-[var(--color-text)] p-1 rounded"
            title="ESC to close"
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

        {/* Tab strip */}
        <div className="flex border-b border-[var(--color-border)] bg-[var(--color-bg)]">
          {tabs.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className={
                'flex items-center gap-1.5 px-3 py-2 text-[11px] border-b-2 transition ' +
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
              <div className="mb-3 text-[10px] text-[var(--color-dim)]">
                你的笔记 (DB 持久化). LLM 抽取的 tag 后续 wire — 现在你输入啥就存啥.
              </div>
              <div className="space-y-2 mb-4">
                {notes.length === 0 && (
                  <div className="text-[10px] italic text-[var(--color-dim)] py-1">No notes yet — 写下你对这只股的想法.</div>
                )}
                {notes.map((n) => (
                  <div key={n.id} className="border border-[var(--color-border)]/40 rounded p-2">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[9px] font-mono text-[var(--color-dim)]">{new Date(n.ts).toLocaleString()}</span>
                      {n.tag && (
                        <span className="text-[9px] font-mono px-1.5 py-0 rounded border border-amber-500/40 text-amber-300">
                          {n.tag}
                        </span>
                      )}
                      {n.source === 'llm-extract' && (
                        <span className="text-[8.5px] text-[var(--color-dim)] italic">(LLM)</span>
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
                <div className="flex items-center gap-2 mt-1">
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

  useEffect(() => { setPendingContext({ symbol: ticker }) }, [ticker])

  return (
    <div className="flex flex-col h-full -m-4">
      <div className="flex-1 min-h-0">
        <ChatPanel
          projectId={projectId}
          pendingPrompt={pendingPrompt}
          pendingContext={pendingContext}
          onConsumePendingPrompt={() => setPendingPrompt(null)}
          hideSessions={true}
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
