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
import { useScannerHealth } from '@/lib/api'
import { CheckCircle2, AlertTriangle } from 'lucide-react'

export function ScannerHealthBadge() {
  const q = useScannerHealth()
  const [open, setOpen] = useState(false)
  const data = q.data
  if (q.isLoading || !data) return null
  const stale = data.jobs.filter(j => j.is_stale)
  const fresh = data.n_jobs - data.n_stale

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
        <div className="absolute right-0 top-full mt-1 w-[300px] bg-[var(--color-panel)] border border-[var(--color-border)] rounded shadow-xl z-50 text-[10px]">
          <div className="px-3 py-2 border-b border-[var(--color-border)]">
            <div className="font-semibold text-[var(--color-text)]">Scanner health</div>
            <div className="text-[var(--color-dim)] mt-0.5">
              {fresh} fresh · {stale.length} stale (≥ 2× 期望间隔)
            </div>
          </div>
          <div className="max-h-[300px] overflow-y-auto">
            {data.jobs.map(j => (
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
                <span className="text-[var(--color-dim)] font-mono">
                  {j.minutes_since_success != null
                    ? `${j.minutes_since_success}m ago`
                    : 'never'}
                </span>
              </div>
            ))}
          </div>
          <div className="px-3 py-2 text-[var(--color-dim)] italic">
            Stale = no successful run in &gt; 2× expected interval.
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
