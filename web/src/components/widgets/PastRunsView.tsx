/**
 * PastRunsView — Phase 6 followup #1: detailed past run log.
 *
 * Backend `/api/db/runs` (already exists in agent/finance/persistence/api.py)
 * exposes the full analysis_runs history. Every scheduler tick or manual
 * action leaves a row: run_id, run_type, job_name, started_at, completed_at,
 * status, error_message, rows_written, duration_seconds.
 *
 * This widget renders the rows as a tight timeline so the user can answer
 * "what did the agent actually do, when, and did it succeed?" — closing
 * the audit loop the lattice's L3 calls don't cover (data + scheduler
 * activity vs. LLM reasoning activity).
 *
 * Designed to slot into an existing tab as a panel (default: Audit), but
 * is fully self-contained — pass `defaultJobFilter` to scope to one job.
 */

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Clock, AlertTriangle, CheckCircle2, RefreshCw, Database } from 'lucide-react'
import { useFinPastRuns, useFinRunRows, type FinPastRun } from '@/lib/api'


function formatDuration(secs: number | null): string {
  if (secs == null) return '—'
  if (secs < 1) return `${(secs * 1000).toFixed(0)} ms`
  if (secs < 60) return `${secs.toFixed(2)}s`
  if (secs < 3600) return `${(secs / 60).toFixed(1)}m`
  return `${(secs / 3600).toFixed(1)}h`
}


function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return iso }
}


function StatusPill({ status }: { status: string }) {
  const cfg: Record<string, { color: string; bg: string; label: string }> = {
    completed: { color: 'var(--color-green)', bg: 'rgba(0,200,120,0.10)', label: '✓ done' },
    failed:    { color: 'var(--color-red,#f06060)', bg: 'rgba(240,96,96,0.10)', label: '✗ fail' },
    running:   { color: 'var(--color-amber,#e5a200)', bg: 'rgba(229,162,0,0.10)', label: '⟳ run' },
    cancelled: { color: 'var(--color-dim)', bg: 'rgba(120,120,120,0.10)', label: '⊘ cancel' },
  }
  const c = cfg[status] ?? { color: 'var(--color-dim)', bg: 'transparent', label: status }
  return (
    <span
      data-testid={`run-status-${status}`}
      className="px-1.5 py-0.5 rounded text-[9px] font-mono whitespace-nowrap"
      style={{ color: c.color, background: c.bg, border: `1px solid ${c.color}` }}
    >
      {c.label}
    </span>
  )
}


function PastRunRow({ row }: { row: FinPastRun }) {
  const [open, setOpen] = useState(false)
  const hasError = row.status === 'failed' || !!row.error_message
  return (
    <div
      data-testid={`past-run-row-${row.run_id}`}
      data-source={`/api/db/runs (run_id=${row.run_id})`}
      className="border-b border-[var(--color-border)] last:border-b-0"
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-1 text-left text-[10px] hover:bg-[var(--color-bg)] transition"
      >
        {open
          ? <ChevronDown size={11} className="text-[var(--color-dim)] shrink-0" />
          : <ChevronRight size={11} className="text-[var(--color-dim)] shrink-0" />}
        <StatusPill status={row.status} />
        <span className="font-mono text-[var(--color-text)] truncate" style={{ minWidth: 100 }}>
          {row.job_name}
        </span>
        <span className="text-[var(--color-dim)] shrink-0">{formatTime(row.started_at)}</span>
        <span className="ml-auto text-[var(--color-dim)] flex items-center gap-1 shrink-0">
          <Clock size={9} />{formatDuration(row.duration_seconds)}
        </span>
        {row.rows_written != null && row.rows_written > 0 && (
          <span className="text-[var(--color-accent)] shrink-0">+{row.rows_written}</span>
        )}
        {hasError && <AlertTriangle size={10} className="text-[var(--color-red,#f06060)]" />}
      </button>

      {open && (
        <div className="px-6 pb-2 text-[9px] font-mono text-[var(--color-dim)] flex flex-col gap-0.5">
          <div>run_id: <span className="text-[var(--color-text)]">{row.run_id}</span></div>
          <div>run_type: <span className="text-[var(--color-text)]">{row.run_type}</span></div>
          <div>started: <span className="text-[var(--color-text)]">{row.started_at}</span></div>
          <div>completed: <span className="text-[var(--color-text)]">{row.completed_at ?? '(still running)'}</span></div>
          {row.universe_size != null && (
            <div>universe: <span className="text-[var(--color-text)]">{row.universe_size}</span></div>
          )}
          {row.rows_written != null && (
            <div>rows_written: <span className="text-[var(--color-text)]">{row.rows_written}</span></div>
          )}
          {row.error_message && (
            <div className="text-[var(--color-red,#f06060)] mt-0.5 whitespace-pre-wrap break-words">
              error: {row.error_message}
            </div>
          )}
          {row.metadata && Object.keys(row.metadata).length > 0 && (
            <details className="mt-0.5">
              <summary className="cursor-pointer hover:text-[var(--color-text)]">metadata</summary>
              <pre className="text-[8.5px] mt-0.5 p-1 bg-[var(--color-bg)] border border-[var(--color-border)] rounded overflow-x-auto">
                {JSON.stringify(row.metadata, null, 2)}
              </pre>
            </details>
          )}
          {/* Phase 6 followup: drill-down into the actual rows this
              run wrote, grouped by target table. Lazy-fetched only on
              expand. */}
          <RunRowsDrilldown runId={row.run_id} jobName={row.job_name} />
        </div>
      )}
    </div>
  )
}


