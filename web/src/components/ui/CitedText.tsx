import { parseCitations, type Citation } from '@/lib/citations'

interface Props {
  text: string
  /** Invoked when the user clicks a citation chip. Typically wired
   *  to open chat with the cited symbol as context. */
  onCiteClick?: (cite: Citation) => void
  className?: string
}

/**
 * Renders agent output that may contain [[SYMBOL]] / [[sector:Name]]
 * / [[pos:TICKER]] tags as clickable chips mixed with normal text.
 * If no citations, it's just a span — zero broken UX when the model
 * forgets to tag.
 */
export function CitedText({ text, onCiteClick, className }: Props) {
  const segments = parseCitations(text)
  return (
    <span className={className}>
      {segments.map((s, i) => {
        if (s.type === 'text') {
          return <span key={i}>{s.text}</span>
        }
        const c = s.cite
        const color =
          c.kind === 'pos' ? 'var(--color-amber, #e5a200)' :
          c.kind === 'sector' ? 'var(--color-accent)' :
          'var(--color-green)'
        return (
          <button
            key={i}
            data-testid={`cite-${c.kind}-${c.id}`}
            onClick={() => onCiteClick?.(c)}
            title={`${c.kind === 'pos' ? 'position: ' : c.kind === 'sector' ? 'sector: ' : 'symbol: '}${c.id}`}
            className="inline-flex items-center gap-0.5 px-1 py-0 rounded text-[10px] font-mono border transition"
            style={{
              color,
              borderColor: color,
              background: 'transparent',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = color + '20')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            {c.label}
          </button>
        )
      })}
    </span>
  )
}
