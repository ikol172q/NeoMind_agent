import { useSentiment } from '@/lib/api'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Plot } from '@/components/ui/Plot'
import { cn } from '@/lib/utils'
import { RefreshCw, MessageSquare } from 'lucide-react'

interface Props {
  onJumpToChat?: (prompt: string, ctx?: { symbol?: string; project?: boolean }) => void
}

function toneColor(label: string): string {
  if (label === 'extreme greed' || label === 'greed') return 'var(--color-green)'
  if (label === 'neutral' || label === 'unknown') return 'var(--color-dim)'
  return 'var(--color-red)'
}

/**
 * Market "temperature" gauge. Composite of three free-data
 * sub-scores (VIX position, SPY 20d momentum, S&P 100 breadth)
 * mapped to a 0–100 fear ↔ greed scale.
 *
 * This is NOT a news-polarity classifier — that needs a local NLP
 * model we're not willing to bundle. It's a market-state signal:
 * the numbers above tell you where the tape is right now.
 */
export function SentimentGaugeWidget({ onJumpToChat }: Props) {
  const q = useSentiment()
  const d = q.data
  const score = d?.composite_score ?? null
  const label = d?.label ?? 'unknown'

  const gaugeData = [
    {
      type: 'indicator',
      mode: 'gauge+number',
      value: score ?? 0,
      number: {
        font: { size: 32, color: toneColor(label) },
        suffix: '',
      },
      gauge: {
        axis: {
          range: [0, 100],
          tickwidth: 1,
          tickcolor: '#2a3040',
          tickvals: [0, 25, 50, 75, 100],
          ticktext: ['', '', '', '', ''],
        },
        bar: { color: toneColor(label), thickness: 0.22 },
        bgcolor: 'transparent',
        borderwidth: 0,
        steps: [
          { range: [0, 25], color: 'rgba(196, 77, 88, 0.25)' },   // extreme fear
          { range: [25, 45], color: 'rgba(196, 77, 88, 0.12)' },  // fear
          { range: [45, 55], color: 'rgba(139, 147, 168, 0.15)' },// neutral
          { range: [55, 75], color: 'rgba(111, 208, 122, 0.12)' },// greed
          { range: [75, 100], color: 'rgba(111, 208, 122, 0.25)' }, // extreme greed
        ],
        threshold: {
          line: { color: toneColor(label), width: 3 },
          thickness: 0.85,
          value: score ?? 0,
        },
      },
    },
  ] as Array<Record<string, unknown>>

  function ask() {
    if (!onJumpToChat || !d) return
    const c = d.components
    const prompt =
      `Market temperature: ${d.composite_score ?? '?'} / 100 (${d.label}). ` +
      `VIX ${c.vix.raw ?? '?'} at ${c.vix.percentile_pct ?? '?'}th pct. ` +
      `SPY 20d ${c.spy_momentum.return_20d_pct ?? '?'}%. ` +
      `Breadth ${c.breadth.up ?? '?'}/${c.breadth.total ?? '?'} up. ` +
      `Is this reading actionable? What would flip it fastest? <150 words.`
    onJumpToChat(prompt, { project: true })
  }

  return (
    <Card className="h-full flex flex-col" data-testid="sentiment-gauge-widget">
      <CardHeader
        title="Market Temp"
        subtitle={d ? `${label} · composite ${score ?? '?'} / 100` : 'loading…'}
        right={
          <div className="flex gap-1">
            {onJumpToChat && d && (
              <Button size="sm" variant="ghost" onClick={ask} data-testid="sentiment-ask" title="ask fin about this reading">
                <MessageSquare size={11} />
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => q.refetch()} disabled={q.isFetching}>
              <RefreshCw size={11} className={q.isFetching ? 'animate-spin' : ''} />
            </Button>
          </div>
        }
      />
      <CardBody className="flex-1 flex flex-col gap-1 p-2 min-h-0" data-testid="sentiment-body">
        {q.isLoading && <div className="text-[var(--color-dim)] text-xs">loading…</div>}
        {q.isError && (
          <div className="text-[var(--color-red)] text-[11px]">
            {(q.error as Error).message.slice(0, 200)}
          </div>
        )}
        {d && (
          <>
            <div className="flex-1 min-h-0" data-testid="sentiment-plot">
              <Plot
                data={gaugeData}
                layout={{
                  margin: { l: 10, r: 10, t: 10, b: 10 },
                  paper_bgcolor: 'transparent',
                  font: { color: '#d8dde6', family: 'ui-monospace' },
                }}
                config={{ displayModeBar: false, responsive: true }}
              />
            </div>
            <div className="grid grid-cols-3 gap-2 px-1 pt-1 text-[10px] border-t border-[var(--color-border)]">
              <SubScore
                label="VIX"
                score={d.components.vix.score}
                detail={d.components.vix.raw != null ? `${d.components.vix.raw}` : '—'}
              />
              <SubScore
                label="Momentum"
                score={d.components.spy_momentum.score}
                detail={
                  d.components.spy_momentum.return_20d_pct != null
                    ? `${d.components.spy_momentum.return_20d_pct >= 0 ? '+' : ''}${d.components.spy_momentum.return_20d_pct}%`
                    : '—'
                }
              />
              <SubScore
                label="Breadth"
                score={d.components.breadth.score}
                detail={
                  d.components.breadth.total
                    ? `${d.components.breadth.up}/${d.components.breadth.total}`
                    : '—'
                }
              />
            </div>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function SubScore({ label, score, detail }: { label: string; score: number | null; detail: string }) {
  const tone =
    score == null ? 'text-[var(--color-dim)]' :
    score >= 60 ? 'text-[var(--color-green)]' :
    score >= 40 ? 'text-[var(--color-text)]' : 'text-[var(--color-red)]'
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-[var(--color-dim)]">{label}</div>
      <div className={cn('font-mono', tone)}>
        {score == null ? '—' : score.toFixed(0)}
        <span className="text-[var(--color-dim)] ml-1">{detail}</span>
      </div>
    </div>
  )
}