/** Drill-down: what rows did this run actually write?
 *  Lazy-fetches /api/db/runs/{run_id}/rows on first render. */
function RunRowsDrilldown({ runId, jobName }: { runId: string; jobName: string }) {
  const q = useFinRunRows(runId, true)
  if (q.isLoading) return (
    <div className="mt-1 italic">loading rows written by this run…</div>
  )
  if (q.isError) return (
    <div className="mt-1 text-[var(--color-red,#f06060)]">
      drill-down failed: {(q.error as Error).message}
    </div>
  )
  const data = q.data
  if (!data) return null
  const tables = Object.entries(data.by_table).filter(([, t]) => (t.count ?? 0) > 0)

  return (
    <div className="mt-1.5 flex flex-col gap-1">
      <div className="flex items-center gap-1 text-[9.5px] uppercase tracking-wider text-[var(--color-dim)]">
        <Database size={9} />
        <span>Rows written ({data.total_rows} total)</span>
      </div>
      {tables.length === 0 ? (
        <div className="italic text-[8.5px]">
          This run produced 0 persistent rows.
          {jobName === 'compliance_check' && ' (Normal — no wash sale / PDT events to detect.)'}
        </div>
      ) : (
        tables.map(([tbl, info]) => (
          <details key={tbl} className="border border-[var(--color-border)] rounded">
            <summary className="cursor-pointer px-1.5 py-0.5 text-[9px] hover:bg-[var(--color-bg)]/40 flex items-center gap-1">
              <span className="font-mono text-[var(--color-text)]">{tbl}</span>
              <span className="text-[var(--color-accent)]">+{info.count}</span>
              {info.match_method && (
                <span className="italic text-[8px]">({info.match_method})</span>
              )}
            </summary>
            {info.rows.length > 0 && (
              <div className="px-1.5 pb-1 overflow-x-auto">
                <table className="text-[8.5px] border-collapse w-full font-mono">
                  <thead>
                    <tr className="text-[var(--color-dim)]">
                      {Object.keys(info.rows[0]).slice(0, 8).map((k) => (
                        <th key={k} className="text-left pr-2 pb-0.5 border-b border-[var(--color-border)]">{k}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {info.rows.slice(0, 20).map((r, i) => (
                      <tr key={i} className="text-[var(--color-text)]">
                        {Object.keys(info.rows[0]).slice(0, 8).map((k) => (
                          <td key={k} className="pr-2 py-0 truncate max-w-[140px]" title={String(r[k] ?? '')}>
                            {String(r[k] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {info.rows.length > 20 && (
                  <div className="text-[8px] italic mt-0.5">…+{info.rows.length - 20} more</div>
                )}
              </div>
            )}
          </details>
        ))
      )}
    </div>
  )
}


export function PastRunsView({
  defaultJobFilter,
  defaultLimit = 50,
  collapsed: collapsedProp,
  title = 'Past runs',
}: {
  defaultJobFilter?: string
  defaultLimit?: number
  collapsed?: boolean
  title?: string
} = {}) {
  const [collapsed, setCollapsed] = useState<boolean>(collapsedProp ?? false)
  const [job, setJob] = useState<string | undefined>(defaultJobFilter)
  const [limit, setLimit] = useState<number>(defaultLimit)
  const q = useFinPastRuns({ jobName: job, limit })

  const groups = useMemo(() => {
    const rows = q.data?.runs ?? []
    const by: Record<string, { count: number; ok: number; failed: number; lastAt: string }> = {}
    for (const r of rows) {
      const g = (by[r.job_name] ??= { count: 0, ok: 0, failed: 0, lastAt: r.started_at })
      g.count += 1
      if (r.status === 'completed') g.ok += 1
      if (r.status === 'failed') g.failed += 1
      if (r.started_at > g.lastAt) g.lastAt = r.started_at
    }
    return by
  }, [q.data])

  const allJobs = Object.keys(groups).sort()

  return (
    <div
      data-testid="past-runs-view"
      data-source="/api/db/runs"
      className="border border-[var(--color-border)] rounded bg-[var(--color-panel,transparent)] flex flex-col"
    >
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex items-center gap-2 px-2 py-1 text-[11px] uppercase tracking-wider text-[var(--color-dim)] hover:text-[var(--color-text)] transition border-b border-[var(--color-border)]"
      >
        {collapsed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
        <Clock size={11} />
        <span>{title}</span>
        <span className="text-[var(--color-dim)] normal-case">
          ({q.data?.count ?? '…'} runs{job ? ` · filter:${job}` : ''})
        </span>
        {q.isFetching && <RefreshCw size={10} className="animate-spin ml-auto" />}
        {!q.isFetching && q.data && q.data.runs.some(r => r.status === 'failed') && (
          <AlertTriangle size={11} className="text-[var(--color-red,#f06060)] ml-auto" />
        )}
        {!q.isFetching && q.data && !q.data.runs.some(r => r.status === 'failed') && (
          <CheckCircle2 size={11} className="text-[var(--color-green)] ml-auto" />
        )}
      </button>

      {!collapsed && (
        <>
          {/* filter bar */}
          <div className="flex items-center gap-2 px-2 py-1 text-[9px] border-b border-[var(--color-border)]">
            <span className="text-[var(--color-dim)] uppercase tracking-wider">Job:</span>
            <button
              onClick={() => setJob(undefined)}
              className={`px-1.5 py-0.5 rounded font-mono ${!job ? 'text-[var(--color-text)] border border-[var(--color-accent)]' : 'text-[var(--color-dim)] border border-[var(--color-border)]'}`}
            >
              all
            </button>
            {allJobs.map((j) => {
              const g = groups[j]
              return (
                <button
                  key={j}
                  onClick={() => setJob(j)}
                  className={`px-1.5 py-0.5 rounded font-mono ${job === j ? 'text-[var(--color-text)] border border-[var(--color-accent)]' : 'text-[var(--color-dim)] border border-[var(--color-border)]'}`}
                  title={`${j}: ${g.ok}/${g.count} ok${g.failed ? `, ${g.failed} failed` : ''}`}
                >
                  {j}
                  {g.failed > 0 && <span className="text-[var(--color-red,#f06060)] ml-1">·{g.failed}f</span>}
                </button>
              )
            })}
            <span className="ml-auto text-[var(--color-dim)] flex items-center gap-1">
              limit:
              {[20, 50, 100, 200].map((n) => (
                <button
                  key={n}
                  onClick={() => setLimit(n)}
                  className={`px-1 ${limit === n ? 'text-[var(--color-text)] underline' : ''}`}
                >
                  {n}
                </button>
              ))}
              <button
                onClick={() => q.refetch()}
                className="ml-1 text-[var(--color-dim)] hover:text-[var(--color-text)]"
                title="refresh"
              >
                <RefreshCw size={10} />
              </button>
            </span>
          </div>

          {/* rows */}
          <div className="flex flex-col">
            {q.data?.runs?.length ? (
              q.data.runs.map((r) => <PastRunRow key={r.run_id} row={r} />)
            ) : q.isLoading ? (
              <div className="text-[10px] italic text-[var(--color-dim)] px-2 py-3">
                loading recent runs…
              </div>
            ) : (
              <div className="text-[10px] italic text-[var(--color-dim)] px-2 py-3">
                No analysis runs yet. The scheduler writes a row each time a job
                fires; manual runs (e.g. <code>compliance_check</code>,
                <code> daily_market_pull</code>) also leave a row.
              </div>
            )}
          </div>

          {/* footer explanation */}
          <div className="text-[8.5px] italic text-[var(--color-dim)] px-2 py-1 border-t border-[var(--color-border)]">
            Source: <code>/api/db/runs</code> → table <code>analysis_runs</code>.
            Click any row to expand. Errors highlighted red. Auto-refreshes every 30s.
          </div>
        </>
      )}
    </div>
  )
}
