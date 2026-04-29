/**
 * LastAuditPanel — visible "did the auditor actually run?" surface
 * with a TimeScope filter and an Aggregated/Timeline view switch.
 *
 * Why this exists
 * ---------------
 * The Strategies tab shows ⚠ unverified on every entry that hasn't
 * been promoted to `verified` / `partially_verified`.  But three
 * very different states render the SAME ⚠ chip:
 *
 *   (a) the daily auditor never ran (cron never fired — APScheduler
 *       in-process state lost on uvicorn restart)
 *   (b) the auditor ran but the corpus didn't ground any numeric
 *       claims (mechanical validator working as designed: rejected
 *       fabrications)
 *   (c) the auditor ran and PROMOTED some entries — but the entry
 *       you're looking at wasn't in this batch (we audit 5/day)
 *
 * Layout
 * ------
 *   Row 1   ▸  TimeScope pills          [今天 | 某一天 | 某段时间 | 全部]
 *              (+ inline date inputs depending on scope)
 *   Row 2   ▸  ViewMode pills (only in Range scope)
 *                                       [Aggregated | Timeline]
 *   Row 3   ▸  status icon + summary line + Run-now button
 *              (Run-now is INTENTIONALLY separated from time controls
 *               so picking a past date does NOT trigger a build —
 *               matches user's "选择时间和刷新分开" requirement)
 *   Body    ▸  Aggregated (default) — per-run table for the scope
 *              Timeline (range only) — per-day rollup
 *
 * Data plumbing
 * -------------
 * useSchedulerRuns('audit_strategies', limit, { startedAfter, startedBefore })
 * — bounds keyed into the cache, refetches automatically on scope change.
 *
 * 1:1 sync with the lattice as-of state
 * -------------------------------------
 * The user's hard rule: "Strategies tab 和 Research tab 里面的结果是
 * 1:1 对应的，尤其是在选定时间（或者时间范围之后）".  So the audit-
 * panel scope is bidirectionally bound to App.tsx's ``appAsOf``:
 *
 *   audit scope            →  appAsOf           (effect on lattice)
 *   today / live / all     →  'live'            current snapshot
 *   single { date }        →  date              that day's snapshot
 *   range  { from, to }    →  to                end-of-range snapshot
 *
 *   appAsOf change         →  audit scope       (driven from top nav)
 *   'live'                 →  today (default)   audit defaults to today
 *   YYYY-MM-DD             →  single { date }   audit shows that day
 *
 * The `asOf` + `onChangeAsOf` props plumb this through.
 *
 * Bilingual: 中文为主，英文术语保留.
 */

import { useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Clock,
  CalendarDays,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJSON, useSchedulerRuns, type SchedulerRun } from '@/lib/api'


// ── helpers ───────────────────────────────────────────────────────

function localTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return iso
  }
}

function ago(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    const ms = Date.now() - new Date(iso).getTime()
    if (ms < 0) return 'in the future?'
    const sec = Math.round(ms / 1000)
    if (sec < 60) return `${sec}s 前 / ${sec}s ago`
    const min = Math.round(sec / 60)
    if (min < 60) return `${min} 分钟前 / ${min}m ago`
    const hr  = Math.round(min / 60)
    if (hr < 36) return `${hr} 小时前 / ${hr}h ago`
    const day = Math.round(hr / 24)
    return `${day} 天前 / ${day}d ago`
  } catch {
    return ''
  }
}

/** Today's date in local time as YYYY-MM-DD. */
function todayLocal(): string {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/** Convert an YYYY-MM-DD (local) to ISO 8601 UTC at start of that day,
 *  then optionally end-of-day.  Used to translate user-picked local
 *  calendar dates into the UTC bounds the backend filter expects. */
function dayBoundsLocal(
  ymd: string, edge: 'start' | 'end',
): string {
  // Construct as a local datetime at 00:00 / 23:59:59.999, then
  // serialize as ISO (which carries the UTC offset).  This way the
  // user picks "2026-04-28" in their local TZ and the bound matches
  // their day, not UTC's day.
  const [y, m, d] = ymd.split('-').map((n) => Number(n))
  const dt = edge === 'start'
    ? new Date(y, m - 1, d, 0, 0, 0, 0)
    : new Date(y, m - 1, d, 23, 59, 59, 999)
  return dt.toISOString()
}

/** Group an YMD bound from an ISO timestamp (local TZ). */
function ymdLocal(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    return `${yyyy}-${mm}-${dd}`
  } catch {
    return ''
  }
}


