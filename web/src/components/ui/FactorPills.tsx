import { useFactors } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Props {
  symbol: string
  /** Enabled gate — caller usually only arms this when the row is
   *  expanded to Tier 2 or higher. Avoids fanning out factor fetches
   *  to every watchlist row on page mount. */
  enabled?: boolean
  /** Show the 5 factor pills. Default true. */
  showAxes?: boolean
  /** Show the composite letter to the left of the pills. */
  showOverall?: boolean
  className?: string
}

const AXIS_ORDER: Array<keyof NonNullable<ReturnType<typeof useFactors>['data']>['axes']> = [
  'momentum', 'value', 'quality', 'growth', 'revisions',
]

const AXIS_LABEL: Record<string, string> = {
  momentum: 'M',
  value: 'V',
  quality: 'Q',
  growth: 'G',
  revisions: 'R',
}

const AXIS_TITLE: Record<string, string> = {
  momentum: 'Momentum — how much has the stock run vs peers (3M RS rank)',
  value: 'Value — how cheap is it (trailing P/E band)',
  quality: 'Quality — ROE + leverage + margin composite',
  growth: 'Growth — revenue + earnings YoY',
  revisions: 'Revisions — forward vs current EPS (analyst direction)',
}

function gradeColor(g: string): { fg: string; bg: string } {
  if (g.startsWith('A')) return { fg: 'var(--color-green)', bg: 'rgba(111, 208, 122, 0.15)' }
  if (g === 'B') return { fg: 'var(--color-accent)', bg: 'rgba(100, 180, 220, 0.15)' }
  if (g === 'C') return { fg: 'var(--color-text)', bg: 'rgba(139, 147, 168, 0.18)' }
  if (g === 'D') return { fg: '#e5a200', bg: 'rgba(229, 162, 0, 0.15)' }
  if (g === 'F') return { fg: 'var(--color-red)', bg: 'rgba(229, 115, 115, 0.18)' }
  return { fg: 'var(--color-dim)', bg: 'transparent' }
}

/**
 * Tier-2 widget primitive: 5 factor pills (M V Q G R) + optional
 * composite letter. This is the Seeking-Alpha-Quant layer — hard-
 * coded tiers, no LLM, pure math.
 *
 * The hover title on each pill shows the raw number + note so the
 * user can drill from A → "ROE 15%, D/E 120%, margin 28%" without
 * expanding the row fully.
 */
export function FactorPills({
  symbol,
  enabled = true,
  showAxes = true,
  showOverall = true,
  className,
}: Props) {
  const q = useFactors(symbol, enabled)
  const data = q.data

  if (q.isLoading) {
    return (
      <span className={cn('text-[9px] text-[var(--color-dim)] italic', className)}>
        grading…
      </span>
    )
  }
  if (q.isError || !data) {
    return (
      <span className={cn('text-[9px] text-[var(--color-dim)]', className)}>—</span>
    )
  }

  const overall = gradeColor(data.overall_grade)

  return (
    <span className={cn('inline-flex items-center gap-1', className)} data-testid={`factor-pills-${symbol}`}>
      {showOverall && (
        <span
          data-testid={`factor-overall-${symbol}`}
          className="font-mono text-[11px] px-1.5 py-0.5 rounded"
          style={{ color: overall.fg, background: overall.bg }}
          title="Overall composite grade"
        >
          {data.overall_grade}
        </span>
      )}
      {showAxes && AXIS_ORDER.map(axis => {
        const a = data.axes[axis]
        const c = gradeColor(a.grade)
        return (
          <span
            key={axis}
            data-testid={`factor-axis-${symbol}-${axis}`}
            className="inline-flex items-center gap-0.5 text-[10px] font-mono px-1 py-0.5 rounded"
            style={{ color: c.fg, background: c.bg }}
            title={`${AXIS_TITLE[axis]}\n${a.note}`}
          >
            <span className="text-[var(--color-dim)] text-[9px]">{AXIS_LABEL[axis]}</span>
            <span>{a.grade}</span>
          </span>
        )
      })}
    </span>
  )
}
