import { useState } from 'react'
import { useChart } from '@/lib/api'
import { Plot } from '@/components/ui/Plot'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'

export function ChartWidget() {
  const [symbol, setSymbol] = useState('AAPL')
  const [period, setPeriod] = useState('3mo')
  const [committed, setCommitted] = useState<string | null>('AAPL')
  const c = useChart(committed, period, '1d')

  function submit() {
    const s = symbol.trim().toUpperCase()
    if (s) setCommitted(s)
  }

  const data: Array<Record<string, unknown>> = []
  if (c.data?.bars?.length) {
    const bars = c.data.bars
    const xs = bars.map(b => b.date)
    data.push({
      x: xs,
      open: bars.map(b => b.open), high: bars.map(b => b.high),
      low: bars.map(b => b.low), close: bars.map(b => b.close),
      type: 'candlestick', name: committed ?? '',
      increasing: { line: { color: '#6fd07a' } },
      decreasing: { line: { color: '#e57373' } },
    })
    const ind = (c.data.indicators || {}) as Record<string, unknown>
    if (Array.isArray(ind.sma20)) {
      data.push({ x: xs, y: ind.sma20, type: 'scatter', mode: 'lines', name: 'SMA20',
        line: { color: '#f3c969', width: 1.3 } })
    }
    if (Array.isArray(ind.ema20)) {
      data.push({ x: xs, y: ind.ema20, type: 'scatter', mode: 'lines', name: 'EMA20',
        line: { color: '#4dd0e1', width: 1.3 } })
    }
  }

  return (
    <Card className="h-full flex flex-col">
      <CardHeader title="Chart" subtitle={committed ? `${committed} · ${period}` : ''} />
      <CardBody className="flex-1 flex flex-col gap-2">
        <div className="flex gap-2">
          <Input value={symbol} onChange={e => setSymbol(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()} placeholder="AAPL"
            className="flex-1 uppercase" />
          <select
            value={period}
            onChange={e => setPeriod(e.target.value)}
            className="bg-[#0e1219] border border-[var(--color-border)] rounded px-2 text-xs"
          >
            {['1mo','3mo','6mo','1y','2y','5y'].map(p => <option key={p}>{p}</option>)}
          </select>
          <Button onClick={submit}>Load</Button>
        </div>
        <div className="flex-1 relative min-h-0">
          {c.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
          {data.length > 0 && (
            <Plot
              data={data}
              layout={{
                margin: { l: 40, r: 20, t: 10, b: 30 },
                paper_bgcolor: 'transparent',
                plot_bgcolor: '#0e1219',
                font: { color: '#d8dde6', size: 10, family: 'ui-monospace' },
                xaxis: { gridcolor: '#1a1f2c', rangeslider: { visible: false } },
                yaxis: { gridcolor: '#1a1f2c' },
                showlegend: true,
                legend: { orientation: 'h', y: -0.2 },
              }}
              config={{ displayModeBar: false, responsive: true }}
            />
          )}
        </div>
      </CardBody>
    </Card>
  )
}
