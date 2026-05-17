/**
 * EarningsHistoryMini — Phase 3.
 *
 * Small bar chart showing the last 4-8 quarters of EPS surprise%.
 * Each bar's height = abs(surprise_pct), color = beat (green) or
 * miss (red). Shown in StockResearchDrawer chain panel as decision
 * context: "this company has beat 4 quarters in a row" is meaningful.
 *
 * Per plan §5 Pillar 6 (information dimension coverage).
 */
import { useEarningsHistory } from '@/lib/api'
import { TrendingUp } from 'lucide-react'

const MAX_BAR_PX = 36   // tallest bar height in px

export function EarningsHistoryMini({ ticker }: { ticker: string }) {
  const q = useEarningsHistory(ticker, 8)
  const rows = (q.data?.history ?? []).slice().reverse()  // chronological L→R
  if (q.isLoading) {
    return (
      <div className="text-[10px] italic text-[var(--color-dim)] py-1">
        loading earnings history…
      </div>
    )
  }
  if (rows.length === 0) {
    // No history yet — surface honestly so user knows the
    // earnings_calendar daily job hasn't backfilled this ticker
    return (
      <div className="text-[10px] italic text-[var(--color-dim)] py-1">
        no earnings history cached — daily job runs at 07:10 weekdays
        (or run manually via /api/scheduler/run/earnings_calendar)
      </div>
    )
  }

  const beats = rows.filter(r => (r.surprise_pct ?? 0) > 0).length
  const misses = rows.filter(r => (r.surprise_pct ?? 0) < 0).length
  const maxAbsSurprise = Math.max(
    ...rows.map(r => Math.abs(r.surprise_pct ?? 0)),
    1.0,
  )

  return (
    <div className="border border-[var(--color-border)]/50 rounded p-2 my-2">
      <div className="flex items-center gap-2 mb-2 text-[10px] flex-wrap">
        <TrendingUp size={11} className="text-[var(--color-dim)]" />
        <span className="font-semibold text-[var(--color-text)]">业绩 surprise 历史</span>
        <span className="text-[var(--color-dim)]">
          {beats}/{rows.length} beats · {misses} misses
        </span>
        {/* 2026-05-16: provenance stamp — every data panel must show
            where it came from + when it was pulled. */}
        <span className="ml-auto text-[8.5px] italic text-[var(--color-dim)]">
          source: yfinance · earnings_calendar cron
        </span>
      </div>

      {/* Bar chart row */}
      <div className="flex items-end gap-1 h-[44px]">
        {rows.map((r, i) => {
          const sp = r.surprise_pct ?? 0
          const isBeat = sp > 0
          const isMiss = sp < 0
          const heightPx = Math.max(2, Math.abs(sp) / maxAbsSurprise * MAX_BAR_PX)
          const color = isBeat ? 'bg-emerald-500/70'
                      : isMiss ? 'bg-red-500/70'
                      : 'bg-[var(--color-dim)]/40'
          return (
            <div
              key={i}
              className="flex-1 flex flex-col items-center justify-end"
              title={`${r.earnings_date}: est ${r.eps_est?.toFixed(2) ?? '—'} actual ${r.eps_actual?.toFixed(2) ?? '—'} surprise ${sp >= 0 ? '+' : ''}${sp.toFixed(2)}%`}
            >
              <div
                className={`w-full rounded-t ${color}`}
                style={{ height: `${heightPx}px` }}
              />
            </div>
          )
        })}
      </div>

      {/* Date labels */}
      <div className="flex gap-1 mt-1 text-[7.5px] text-[var(--color-dim)] font-mono">
        {rows.map((r, i) => (
          <div key={i} className="flex-1 text-center truncate">
            {r.earnings_date.slice(5)}
          </div>
        ))}
      </div>
    </div>
  )
}
