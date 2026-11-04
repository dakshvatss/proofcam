import { cn } from '../../lib/utils'

/** ProofCam mark: viewfinder corners around a solid point (the observed fact). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden className={cn('h-6 w-6', className)}>
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" className="fill-surface stroke-line-strong" />
      <path d="M8 13V9.5A1.5 1.5 0 0 1 9.5 8H13M19 8h3.5A1.5 1.5 0 0 1 24 9.5V13M24 19v3.5a1.5 1.5 0 0 1-1.5 1.5H19M13 24H9.5A1.5 1.5 0 0 1 8 22.5V19"
        className="stroke-fg" strokeWidth="1.75" strokeLinecap="round" />
      <circle cx="16" cy="16" r="2.75" className="fill-accent" />
    </svg>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2 text-[15px] font-semibold tracking-tight text-fg', className)}>
      <LogoMark />
      ProofCam
    </span>
  )
}
