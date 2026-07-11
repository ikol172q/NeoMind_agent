/**
 * FreshnessChip — one consistent "is this data current?" badge for the corner
 * of any refreshable module.
 *
 * Before this, the dashboard had 6+ ad-hoc "N ago" implementations and many
 * widgets showed no recency at all — so you couldn't tell at a glance whether
 * what you're looking at is the latest. This chip is the single primitive.
 *
 * Two modes:
 *  • JOB mode  <FreshnessChip job="research_loop_scan" /> — reads the real
 *    last_success_at / is_stale of a scheduler job from /api/scheduler/
 *    scanner_health. Use for data produced by a scheduled job (research loop,
 *    news pull, signal scans, snapshots). This is where genuinely stale/stuck
 *    data shows up.
 *  • TIME mode <FreshnessChip updatedAt={q.dataUpdatedAt} isFetching={q.isFetching}
 *    isError={q.isError} staleAfterMin={2} /> — for live-polled data (account,
 *    risk, quotes). Shows when the client last got data; turns red if the query
 *    errors/stalls (catches e.g. a dead IBKR gateway while numbers look normal).
 *
 * Status: 🟢 fresh · 🟡 stale (past threshold) · 🔴 stuck (never ran / error) ·
 * ⏳ refreshing · ⚪ unknown. Compact: a colored dot + relative age. Hover for
 * the full timestamp + why.
 */
import { useScannerHealth } from '@/lib/api'
import { fmtRelativeTime } from '@/lib/utils'

type Status = 'fresh' | 'stale' | 'stuck' | 'refreshing' | 'unknown'

export interface FreshnessChipProps {
  /** JOB mode: scheduler job name. Takes precedence over the time-mode props. */
  job?: string
  /** TIME mode: ms-epoch the shown data was last fetched (query.dataUpdatedAt). */
  updatedAt?: number | null
  isFetching?: boolean
  isError?: boolean
  /** TIME-mode staleness threshold in minutes (default 5). */
  staleAfterMin?: number
  /** Optional short prefix, e.g. "研究". */
  label?: string
  className?: string
}

const DOT: Record<Status, string> = {
  fresh: 'text-emerald-400',
  stale: 'text-amber-400',
  stuck: 'text-red-400',
  refreshing: 'text-[var(--color-accent)] animate-pulse',
  unknown: 'text-[var(--color-dim)]',
}

const WORD: Record<Status, string> = {
  fresh: '新鲜', stale: '过期', stuck: '卡住', refreshing: '刷新中', unknown: '未知',
}

/** ISO → "5m ago" via the canonical helper (kept relative, not absolute). */
function ago(iso: string | null | undefined): string {
  const r = fmtRelativeTime(iso ?? undefined)
  return r || '—'
}

function Pill({ status, text, title, label }: {
  status: Status; text: string; title: string; label?: string
}) {
  return (
    <span
      className="inline-flex items-center gap-1 text-[9.5px] font-mono leading-none whitespace-nowrap select-none"
      title={title}
    >
      {label && <span className="text-[var(--color-dim)] uppercase tracking-wide">{label}</span>}
      <span className={DOT[status]}>●</span>
      <span className="text-[var(--color-dim)]">{text}</span>
    </span>
  )
}

/** JOB mode — read scanner_health for one scheduler job. */
function JobChip({ job, label }: { job: string; label?: string }) {
  const q = useScannerHealth()
  if (q.isLoading || !q.data) {
    return <Pill status="unknown" text="…" title={`读取 ${job} 状态中`} label={label} />
  }
  const row = q.data.jobs.find(j => j.name === job)
  if (!row) {
    return <Pill status="unknown" text="无此 job" title={`scanner_health 里没有 ${job}`} label={label} />
  }
  const last = row.last_success_at
  if (!last) {
    return (
      <Pill
        status="stuck"
        text="从未成功"
        title={`${job} 从未成功跑过（cron ${row.cron}）。可能是新加的还没到点，也可能真卡住了。`}
        label={label}
      />
    )
  }
  const status: Status = row.is_stale ? 'stale' : 'fresh'
  return (
    <Pill
      status={status}
      text={ago(last)}
      title={
        `${job} · 上次成功 ${last}\n` +
        `${row.minutes_since_success ?? '?'} 分钟前，期望每 ${row.expected_interval_min} 分钟内一次\n` +
        (row.is_stale ? '⚠️ 已过期（超过 2× 预期间隔）' : '✓ 新鲜')
      }
      label={label}
    />
  )
}

/** TIME mode — derive from a React Query result's timestamps. */
function TimeChip({ updatedAt, isFetching, isError, staleAfterMin = 5, label }: FreshnessChipProps) {
  if (isFetching && !updatedAt) {
    return <Pill status="refreshing" text="加载中" title="首次加载中" label={label} />
  }
  if (isError) {
    return <Pill status="stuck" text="拉取失败" title="最近一次拉取报错——显示的可能是旧数据或空" label={label} />
  }
  if (!updatedAt) {
    return <Pill status="unknown" text="—" title="没有更新时间" label={label} />
  }
  const ageMin = (Date.now() - updatedAt) / 60000
  const iso = new Date(updatedAt).toISOString()
  const status: Status = isFetching ? 'refreshing' : ageMin > staleAfterMin ? 'stale' : 'fresh'
  return (
    <Pill
      status={status}
      text={isFetching ? '刷新中' : ago(iso)}
      title={
        `数据拉取于 ${new Date(updatedAt).toLocaleString()}\n` +
        `${Math.round(ageMin)} 分钟前` +
        (status === 'stale' ? `\n⚠️ 超过 ${staleAfterMin} 分钟没更新——可能自动刷新停了` : '') +
        (status === 'fresh' ? '\n✓ 新鲜（自动刷新正常）' : '')
      }
      label={label}
    />
  )
}

export function FreshnessChip(props: FreshnessChipProps) {
  const { className } = props
  const inner = props.job
    ? <JobChip job={props.job} label={props.label} />
    : <TimeChip {...props} />
  return className ? <span className={className}>{inner}</span> : inner
}

/** Tiny status-word legend used in tooltips / help. Exported for reuse. */
export const FRESHNESS_LEGEND = WORD
