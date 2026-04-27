/**
 * Data Lake — Phase B6-Step2 visible browser over the provenance stack.
 *
 * Three sub-views:
 *   • Cache Stats  — /api/compute/cache/stats summary
 *   • Crawl Runs   — /api/raw/crawl-runs (B1-B3 raw store)
 *   • Compute Runs — /api/compute/runs (B4 dep_hash cache)
 *
 * Read-only.  No actions, no triggers.  This tab answers questions
 * the operator asked the design doc:
 *   "did the cache work today?"
 *   "what crawls happened this week?"
 *   "show me the raw bytes that fed today's L3 calls."
 *
 * Each row drills into JSON detail in a side panel; the breadcrumb
 * already in DigestView/Strategies (B6-Step1) cross-links to here.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchJSON } from '@/lib/api'
import { Database, Layers, Activity, ChevronRight } from 'lucide-react'

interface Props {
  projectId: string
}

type Pane = 'stats' | 'crawl' | 'compute'

export function DataLakeTab({ projectId }: Props) {
  const [pane, setPane] = useState<Pane>('stats')

  return (
    <div className="h-full flex flex-col bg-[var(--color-bg)]">
      {/* Sub-nav */}
      <div className="flex items-center gap-0 px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-panel)] shrink-0">
        <SubTab active={pane === 'stats'}   onClick={() => setPane('stats')}   icon={<Activity size={12} />}>
          Cache Stats
        </SubTab>
        <SubTab active={pane === 'crawl'}   onClick={() => setPane('crawl')}   icon={<Database size={12} />}>
          Crawl Runs
        </SubTab>
        <SubTab active={pane === 'compute'} onClick={() => setPane('compute')} icon={<Layers size={12} />}>
          Compute Runs
        </SubTab>
        <span className="ml-auto text-[10px] text-[var(--color-dim)]">
          project: <span className="font-mono text-[var(--color-text)]">{projectId}</span>
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {pane === 'stats'   && <CacheStatsPane projectId={projectId} />}
        {pane === 'crawl'   && <CrawlRunsPane projectId={projectId} />}
        {pane === 'compute' && <ComputeRunsPane projectId={projectId} />}
      </div>
    </div>
  )
}

function SubTab({ active, onClick, icon, children }: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={
        'flex items-center gap-1.5 px-3 py-1 text-[11px] border-b-2 -mb-1.5 ' +
        (active
          ? 'text-[var(--color-text)] border-[var(--color-accent)]'
          : 'text-[var(--color-dim)] border-transparent hover:text-[var(--color-text)]')
      }
    >
      {icon}
      {children}
    </button>
  )
}

// ── Cache Stats ────────────────────────────────────────────────────

interface CacheStats {
  project_id: string
  n_hits: number
  n_misses: number
  hit_ratio: number
  bytes_avoided: number
  n_success_runs: number
  n_steps: number
  top_steps: { step: string; n: number }[]
}

