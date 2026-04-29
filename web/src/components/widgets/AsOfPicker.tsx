/**
 * AsOfPicker — Phase A (temporal replay): global "as of" date selector.
 *
 * Sits in the top nav. Default = 'live' (current behaviour). User can
 * pick any date that has a snapshot on disk; the picker reads
 * /api/lattice/snapshots to populate the dropdown. When changed, the
 * value is lifted to App.tsx and threaded into every lattice-derived
 * API call from both Research and Strategies tabs.
 *
 * Design doc: docs/design/2026-04-26_temporal-replay-architecture.md
 */

import { useState } from 'react'
import { Calendar, ChevronDown, Loader2, Radio, RefreshCw } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchJSON,
  useLatticeSnapshots,
  type LatticeSnapshotEntry,
} from '@/lib/api'


export interface AsOfPickerProps {
  projectId: string
  value: string  // 'live' | 'YYYY-MM-DD'
  onChange: (next: string) => void
}


export function AsOfPicker({ projectId, value, onChange }: AsOfPickerProps) {
  const [open, setOpen] = useState(false)
  const q = useLatticeSnapshots(projectId)
  const snapshots: LatticeSnapshotEntry[] = q.data?.snapshots ?? []
  const qc = useQueryClient()

  // Force a non-cached lattice build.  Hits /api/lattice/calls with
  // ``fresh=true``; backend bypasses dep_hash cache, runs L1+L2+L3
  // fresh, and writes a new snapshot with today's UTC date.  After
  // success we invalidate every cache that reads from /calls so the
  // dropdown immediately reflects the new row + Research+Strategies
  // tabs re-fetch the new payload.  Cost is 2-3 LLM calls (≈ 30-60s),
  // so the UI shows a spinner the whole time.
  const forceFresh = useMutation({
    mutationFn: () =>
      fetchJSON<unknown>(
        `/api/lattice/calls?project_id=${encodeURIComponent(projectId)}&fresh=true`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['lattice_snapshots', projectId] })
      qc.invalidateQueries({ queryKey: ['lattice_calls'] })
      qc.invalidateQueries({ queryKey: ['lattice_themes'] })
      qc.invalidateQueries({ queryKey: ['lattice_observations'] })
      qc.invalidateQueries({ queryKey: ['lattice_graph'] })
      qc.invalidateQueries({ queryKey: ['fin_strategies_today_fit'] })
      // Bounce back to LIVE so the user sees the just-generated payload
      // (instead of staying pinned to whatever past date they were on).
      onChange('live')
    },
  })

  const isLive = value === 'live'
  // Display date in user's local timezone for consistency with the
  // dropdown rows. The underlying ``value`` is still the server-side
  // UTC calendar date (used to look up the snapshot file) — we only
  // change what's shown.
  const matched = !isLive
    ? snapshots.find((s) => s.date === value)
    : undefined
  const localLabel = matched?.recorded_at
    ? new Date(matched.recorded_at).toLocaleDateString(undefined, {
        year: 'numeric', month: '2-digit', day: '2-digit',
      })
    : value   // fallback before snapshots load
  const label = isLive ? 'LIVE' : localLabel
  const labelColor = isLive
    ? 'var(--color-green)'
    : 'var(--color-amber,#e5a200)'

  return (
    <div className="relative flex items-center gap-1" data-testid="as-of-picker">
      <button
        onClick={() => setOpen(o => !o)}
        data-testid="as-of-picker-trigger"
        className="flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-mono rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 transition"
        style={{ color: labelColor }}
        title={
          isLive
            ? 'Live: lattice + strategy fit computed from current data'
            : `Replay: lattice + strategy fit from snapshot.\n` +
              `local date: ${localLabel}\n` +
              `UTC date (server): ${value}`
        }
      >
        {isLive ? <Radio size={10} /> : <Calendar size={10} />}
        <span>{label}</span>
        <ChevronDown size={9} />
      </button>

      {/* Force-fresh: bypass dep_hash cache, generate today's lattice
          snapshot now.  This is the answer to user's '为啥下拉里没有
          今天的结果?' — the daily cron isn't there, the strict cache
          returns stale on cache-hit, so today's row only appears after
          an explicit fresh build.  Cost: 2-3 LLM calls (~30-60s). */}
      <button
        onClick={() => forceFresh.mutate()}
        disabled={forceFresh.isPending}
        data-testid="as-of-force-fresh"
        className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-mono rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60 text-[var(--color-text)] disabled:opacity-50 disabled:cursor-not-allowed transition"
        title={
          'Force fresh build — 绕过 dep_hash cache, 跑 L1+L2+L3 重新生成 lattice，' +
          '写一条今天的 snapshot。耗时约 30–60 秒（2-3 个 LLM 调用）。\n' +
          '完成后下拉里会自动多出今天那一行；视图会切回 LIVE。\n' +
          '与上面日期选择无关 — 这个按钮永远生成"现在"。'
        }
      >
        {forceFresh.isPending
          ? <Loader2 size={10} className="animate-spin" />
          : <RefreshCw size={10} />
        }
        <span>{forceFresh.isPending ? 'building…' : 'fresh'}</span>
      </button>

      {forceFresh.isError && (
        <span
          className="text-[9px] text-[var(--color-red,#e07070)] font-mono"
          title={String((forceFresh.error as Error)?.message ?? forceFresh.error)}
        >
          fresh failed
        </span>
      )}

      {open && (
        <>
          {/* Click-away catcher */}
          <button
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-40 cursor-default"
            tabIndex={-1}
            aria-hidden="true"
          />
          <div
            data-testid="as-of-picker-menu"
            className="absolute right-0 top-full mt-1 w-[260px] rounded border border-[var(--color-border)] bg-[var(--color-panel)] shadow-lg z-50 max-h-[400px] overflow-y-auto"
          >
            <div className="px-2 py-1 border-b border-[var(--color-border)] text-[9px] uppercase tracking-wider text-[var(--color-dim)]">
              Source of truth
            </div>
            <button
              onClick={() => { onChange('live'); setOpen(false) }}
              data-testid="as-of-pick-live"
              className={`w-full px-2 py-1.5 text-left text-[10px] font-mono flex items-center gap-2 hover:bg-[var(--color-bg)]/40 ${isLive ? 'text-[var(--color-green)] bg-[var(--color-bg)]/30' : ''}`}
            >
              <Radio size={10} className="shrink-0" />
              <div className="flex-1">
                <div>LIVE</div>
                <div className="text-[8.5px] text-[var(--color-dim)]">
                  current lattice synth, refreshes every render
                </div>
              </div>
            </button>

            <div className="px-2 py-1 border-y border-[var(--color-border)] text-[9px] uppercase tracking-wider text-[var(--color-dim)]">
              Snapshots {snapshots.length > 0 && `(${snapshots.length})`}
            </div>
            {q.isLoading && (
              <div className="text-[10px] italic text-[var(--color-dim)] px-2 py-2">
                loading snapshot index…
              </div>
            )}
            {!q.isLoading && snapshots.length === 0 && (
              <div className="text-[10px] italic text-[var(--color-dim)] px-2 py-2 leading-[1.4]">
                No archived lattice runs yet. Snapshots are written
                automatically each time a fresh /calls build runs.
              </div>
            )}
            {snapshots.map((s) => {
              const selected = value === s.date
              const runCount = (s as LatticeSnapshotEntry & { run_count?: number }).run_count ?? 1
              // The two original lines mixed time-zones — `s.date` is
              // the server's UTC calendar date (e.g. "2026-04-28")
              // while `s.recorded_at` rendered through toLocaleString
              // is the user's local time (e.g. "4/27/2026, 7:31 PM").
              // Past midnight UTC + before midnight local, this read as
              // two different days for the same snapshot. Now: show
              // BOTH lines in local time, with UTC as a hover tooltip.
              const recorded = s.recorded_at ? new Date(s.recorded_at) : null
              const localDate = recorded
                ? recorded.toLocaleDateString(undefined, {
                    year: 'numeric', month: '2-digit', day: '2-digit',
                  })
                : s.date
              const localTime = recorded
                ? recorded.toLocaleTimeString(undefined, {
                    hour: '2-digit', minute: '2-digit', second: '2-digit',
                  })
                : ''
              const tzTip = recorded
                ? `local: ${recorded.toLocaleString()}\nUTC date (server): ${s.date}\nUTC ISO: ${s.recorded_at}`
                : ''
              return (
                <button
                  key={s.date}
                  onClick={() => { onChange(s.date); setOpen(false) }}
                  data-testid={`as-of-pick-${s.date}`}
                  title={tzTip}
                  className={`w-full px-2 py-1.5 text-left text-[10px] font-mono flex items-center gap-2 hover:bg-[var(--color-bg)]/40 ${selected ? 'text-[var(--color-amber,#e5a200)] bg-[var(--color-bg)]/30' : 'text-[var(--color-text)]'}`}
                >
                  <Calendar size={10} className="shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div>{localDate}</div>
                    <div className="text-[8.5px] text-[var(--color-dim)] truncate">
                      {localTime}
                      {runCount > 1 && (
                        <> · {runCount} runs</>
                      )}
                    </div>
                  </div>
                </button>
              )
            })}

            <div className="px-2 py-1 border-t border-[var(--color-border)] text-[8.5px] italic text-[var(--color-dim)] leading-[1.4]">
              The selected date applies to BOTH Research and Strategies
              tabs — themes, today_fit, by-theme, themes-as-of all
              read from the same snapshot.
            </div>
          </div>
        </>
      )}
    </div>
  )
}
