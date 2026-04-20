import { useState } from 'react'
import { useSymbolInsight } from '@/lib/api'
import { Sparkles } from 'lucide-react'

interface Props {
  projectId: string
  symbol: string
  /** Element the hover listener attaches to. Usually a table row. */
  children: React.ReactNode
  /** Keep the hover area lighter — if false, no opacity / cursor change */
  subtle?: boolean
}

/**
 * Wraps a target in a hover-listener that fetches a one-sentence
 * agent read and shows it as a floating tooltip. Zero click.
 *
 * The fetch only starts on the first hover (enabled flag gates it),
 * so pages with 50+ watchlist rows don't pre-fetch 50 insights. Once
 * hovered, the insight caches server-side for 5 min; all subsequent
 * hovers on that symbol are free.
 *
 * Design note: we position the tooltip below the row because rows
 * are narrow-and-wide and below has more available space. Edge
 * cases (near viewport bottom) are handled via CSS max-height +
 * overflow; we don't flip.
 */
export function InsightHover({ projectId, symbol, children, subtle }: Props) {
  const [hovering, setHovering] = useState(false)
  const [armed, setArmed] = useState(false)   // only fetch after first hover
  const q = useSymbolInsight(projectId, symbol, armed)

  function onEnter() {
    setHovering(true)
    if (!armed) setArmed(true)
  }

  return (
    <div
      className={subtle ? '' : 'cursor-help'}
      onMouseEnter={onEnter}
      onMouseLeave={() => setHovering(false)}
      data-testid={`insight-target-${symbol}`}
    >
      {children}
      {hovering && (
        <div
          data-testid={`insight-popover-${symbol}`}
          className="absolute z-50 mt-1 left-0 min-w-[260px] max-w-[380px] px-3 py-2 rounded-md bg-[#0e1219] border border-[var(--color-accent)]/50 shadow-lg shadow-black/40 text-[11px] leading-[1.55] text-[var(--color-text)]"
          // Absolute positioning relies on the wrapper row being
          // position:relative in its parent layout. Most row layouts
          // already are. Watchlist/portfolio explicitly set this below.
        >
          <div className="flex items-center gap-1 mb-1 text-[9px] uppercase tracking-wider text-[var(--color-accent)]">
            <Sparkles size={10} />
            <span>agent read · {symbol}</span>
          </div>
          {q.isLoading && <div className="italic text-[var(--color-dim)]">thinking…</div>}
          {q.isError && (
            <div className="text-[var(--color-red)] text-[10px]">
              {(q.error as Error).message.slice(0, 120)}
            </div>
          )}
          {q.data && <div>{q.data.text}</div>}
        </div>
      )}
    </div>
  )
}
