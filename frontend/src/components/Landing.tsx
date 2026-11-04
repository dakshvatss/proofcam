import { ArrowRight, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from './ui/button'
import { CardTitle } from './ui/card'

const STEPS = [
  'Photograph the installation.',
  'Take the specific views ProofCam asks for.',
  'Get a verdict that cites the photos behind it.',
]

export function Landing({ onStart, starting, message }: { onStart: () => void; starting: boolean; message?: ReactNode }) {
  return (
    <div className="flex min-h-[calc(100dvh-8rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))] flex-col">
      <section className="pt-8">
        <h1 className="text-[1.9rem] font-semibold leading-[1.15] tracking-tight text-fg">
          Visual proof for physical work.
        </h1>
        <p className="mt-3 max-w-[34ch] text-fg-muted">
          ProofCam decides which photo it needs next, and calls a requirement verified only when the photos prove it.
        </p>
      </section>

      {message && <div className="mt-6">{message}</div>}

      <section className="mt-8 rounded-[var(--radius-panel)] border border-line bg-surface">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <CardTitle>Specification</CardTitle>
          <code className="font-mono text-xs text-fg-muted">my_setup</code>
        </div>
        <p className="px-4 py-3.5 text-fg">
          The blue Ethernet cable must connect Router LAN 1 to Switch Port 3.
        </p>
      </section>

      <ol className="mt-6 space-y-3">
        {STEPS.map((t, i) => (
          <li key={t} className="flex items-baseline gap-3 text-sm text-fg-muted">
            <span className="w-4 shrink-0 font-mono text-xs tabular-nums text-fg-subtle">{i + 1}</span>
            {t}
          </li>
        ))}
      </ol>

      <div className="mt-auto space-y-4 pt-10">
        <Button size="lg" onClick={onStart} disabled={starting} className="w-full">
          {starting ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden /> : null}
          Start Inspection
          {!starting && <ArrowRight className="h-5 w-5" aria-hidden />}
        </Button>
        <p className="text-xs leading-relaxed text-fg-subtle">
          Photos are analysed by Meta's models on the server. ProofCam verifies visually observable conditions only;
          it does not certify electrical safety, hidden connectivity, operational performance, or regulatory compliance.
        </p>
      </div>
    </div>
  )
}
