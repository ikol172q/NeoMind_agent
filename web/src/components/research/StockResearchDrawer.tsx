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
  type StockExposureEvent,
} from '@/lib/api'
import {
  X, ExternalLink, Sparkles, BarChart3, Network, Newspaper,
  NotebookPen, MessagesSquare, Building2, Loader2,
} from 'lucide-react'

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
                {profile?.name ?? (profileQ.isLoading ? 'loading…' : '(profile not generated yet)')}
              </span>
              <StatusPillSelector
                current={effectiveStatus}
                userStatusReason={profile?.user_status_reason ?? null}
                userStatusTs={profile?.user_status_ts ?? null}
                onPick={(s) => { setStatusEditing(s); setStatusReasonDraft('') }}
              />
            </div>
            <div className="text-[10px] text-[var(--color-dim)] mt-1 flex items-center gap-3 flex-wrap">
              {profile?.sector && <span>{profile.sector}</span>}
              {profile?.quick_stats?.price     && <span>· {profile.quick_stats.price}</span>}
              {profile?.quick_stats?.marketCap && <span>· cap {profile.quick_stats.marketCap}</span>}
              {profile?.quick_stats?.pe        && <span>· PE {profile.quick_stats.pe}</span>}
              {profile?.style_verdict && <span className="ml-2 italic">{profile.style_verdict}</span>}
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
            <>
              <div className="mb-3 flex items-center gap-2 text-[10px] text-[var(--color-dim)] flex-wrap">
                <Sparkles size={10} className="text-[var(--color-accent)]" />
                {profile?.generated_at
                  ? `NeoMind generated · ${new Date(profile.generated_at).toLocaleString()} (${profile.generated_model ?? '?'})`
                  : 'No cached profile yet'}
                <button
                  className="ml-auto px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1 disabled:opacity-50"
                  onClick={regenerate}
                  disabled={regenMu.isPending}
                  title="调用 NeoMind LLM 生成 (~$0.01, 15-30s)"
                >
                  {regenMu.isPending
                    ? <><Loader2 size={10} className="animate-spin" /> 生成中…</>
                    : <>✨ {hasProfile ? 'regenerate' : 'generate'}</>}
                </button>
                <a
                  href={`https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`}
                  target="_blank" rel="noopener noreferrer"
                  className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1"
                >
                  TradingView <ExternalLink size={9} />
                </a>
                <a
                  href={`https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`}
                  target="_blank" rel="noopener noreferrer"
                  className="px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] flex items-center gap-1"
                >
                  Yahoo <ExternalLink size={9} />
                </a>
              </div>

              {regenMu.error && (
                <div className="mb-2 p-2 rounded border border-red-500/40 bg-red-500/10 text-[10px] text-red-300">
                  生成失败: {regenMu.error.message}
                </div>
              )}

              {!hasProfile && !regenMu.isPending && (
                <div className="text-[11px] italic text-[var(--color-dim)] py-4 leading-[1.6]">
                  {ticker} 还没有 cached profile. 点上面 ✨ generate, NeoMind LLM 会拉
                  数据生成 business summary / 业务分段 / 上下游 / 催化剂 / 风险, 缓存到
                  DB. 下次秒开. 第一次大概 15-30 秒, 花费 ~$0.01.
                </div>
              )}

              {hasProfile && (
                <>
                  <h3 className="text-[12px] font-semibold mb-1.5">业务概览</h3>
                  <p className="mb-3 text-[11px] leading-[1.7]">{profile!.summary}</p>

                  {profile!.segments.length > 0 && (
                    <>
                      <h3 className="text-[12px] font-semibold mb-1.5">业务分段</h3>
                      <div className="space-y-1 mb-3">
                        {profile!.segments.map((s) => (
                          <div key={s.name} className="flex items-center gap-2 text-[11px]">
                            <div className="w-24 flex-shrink-0">{s.name}</div>
                            <div className="flex-1 h-1.5 bg-[var(--color-panel)] rounded">
                              <div className="h-full bg-[var(--color-accent)] rounded" style={{ width: `${s.pct}%` }} />
                            </div>
                            <span className="text-[10px] text-[var(--color-dim)] font-mono w-10 text-right">{s.pct}%</span>
                            {s.note && <span className="text-[9.5px] text-[var(--color-dim)] flex-1">{s.note}</span>}
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {profile!.catalysts.length > 0 && (
                    <>
                      <h3 className="text-[12px] font-semibold mb-1.5">未来催化剂</h3>
                      <div className="space-y-1 mb-3">
                        {profile!.catalysts.map((c, i) => (
                          <div key={i} className="flex items-start gap-2 text-[11px]">
                            <span className={`text-[9px] font-mono w-20 flex-shrink-0 ${
                              c.severity === 'high' ? 'text-red-400' :
                              c.severity === 'med'  ? 'text-amber-400' : 'text-[var(--color-dim)]'
                            }`}>{c.when}</span>
                            <span className="flex-1">{c.what}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}

                  {profile!.risks.length > 0 && (
                    <>
                      <h3 className="text-[12px] font-semibold mb-1.5 text-red-300">主要风险</h3>
                      <ul className="space-y-1 mb-3 list-disc pl-4">
                        {profile!.risks.map((r, i) => (
                          <li key={i} className="text-[11px]">{r}</li>
                        ))}
                      </ul>
                    </>
                  )}

                  {profile!.source_citations.length > 0 && (
                    <>
                      <h3 className="text-[12px] font-semibold mb-1.5 text-[var(--color-dim)]">引用 (LLM 自报)</h3>
                      <ol className="space-y-0.5 mb-3 list-decimal pl-4">
                        {profile!.source_citations.map((s) => (
                          <li key={s.id} className="text-[10px]">
                            <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-[var(--color-accent)] hover:underline">
                              {s.title || s.url}
                            </a>
                          </li>
                        ))}
                      </ol>
                    </>
                  )}
                </>
              )}
            </>
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
              <div className="mb-3 text-[10px] text-[var(--color-dim)]">
                LLM-extracted from SEC 10-K + 行业知识. 每个 ticker 可点 → 打开它的 drawer.
              </div>
              {!hasProfile && (
                <div className="text-[11px] italic text-[var(--color-dim)]">
                  上下游数据来自 LLM-生成 profile. 切到 Overview tab 点 ✨ generate.
                </div>
              )}
              {hasProfile && (
                <>
                  <h3 className="text-[12px] font-semibold mb-2 text-green-300">⬆ Upstream (供应商)</h3>
                  <div className="space-y-1 mb-4">
                    {profile!.upstream.length === 0 && <div className="text-[10px] italic text-[var(--color-dim)]">LLM 未列出</div>}
                    {profile!.upstream.map((u) => (
                      <SupplyRow key={u.ticker} ticker={u.ticker} name={u.name} note={u.role} onClick={openTicker} />
                    ))}
                  </div>

                  <h3 className="text-[12px] font-semibold mb-2 text-blue-300">⬇ Downstream (大客户)</h3>
                  <div className="space-y-1 mb-4">
                    {profile!.downstream.length === 0 && <div className="text-[10px] italic text-[var(--color-dim)]">LLM 未列出</div>}
                    {profile!.downstream.map((d) => (
                      <SupplyRow key={d.ticker} ticker={d.ticker} name={d.name} note={d.role} onClick={openTicker} />
                    ))}
                  </div>

                  <h3 className="text-[12px] font-semibold mb-2 text-amber-300">⚔ Competitors</h3>
                  <div className="space-y-1">
                    {profile!.competitors.length === 0 && <div className="text-[10px] italic text-[var(--color-dim)]">LLM 未列出</div>}
                    {profile!.competitors.map((c) => (
                      <SupplyRow key={c.ticker} ticker={c.ticker} name={c.name} note={c.note ?? ''} onClick={openTicker} />
                    ))}
                  </div>
                </>
              )}
            </>
          )}

          {tab === 'news' && (
            <div className="text-[11px] italic text-[var(--color-dim)] py-2 leading-[1.6]">
              📰 News 后续 wire — 会从 news_scanner 按 ticker filter + LLM 二次过滤
              clickbait. 当前 placeholder, 真实数据接口待补.
            </div>
          )}

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
