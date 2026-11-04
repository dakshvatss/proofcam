import { useId } from 'react'
import { cn } from '../../lib/utils'

/** ProofCam mark: viewfinder corners framing a confirmation tick (evidence captured), on the brand gradient.
 * Original artwork; kept simple enough to read at favicon size (public/favicon.svg is the same drawing). */
export function LogoMark({ className }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn('h-7 w-7 shrink-0', className)}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0866FF" />
          <stop offset="1" stopColor="#28C7FA" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8.5" fill={`url(#${id})`} />
      <path d="M8 12.5V10a2 2 0 0 1 2-2h2.5M19.5 8H22a2 2 0 0 1 2 2v2.5M24 19.5V22a2 2 0 0 1-2 2h-2.5M12.5 24H10a2 2 0 0 1-2-2v-2.5"
        fill="none" stroke="#fff" strokeWidth="2.1" strokeLinecap="round" />
      <path d="M11.9 16.3l2.9 2.9 5.5-5.7" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5 text-[17px] font-semibold tracking-[-0.01em] text-fg', className)}>
      <LogoMark />
      ProofCam
    </span>
  )
}
