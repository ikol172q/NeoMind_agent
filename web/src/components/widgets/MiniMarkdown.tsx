/**
 * MiniMarkdown — tiny self-contained markdown renderer for read-only
 * long-form docs (thesis body_md, trading plans). Handles the subset
 * that actually shows up in those files: #/##/### headings, **bold**,
 * `code`, - / * / · bullets, 1. numbered lists, > blockquotes, and
 * blank-line paragraph breaks.
 *
 * Deliberately NOT react-markdown (not a dep in this repo) and NOT
 * dangerouslySetInnerHTML — everything renders as React nodes, so
 * arbitrary markdown text can't inject HTML. Shared by
 * ResearchInboxWidget + TradingPlansWidget so both read identically.
 */
import { cn } from '@/lib/utils'

// Inline pass: **bold** + `code`. Everything else stays literal text.
function renderInline(text: string, keyPrefix: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((seg, i) => {
    const key = `${keyPrefix}-${i}`
    if (seg.startsWith('**') && seg.endsWith('**')) {
      return (
        <strong key={key} className="font-semibold text-[var(--color-text)]">
          {seg.slice(2, -2)}
        </strong>
      )
    }
    if (seg.startsWith('`') && seg.endsWith('`')) {
      return (
        <code key={key} className="font-mono text-[var(--color-accent)] text-[0.95em]">
          {seg.slice(1, -1)}
        </code>
      )
    }
    return <span key={key}>{seg}</span>
  })
}

export function MiniMarkdown({ text, className }: { text?: string; className?: string }) {
  if (!text || !text.trim()) {
    return <div className="italic text-[var(--color-dim)]">(空)</div>
  }
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  return (
    <div className={cn('leading-relaxed', className)}>
      {lines.map((raw, i) => {
        const t = raw.trim()
        if (!t) return <div key={i} className="h-2" />

        // headings — #, ##, ###+
        const h = /^(#{1,6})\s+(.*)$/.exec(t)
        if (h) {
          const level = h[1].length
          const cls =
            level <= 1
              ? 'text-[12.5px] font-bold text-[var(--color-text)] mt-2.5 mb-1'
              : level === 2
                ? 'text-[11.5px] font-semibold text-[var(--color-text)] mt-2 mb-0.5'
                : 'text-[10.5px] font-semibold text-[var(--color-dim)] uppercase tracking-wide mt-1.5'
          return (
            <div key={i} className={cls}>
              {renderInline(h[2], String(i))}
            </div>
          )
        }

        // blockquote
        if (t.startsWith('>')) {
          return (
            <div
              key={i}
              className="border-l-2 border-[var(--color-border)] pl-2 my-0.5 text-[var(--color-dim)] italic"
            >
              {renderInline(t.replace(/^>\s?/, ''), String(i))}
            </div>
          )
        }

        // bullets — top-level vs. indented sub-bullet
        const b = /^[-*•·]\s+(.*)$/.exec(t)
        if (b) {
          const indented = /^\s+/.test(raw)
          return (
            <div key={i} className={cn('flex gap-1.5', indented ? 'pl-5' : 'pl-1.5')}>
              <span className="text-[var(--color-dim)] flex-shrink-0">
                {indented ? '–' : '·'}
              </span>
              <span className="min-w-0">{renderInline(b[1], String(i))}</span>
            </div>
          )
        }

        // numbered list
        const n = /^(\d+)\.\s+(.*)$/.exec(t)
        if (n) {
          return (
            <div key={i} className="flex gap-1.5 pl-1.5">
              <span className="text-[var(--color-dim)] flex-shrink-0 font-mono">{n[1]}.</span>
              <span className="min-w-0">{renderInline(n[2], String(i))}</span>
            </div>
          )
        }

        // paragraph
        return (
          <div key={i} className="my-0.5">
            {renderInline(t, String(i))}
          </div>
        )
      })}
    </div>
  )
}
