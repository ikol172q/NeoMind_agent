import { useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Plot } from '@/components/ui/Plot'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import { X, Plus, MessageSquare } from 'lucide-react'

interface Props {
  onJumpToChat?: (prompt: string) => void
}

// Line colours cycle as the user adds symbols. Muted enough to
// coexist with the dashboard's dim panel, bright enough to pick
// out individual lines in overlay mode.
const LINE_COLORS = [
  '#4dd0e1',  // cyan   — 1st
  '#f3c969',  // amber  — 2nd
  '#b388ff',  // violet — 3rd
  '#6fd07a',  // green  — 4th
]

const PERIODS = ['1mo', '3mo', '6mo', '1y', '2y'] as const
type Period = typeof PERIODS[number]

interface ChartResp {
  symbol: string
  bars: Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>
}

/**
 * Multi-symbol comparison chart. Each symbol's close is rebased to
 * 100 at the first bar so curves are directly comparable — a stock
 * at $500 doesn't visually overwhelm one at $30. Agent-facing:
 * ask button passes the full list + period to Chat.
 */
export function MultiChartWidget({ onJumpToChat }: Props) {
  const [symbols, setSymbols] = useState<string[]>(['AAPL', 'MSFT'])
  const [draft, setDraft] = useState('')
  const [period, setPeriod] = useState<Period>('3mo')

  // One query per symbol; TanStack dedupes by key so rebinding is cheap
  const queries = useQueries({
    queries: symbols.map(sym => ({
      queryKey: ['chart', sym, period, '1d'],
      queryFn: () => fetch(`/api/chart/${encodeURIComponent(sym)}?period=${period}&interval=1d&indicators=`)
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json() as Promise<ChartResp>
        }),
      staleTime: 60_000,
      enabled: !!sym,
    })),
  })

  const allLoaded = queries.every(q => !q.isLoading)
  const anyError = queries.some(q => q.isError)

  const traces = useMemo(() => {
    return symbols.map((sym, i) => {
      const q = queries[i]
      const bars = q.data?.bars ?? []
      if (bars.length === 0) return null
      const base = bars[0].close
      if (!base) return null
      const xs = bars.map(b => b.date)
      const ys = bars.map(b => (b.close / base - 1) * 100)  // % change from start
      return {
        x: xs,
        y: ys,
        type: 'scatter',
        mode: 'lines',
        name: sym,
        line: { color: LINE_COLORS[i % LINE_COLORS.length], width: 1.5 },
        hovertemplate: '<b>%{fullData.name}</b><br>%{x}<br>%{y:.2f}%<extra></extra>',
      }
    }).filter(Boolean) as Array<Record<string, unknown>>
  }, [queries, symbols])

  function add() {
    const s = draft.trim().toUpperCase()
    if (!s) return
    if (symbols.includes(s)) { setDraft(''); return }
    if (symbols.length >= 4) return  // keep the overlay readable
    setSymbols([...symbols, s])
    setDraft('')
  }

  function remove(sym: string) {
    setSymbols(symbols.filter(s => s !== sym))
  }

  function ask() {
    if (!onJumpToChat || symbols.length === 0) return
    const prompt =
      `Compare ${symbols.join(', ')} over the last ${period}. ` +
      `Which outperformed? 3 concrete drivers of the divergence, ` +
      `then one line on what could flip the leader. <150 words.`
    onJumpToChat(prompt)
  }

  return (
    <Card className="h-full flex flex-col" data-testid="multi-chart-widget">
      <CardHeader
        title="Compare"
        subtitle={symbols.length ? `${symbols.length} symbols · ${period}, rebased` : 'add symbols to compare'}
        right={
          onJumpToChat && symbols.length >= 2 ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={ask}
              data-testid="multi-chart-ask"
              title="ask fin to compare these"
            >
              <MessageSquare size={11} />
            </Button>
          ) : undefined
        }
      />
      <CardBody className="flex-1 flex flex-col gap-2 p-2 min-h-0">
        {/* Chip + input row */}
        <div className="flex gap-1 items-center flex-wrap">
          {symbols.map((s, i) => (
            <span
              key={s}
              data-testid={`multi-chart-chip-${s}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono"
              style={{
                borderLeft: `3px solid ${LINE_COLORS[i % LINE_COLORS.length]}`,
                background: 'var(--color-border)',
              }}
            >
              {s}
              <button
                onClick={() => remove(s)}
                data-testid={`multi-chart-remove-${s}`}
                className="text-[var(--color-dim)] hover:text-[var(--color-red)] transition"
                title="remove"
              >
                <X size={10} />
              </button>
            </span>
          ))}
          {symbols.length < 4 && (
            <div className="flex gap-1 items-center">
              <Input
                data-testid="multi-chart-new-symbol"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && add()}
                placeholder="add…"
                className="w-20 uppercase"
              />
              <Button size="sm" onClick={add} data-testid="multi-chart-add" disabled={!draft.trim()}>
                <Plus size={10} />
              </Button>
            </div>
          )}
          <div className="flex-1" />
          <div className="flex gap-1">
            {PERIODS.map(p => (
              <button
                key={p}
                data-testid={`multi-chart-period-${p}`}
                onClick={() => setPeriod(p)}
                className={cn(
                  'px-1.5 py-0.5 text-[10px] uppercase tracking-wider rounded transition',
                  period === p
                    ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                    : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/40',
                )}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Plot */}
        <div className="flex-1 min-h-0 relative" data-testid="multi-chart-plot">
          {!allLoaded && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
          {anyError && (
            <div className="text-[var(--color-red)] text-[11px]">
              one or more symbols failed — check tickers
            </div>
          )}
          {symbols.length === 0 && (
            <div className="text-[var(--color-dim)] italic text-[11px] text-center p-4">
              Empty — add 2+ symbols above to compare their performance.
            </div>
          )}
          {traces.length > 0 && (
            <Plot
              data={traces}
              layout={{
                margin: { l: 40, r: 10, t: 10, b: 30 },
                paper_bgcolor: 'transparent',
                plot_bgcolor: '#0e1219',
                font: { color: '#d8dde6', size: 10, family: 'ui-monospace' },
                xaxis: { gridcolor: '#1a1f2c' },
                yaxis: { gridcolor: '#1a1f2c', ticksuffix: '%', zerolinecolor: '#2a3040' },
                showlegend: true,
                legend: { orientation: 'h', y: -0.2 },
                hovermode: 'x unified',
              }}
              config={{ displayModeBar: false, responsive: true }}
            />
          )}
        </div>
      </CardBody>
    </Card>
  )
}