function CacheStatsPane({ projectId }: { projectId: string }) {
  const q = useQuery({
    queryKey: ['compute_cache_stats', projectId],
    queryFn: () =>
      fetchJSON<CacheStats>(
        `/api/compute/cache/stats?project_id=${encodeURIComponent(projectId)}`,
      ),
    refetchInterval: 5_000,
    refetchOnWindowFocus: false,
  })

  if (q.isLoading) return <Spinner label="reading dep_hash cache stats…" />
  if (q.isError) return <ErrorBox err={q.error} />
  const s = q.data
  if (!s) return null

  return (
    <div className="p-4 max-w-[900px] mx-auto">
      <div className="grid grid-cols-4 gap-2 mb-4">
        <Stat label="Hits"          value={s.n_hits} />
        <Stat label="Misses"        value={s.n_misses} />
        <Stat label="Hit ratio"     value={`${Math.round(s.hit_ratio * 100)}%`} />
        <Stat label="Bytes avoided" value={fmtBytes(s.bytes_avoided)} highlight />
      </div>

      <div className="grid grid-cols-2 gap-2 mb-4">
        <Stat label="Success runs"     value={s.n_success_runs} />
        <Stat label="Distinct steps"   value={s.n_steps} />
      </div>

      {s.top_steps.length > 0 && (
        <div className="rounded border border-[var(--color-border)] bg-[var(--color-panel)] p-3">
          <div className="text-[11px] text-[var(--color-dim)] mb-2 uppercase tracking-wide">
            Top steps by run count
          </div>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-[10.5px] text-[var(--color-dim)]">
                <th className="font-normal py-1 w-1/2">Step</th>
                <th className="font-normal py-1">Cached runs</th>
              </tr>
            </thead>
            <tbody>
              {s.top_steps.map((row: { step: string; n: number }) => (
                <tr key={row.step} className="border-t border-[var(--color-border)]">
                  <td className="py-1 font-mono">{row.step}</td>
                  <td className="py-1 font-mono">{row.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 text-[10.5px] text-[var(--color-dim)] leading-relaxed">
        Stats are lifetime — they accumulate across uvicorn restarts and
        ship in <span className="font-mono">_dep_index.sqlite</span>{' '}
        under the project compute root.  Auto-refreshes every 5s.
      </div>
    </div>
  )
}

function Stat({ label, value, highlight }: { label: string; value: number | string; highlight?: boolean }) {
  return (
    <div
      className={
        'rounded border border-[var(--color-border)] p-3 ' +
        (highlight ? 'bg-[var(--color-accent-bg,var(--color-panel))]' : 'bg-[var(--color-panel)]')
      }
    >
      <div className="text-[10px] text-[var(--color-dim)] uppercase tracking-wide">{label}</div>
      <div className="text-[18px] font-semibold text-[var(--color-text)] mt-0.5">{value}</div>
    </div>
  )
}

// ── Crawl Runs ────────────────────────────────────────────────────

interface CrawlRunRow {
  crawl_run_id: string
  source: string
  started_at: string
  completed_at: string | null
  status: string
  blob_count: number
  new_blob_count: number
  schema_version: number
}

interface CrawlRunsResponse {
  project_id: string
  count: number
  runs: CrawlRunRow[]
}

function CrawlRunsPane({ projectId }: { projectId: string }) {
  const q = useQuery({
    queryKey: ['raw_crawl_runs', projectId],
    queryFn: () =>
      fetchJSON<CrawlRunsResponse>(
        `/api/raw/crawl-runs?project_id=${encodeURIComponent(projectId)}&limit=50`,
      ),
    refetchInterval: 10_000,
    refetchOnWindowFocus: false,
  })
  const [openId, setOpenId] = useState<string | null>(null)

  if (q.isLoading) return <Spinner label="loading raw crawl runs…" />
  if (q.isError) return <ErrorBox err={q.error} />
  const runs = q.data?.runs ?? []

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <div className="text-[11px] text-[var(--color-dim)] mb-2">
        {q.data?.count ?? 0} crawl runs · auto-refreshes every 10s
      </div>
      <div className="rounded border border-[var(--color-border)] bg-[var(--color-panel)]">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left text-[10px] text-[var(--color-dim)]">
              <th className="font-normal py-1.5 px-2">When</th>
              <th className="font-normal py-1.5 px-2">Source</th>
              <th className="font-normal py-1.5 px-2">Run ID</th>
              <th className="font-normal py-1.5 px-2 text-right">Blobs</th>
              <th className="font-normal py-1.5 px-2 text-right">New</th>
              <th className="font-normal py-1.5 px-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r: CrawlRunRow) => (
              <RunRow
                key={r.crawl_run_id}
                row={r}
                expanded={openId === r.crawl_run_id}
                onToggle={() =>
                  setOpenId((cur: string | null) =>
                    cur === r.crawl_run_id ? null : r.crawl_run_id,
                  )
                }
                projectId={projectId}
              />
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-[var(--color-dim)]">
                  no crawl runs yet — try{' '}
                  <code className="text-[var(--color-accent)]">
                    POST /api/raw/_dev/crawl_news_synthetic?project_id={projectId}
                  </code>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RunRow({
  row,
  expanded,
  onToggle,
  projectId,
}: {
  row: CrawlRunRow
  expanded: boolean
  onToggle: () => void
  projectId: string
}) {
  return (
    <>
      <tr
        className="border-t border-[var(--color-border)] cursor-pointer hover:bg-[var(--color-bg)]"
        onClick={onToggle}
      >
        <td className="py-1.5 px-2 font-mono text-[10.5px]">{fmtIso(row.started_at)}</td>
        <td className="py-1.5 px-2">{row.source}</td>
        <td className="py-1.5 px-2 font-mono text-[10.5px]">{row.crawl_run_id.slice(0, 8)}</td>
        <td className="py-1.5 px-2 text-right font-mono">{row.blob_count}</td>
        <td className="py-1.5 px-2 text-right font-mono">{row.new_blob_count}</td>
        <td className="py-1.5 px-2">
          <StatusBadge status={row.status} />
        </td>
      </tr>
      {expanded && <CrawlRunDetail row={row} projectId={projectId} />}
    </>
  )
}

interface CrawlRunDetail {
  manifest: {
    superseded_versions?: { url: string; old_hash: string; new_hash: string }[]
  } | null
  report: {
    totals?: Record<string, number>
    anomaly_alerts?: string[]
    sample?: { sha256: string; url?: string; first_120_chars?: string }[]
  } | null
}

function CrawlRunDetail({ row, projectId }: { row: CrawlRunRow; projectId: string }) {
  const date = row.started_at.slice(0, 10)
  const q = useQuery({
    queryKey: ['raw_crawl_run_detail', projectId, row.crawl_run_id, date],
    queryFn: () =>
      fetchJSON<CrawlRunDetail>(
        `/api/raw/crawl-runs/${encodeURIComponent(row.crawl_run_id)}` +
          `?project_id=${encodeURIComponent(projectId)}&date=${encodeURIComponent(date)}`,
      ),
    staleTime: Infinity,
  })
  return (
    <tr>
      <td colSpan={6} className="bg-[var(--color-bg)] p-3 border-t border-[var(--color-border)]">
        {q.isLoading && <span className="text-[10.5px] text-[var(--color-dim)]">loading detail…</span>}
        {q.isError && <ErrorBox err={q.error} />}
        {q.data && (
          <div className="text-[10.5px] grid grid-cols-2 gap-3">
            <div>
              <div className="text-[var(--color-dim)] uppercase tracking-wide mb-1">totals</div>
              <pre className="font-mono text-[10px] whitespace-pre-wrap">
                {JSON.stringify(q.data.report?.totals ?? {}, null, 2)}
              </pre>
            </div>
            <div>
              <div className="text-[var(--color-dim)] uppercase tracking-wide mb-1">anomaly alerts</div>
              {(q.data.report?.anomaly_alerts ?? []).length === 0 ? (
                <span className="text-[var(--color-dim)] italic">none</span>
              ) : (
                <ul className="list-disc ml-4 text-[var(--color-amber,#ff9800)]">
                  {(q.data.report!.anomaly_alerts ?? []).map((a: string, i: number) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              )}
            </div>
            <div className="col-span-2">
              <div className="text-[var(--color-dim)] uppercase tracking-wide mb-1">
                supersede chain ({(q.data.manifest?.superseded_versions ?? []).length})
              </div>
              {(q.data.manifest?.superseded_versions ?? []).length === 0 ? (
                <span className="text-[var(--color-dim)] italic">no silent edits this run</span>
              ) : (
                <table className="w-full text-[10px] font-mono">
                  <thead>
                    <tr className="text-left text-[var(--color-dim)]">
                      <th className="font-normal pr-3">URL</th>
                      <th className="font-normal pr-3">old → new</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(q.data.manifest!.superseded_versions ?? []).slice(0, 10).map(
                      (s: { url: string; old_hash: string; new_hash: string }, i: number) => (
                        <tr key={i}>
                          <td className="pr-3 truncate max-w-[400px]">{s.url}</td>
                          <td className="pr-3">
                            {s.old_hash.slice(0, 8)} → {s.new_hash.slice(0, 8)}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </td>
    </tr>
  )
}

// ── Compute Runs ──────────────────────────────────────────────────

interface ComputeRunRow {
  compute_run_id: string
  dep_hash: string
  step: string
  crawl_run_id: string | null
  started_at: string
  completed_at: string | null
  status: string
  size_bytes: number | null
}

interface ComputeRunsResponse {
  project_id: string
  count: number
  runs: ComputeRunRow[]
}

function ComputeRunsPane({ projectId }: { projectId: string }) {
  const [stepFilter, setStepFilter] = useState<string>('')
  const q = useQuery({
    queryKey: ['compute_runs', projectId, stepFilter],
    queryFn: () =>
      fetchJSON<ComputeRunsResponse>(
        `/api/compute/runs?project_id=${encodeURIComponent(projectId)}` +
          `&limit=80${stepFilter ? `&step=${encodeURIComponent(stepFilter)}` : ''}`,
      ),
    refetchInterval: 10_000,
    refetchOnWindowFocus: false,
  })
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <div className="flex items-center gap-2 mb-2 text-[11px]">
        <span className="text-[var(--color-dim)]">filter step:</span>
        {['', 'observations', 'themes', 'calls'].map((s) => (
          <button
            key={s || 'all'}
            onClick={() => setStepFilter(s)}
            className={
              'px-2 py-0.5 rounded border ' +
              (stepFilter === s
                ? 'bg-[var(--color-accent)] text-[var(--color-bg)] border-[var(--color-accent)]'
                : 'border-[var(--color-border)] text-[var(--color-dim)] hover:text-[var(--color-text)]')
            }
          >
            {s || 'all'}
          </button>
        ))}
        <span className="ml-auto text-[var(--color-dim)]">
          {q.data?.count ?? 0} runs · refresh every 10s
        </span>
      </div>
      {q.isLoading && <Spinner label="loading compute runs…" />}
      {q.isError && <ErrorBox err={q.error} />}
      {q.data && (
        <div className="rounded border border-[var(--color-border)] bg-[var(--color-panel)]">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-[10px] text-[var(--color-dim)]">
                <th className="font-normal py-1.5 px-2">When</th>
                <th className="font-normal py-1.5 px-2">Step</th>
                <th className="font-normal py-1.5 px-2">Run ID</th>
                <th className="font-normal py-1.5 px-2">Dep Hash</th>
                <th className="font-normal py-1.5 px-2 text-right">Size</th>
                <th className="font-normal py-1.5 px-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {(q.data.runs ?? []).map((r: ComputeRunRow) => (
                <ComputeRunRowEl
                  key={r.compute_run_id}
                  row={r}
                  expanded={openId === r.compute_run_id}
                  onToggle={() =>
                    setOpenId((cur: string | null) =>
                      cur === r.compute_run_id ? null : r.compute_run_id,
                    )
                  }
                  projectId={projectId}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ComputeRunRowEl({
  row,
  expanded,
  onToggle,
  projectId,
}: {
  row: ComputeRunRow
  expanded: boolean
  onToggle: () => void
  projectId: string
}) {
  return (
    <>
      <tr
        className="border-t border-[var(--color-border)] cursor-pointer hover:bg-[var(--color-bg)]"
        onClick={onToggle}
      >
        <td className="py-1.5 px-2 font-mono text-[10.5px]">{fmtIso(row.started_at)}</td>
        <td className="py-1.5 px-2 font-mono">{row.step}</td>
        <td className="py-1.5 px-2 font-mono text-[10.5px]">{row.compute_run_id.slice(0, 8)}</td>
        <td className="py-1.5 px-2 font-mono text-[10.5px]">{row.dep_hash.slice(0, 12)}</td>
        <td className="py-1.5 px-2 text-right font-mono">{row.size_bytes ? fmtBytes(row.size_bytes) : '—'}</td>
        <td className="py-1.5 px-2">
          <StatusBadge status={row.status} />
        </td>
      </tr>
      {expanded && <ComputeRunDetail row={row} projectId={projectId} />}
    </>
  )
}

interface ComputeRunDetail {
  run: {
    compute_run_id: string
    dep_hash: string
    step: string
    started_at: string
    completed_at: string | null
    status: string
    snapshot_path: string | null
    size_bytes: number | null
    params: Record<string, unknown>
  }
}

function ComputeRunDetail({ row, projectId }: { row: ComputeRunRow; projectId: string }) {
  const q = useQuery({
    queryKey: ['compute_run_detail', projectId, row.compute_run_id],
    queryFn: () =>
      fetchJSON<ComputeRunDetail>(
        `/api/compute/runs/${encodeURIComponent(row.compute_run_id)}` +
          `?project_id=${encodeURIComponent(projectId)}`,
      ),
    staleTime: Infinity,
  })
  return (
    <tr>
      <td colSpan={6} className="bg-[var(--color-bg)] p-3 border-t border-[var(--color-border)]">
        {q.isLoading && <span className="text-[10.5px] text-[var(--color-dim)]">loading detail…</span>}
        {q.isError && <ErrorBox err={q.error} />}
        {q.data && (
          <div className="grid grid-cols-2 gap-3 text-[10.5px]">
            <div>
              <div className="text-[var(--color-dim)] uppercase tracking-wide mb-1">params</div>
              <pre className="font-mono text-[10px] whitespace-pre-wrap break-all">
                {JSON.stringify(q.data.run.params, null, 2)}
              </pre>
            </div>
            <div>
              <div className="text-[var(--color-dim)] uppercase tracking-wide mb-1">artifact</div>
              <div className="font-mono text-[10px] break-all">
                <div>
                  <span className="text-[var(--color-dim)]">dep_hash:</span> {q.data.run.dep_hash}
                </div>
                {q.data.run.snapshot_path && (
                  <div>
                    <span className="text-[var(--color-dim)]">snapshot:</span> {q.data.run.snapshot_path}
                  </div>
                )}
                <div>
                  <span className="text-[var(--color-dim)]">size:</span>{' '}
                  {q.data.run.size_bytes ? fmtBytes(q.data.run.size_bytes) : '—'}
                </div>
                <div>
                  <span className="text-[var(--color-dim)]">started:</span> {q.data.run.started_at}
                </div>
                {q.data.run.completed_at && (
                  <div>
                    <span className="text-[var(--color-dim)]">completed:</span> {q.data.run.completed_at}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </td>
    </tr>
  )
}

// ── Helpers ────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const ok = status === 'success' || status === 'completed'
  const color = ok
    ? 'var(--color-green, #4caf50)'
    : status === 'failed'
      ? 'var(--color-red, #f44336)'
      : 'var(--color-amber, #ff9800)'
  return (
    <span
      className="px-1.5 py-[1px] rounded text-[9.5px] uppercase tracking-wide"
      style={{ background: color, color: 'var(--color-bg, #000)' }}
    >
      {status}
    </span>
  )
}

function Spinner({ label }: { label: string }) {
  return (
    <div className="p-6 text-center text-[11px] text-[var(--color-dim)] italic">{label}</div>
  )
}

function ErrorBox({ err }: { err: unknown }) {
  return (
    <div className="p-3 text-[11px] text-[var(--color-red,#f44336)]">
      {(err as Error)?.message?.slice(0, 250) || 'unknown error'}
    </div>
  )
}

function fmtIso(s: string): string {
  if (!s) return ''
  try {
    return new Date(s).toLocaleString('en-GB', { hour12: false })
  } catch {
    return s.slice(0, 19)
  }
}

function fmtBytes(n: number): string {
  if (n === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(n) / Math.log(k)))
  return `${(n / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1)} ${sizes[i]}`
}

// suppress unused
void ChevronRight
