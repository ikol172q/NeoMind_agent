import { cn } from '@/lib/utils'

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'bg-[var(--color-panel)] border border-[var(--color-border)] rounded-md overflow-hidden',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title, subtitle, right,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  right?: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-border)]">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-dim)]">
          {title}
        </div>
        {subtitle && <div className="text-xs text-[var(--color-text)] mt-0.5">{subtitle}</div>}
      </div>
      {right && <div>{right}</div>}
    </div>
  )
}

export function CardBody({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-3', className)} {...rest}>{children}</div>
}

/**
 * Shared visual treatment for the *expanded body* of an inline collapsible
 * section. Indents the content and draws a left accent rail + faint tint so
 * the sub-blocks read as CHILDREN of their section header (not siblings at the
 * same level). Single source of truth — every expandable section uses this so
 * the nesting looks consistent instead of scattered.
 *
 * Only for INLINE sections (expanded content sits in the page flow). Do NOT use
 * for floating dropdowns / popovers / modals — those already overlay content
 * and are visually separated.
 */
export const nestedGroupClass =
  'mt-1 ml-4 space-y-3 rounded-md border-l-[3px] border-[var(--color-accent)]/60 bg-[var(--color-accent)]/5 pl-3 pr-2 py-2'

export function NestedGroup({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn(nestedGroupClass, className)} {...rest}>{children}</div>
}

/**
 * Lighter sibling of {@link nestedGroupClass} for a *table-row / list-item*
 * detail expansion (click a row → see its detail). Same accent-rail language
 * so the whole app reads as one system, but no tray/tint — a per-row filled
 * box would be visually heavy. Append to the row-detail body's own wrapper.
 */
export const nestedRailClass =
  'ml-3 border-l-2 border-[var(--color-accent)]/30 pl-3'
