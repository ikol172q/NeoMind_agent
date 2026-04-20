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
  title: string
  subtitle?: string
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
