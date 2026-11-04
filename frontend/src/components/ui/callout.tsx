import { CircleAlert, Info, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/utils'

const TONES: Record<'info' | 'warn' | 'error', { icon: LucideIcon; box: string; icon_: string }> = {
  info: { icon: Info, box: 'border-line bg-surface text-fg', icon_: 'text-fg-muted' },
  warn: { icon: TriangleAlert, box: 'border-warn/35 bg-warn/[0.07] text-fg', icon_: 'text-warn' },
  error: { icon: CircleAlert, box: 'border-bad/40 bg-bad/[0.08] text-fg', icon_: 'text-bad' },
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
      className={cn('flex gap-3 rounded-[var(--radius-control)] border px-3.5 py-3 text-sm', t.box, className)}
      {...props}
    >
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', t.icon_)} aria-hidden />
      <div className="min-w-0 flex-1 space-y-2">
        {title && <p className="font-medium">{title}</p>}
        <div className={title ? 'text-fg-muted' : undefined}>{children}</div>
        {action}
      </div>
    </div>
  )
}
