/**
 * CatalystCalendarWidget — 30-day catalyst timeline for held tickers.
 *
 * Catalysts that move position-sized $$: earnings dates + thesis exit
 * triggers (when parseable) + macro events. Aggregated into a single
 * chronological list so user can see "next 30 days of stuff that
 * matters" without scanning per-ticker.
 *
 * Sources (already in DB):
 *   - signal_events.signal_type='earnings_upcoming' (per-ticker)
 *   - signal_events.signal_type='macro_event'        (theme-level)
 *
 * Filter: held tickers only by default (the user's actual $$);
 * toggle to anchor (watchlist) to see broader.
 */
import { useMemo, useState } from 'react'
import { useStockResearch } from '@/components/research/StockResearchContext'
import {
  useRecentSignals, usePortfolioSummary, useUserWatchlist,
  type SignalEvent,
} from '@/lib/api'
import { FreshnessChip } from './FreshnessChip'
import { Calendar, Target, ChevronDown, ChevronRight } from 'lucide-react'
import { useCollapsed } from '@/lib/useCollapsed'


function parseEarningsBody(body: unknown): { date: string; days: number; eps_est?: number } | null {
  if (!body || typeof body !== 'object') return null
  const b = body as Record<string, unknown>

  // earnings_upcoming schema: earnings_date + days_until + eps_estimate
  const earningsDate = String(b.earnings_date ?? '')
  const earningsDays = Number(b.days_until ?? NaN)
  if (earningsDate && isFinite(earningsDays) && earningsDays >= 0) {
    return {
      date: earningsDate,
      days: earningsDays,
      eps_est: typeof b.eps_estimate === 'number' ? b.eps_estimate : undefined,
    }
  }

  // macro_release schema: date 'MM-DD-YYYY' + country + impact
  // Re-parse to compute days_until since cron emits this once and the
  // event ages — must derive freshness client-side or it'll never show.
  const macroDateRaw = String(b.date ?? '')
  const m = macroDateRaw.match(/^(\d{2})-(\d{2})-(\d{4})$/)
  if (m) {
    const [, mm, dd, yyyy] = m
    const target = new Date(`${yyyy}-${mm}-${dd}T00:00:00Z`)
    if (!isNaN(target.getTime())) {
      const now = new Date()
      const days = Math.floor((target.getTime() - now.getTime()) / 86400000)
      if (days >= 0) {
        return { date: `${yyyy}-${mm}-${dd}`, days }
      }
    }
  }
  return null
}


type ScopeMode = 'held' | 'watchlist' | 'all'


