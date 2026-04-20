import { cn } from '@/lib/utils'

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  ref?: React.Ref<HTMLInputElement>
}

// React 19: ref is a regular prop, no forwardRef needed.
export function Input({ ref, className, ...rest }: InputProps) {
  return (
    <input
      ref={ref}
      className={cn(
        'bg-[#0e1219] border border-[var(--color-border)] rounded px-2.5 py-1.5 text-xs',
        'focus:outline-none focus:border-[var(--color-accent)] transition',
        'placeholder:text-[var(--color-dim)]',
        className,
      )}
      {...rest}
    />
  )
}
