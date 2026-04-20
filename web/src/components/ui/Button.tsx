import { cn } from '@/lib/utils'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'ghost' | 'outline' | 'danger'
  size?: 'sm' | 'md'
}

export function Button({
  className, variant = 'default', size = 'md', children, ...rest
}: ButtonProps) {
  const base = 'inline-flex items-center gap-1.5 rounded transition font-semibold disabled:opacity-40 disabled:cursor-default select-none'
  const sizeCls = size === 'sm' ? 'px-2 py-1 text-[11px]' : 'px-3 py-1.5 text-xs'
  const variantCls = {
    default: 'bg-[var(--color-accent)] text-[var(--color-bg)] hover:brightness-110',
    ghost:   'text-[var(--color-text)] hover:bg-[var(--color-border)]',
    outline: 'border border-[var(--color-border)] text-[var(--color-text)] hover:bg-[var(--color-border)]',
    danger:  'border border-[var(--color-red)] text-[var(--color-red)] hover:bg-[var(--color-red)]/10',
  }[variant]
  return (
    <button className={cn(base, sizeCls, variantCls, className)} {...rest}>
      {children}
    </button>
  )
}
