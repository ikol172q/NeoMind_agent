/**
 * ScannerHealthBadge — Phase 3.
 *
 * Small badge in the dashboard header. Shows green check when all
 * scanners are fresh (within 2× expected interval). Shows amber
 * warning + count when ≥1 scanner is stale. Click → tooltip with
 * the offenders.
 *
 * Per plan §5 Pillar 3 + §7 Phase 3 — defensive observability so
 * user notices broken scanners before stale data corrupts decisions.
 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useScannerHealth, fetchJSON } from '@/lib/api'
import { CheckCircle2, AlertTriangle, RefreshCw, Loader2 } from 'lucide-react'

export function ScannerHealthBadge() {
  const q = useScannerHealth()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  // Per-row pending state: which job_name is currently being triggered.
  const [running, setRunning] = useState<string | null>(null)
  // Last-run banner: { job, n_emitted, error } — shows what the click
  // actually did so the user isn't left wondering.
  const [lastResult, setLastResult] = useState<{ job: string; n: number; err?: string } | null>(null)
  const data = q.data
  if (q.isLoading || !data) return null
  const stale = data.jobs.filter(j => j.is_stale)
  const fresh = data.n_jobs - data.n_stale

  async function triggerJob(jobName: string) {
    setRunning(jobName)
    setLastResult(null)
    try {
      const resp = await fetchJSON<{ job: string; result: any }>(
        `/api/scheduler/run/${jobName}`, { method: 'POST' },
      )
      const r = resp.result ?? {}
      // signal_hourly stashes per-scanner n_emitted in nested keys; for
      // others, prefer top-level n_emitted or fall back to scan.n_emitted.
      let n = 0
      if (typeof r.n_emitted === 'number') n = r.n_emitted
      else if (r.scan && typeof r.scan.n_emitted === 'number') n = r.scan.n_emitted
      else {
        // Sum nested scanner *_scan blocks (signal_hourly style)
        for (const k of Object.keys(r)) {
          if (k.endsWith('_scan') && r[k] && typeof r[k] === 'object' && typeof r[k].n_emitted === 'number') {
            n += r[k].n_emitted
          }
        }
      }
      setLastResult({ job: jobName, n })
      // Refresh staleness + downstream events
      qc.invalidateQueries({ queryKey: ['scanner_health'] })
      qc.invalidateQueries({ queryKey: ['signals_recent'] })
      qc.invalidateQueries({ queryKey: ['signals_today'] })
      qc.invalidateQueries({ queryKey: ['regime', 'runs'] })
    } catch (e: any) {
      setLastResult({ job: jobName, n: 0, err: String(e?.message ?? e) })
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(o => !o)}
        title={
          stale.length === 0
            ? `所有 ${data.n_jobs} 个 scanner 都新鲜 (≤ 2× 期望间隔)`
            : `${stale.length}/${data.n_jobs} scanner stale — 点查看`
        }
        className={`text-[10px] flex items-center gap-1 px-2 py-1 rounded border ${
          stale.length === 0
            ? 'border-emerald-500/40 text-emerald-300'
            : 'border-amber-500/40 text-amber-300 bg-amber-500/10'
        }`}
      >
        {stale.length === 0
          ? <><CheckCircle2 size={10} /> {data.n_jobs} scanners</>
          : <><AlertTriangle size={10} /> {stale.length}/{data.n_jobs} stale</>}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-[360px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded shadow-xl z-50 text-[10px]">
          <div className="px-3 py-2 border-b border-[var(--color-border)]">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-[var(--color-text)]">Scanner health</span>
              <span className="ml-auto text-[9px] text-[var(--color-dim)] italic" title="点 ↻ 强制立即跑该 job (POST /api/scheduler/run/<name>)">
                点 ↻ 立即跑该 job
              </span>
            </div>
            <div className="text-[var(--color-dim)] mt-0.5">
              {fresh} fresh · {stale.length} stale (≥ 2× 期望间隔)
            </div>
          </div>
          {lastResult && (
            <div className={`px-3 py-1.5 border-b border-[var(--color-border)] text-[9.5px] ${
              lastResult.err ? 'text-[var(--color-red,#e07070)]' : 'text-[var(--color-text)]'
            }`}>
              {lastResult.err
                ? <>✗ <code>{lastResult.job}</code> 失败: {lastResult.err}</>
                : <>✓ <code>{lastResult.job}</code> 跑完 · emit <b>{lastResult.n}</b> 条新 event</>}
            </div>
          )}
          <div className="max-h-[300px] overflow-y-auto">
            {data.jobs.map(j => {
              const isRunning = running === j.name
              return (
                <div
                  key={j.name}
                  className={`px-3 py-1 border-b border-[var(--color-border)]/50 flex items-center gap-2 ${
                    j.is_stale ? 'bg-amber-500/[0.05]' : ''
                  }`}
                >
                  <span className={j.is_stale ? 'text-amber-300' : 'text-emerald-300'}>
                    {j.is_stale ? '⚠' : '✓'}
                  </span>
                  <span className="font-mono text-[var(--color-text)] flex-1 truncate">
                    {j.name}
                  </span>
                  <span className="text-[var(--color-dim)] font-mono text-[9.5px]">
                    {j.minutes_since_success != null
                      ? `${j.minutes_since_success}m ago`
                      : 'never'}
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); triggerJob(j.name) }}
                    disabled={isRunning || running !== null}
                    title={isRunning ? '运行中…' : `立即跑一次 ${j.name}\nPOST /api/scheduler/run/${j.name}`}
                    className="w-5 h-5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] text-[var(--color-dim)] disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center"
                  >
                    {isRunning
                      ? <Loader2 size={9} className="animate-spin" />
                      : <RefreshCw size={9} />
                    }
                  </button>
                </div>
              )
            })}
          </div>
          <div className="px-3 py-2 text-[var(--color-dim)] italic leading-[1.5]">
            Stale = no successful run in &gt; 2× expected interval。
            点行尾 ↻ 立即跑（绕过 cron）；其它地方的 ↻ 见 Strategies tab "Today's Signals" 顶部 (跑全部) 和顶栏 🧠 rebuild lattice (重算策略推荐).
            Click outside to close.
          </div>
        </div>
      )}

      {/* Click-outside closer */}
      {open && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setOpen(false)}
        />
      )}
    </div>
  )
}