export function CatalystCalendarWidget() {
  const [scope, setScope] = useState<ScopeMode>('held')
  const [collapsed, toggle] = useCollapsed('catalyst')
  const { openTicker } = useStockResearch()
  const portfolio = usePortfolioSummary()
  const wl = useUserWatchlist()
  // 2026-05-16: query earnings + macro by scanner name. A generic
  // useRecentSignals({limit:100}) gets dominated by news_mention and
  // pushes daily earnings_upcoming events (which fire once at 04:00
  // UTC) off the tail — catalyst widget showed 0 even when DB had
  // valid NVDA/WMT earnings in <14d.
  const earningsQ = useRecentSignals({ scanner: 'earnings_calendar', limit: 200 })
  const macroQ    = useRecentSignals({ scanner: 'macro_calendar',    limit: 100 })

  const heldSet = useMemo(() => {
    const set = new Set<string>()
    for (const t of portfolio.data?.by_ticker ?? []) set.add(t.ticker.toUpperCase())
    return set
  }, [portfolio.data])
  const anchorSet = useMemo(() => {
    const set = new Set<string>(heldSet)
    for (const e of wl.data?.user_watchlist ?? []) {
      if (e?.ticker) set.add(e.ticker.toUpperCase())
    }
    return set
  }, [wl.data, heldSet])

  const items = useMemo(() => {
    const rows: Array<{
      ticker: string | null
      date: string
      days: number
      title: string
      scanner: string
      severity: string
      eps_est?: number
      source_url?: string | null
      event: SignalEvent
    }> = []
    const allEvents = [
      ...(earningsQ.data?.events ?? []),
      ...(macroQ.data?.events ?? []),
    ]
    for (const e of allEvents) {
      if (e.signal_type !== 'earnings_upcoming'
          && e.signal_type !== 'macro_event'
          && e.signal_type !== 'macro_release') continue
      const tk = e.ticker?.toUpperCase() ?? null
      // Macro events have no ticker → always relevant to user regardless
      // of scope (they move whole market).
      if (tk !== null) {
        if (scope === 'held' && !heldSet.has(tk)) continue
        if (scope === 'watchlist' && !anchorSet.has(tk)) continue
      }
      const parsed = parseEarningsBody(e.body)
      if (!parsed) continue
      if (parsed.days > 30) continue
      rows.push({
        ticker:    tk,
        date:      parsed.date,
        days:      parsed.days,
        title:     e.title ?? '',
        scanner:   e.scanner_name,
        severity:  e.severity,
        eps_est:   parsed.eps_est,
        source_url: e.source_url,
        event:     e,
      })
    }
    // Dedup by ticker — keep nearest-day per ticker
    const byTicker = new Map<string, typeof rows[0]>()
    for (const r of rows) {
      const key = r.ticker ?? r.title
      const existing = byTicker.get(key)
      if (!existing || r.days < existing.days) byTicker.set(key, r)
    }
    return Array.from(byTicker.values()).sort((a, b) => a.days - b.days)
  }, [earningsQ.data, macroQ.data, scope, heldSet, anchorSet])

  return (
    <div
      data-testid="catalyst-calendar-widget"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-panel)]/40 p-2.5"
    >
      <div className="flex items-baseline gap-2 mb-2 text-[10px] flex-wrap">
        <button
          onClick={toggle}
          title={collapsed ? '展开' : '折叠'}
          className="flex items-center gap-1 text-[var(--color-text)] font-semibold text-[11px] hover:opacity-80"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          <Calendar size={12} /> 30d catalysts
        </button>
        <span className="italic text-[var(--color-dim)]">
          · 业绩 + macro events within 30d
        </span>
        <div className="flex gap-0.5 ml-2">
          {(['held', 'watchlist', 'all'] as ScopeMode[]).map(m => {
            const active = m === scope
            const label = m === 'held' ? '🎯 your $$' : m === 'watchlist' ? '⭐ anchors' : '🌐 all'
            return (
              <button
                key={m}
                onClick={() => setScope(m)}
                className={`text-[9.5px] px-2 py-0.5 rounded border ${
                  active
                    ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
                    : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]'
                }`}
              >{label}</button>
            )
          })}
        </div>
        <span className="ml-auto flex items-center gap-2">
          <FreshnessChip job="earnings_calendar" />
          <span className="text-[9px] font-mono text-[var(--color-dim)]">{items.length} within 30d</span>
        </span>
      </div>

      {!collapsed && (<>
      {earningsQ.isLoading && (
        <div className="text-[10px] italic text-[var(--color-dim)]">loading…</div>
      )}

      {!earningsQ.isLoading && items.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-1.5 leading-snug">
          {scope === 'held'
            ? '✓ 你持仓内 30d 无业绩 / macro 大事件 — 短期没有临近 catalyst'
            : '无 catalyst — earnings_calendar / macro_calendar cron 可能未刷'}
        </div>
      )}

      {items.length > 0 && (
        <div className="space-y-0.5">
          {items.map(r => (
            <div key={r.event.event_id} className="text-[10px] flex items-baseline gap-2 leading-tight">
              {/* Days countdown badge */}
              <span className={
                `font-mono w-8 text-center flex-shrink-0 px-1 rounded ${
                  r.days <= 1 ? 'bg-red-500/20 text-red-300' :
                  r.days <= 5 ? 'bg-amber-500/20 text-amber-300' :
                  r.days <= 14 ? 'text-amber-300/80' :
                  'text-[var(--color-dim)]'
                }`
              }>
                {r.days === 0 ? '今天' : `${r.days}d`}
              </span>
              <span className="font-mono text-[var(--color-dim)] w-[60px] flex-shrink-0">
                {r.date}
              </span>
              {r.ticker ? (
                <button
                  onClick={() => openTicker(r.ticker!)}
                  title={`walk to ${r.ticker}`}
                  className="font-mono font-bold text-[var(--color-text)] hover:text-[var(--color-accent)] underline decoration-dotted underline-offset-2 w-[55px] flex-shrink-0 text-left"
                >{r.ticker}</button>
              ) : (
                <span className="font-mono text-[var(--color-dim)] italic w-[55px] flex-shrink-0">macro</span>
              )}
              {heldSet.has(r.ticker ?? '') && (
                <Target size={9} className="text-red-300 flex-shrink-0" />
              )}
              <span className="text-[var(--color-text)]/80 truncate flex-1 min-w-0">
                {r.title}
              </span>
              {r.eps_est != null && (
                <span className="text-[9px] font-mono text-[var(--color-dim)] flex-shrink-0">
                  EPS est ${r.eps_est.toFixed(2)}
                </span>
              )}
              {r.source_url && (
                <a href={r.source_url} target="_blank" rel="noopener noreferrer"
                   className="text-[9px] text-[var(--color-accent)] hover:underline flex-shrink-0">↗</a>
              )}
            </div>
          ))}
        </div>
      )}
      </>)}
    </div>
  )
}
