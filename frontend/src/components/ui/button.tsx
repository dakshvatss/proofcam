import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

// shadcn/ui-style button (hand-written; same API shape: variant + size). Focus ring comes from the global
// :focus-visible rule in index.css so every control shares it.
const VARIANTS = {
  primary: 'bg-accent text-accent-ink font-semibold hover:bg-accent-strong active:bg-accent',
  secondary: 'border border-line-strong bg-raised text-fg hover:border-fg-subtle/60 hover:bg-[#1e2226]',
  ghost: 'text-fg-muted hover:bg-raised hover:text-fg',
  danger: 'bg-bad text-[#2a0904] font-semibold hover:brightness-110',
} as const
const SIZES = {
  sm: 'h-9 gap-1.5 px-3 text-[13px]',
  md: 'h-11 gap-2 px-4 text-[15px]',
  lg: 'h-14 gap-2 px-6 text-base',
  icon: 'h-11 w-11',
} as const

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANTS
  size?: keyof typeof SIZES
}

export function Button({ className, variant = 'primary', size = 'md', type = 'button', ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex select-none items-center justify-center whitespace-nowrap rounded-[var(--radius-control)] font-medium',
        'transition-[background-color,border-color,color,filter,transform] duration-150 ease-out active:scale-[0.98]',
        'disabled:pointer-events-none disabled:opacity-40 [&_svg]:shrink-0',
        VARIANTS[variant], SIZES[size], className,
      )}
      {...props}
    />
  )
}
