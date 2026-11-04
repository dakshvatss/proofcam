import { CircleAlert, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/utils'

const TONES: Record<'info' | 'warn' | 'error', { icon: LucideIcon; box: string; icon_: string }> = {
  info: { icon: Info, box: 'border-line bg-surface text-fg', icon_: 'text-accent' },
  warn: { icon: TriangleAlert, box: 'border-warn/25 bg-[#fff8ef] text-fg', icon_: 'text-warn' },
  error: { icon: CircleAlert, box: 'border-bad/25 bg-[#fff5f4] text-fg', icon_: 'text-bad' },
}

/** Inline message (notices, errors, states). Errors are announced as alerts, the rest politely. */
export function Callout({ tone = 'info', title, action, className, children, ...props }: Omit<HTMLAttributes<HTMLDivElement>, 'title'> & {
  tone?: keyof typeof TONES
  title?: ReactNode
  action?: ReactNode
}) {
  const t = TONES[tone]
  const Icon = t.icon
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('flex gap-3 rounded-[var(--radius-control)] border px-4 py-3.5 text-sm shadow-[var(--shadow-card)]', t.box, className)}
      {...props}
    >
      <Icon className={cn('mt-0.5 h-[18px] w-[18px] shrink-0', t.icon_)} aria-hidden />
      <div className="min-w-0 flex-1 space-y-2">
        {title && <p className="font-semibold">{title}</p>}
        <div className={title ? 'text-fg-muted' : undefined}>{children}</div>
        {action}
      </div>
    </div>
  )
}
