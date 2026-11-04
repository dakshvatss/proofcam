import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

/** The one surface style: white, hairline border, soft elevation. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('rounded-[var(--radius-panel)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]', className)}
      {...props} />
  )
}

/** Section label used above every group of content. */
export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn('text-xs font-semibold uppercase tracking-[0.08em] text-fg-subtle', className)} {...props} />
}

const BADGE = {
  accent: 'border-accent/25 bg-accent-soft text-accent-strong',
  ok: 'border-ok/25 bg-ok/[0.08] text-ok',
  bad: 'border-bad/25 bg-bad/[0.07] text-bad',
  warn: 'border-warn/25 bg-warn/[0.08] text-warn',
  neutral: 'border-line-strong bg-surface text-fg-muted',
} as const

export function Badge({ className, tone = 'neutral', ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof BADGE }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[13px] font-medium [&_svg]:h-3.5 [&_svg]:w-3.5',
        BADGE[tone], className,
      )}
      {...props}
    />
  )
}
