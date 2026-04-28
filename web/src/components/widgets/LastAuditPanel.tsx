/**
 * LastAuditPanel — visible "did the auditor actually run?" surface.
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
 * Without a run-history surface, "system is broken" is
 * indistinguishable from "system worked, kept things honest".  This
 * panel surfaces:
 *
 *   • when the auditor last ran (local time + "X hours ago")
 *   • how many entries it touched + the verdict breakdown
 *   • any error from a failed run
 *   • a "Run audit now" button (hits POST /api/scheduler/run/audit_strategies)
 *   • expand → last 5 runs as a compact table
 *
 * Data plumbing: GET /api/scheduler/runs/audit_strategies?limit=5
 * (rows live in `analysis_runs`; the rich summary is JSON in
 * `metadata_json`, populated by audit_strategies.run on completion).
 *
 * Bilingual: 中文为主，英文术语保留 — matches user preference.
 */

import { useState } from 'react'
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Clock,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJSON, useSchedulerRuns, type SchedulerRun } from '@/lib/api'


/** Format an ISO UTC timestamp as a local-time short-form string. */
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

/** Human-friendly "X minutes/hours/days ago" relative to now. */
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


export function LastAuditPanel() {
  const qc = useQueryClient()
  const q = useSchedulerRuns('audit_strategies', 10)
  const [expanded, setExpanded] = useState(false)

  const runNow = useMutation({
    mutationFn: () =>
      fetchJSON<{ job: string; result: unknown }>(
        '/api/scheduler/run/audit_strategies',
        { method: 'POST' },
      ),
    onSuccess: () => {
      // The new run becomes the latest row — refetch so the panel
      // immediately reflects what just happened. Also refetch the
      // strategies catalog (auditor writes back into strategies.yaml,
      // but in this V1 the YAML is read at process start; an explicit
      // catalog invalidation still helps if we later wire it through).
      qc.invalidateQueries({ queryKey: ['fin_scheduler_runs', 'audit_strategies'] })
      qc.invalidateQueries({ queryKey: ['fin_scheduler_jobs'] })
      qc.invalidateQueries({ queryKey: ['fin_strategies'] })
    },
  })

  const runs: SchedulerRun[] = q.data?.runs ?? []
  const last = runs[0]

  // Status icon + colour from the most recent run.  No run yet → grey.
  let StatusIcon = Clock
  let statusColor = 'var(--color-dim)'
  let statusLabel = '从未运行 / never run'
  if (last) {
    if (last.status === 'completed') {
      const errs = (last.metadata.errors_n as number | undefined) ?? 0
      if (errs > 0) {
        StatusIcon = AlertTriangle
        statusColor = 'var(--color-amber,#e5a200)'
        statusLabel = '完成 (有 fetch 错误) / completed with errors'
      } else {
        StatusIcon = CheckCircle2
        statusColor = 'var(--color-green)'
        statusLabel = '完成 / completed'
      }
    } else if (last.status === 'failed') {
      StatusIcon = XCircle
      statusColor = 'var(--color-red,#e07070)'
      statusLabel = '失败 / failed'
    } else if (last.status === 'running') {
      StatusIcon = Loader2
      statusColor = 'var(--color-accent)'
      statusLabel = '运行中 / running'
    }
  }

  return (
    <div
      data-testid="last-audit-panel"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40"
    >
      <div className="flex items-center gap-2 px-2.5 py-2 text-[10px]">
        <button
          onClick={() => setExpanded((v) => !v)}
          data-testid="last-audit-toggle"
          className="flex items-center gap-1 text-[var(--color-dim)] hover:text-[var(--color-text)]"
          title="展开看最近 N 次审计 / expand to see last N audit runs"
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
            上次审计 / Last audit
          </span>

          {q.isLoading && !last && (
            <span className="italic text-[var(--color-dim)]">loading…</span>
          )}

          {!q.isLoading && !last && (
            <span className="text-[var(--color-amber,#e5a200)]">
              auditor 还没跑过 — 36 个 strategies 全部停留在 ⚠ unverified。
              点 "Run now" 立即跑一次 (会调 LLM 做 extractor + 机械校验，
              耗时 ~30s)。
            </span>
          )}

          {last && (
            <>
              <span className="font-mono" style={{ color: statusColor }}>
                {statusLabel}
              </span>
              <span className="font-mono text-[var(--color-text)]">
                {localTime(last.completed_at ?? last.started_at)}
              </span>
              <span className="text-[var(--color-dim)]">
                ({ago(last.completed_at ?? last.started_at)})
              </span>
              <span className="text-[var(--color-border)]">·</span>

              <span className="font-mono">
                <span className="text-[var(--color-dim)]">audited </span>
                <span className="text-[var(--color-text)]">
                  {(last.metadata.audited_n as number | undefined) ?? '—'}
                </span>
              </span>
              <span className="font-mono">
                <span className="text-[var(--color-dim)]">→ promoted </span>
                <span style={{
                  color: ((last.metadata.promoted_n as number) ?? 0) > 0
                    ? 'var(--color-green)' : 'var(--color-dim)',
                }}>
                  {(last.metadata.promoted_n as number | undefined) ?? '—'}
                </span>
              </span>
              <span className="font-mono">
                <span className="text-[var(--color-dim)]">still unverified </span>
                <span style={{
                  color: ((last.metadata.still_unverified as number) ?? 0) > 0
                    ? 'var(--color-amber,#e5a200)' : 'var(--color-dim)',
                }}>
                  {(last.metadata.still_unverified as number | undefined) ?? '—'}
                </span>
              </span>
              {((last.metadata.errors_n as number | undefined) ?? 0) > 0 && (
                <span className="font-mono">
                  <span className="text-[var(--color-dim)]">errors </span>
                  <span style={{ color: 'var(--color-red,#e07070)' }}>
                    {last.metadata.errors_n as number}
                  </span>
                </span>
              )}
            </>
          )}
        </div>

        <button
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
          data-testid="last-audit-run-now"
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] text-[var(--color-text)] disabled:opacity-50 disabled:cursor-not-allowed"
          title="同步触发一次审计（synchronous, ~30s — LLM as extractor + 机械校验）"
        >
          <RefreshCw
            size={11}
            className={runNow.isPending ? 'animate-spin' : ''}
          />
          <span>{runNow.isPending ? '运行中… / running…' : 'Run now'}</span>
        </button>
      </div>

      {/* Last-run explanation + sample, when present */}
      {last?.metadata.explanation && !expanded && (
        <div className="px-2.5 pb-2 text-[10px] text-[var(--color-dim)] leading-[1.5] -mt-1">
          {String(last.metadata.explanation)}
        </div>
      )}

      {runNow.isError && (
        <div className="px-2.5 pb-2 text-[10px] text-[var(--color-red,#e07070)] font-mono">
          run-now failed: {String((runNow.error as Error)?.message ?? runNow.error)}
        </div>
      )}

      {expanded && (
        <div className="px-2.5 pb-2 border-t border-[var(--color-border)] mt-1 pt-2">
          <div className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)] mb-1.5">
            Recent runs ({runs.length})
          </div>
          {runs.length === 0 && (
            <div className="text-[10px] italic text-[var(--color-dim)]">
              No runs recorded yet.
            </div>
          )}
          {runs.length > 0 && (
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
                        <td className="py-1 pr-2 text-[var(--color-dim)]">
                          {r.run_type}
                        </td>
                        <td
                          className="py-1 pr-2"
                          style={{ color: statusCol }}
                        >
                          {r.status}
                        </td>
                        <td className="py-1 pr-2 text-right text-[var(--color-text)]">
                          {(m.audited_n as number | undefined) ?? '—'}
                        </td>
                        <td className="py-1 pr-2 text-right">
                          <span
                            style={{
                              color: ((m.promoted_n as number) ?? 0) > 0
                                ? 'var(--color-green)'
                                : 'var(--color-dim)',
                            }}
                          >
                            {(m.promoted_n as number | undefined) ?? '—'}
                          </span>
                        </td>
                        <td className="py-1 pr-2 text-right">
                          <span
                            style={{
                              color: ((m.still_unverified as number) ?? 0) > 0
                                ? 'var(--color-amber,#e5a200)'
                                : 'var(--color-dim)',
                            }}
                          >
                            {(m.still_unverified as number | undefined) ?? '—'}
                          </span>
                        </td>
                        <td className="py-1 pr-2 text-right">
                          <span
                            style={{
                              color: errs > 0
                                ? 'var(--color-red,#e07070)'
                                : 'var(--color-dim)',
                            }}
                          >
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
          )}

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
