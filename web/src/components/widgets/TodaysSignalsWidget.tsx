/**
 * TodaysSignalsWidget — Phase L "Today's 3 things you need to know".
 *
 * Replaces the dashboard-as-passive-display paradigm with a curated
 * push inbox.  Only shows when there's actually something to surface;
 * otherwise renders an explicit "all quiet" state.
 *
 * Each signal:
 *   - one-line headline with timestamp
 *   - color (green = positive confluence, red = warning, amber = mixed)
 *   - drill-in to evidence chain (contributing events + sources)
 *   - dismiss button (hides for 24h)
 */
import { useState } from 'react'
import {
  useTodaySignals, dismissSignal, triggerAllScans,
  type SignalConfluence,
} from '@/lib/api'
import { useQueryClient } from '@tanstack/react-query'


function relTime(iso: string): string {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return iso
  const secs = (Date.now() - dt.getTime()) / 1000
  if (secs < 60) return `${Math.floor(secs)}s 前`
  if (secs < 3600) return `${Math.floor(secs / 60)}m 前`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h 前`
  if (secs < 86400 * 14) return `${Math.floor(secs / 86400)}d 前`
  return `${Math.floor(secs / 86400 / 7)}w 前`
}


interface ScanReport {
  perScanner: Array<{ name: string; emitted: number; error?: string | null }>
  totalEmitted:    number
  newConfluences: number
  ts:              number
}


export function TodaysSignalsWidget() {
  const q = useTodaySignals(5)
  const qc = useQueryClient()
  const [scanning, setScanning] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [report, setReport] = useState<ScanReport | null>(null)

  const signals = q.data?.signals ?? []

  const onScan = async () => {
    setScanning(true)
    setReport(null)
    // Phase M1b: invalidate runs IMMEDIATELY so the `running` row
    // shows up in NeoMindLive ops view while the scan is still
    // in flight (rather than waiting ~30s for the scan to finish).
    // Then poll a few times during the scan to flip to `completed`.
    qc.invalidateQueries({ queryKey: ['regime', 'runs'] })
    const polls = [
      setTimeout(() => qc.invalidateQueries({ queryKey: ['regime', 'runs'] }), 2_000),
      setTimeout(() => qc.invalidateQueries({ queryKey: ['regime', 'runs'] }), 5_000),
      setTimeout(() => qc.invalidateQueries({ queryKey: ['regime', 'runs'] }), 10_000),
    ]
    try {
      const result = await triggerAllScans()
      // Build inline report so the user can see what the scan actually
      // did — most clicks return n_emitted=0 because dedup is killing
      // events whose URLs were already seen, and confluence won't fire
      // unless ≥2 scanners hit the same ticker in 72h.  Without this
      // banner the user has no idea whether the click did anything.
      const scanners = (result.scanners ?? {}) as Record<string, any>
      const perScanner = Object.entries(scanners).map(([k, v]) => {
        const name = k.replace(/_scan$/, '')
        if (v && typeof v === 'object' && 'error' in v && v.error) {
          return { name, emitted: 0, error: String(v.error) }
        }
        const emitted = (v && typeof v === 'object' && 'n_emitted' in v)
          ? Number(v.n_emitted) || 0 : 0
        return { name, emitted }
      })
      const totalEmitted = perScanner.reduce((s, r) => s + r.emitted, 0)
      setReport({
        perScanner,
        totalEmitted,
        newConfluences: Number(result.new_confluences) || 0,
        ts: Date.now(),
      })
      await qc.invalidateQueries({ queryKey: ['signals_today'] })
      await qc.invalidateQueries({ queryKey: ['signals_recent'] })
      await qc.invalidateQueries({ queryKey: ['regime', 'runs'] })
    } finally {
      polls.forEach(clearTimeout)
      setScanning(false)
    }
  }

  const onDismiss = async (cid: string) => {
    await dismissSignal(cid)
    await qc.invalidateQueries({ queryKey: ['signals_today'] })
  }

  return (
    <div
      data-testid="todays-signals"
      className="mb-3 rounded border border-[var(--color-border)] bg-[var(--color-bg)]/40 p-2.5"
    >
      <div className="flex items-center gap-2 mb-2 text-[10px] text-[var(--color-dim)]">
        <span className="font-semibold text-[var(--color-text)]">
          📬 Today's Signals — only when something matters
        </span>
        {signals.length > 0 && (
          <span className="font-mono">{signals.length} active</span>
        )}
        <button
          onClick={onScan}
          disabled={scanning}
          className="ml-auto text-[9.5px] px-2 py-0.5 rounded border border-[var(--color-border)] hover:border-[var(--color-accent)]/60"
        >
          {scanning ? '扫描中…' : '↻ 立即扫描'}
        </button>
      </div>

      {report && (
        <div className="mb-2 rounded border border-[var(--color-border)] bg-[var(--color-panel)]/40 p-1.5 text-[9.5px] leading-[1.5] flex items-start gap-2">
          <span className="font-semibold text-[var(--color-accent)] flex-shrink-0">扫描结果</span>
          <div className="flex-1">
            <div className="font-mono">
              {report.perScanner.map((s, i) => (
                <span key={s.name}>
                  {i > 0 && <span className="text-[var(--color-dim)]"> · </span>}
                  <span className={s.error
                    ? 'text-[var(--color-danger)]'
                    : (s.emitted > 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-dim)]')}>
                    {s.name}={s.error ? 'err' : s.emitted}
                  </span>
                </span>
              ))}
              <span className="text-[var(--color-dim)]"> · </span>
              <span className={report.newConfluences > 0
                ? 'text-[var(--color-success)] font-semibold'
                : 'text-[var(--color-dim)]'}>
                new_confluences={report.newConfluences}
              </span>
            </div>
            {report.totalEmitted === 0 && (
              <div className="mt-0.5 text-[var(--color-dim)] italic">
                所有 scanner 都跑了，但 0 条新 event — 大概率是 dedup 把已经见过的 URL/ticker 全过滤了。
              </div>
            )}
            {report.totalEmitted > 0 && report.newConfluences === 0 && (
              <div className="mt-0.5 text-[var(--color-dim)] italic">
                有 {report.totalEmitted} 条新 event，但没新 confluence — confluence 要 ≥2 个不同 scanner 在 72h 内击中同一 ticker。
                单 scanner 的新事件可以在 NeoMindLive 的 scanners 视图里看到。
              </div>
            )}
            {report.newConfluences > 0 && (
              <div className="mt-0.5 text-[var(--color-success)]">
                ✓ {report.newConfluences} 个新 confluence 已 promote 到上面 active 列表。
              </div>
            )}
          </div>
          <button
            onClick={() => setReport(null)}
            className="text-[var(--color-dim)] hover:text-[var(--color-text)] text-[10px] flex-shrink-0"
            title="dismiss"
          >×</button>
        </div>
      )}

      {q.isLoading && (
        <div className="text-[10px] text-[var(--color-dim)]">loading…</div>
      )}

      {!q.isLoading && signals.length === 0 && (
        <div className="text-[10px] italic text-[var(--color-dim)] py-2 leading-[1.5]">
          ✓ All quiet — no confluences in the last 72h. NeoMind is still
          scanning every hour; when ≥2 independent sources agree on a
          ticker or theme, it'll appear here.
          <br />
          <span className="text-[8.5px]">
            (空状态 = 系统正常，没东西需要打扰你。这就是设计目标。)
          </span>
        </div>
      )}

      <div className="space-y-1.5">
        {signals.map((s) => (
          <SignalCard
            key={s.confluence_id}
            sig={s}
            isExpanded={expanded === s.confluence_id}
            onToggle={() => setExpanded(expanded === s.confluence_id ? null : s.confluence_id)}
            onDismiss={() => onDismiss(s.confluence_id)}
          />
        ))}
      </div>
    </div>
  )
}


function SignalCard({
  sig, isExpanded, onToggle, onDismiss,
}: {
  sig: SignalConfluence
  isExpanded: boolean
  onToggle: () => void
  onDismiss: () => void
}) {
  const colorBg =
    sig.color === 'green' ? 'border-[var(--color-green)]/60 bg-[var(--color-green)]/[0.05]' :
    sig.color === 'red'   ? 'border-[var(--color-red,#e07070)]/60 bg-[var(--color-red,#e07070)]/[0.05]' :
                            'border-[var(--color-amber,#e5a200)]/40 bg-[var(--color-amber,#e5a200)]/[0.04]'
  const dot =
    sig.color === 'green' ? '🟢' :
    sig.color === 'red'   ? '🔴' :
                            '🟡'
  return (
    <div
      data-testid={`signal-${sig.confluence_id}`}
      className={`rounded border ${colorBg}`}
    >
      <div className="flex items-center gap-2 px-2.5 py-1.5">
        <span className="text-[12px]">{dot}</span>
        <button
          onClick={onToggle}
          className="flex-1 text-left text-[10px] flex items-center gap-2"
        >
          <span className="text-[var(--color-text)] font-medium">
            {sig.ticker ?? sig.theme}
          </span>
          <span className="text-[9.5px] text-[var(--color-dim)] truncate">
            — {sig.n_sources}-source confluence
          </span>
          <span className="text-[8.5px] text-[var(--color-dim)] font-mono ml-auto">
            ({relTime(sig.detected_at)})
          </span>
        </button>
        <button
          onClick={onDismiss}
          className="text-[9.5px] text-[var(--color-dim)] hover:text-[var(--color-text)] px-1.5 py-0.5 rounded"
          title="Dismiss for 24h"
        >
          ✕
        </button>
        <span className="text-[9.5px] text-[var(--color-dim)]">{isExpanded ? '▾' : '▸'}</span>
      </div>

      {isExpanded && (
        <div className="px-2.5 pb-2.5">
          <div className="rounded bg-[var(--color-bg)]/60 border border-[var(--color-border)] p-2">
            <div className="text-[9.5px] uppercase tracking-wider text-[var(--color-dim)] mb-1">
              证据链 / Evidence chain
            </div>
            {sig.events && sig.events.length > 0 ? (
              <div className="space-y-0.5">
                {sig.events.map((e) => (
                  <div key={e.event_id} className="text-[9.5px] flex items-start gap-2 leading-[1.5]">
                    <span className="text-[var(--color-dim)] uppercase tracking-wider w-16 flex-shrink-0">
                      {e.scanner_name}
                    </span>
                    <span className="text-[var(--color-text)] flex-1">{e.title}</span>
                    <span className="text-[8.5px] text-[var(--color-dim)] font-mono whitespace-nowrap">
                      ({relTime(e.source_timestamp ?? e.detected_at)})
                    </span>
                    {e.source_url && (
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[8.5px] text-[var(--color-accent)] hover:underline"
                      >
                        🔗
                      </a>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[9.5px] italic text-[var(--color-dim)]">
                {sig.interpretation ?? 'no events linked'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
