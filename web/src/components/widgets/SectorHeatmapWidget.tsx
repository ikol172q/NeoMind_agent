import { useState } from 'react'
import { useSectors } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Plot } from '@/components/ui/Plot'
import { cn } from '@/lib/utils'
import { RefreshCw } from 'lucide-react'

interface Props {
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

/**
 * Sector heat-map (plotly treemap). Size = market cap (CN) / dollar
 * volume (US). Colour = today's % change on a diverging red→green
 * palette clamped to ±3% so normal days don't all look grey.
 *
 * Click a cell → if the parent wired `onJumpToChat`, prefills a
 * chat prompt asking the agent about that sector's drivers.
 */
export function SectorHeatmapWidget({ onJumpToChat }: Props) {
  const [market, setMarket] = useState<'US' | 'CN'>('US')
  const q = useSectors(market)
  const sectors = q.data?.sectors ?? []

  // ── Treemap trace ──
  const COLOR_CLAMP = 3  // ±3% caps colour scale; bigger moves stay at extreme
  const labels: string[] = []
  const parents: string[] = []
  const values: number[] = []
  const colors: number[] = []
  const text: string[] = []
  const customdata: string[][] = []

  // Synthetic root so plotly renders as a treemap with a single top
  labels.push('All')
  parents.push('')
  values.push(0)
  colors.push(0)
  text.push('')
  customdata.push(['', ''])

  for (const s of sectors) {
    labels.push(s.name)
    parents.push('All')
    values.push(Math.max(s.size || 1, 1))
    const clamped = Math.max(-COLOR_CLAMP, Math.min(COLOR_CLAMP, s.change_pct))
    colors.push(clamped)
    const leader = s.leader ? `<br>Leader: ${s.leader} ${s.leader_pct?.toFixed(2) ?? '?'}%` : ''
    text.push(
      `<b>${s.name}</b><br>${s.symbol}<br>${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%${leader}`,
    )
    customdata.push([s.name, s.symbol])
  }

  const data = [
    {
      type: 'treemap',
      labels,
      parents,
      values,
      text,
      customdata,
      textinfo: 'label+text',
      hoverinfo: 'text',
      textposition: 'middle center',
      branchvalues: 'total',
      marker: {
        colors,
        cmin: -COLOR_CLAMP,
        cmid: 0,
        cmax: COLOR_CLAMP,
        colorscale: [
          [0, '#c44d58'],       // -3%  red
          [0.5, '#1e2633'],     //  0   neutral (blends with panel bg)
          [1, '#6fd07a'],       // +3%  green
        ],
        line: { color: '#0e1219', width: 1 },
      },
      pathbar: { visible: false },
    },
  ] as Array<Record<string, unknown>>

  function onPlotClick(ev: unknown) {
    if (!onJumpToChat) return
    const e = ev as { points?: Array<{ customdata?: [string, string] }> }
    const pt = e.points?.[0]
    if (!pt?.customdata) return
    const [name, symbol] = pt.customdata
    if (!name || name === 'All') return
    const marketLabel = market === 'US' ? 'US SPDR sector' : 'CN 行业板块'
    const prompt = `What's driving the ${marketLabel} "${name}" (${symbol}) today? Give 3 concrete catalysts or dynamics, not fluff. <150 words.`
    onJumpToChat(prompt, { project: true })
  }

  return (
    <Card className="h-full flex flex-col" data-testid="sector-heatmap-widget">
      <CardHeader
        title="Sector Heatmap"
        subtitle={`${market} · ${sectors.length} sectors`}
        right={
          <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
          </Button>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-2 p-2 min-h-0">
        <div className="flex gap-1">
          {(['US', 'CN'] as const).map(m => (
            <button
              key={m}
              data-testid={`sector-market-${m}`}
              onClick={() => setMarket(m)}
              className={cn(
                'px-3 py-1 text-[10px] uppercase tracking-wider rounded transition',
                market === m
                  ? 'bg-[var(--color-border)] text-[var(--color-accent)]'
                  : 'text-[var(--color-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-border)]/40',
              )}
            >
              {m}
            </button>
          ))}
          <div className="flex-1" />
          {onJumpToChat && (
            <span className="text-[10px] text-[var(--color-dim)] self-center italic">
              click a sector to ask fin
            </span>
          )}
        </div>
        <div className="flex-1 min-h-0 relative" data-testid="sector-heatmap-plot">
          {q.isLoading && (
            <div className="text-[var(--color-dim)] text-xs">loading…</div>
          )}
          {q.isError && (
            <div className="text-[var(--color-red)] text-xs">
              {(q.error as Error).message.slice(0, 200)}
            </div>
          )}
          {sectors.length > 0 && (
            <Plot
              data={data}
              layout={{
                margin: { l: 0, r: 0, t: 0, b: 0 },
                paper_bgcolor: 'transparent',
                font: { color: '#d8dde6', size: 11, family: 'ui-monospace' },
              }}
              config={{ displayModeBar: false, responsive: true }}
              onClick={onPlotClick}
            />
          )}
        </div>
      </CardBody>
    </Card>
  )
}