// ── types ─────────────────────────────────────────────────────────

type Scope = 'today' | 'single' | 'range' | 'all'
type ViewMode = 'aggregated' | 'timeline'

interface RangeBounds {
  /** ISO 8601, undefined means no lower bound. */
  startedAfter?: string
  startedBefore?: string
}


// ── component ─────────────────────────────────────────────────────

export interface LastAuditPanelProps {
  /** App-level lattice as-of value: 'live' or 'YYYY-MM-DD'.
   *  Audit panel scope syncs to this — lattice and audit stay 1:1. */
  asOf: string
  /** Bubble scope changes back up so the lattice in BOTH tabs follows.
   *  Called with 'live' for today/all-time scopes, or a YYYY-MM-DD
   *  for single-day / range (= range end date). */
  onChangeAsOf: (next: string) => void
}

/** Initial scope inferred from the appAsOf prop. 'live' → today
 *  (the most useful default); a date string → single-day pinned to it. */
function scopeFromAsOf(asOf: string): { scope: Scope, singleDate: string } {
  if (!asOf || asOf === 'live') {
    return { scope: 'today', singleDate: todayLocal() }
  }
  return { scope: 'single', singleDate: asOf }
}

export function LastAuditPanel({ asOf, onChangeAsOf }: LastAuditPanelProps) {
  const qc = useQueryClient()

  // Scope state — initial value from the App-level asOf
  const init = useMemo(() => scopeFromAsOf(asOf), [])  // run once
  const [scope, setScope] = useState<Scope>(init.scope)
  const [singleDate, setSingleDate] = useState<string>(init.singleDate)
  // Default range: last 7 days inclusive
  const [rangeFrom, setRangeFrom] = useState<string>(() => {
    const d = new Date()
    d.setDate(d.getDate() - 6)
    return ymdLocal(d.toISOString())
  })
  const [rangeTo, setRangeTo] = useState<string>(todayLocal())

  // View mode for range scope
  const [viewMode, setViewMode] = useState<ViewMode>('aggregated')

  // ── 1:1 sync wiring ────────────────────────────────────────────
  // (a) when scope state changes, push the matching as-of UP so the
  //     lattice in BOTH tabs follows. today/all → live; single →
  //     date; range → range end.
  useEffect(() => {
    let next: string
    if (scope === 'today' || scope === 'all') next = 'live'
    else if (scope === 'single') next = singleDate
    else /* range */               next = rangeTo
    if (next !== asOf) onChangeAsOf(next)
    // We deliberately don't put `asOf` in deps — that's the inbound
    // direction handled in the next effect. Re-running on asOf here
    // would create a feedback loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, singleDate, rangeTo])

  // (b) when asOf changes externally (top-nav AsOfPicker), reflect
  //     it in scope state.  'live' → today; YYYY-MM-DD → single day.
  //     Skip the update if scope already matches to avoid bouncing.
  useEffect(() => {
    if (asOf === 'live') {
      if (scope !== 'today' && scope !== 'all' && scope !== 'range') {
        setScope('today')
      }
    } else {
      // a date — single day mode pinned to it, unless user is in range
      if (scope === 'today' || scope === 'all') {
        setScope('single')
        setSingleDate(asOf)
      } else if (scope === 'single' && asOf !== singleDate) {
        setSingleDate(asOf)
      }
      // if user is in 'range', leave their range alone — they
      // explicitly chose it. The OUTBOUND effect already keeps
      // asOf == rangeTo, so external asOf change here would only
      // happen if rangeTo is being driven by us anyway.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOf])

  // Translate scope state → query bounds.  No bounds = "all time".
  const bounds: RangeBounds = useMemo(() => {
    if (scope === 'today') {
      return {
        startedAfter:  dayBoundsLocal(todayLocal(), 'start'),
        startedBefore: dayBoundsLocal(todayLocal(), 'end'),
      }
    }
    if (scope === 'single') {
      return {
        startedAfter:  dayBoundsLocal(singleDate, 'start'),
        startedBefore: dayBoundsLocal(singleDate, 'end'),
      }
    }
    if (scope === 'range') {
      return {
        startedAfter:  dayBoundsLocal(rangeFrom, 'start'),
        startedBefore: dayBoundsLocal(rangeTo, 'end'),
      }
    }
    return {} // all time
  }, [scope, singleDate, rangeFrom, rangeTo])

  // Larger limit when scope is wider so range views aren't truncated.
  const limit = scope === 'all' ? 200 : scope === 'range' ? 200 : 50
  const q = useSchedulerRuns('audit_strategies', limit, {
    startedAfter:  bounds.startedAfter ?? null,
    startedBefore: bounds.startedBefore ?? null,
  })
  const runs: SchedulerRun[] = q.data?.runs ?? []

  // Expand state for the per-run table at the bottom
  const [expanded, setExpanded] = useState(false)

  // Run-now mutation (always uses *current* data — no scope coupling)
  const runNow = useMutation({
    mutationFn: () =>
      fetchJSON<{ job: string; result: unknown }>(
        '/api/scheduler/run/audit_strategies',
        { method: 'POST' },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['fin_scheduler_runs', 'audit_strategies'] })
      qc.invalidateQueries({ queryKey: ['fin_scheduler_jobs'] })
      qc.invalidateQueries({ queryKey: ['fin_strategies'] })
    },
  })

  // Aggregate metric over the selected runs.
  const totals = useMemo(() => {
    let audited = 0, promoted = 0, stillUnv = 0, errs = 0, durSec = 0
    for (const r of runs) {
      audited  += (r.metadata.audited_n        as number | undefined) ?? 0
      promoted += (r.metadata.promoted_n       as number | undefined) ?? 0
      stillUnv += (r.metadata.still_unverified as number | undefined) ?? 0
      errs     += (r.metadata.errors_n         as number | undefined) ?? 0
      durSec   += r.duration_seconds ?? 0
    }
    return { audited, promoted, stillUnv, errs, durSec, n: runs.length }
  }, [runs])

  // Timeline aggregation: bucket by local day → totals.
  const timelineRows = useMemo(() => {
    const byDay = new Map<string, {
      day: string, n: number, audited: number, promoted: number,
      stillUnv: number, errs: number,
    }>()
    for (const r of runs) {
      const day = ymdLocal(r.completed_at ?? r.started_at)
      if (!day) continue
      const cur = byDay.get(day) ?? {
        day, n: 0, audited: 0, promoted: 0, stillUnv: 0, errs: 0,
      }
      cur.n        += 1
      cur.audited  += (r.metadata.audited_n        as number | undefined) ?? 0
      cur.promoted += (r.metadata.promoted_n       as number | undefined) ?? 0
      cur.stillUnv += (r.metadata.still_unverified as number | undefined) ?? 0
      cur.errs     += (r.metadata.errors_n         as number | undefined) ?? 0
      byDay.set(day, cur)
    }
    // newest day first
    return Array.from(byDay.values()).sort((a, b) => b.day.localeCompare(a.day))
  }, [runs])

  // For the status icon at the top of the summary row.
  const last = runs[0]
  let StatusIcon = Clock
  let statusColor = 'var(--color-dim)'
  if (last) {
    if (last.status === 'completed') {
      const errs = (last.metadata.errors_n as number | undefined) ?? 0
      if (errs > 0) {
        StatusIcon = AlertTriangle
        statusColor = 'var(--color-amber,#e5a200)'
      } else {
        StatusIcon = CheckCircle2
        statusColor = 'var(--color-green)'
      }
    } else if (last.status === 'failed') {
      StatusIcon = XCircle
      statusColor = 'var(--color-red,#e07070)'
    } else if (last.status === 'running') {
      StatusIcon = Loader2
      statusColor = 'var(--color-accent)'
    }
  }

  return (
    <div
      data-testid="last-audit-panel"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40"
    >
      {/* ── Row 1: TimeScope pills + per-scope inputs ── */}
      <div className="px-2.5 pt-2 pb-1.5 flex flex-wrap items-center gap-2 text-[10px]">
        <CalendarDays size={11} className="text-[var(--color-dim)]" />
        <span className="text-[var(--color-dim)]">范围 / Scope:</span>
        <ScopePill label="今天 / Today"     active={scope === 'today'}  onClick={() => setScope('today')}  testid="scope-today" />
        <ScopePill label="某一天 / Single day" active={scope === 'single'} onClick={() => setScope('single')} testid="scope-single" />
        <ScopePill label="某段时间 / Range" active={scope === 'range'}  onClick={() => setScope('range')}  testid="scope-range" />
        <ScopePill label="全部 / All time"  active={scope === 'all'}    onClick={() => setScope('all')}    testid="scope-all" />

        {scope === 'single' && (
          <input
            data-testid="scope-single-date"
            type="date"
            value={singleDate}
            onChange={(e) => setSingleDate(e.target.value)}
            max={todayLocal()}
            className="ml-1 px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[10px] text-[var(--color-text)]"
          />
        )}
        {scope === 'range' && (
          <>
            <input
              data-testid="scope-range-from"
              type="date"
              value={rangeFrom}
              onChange={(e) => setRangeFrom(e.target.value)}
              max={rangeTo || todayLocal()}
              className="ml-1 px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[10px] text-[var(--color-text)]"
            />
            <span className="text-[var(--color-dim)]">→</span>
            <input
              data-testid="scope-range-to"
              type="date"
              value={rangeTo}
              onChange={(e) => setRangeTo(e.target.value)}
              min={rangeFrom}
              max={todayLocal()}
              className="px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-panel)] text-[10px] text-[var(--color-text)]"
            />
          </>
        )}
      </div>

      {/* ── Row 2: View-mode pills (range only) ── */}
      {scope === 'range' && (
        <div className="px-2.5 pb-1.5 flex flex-wrap items-center gap-2 text-[10px]">
          <span className="text-[var(--color-dim)]">视图 / View:</span>
          <ScopePill label="汇总 / Aggregated" active={viewMode === 'aggregated'} onClick={() => setViewMode('aggregated')} testid="view-aggregated" />
          <ScopePill label="按天 / Timeline"   active={viewMode === 'timeline'}   onClick={() => setViewMode('timeline')}   testid="view-timeline" />
        </div>
      )}

      {/* ── Row 3: status + summary line + Run-now button ── */}
      <div className="flex items-center gap-2 px-2.5 py-2 border-t border-[var(--color-border)] text-[10px]">
        <button
          onClick={() => setExpanded((v) => !v)}
          data-testid="last-audit-toggle"
          className="flex items-center gap-1 text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="展开看 scope 内每一次 run 的详情"
        >
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <StatusIcon
            size={12}
            style={{ color: statusColor }}
            className={last?.status === 'running' ? 'animate-spin' : ''}
          />
        </button>

        <div className="flex-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[var(--color-text)] font-semibold">
            {scope === 'today'  && '今天的审计 / Today’s audit'}
            {scope === 'single' && `${singleDate} 的审计 / Audit on ${singleDate}`}
            {scope === 'range'  && `${rangeFrom} → ${rangeTo} 的审计 / Audits in range`}
            {scope === 'all'    && '全部审计历史 / All audit history'}
          </span>

          {q.isLoading && (
            <span className="italic text-[var(--color-dim)]">loading…</span>
          )}

          {!q.isLoading && runs.length === 0 && (
            <span className="text-[var(--color-amber,#e5a200)]">
              {scope === 'today'
                ? 'auditor 今天还没跑过。点 "Run now" 立即跑（~30s，调 LLM 做 extractor + 机械校验）。'
                : '该范围内没有审计记录。'}
            </span>
          )}

          {runs.length > 0 && (
            <>
              <span className="font-mono text-[var(--color-text)]">
                {totals.n} run{totals.n === 1 ? '' : 's'}
              </span>
              <span className="text-[var(--color-border)]">·</span>
              <span className="font-mono">
                <span className="text-[var(--color-dim)]">audited </span>
                <span className="text-[var(--color-text)]">{totals.audited}</span>
              </span>
              <span className="font-mono">
                <span className="text-[var(--color-dim)]">→ promoted </span>
                <span style={{
                  color: totals.promoted > 0 ? 'var(--color-green)' : 'var(--color-dim)',
                }}>
                  {totals.promoted}
                </span>
              </span>
              <span className="font-mono">
                <span className="text-[var(--color-dim)]">still unverified </span>
                <span style={{
                  color: totals.stillUnv > 0 ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)',
                }}>
                  {totals.stillUnv}
                </span>
              </span>
              {totals.errs > 0 && (
                <span className="font-mono">
                  <span className="text-[var(--color-dim)]">errors </span>
                  <span style={{ color: 'var(--color-red,#e07070)' }}>{totals.errs}</span>
                </span>
              )}
              {scope !== 'today' && last && (
                <>
                  <span className="text-[var(--color-border)]">·</span>
                  <span className="text-[var(--color-dim)] font-mono">
                    last in scope: {localTime(last.completed_at ?? last.started_at)} ({ago(last.completed_at ?? last.started_at)})
                  </span>
                </>
              )}
            </>
          )}
        </div>

        {/* Run-now is intentionally OUTSIDE the time-scope group, so
            picking a past date never accidentally triggers a build.
            The button always runs the auditor against current data. */}
        <button
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
          data-testid="last-audit-run-now"
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] disabled:opacity-50 disabled:cursor-not-allowed"
          title="同步触发一次审计（~30s）— 永远用当前数据，与上面 scope 无关"
        >
          <RefreshCw
            size={11}
            className={runNow.isPending ? 'animate-spin' : ''}
          />
          <span>{runNow.isPending ? '运行中… / running…' : 'Run now'}</span>
        </button>
      </div>

      {/* ── Last-run explanation (collapsed view, single/today scopes only) ── */}
      {!expanded && last?.metadata.explanation
        && (scope === 'today' || scope === 'single') && (
        <div className="px-2.5 pb-2 text-[10px] text-[var(--color-dim)] leading-[1.5] -mt-1">
          {String(last.metadata.explanation)}
        </div>
      )}

      {runNow.isError && (
        <div className="px-2.5 pb-2 text-[10px] text-[var(--color-red,#e07070)] font-mono">
          run-now failed: {String((runNow.error as Error)?.message ?? runNow.error)}
        </div>
      )}

      {/* ── Body ── */}
      {expanded && (
        <div className="px-2.5 pb-2 border-t border-[var(--color-border)] mt-1 pt-2">
          {scope === 'range' && viewMode === 'timeline'
            ? <TimelineTable rows={timelineRows} />
            : <RunsTable runs={runs} />
          }

          <div className="mt-2 text-[9.5px] italic text-[var(--color-dim)] leading-[1.5]">
            Cron: 默认每天 04:00 UTC 跑一次，每次审计 5 条 / day。
            36 条全审完需要 8 天。
            <b className="text-[var(--color-text)]">
              {' '}如果 still ⚠ 没下降，不一定是系统坏 — 可能是 corpus
              不支持 Phase 3 subagent 写的具体数字（"≈70% win rate"
              这种），机械校验拒绝了，所以没 promote。
            </b>
            {' '}查 docs/strategies/audit_logs/ 能看到每次的 verdict 详情。
          </div>
        </div>
      )}
    </div>
  )
}


// ── sub-components ────────────────────────────────────────────────

function ScopePill({
  label, active, onClick, testid,
}: {
  label: string
  active: boolean
  onClick: () => void
  testid: string
}) {
  return (
    <button
      data-testid={testid}
      onClick={onClick}
      className={`px-1.5 py-0.5 rounded border text-[10px] ${
        active
          ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-[var(--color-bg)]/60'
          : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]'
      }`}
    >
      {label}
    </button>
  )
}

function RunsTable({ runs }: { runs: SchedulerRun[] }) {
  if (runs.length === 0) {
    return (
      <div className="text-[10px] italic text-[var(--color-dim)]">
        No runs in this scope.
      </div>
    )
  }
  return (
    <>
      <div className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)] mb-1.5">
        Runs in scope ({runs.length})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[10px] font-mono">
          <thead>
            <tr className="text-[var(--color-dim)] border-b border-[var(--color-border)]">
              <th className="text-left py-1 pr-2">when</th>
              <th className="text-left py-1 pr-2">type</th>
              <th className="text-left py-1 pr-2">status</th>
              <th className="text-right py-1 pr-2">audited</th>
              <th className="text-right py-1 pr-2">promoted</th>
              <th className="text-right py-1 pr-2">still ⚠</th>
              <th className="text-right py-1 pr-2">errors</th>
              <th className="text-right py-1 pr-2">dur</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const m = r.metadata
              const errs = (m.errors_n as number | undefined) ?? 0
              const statusCol =
                r.status === 'completed' && errs === 0
                  ? 'var(--color-green)'
                  : r.status === 'failed'
                    ? 'var(--color-red,#e07070)'
                    : 'var(--color-amber,#e5a200)'
              return (
                <tr
                  key={r.run_id}
                  className="border-b border-[var(--color-border)]/30"
                  title={
                    (m.explanation as string | undefined) ??
                    (r.error_message ?? '')
                  }
                >
                  <td className="py-1 pr-2 text-[var(--color-text)]">
                    {localTime(r.completed_at ?? r.started_at)}
                  </td>
                  <td className="py-1 pr-2 text-[var(--color-dim)]">{r.run_type}</td>
                  <td className="py-1 pr-2" style={{ color: statusCol }}>{r.status}</td>
                  <td className="py-1 pr-2 text-right text-[var(--color-text)]">
                    {(m.audited_n as number | undefined) ?? '—'}
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <span style={{
                      color: ((m.promoted_n as number) ?? 0) > 0
                        ? 'var(--color-green)'
                        : 'var(--color-dim)',
                    }}>
                      {(m.promoted_n as number | undefined) ?? '—'}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <span style={{
                      color: ((m.still_unverified as number) ?? 0) > 0
                        ? 'var(--color-amber,#e5a200)'
                        : 'var(--color-dim)',
                    }}>
                      {(m.still_unverified as number | undefined) ?? '—'}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-right">
                    <span style={{
                      color: errs > 0
                        ? 'var(--color-red,#e07070)'
                        : 'var(--color-dim)',
                    }}>
                      {errs || '—'}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-right text-[var(--color-dim)]">
                    {r.duration_seconds != null
                      ? `${r.duration_seconds.toFixed(1)}s`
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function TimelineTable({
  rows,
}: {
  rows: Array<{
    day: string
    n: number
    audited: number
    promoted: number
    stillUnv: number
    errs: number
  }>
}) {
  if (rows.length === 0) {
    return (
      <div className="text-[10px] italic text-[var(--color-dim)]">
        No runs in this range — pick a wider window or check the cron.
      </div>
    )
  }
  return (
    <>
      <div className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)] mb-1.5">
        By day ({rows.length})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[10px] font-mono">
          <thead>
            <tr className="text-[var(--color-dim)] border-b border-[var(--color-border)]">
              <th className="text-left py-1 pr-2">day</th>
              <th className="text-right py-1 pr-2">runs</th>
              <th className="text-right py-1 pr-2">audited</th>
              <th className="text-right py-1 pr-2">promoted</th>
              <th className="text-right py-1 pr-2">still ⚠</th>
              <th className="text-right py-1 pr-2">errors</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.day} className="border-b border-[var(--color-border)]/30">
                <td className="py-1 pr-2 text-[var(--color-text)]">{r.day}</td>
                <td className="py-1 pr-2 text-right text-[var(--color-text)]">{r.n}</td>
                <td className="py-1 pr-2 text-right text-[var(--color-text)]">{r.audited}</td>
                <td className="py-1 pr-2 text-right">
                  <span style={{
                    color: r.promoted > 0 ? 'var(--color-green)' : 'var(--color-dim)',
                  }}>
                    {r.promoted}
                  </span>
                </td>
                <td className="py-1 pr-2 text-right">
                  <span style={{
                    color: r.stillUnv > 0 ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)',
                  }}>
                    {r.stillUnv}
                  </span>
                </td>
                <td className="py-1 pr-2 text-right">
                  <span style={{
                    color: r.errs > 0 ? 'var(--color-red,#e07070)' : 'var(--color-dim)',
                  }}>
                    {r.errs || '—'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
