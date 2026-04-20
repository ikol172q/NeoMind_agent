import { useMemo, useState } from 'react'
import { useRS, type RSEntry } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { InsightHover } from '@/components/ui/InsightHover'
import { cn, fmtNum } from '@/lib/utils'
import { RefreshCw, MessageSquare } from 'lucide-react'

type Window = '3m' | '6m' | 'ytd'

interface Props {
  projectId: string
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

/**
 * Relative-strength grid. Sorts a US S&P-100 universe by a chosen
 * return window (3M / 6M / YTD). Each row shows the three windows
 * side-by-side with a proportional color bar so you can spot-check
 * consistency across windows.
 *
 * Row click / chat button → prefills a chat prompt asking the
 * agent about the stock's recent move.
 */
export function RSGridWidget({ projectId, onJumpToChat }: Props) {
  const rs = useRS('US', 100)
  const [win, setWin] = useState<Window>('3m')
  const [limit, setLimit] = useState<number>(20)

  const sortKey = (
    win === '3m' ? 'return_3m' :
    win === '6m' ? 'return_6m' : 'return_ytd'
  ) as keyof RSEntry

  const sorted = useMemo(() => {
    const all = rs.data?.entries ?? []
    return [...all]
      .filter(e => (e[sortKey] as number | null) != null)
      .sort((a, b) => (Number(b[sortKey]) ?? -Infinity) - (Number(a[sortKey]) ?? -Infinity))
      .slice(0, limit)
  }, [rs.data, sortKey, limit])

  // For the color bar, scale against the top value of the active
  // window in the current view (so bars visually differentiate).
  const topAbs = useMemo(() => {
    if (sorted.length === 0) return 1
    return Math.max(
      Math.abs(Number(sorted[0][sortKey])),
      Math.abs(Number(sorted[sorted.length - 1][sortKey])),
    ) || 1
  }, [sorted, sortKey])

  function ask(row: RSEntry) {
    if (!onJumpToChat) return
    const pretty = (n: number | null) => n == null ? 'n/a' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`
    const prompt =
      `${row.symbol} has returned 3m:${pretty(row.return_3m)}, ` +
      `6m:${pretty(row.return_6m)}, YTD:${pretty(row.return_ytd)}. ` +
      `What's driving this? 3 concrete catalysts, then one risk. <150 words.`
    onJumpToChat(prompt, { symbol: row.symbol })
  }

  return (
    <Card className="h-full flex flex-col" data-testid="rs-grid-widget">
      <CardHeader
        title="Relative Strength"
        subtitle={`US · top ${limit} by ${win.toUpperCase()} return`}
        right={
          <Button size="sm" variant="ghost" onClick={() => rs.refetch()} disabled={rs.isFetching}>
            <RefreshCw size={11} className={rs.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-2 overflow-hidden p-2">
        {/* Toolbar */}
        <div className="flex gap-1 items-center">
          {(['3m', '6m', 'ytd'] as Window[]).map(w => (
            <button
              key={w}
              data-testid={`rs-win-${w}`}
              onClick={() => setWin(w)}
              className={cn(
                'px-2 py-0.5 text-[10px] uppercase tracking-wider rounded transition',
                win === w
                  ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                  : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/40',
              )}
            >
              {w}
            </button>
          ))}
          <div className="flex-1" />
          <select
            value={limit}
            onChange={e => setLimit(parseInt(e.target.value, 10))}
            className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-[10px] py-0.5"
            data-testid="rs-limit"
          >
            {[10, 20, 50, 100].map(n => <option key={n} value={n}>top {n}</option>)}
          </select>
        </div>

        {/* Header row */}
        <div className="grid grid-cols-[3rem_4.5rem_1fr_3.5rem_3.5rem_3.5rem_1.5rem] gap-2 items-center px-1 text-[9px] uppercase tracking-wider text-[var(--color-dim)] border-b border-[var(--color-border)] pb-1">
          <span>#</span>
          <span>Symbol</span>
          <span>Bar</span>
          <span className="text-right">3M</span>
          <span className="text-right">6M</span>
          <span className="text-right">YTD</span>
          <span />
        </div>

        <div className="flex-1 overflow-y-auto" data-testid="rs-rows">
          {rs.isLoading && <div className="text-[var(--color-dim)] text-xs p-2">loading…</div>}
          {rs.isError && (
            <div className="text-[var(--color-red)] text-[11px] p-2">
              {(rs.error as Error).message.slice(0, 200)}
            </div>
          )}
          {sorted.map((r, i) => (
            <InsightHover key={r.symbol} projectId={projectId} symbol={r.symbol}>
              <div className="relative">
                <RSRow
                  row={r}
                  rank={i + 1}
                  sortKey={sortKey as 'return_3m' | 'return_6m' | 'return_ytd'}
                  topAbs={topAbs}
                  onAsk={onJumpToChat ? () => ask(r) : undefined}
                />
              </div>
            </InsightHover>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}

interface RowProps {
  row: RSEntry
  rank: number
  sortKey: 'return_3m' | 'return_6m' | 'return_ytd'
  topAbs: number
  onAsk?: () => void
}

function RSRow({ row, rank, sortKey, topAbs, onAsk }: RowProps) {
  const ret = row[sortKey]
  const pct = typeof ret === 'number' ? ret : 0
  const frac = Math.max(-1, Math.min(1, pct / topAbs))
  const up = pct >= 0
  const barColor = up ? 'bg-[var(--color-green)]/50' : 'bg-[var(--color-red)]/50'
  const textFor = (n: number | null) => {
    if (n == null) return <span className="text-[var(--color-dim)]">—</span>
    const sign = n >= 0 ? '+' : ''
    const cls = n >= 0 ? 'text-[var(--color-green)]' : 'text-[var(--color-red)]'
    return <span className={cls}>{sign}{fmtNum(n)}%</span>
  }

  return (
    <div
      data-testid={`rs-row-${row.symbol}`}
      className="grid grid-cols-[3rem_4.5rem_1fr_3.5rem_3.5rem_3.5rem_1.5rem] gap-2 items-center px-1 py-1 text-[11px] font-mono border-b border-[var(--color-border)]/30 hover:bg-[var(--color-border)]/20"
    >
      <span className="text-[var(--color-dim)]">{rank}</span>
      <span className="text-[var(--color-text)]">{row.symbol}</span>
      <div className="relative h-3 bg-[var(--color-border)]/30 rounded-sm overflow-hidden">
        {/* Bar is anchored center-line so negative extends left, positive right */}
        <div
          className={cn('absolute top-0 bottom-0', barColor)}
          style={{
            left: up ? '50%' : `${50 - Math.abs(frac) * 50}%`,
            width: `${Math.abs(frac) * 50}%`,
          }}
        />
        <div className="absolute top-0 bottom-0 left-1/2 w-px bg-[var(--color-border)]" />
      </div>
      <span className="text-right">{textFor(row.return_3m)}</span>
      <span className="text-right">{textFor(row.return_6m)}</span>
      <span className="text-right">{textFor(row.return_ytd)}</span>
      <button
        data-testid={`rs-ask-${row.symbol}`}
        onClick={onAsk}
        disabled={!onAsk}
        className="text-[var(--color-dim)] hover:text-[var(--color-accent)] disabled:opacity-0 transition"
        title="ask fin about this mover"
      >
        <MessageSquare size={11} />
      </button>
    </div>
  )
}
