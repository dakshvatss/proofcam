import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

/** The one surface style: hairline border, no shadow. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-[var(--radius-panel)] border border-line bg-surface p-4', className)} {...props} />
}

/** Small uppercase section label used above every group of content. */
export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 className={cn('text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-subtle', className)} {...props} />
  )
}

const BADGE = {
  accent: 'border-accent/35 text-accent-strong',
  ok: 'border-ok/40 bg-ok/10 text-ok',
  bad: 'border-bad/40 bg-bad/10 text-bad',
  warn: 'border-warn/40 bg-warn/10 text-warn',
  neutral: 'border-line-strong text-fg-muted',
} as const

export function Badge({ className, tone = 'neutral', ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof BADGE }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium [&_svg]:h-3.5 [&_svg]:w-3.5',
        BADGE[tone], className,
      )}
      {...props}
    />
  )
}
