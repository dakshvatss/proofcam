import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

// shadcn/ui-style button (hand-written; same API shape: variant + size). Focus ring comes from the global
// :focus-visible rule in index.css so every control shares it.
const VARIANTS = {
  primary: 'bg-accent text-accent-ink font-semibold shadow-[0_1px_2px_rgb(8_102_255/0.25),0_6px_16px_-6px_rgb(8_102_255/0.45)] hover:bg-accent-strong',
  secondary: 'border border-line-strong bg-surface text-fg shadow-[var(--shadow-card)] hover:border-fg-subtle/40 hover:bg-raised',
  soft: 'bg-accent-soft text-accent-strong font-semibold hover:bg-[#dce9ff]',
  ghost: 'text-fg-muted hover:bg-raised hover:text-fg',
  danger: 'bg-bad text-white font-semibold hover:brightness-110',
} as const
const SIZES = {
  sm: 'h-9 gap-1.5 px-3.5 text-[13px]',
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
        'transition-[background-color,border-color,color,box-shadow,filter,transform] duration-150 ease-out active:scale-[0.98]',
        'disabled:pointer-events-none disabled:opacity-45 [&_svg]:shrink-0',
        VARIANTS[variant], SIZES[size], className,
      )}
      {...props}
    />
  )
}
