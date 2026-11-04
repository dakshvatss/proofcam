import { Box, Gamepad2, Laptop, Network, Router, Server, Tv, type LucideIcon } from 'lucide-react'
import type { RequirementStatus } from '../api/types'
import { CONNECTOR_TEXT, PROGRESS_TEXT, cn } from '../lib/utils'

export interface DiagramLink {
  id: string
  from: string // device name
  to: string
  connector: string
  status?: RequirementStatus | 'PENDING'
}

// Icon from the device's own name/concept; purely illustrative.
function deviceIcon(name: string): LucideIcon {
  const n = name.toLowerCase()
  if (/router|wi-?fi|modem/.test(n)) return Router
  if (/switch|hub/.test(n)) return Network
  if (/playstation|console|ps5|xbox|game/.test(n)) return Gamepad2
  if (/tv|television|display|monitor|screen/.test(n)) return Tv
  if (/laptop|notebook/.test(n)) return Laptop
  if (/server|nas/.test(n)) return Server
  return Box
}

const LINK_TONE: Record<string, string> = {
  PENDING: 'bg-line-strong',
  VERIFIED: 'bg-ok',
  VIOLATED: 'bg-bad',
  INSUFFICIENT_EVIDENCE: 'bg-warn/70',
}

/** Chain order if the links form one simple path through all devices (A-B, B-C ...), else null. */
function chain(devices: string[], links: DiagramLink[]): { order: string[]; between: DiagramLink[] } | null {
  if (links.length !== devices.length - 1) return null
  const deg = new Map(devices.map((d) => [d, 0]))
  for (const l of links) {
    if (!deg.has(l.from) || !deg.has(l.to) || l.from === l.to) return null
    deg.set(l.from, deg.get(l.from)! + 1)
    deg.set(l.to, deg.get(l.to)! + 1)
  }
  const start = devices.find((d) => deg.get(d) === 1)
  if (!start || [...deg.values()].some((v) => v > 2 || v === 0)) return null
  const order = [start]
  const between: DiagramLink[] = []
  const left = [...links]
  while (left.length) {
    const cur = order[order.length - 1]
    const i = left.findIndex((l) => l.from === cur || l.to === cur)
    if (i < 0) return null
    const l = left.splice(i, 1)[0]
    between.push(l)
    order.push(l.from === cur ? l.to : l.from)
  }
  return order.length === devices.length ? { order, between } : null
}

/** A small, honest picture of what one inspection covers: devices and the required connections between them.
 * Link colours (when given) are the server's per-requirement verdicts. */
export function ConnectionDiagram({ devices, links, className }: { devices: string[]; links: DiagramLink[]; className?: string }) {
  const c = chain(devices, links)
  if (!c) {
    return (
      <ul className={cn('space-y-2', className)}>
        {links.map((l) => (
          <li key={l.id} className="flex items-center gap-2 text-sm text-fg-muted">
            <span className="font-medium text-fg">{l.from}</span>
            <span className="text-xs">— {CONNECTOR_TEXT[l.connector] ?? l.connector} —</span>
            <span className="font-medium text-fg">{l.to}</span>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <div className={cn('flex items-start', className)} aria-hidden>
      {c.order.map((d, i) => {
        const Icon = deviceIcon(d)
        const link = c.between[i]
        return (
          <div key={d} className={cn('flex min-w-0 items-start', i < c.order.length - 1 && 'flex-1')}>
            <div className="flex w-[68px] shrink-0 flex-col items-center gap-1.5 text-center sm:w-24">
              <span className="grid h-12 w-12 place-items-center rounded-2xl border border-line bg-surface text-fg shadow-[var(--shadow-card)]">
                <Icon className="h-[22px] w-[22px]" strokeWidth={1.75} />
              </span>
              <span className="text-xs font-medium leading-tight text-fg">{d}</span>
            </div>
            {link && (
              <div className="mt-[17px] flex min-w-0 flex-1 flex-col items-center gap-1 px-1">
                <span className="max-w-full truncate text-[11px] font-semibold uppercase tracking-[0.04em] text-accent-strong">
                  {CONNECTOR_TEXT[link.connector] ?? link.connector}
                </span>
                <span className={cn('h-[3px] w-full rounded-full', LINK_TONE[link.status ?? 'PENDING'])} />
                {link.status && link.status !== 'PENDING' && (
                  <span className="max-w-full truncate text-[11px] text-fg-subtle">{PROGRESS_TEXT[link.status].toLowerCase()}</span>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
