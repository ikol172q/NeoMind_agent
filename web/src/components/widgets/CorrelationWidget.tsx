import { useState } from 'react'
import { useCorrelation } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'

interface Props {
  projectId: string
}

const WINDOWS = [30, 60, 90, 180] as const
type Window = typeof WINDOWS[number]

function cellColor(v: number): string {
  // Diverging palette: red (negative) → grey (near-zero) → green (positive).
  // Clamp at ±1 (correlation is bounded).
  const clamped = Math.max(-1, Math.min(1, v))
  const alpha = Math.abs(clamped).toFixed(2)
  if (clamped > 0.05) return `rgba(111, 208, 122, ${alpha})`
  if (clamped < -0.05) return `rgba(229, 115, 115, ${alpha})`
  return 'rgba(139, 147, 168, 0.12)'
}

/**
 * Correlation heatmap for the project's watchlist + paper positions.
 * Answers "are my 'diversified' bets actually moving together?" — if
 * all cells are dark green, you hold one factor wearing several
 * tickers' clothing.
 */
export function CorrelationWidget({ projectId }: Props) {
  const [days, setDays] = useState<Window>(90)
  const q = useCorrelation(projectId, days, true)
  const data = q.data

  return (
    <Card className="h-full flex flex-col" data-testid="correlation-widget">
      <CardHeader
        title="Correlation"
        subtitle={
          data
            ? `${data.symbols.length} US symbols · ${data.window_days}d returns`
            : 'watchlist + paper positions'
        }
        right={
          <div className="flex gap-1 items-center">
            {WINDOWS.map(w => (
              <button
                key={w}
                data-testid={`corr-window-${w}`}
                onClick={() => setDays(w)}
                className={cn(
                  'px-1.5 py-0.5 text-[9px] uppercase rounded transition',
                  days === w
                    ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                    : 'text-[var(--color-dim)] hover:text-[var(--color-text)]'
                )}
              >
                {w}d
              </button>
            ))}
            <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
              <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
            </Button>
          </div>
        }
      />
      <CardBody className="flex-1 overflow-auto p-2">
        {q.isLoading && <div className="text-[var(--color-dim)] text-xs">computing…</div>}
        {q.isError && (
          <div className="text-[var(--color-red)] text-[11px]">
            {(q.error as Error).message.slice(0, 200)}
          </div>
        )}
        {data && data.note && (
          <div className="text-[10px] text-[var(--color-dim)] italic mb-2">{data.note}</div>
        )}
        {data && data.matrix.length > 0 && (
          <table
            className="text-[10px] font-mono border-collapse"
            data-testid="correlation-table"
          >
            <thead>
              <tr>
                <th className="p-1" />
                {data.symbols.map(s => (
                  <th key={s} className="p-1 text-[var(--color-dim)] font-normal">{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.symbols.map((row, i) => (
                <tr key={row}>
                  <td className="p-1 text-[var(--color-dim)]">{row}</td>
                  {data.symbols.map((col, j) => {
                    const v = data.matrix[i][j]
                    return (
                      <td
                        key={col}
                        data-testid={`corr-cell-${row}-${col}`}
                        className="px-1.5 py-1 text-center text-[var(--color-text)]"
                        style={{ background: cellColor(v) }}
                        title={`corr(${row}, ${col}) = ${v.toFixed(3)}`}
                      >
                        {v.toFixed(2)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardBody>
    </Card>
  )
}
