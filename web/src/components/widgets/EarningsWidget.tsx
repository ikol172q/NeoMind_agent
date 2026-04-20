import { useMemo } from 'react'
import { useEarnings, type EarningsEntry } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn, fmtNum } from '@/lib/utils'
import { RefreshCw, MessageSquare } from 'lucide-react'

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string) => void
}

/**
 * Earnings calendar + IV tracker for the project's US watchlist.
 *
 * Each row shows:
 *   date · days-until · avg past |move| · 30d realised vol · ATM IV
 *
 * The "move vs IV" spread is the signal: when ATM IV is well above
 * the historical absolute move, the market's pricing a bigger event
 * than the stock usually delivers — worth a look. The widget doesn't
 * make that call for you; ask-agent button hands the row to Fin.
 */
export function EarningsWidget({ projectId, onJumpToChat }: Props) {
  const q = useEarnings(projectId)
  const entries = q.data?.entries ?? []

  const { upcoming, past } = useMemo(() => {
    const up: EarningsEntry[] = []
    const pa: EarningsEntry[] = []
    for (const e of entries) {
      if (e.days_until != null && e.days_until < 0) pa.push(e)
      else up.push(e)
    }
    return { upcoming: up, past: pa }
  }, [entries])

  function ask(e: EarningsEntry) {
    if (!onJumpToChat) return
    const bits: string[] = []
    if (e.days_until != null) bits.push(`earnings in ${e.days_until}d (${e.next_earnings_date})`)
    if (e.atm_iv_pct != null) bits.push(`ATM IV ${e.atm_iv_pct.toFixed(1)}%`)
    if (e.avg_abs_move_pct != null) bits.push(`historical avg |move| ${e.avg_abs_move_pct.toFixed(1)}%`)
    if (e.rv_30d_pct != null) bits.push(`30d RV ${e.rv_30d_pct.toFixed(1)}%`)
    const ctx = bits.join(', ') || 'no context'
    const prompt =
      `${e.symbol}: ${ctx}. Is the option market pricing in too much, too little, or about right? ` +
      `Give 3 concrete points, then one risk. <150 words.`
    onJumpToChat(prompt)
  }

  return (
    <Card className="h-full flex flex-col" data-testid="earnings-widget">
      <CardHeader
        title="Earnings & IV"
        subtitle={`${upcoming.length} upcoming · ${past.length} recent · watchlist US`}
        right={
          <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-1 overflow-hidden p-2">
        {/* Header row */}
        <div className="grid grid-cols-[4.5rem_6rem_2.5rem_3.5rem_3.5rem_3.5rem_1.5rem] gap-2 items-center px-1 text-[9px] uppercase tracking-wider text-[var(--color-dim)] border-b border-[var(--color-border)] pb-1">
          <span>Symbol</span>
          <span>Date</span>
          <span className="text-right">Days</span>
          <span className="text-right" title="average absolute post-earnings move, last 4Q">|Move|</span>
          <span className="text-right" title="30-day realised volatility, annualised">RV</span>
          <span className="text-right" title="ATM call implied volatility, nearest expiry">IV</span>
          <span />
        </div>

        <div className="flex-1 overflow-y-auto" data-testid="earnings-rows">
          {q.isLoading && (
            <div className="text-[var(--color-dim)] text-xs p-2">loading…</div>
          )}
          {q.isError && (
            <div className="text-[var(--color-red)] text-[11px] p-2">
              {(q.error as Error).message.slice(0, 200)}
            </div>
          )}
          {!q.isLoading && entries.length === 0 && (
            <div className="text-[var(--color-dim)] italic text-[11px] text-center p-4">
              Empty — add US symbols to your watchlist to see their earnings here.
            </div>
          )}
          {upcoming.map(e => (
            <EarningsRow key={e.symbol} entry={e} dim={false} onAsk={onJumpToChat ? () => ask(e) : undefined} />
          ))}
          {past.length > 0 && (
            <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)] px-1 pt-2">
              reported — last quarter
            </div>
          )}
          {past.map(e => (
            <EarningsRow key={e.symbol + '-past'} entry={e} dim onAsk={onJumpToChat ? () => ask(e) : undefined} />
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

interface RowProps {
  entry: EarningsEntry
  dim: boolean
  onAsk?: () => void
}

function EarningsRow({ entry, dim, onAsk }: RowProps) {
  const e = entry
  const days = e.days_until

  // Color the IV cell when it's notably above average-abs-move.
  // Heuristic: IV expresses annualised stdev in %; a 1-day event
  // move of ≈ IV/sqrt(252) ≈ IV/15.87. So if IV/16 > avg_abs_move
  // by ≥ 50%, the market is pricing more than the historical norm.
  let ivTone = 'text-[var(--color-text)]'
  if (e.atm_iv_pct != null && e.avg_abs_move_pct != null && e.avg_abs_move_pct > 0) {
    const impliedDaily = e.atm_iv_pct / 16
    const ratio = impliedDaily / e.avg_abs_move_pct
    if (ratio >= 1.5) ivTone = 'text-[var(--color-red)]'
    else if (ratio <= 0.7) ivTone = 'text-[var(--color-green)]'
  }

  return (
    <div
      data-testid={`earnings-row-${e.symbol}`}
      className={cn(
        'grid grid-cols-[4.5rem_6rem_2.5rem_3.5rem_3.5rem_3.5rem_1.5rem] gap-2 items-center px-1 py-1 text-[11px] font-mono border-b border-[var(--color-border)]/30 hover:bg-[var(--color-border)]/20',
        dim && 'opacity-60',
      )}
    >
      <span className="text-[var(--color-text)] truncate">{e.symbol}</span>
      <span className="text-[var(--color-dim)]">{e.next_earnings_date ?? '—'}</span>
      <span className="text-right">
        {days == null ? '—' : <span className={days < 0 ? 'text-[var(--color-dim)]' : days <= 7 ? 'text-[var(--color-accent)]' : ''}>{days >= 0 ? `+${days}` : days}</span>}
      </span>
      <span className="text-right">
        {e.avg_abs_move_pct == null
          ? <span className="text-[var(--color-dim)]">—</span>
          : `${fmtNum(e.avg_abs_move_pct)}%`}
      </span>
      <span className="text-right">
        {e.rv_30d_pct == null
          ? <span className="text-[var(--color-dim)]">—</span>
          : `${fmtNum(e.rv_30d_pct)}%`}
      </span>
      <span className={cn('text-right', ivTone)}>
        {e.atm_iv_pct == null
          ? <span className="text-[var(--color-dim)]">—</span>
          : `${fmtNum(e.atm_iv_pct)}%`}
      </span>
      <button
        data-testid={`earnings-ask-${e.symbol}`}
        onClick={onAsk}
        disabled={!onAsk}
        className="text-[var(--color-dim)] hover:text-[var(--color-accent)] disabled:opacity-0 transition"
        title="ask fin about this earnings"
      >
        <MessageSquare size={11} />
      </button>
    </div>
  )
}
