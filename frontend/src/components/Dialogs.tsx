import { LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { CaptureFrame } from './CameraPanel'
import { Button } from './ui/button'

/** Explicit confirmation before declaring a physical installation change (earlier photos stop counting).
 * A bottom sheet on phones, a centred dialog on wider screens. */
export function ChangeDialog({ open, onCancel, onConfirm }: {
  open: boolean
  onCancel: () => void
  onConfirm: (reason: string) => Promise<boolean>
}) {
  // Mounted only while open, so the reason starts empty every time.
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onCancel])
  if (!open) return null
  const valid = reason.trim().length > 0 && reason.length <= 500
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 backdrop-blur-[2px] sm:items-center sm:p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="change-title"
        className="w-full max-w-md rounded-t-[1.25rem] border border-line-strong bg-surface px-5 pt-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:rounded-[var(--radius-panel)]">
        <span aria-hidden className="mx-auto mb-4 block h-1 w-9 rounded-full bg-line-strong sm:hidden" />
        <h2 id="change-title" className="text-lg font-semibold tracking-tight">Record an installation change?</h2>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">
          Only do this if the equipment was physically changed (for example, a cable was moved). All earlier photos are
          kept in the report but will <strong className="font-semibold text-fg">no longer count</strong> as evidence.
          You will need to photograph the current setup again.
        </p>
        <label className="mt-4 block">
          <span className="text-sm font-medium text-fg">What changed?</span>
          <textarea
            className="mt-2 w-full resize-none rounded-[var(--radius-control)] border border-line-strong bg-canvas p-3 text-base text-fg
              transition-colors duration-150 placeholder:text-fg-subtle focus:border-accent focus:outline-none"
            rows={3}
            maxLength={500}
            value={reason}
            autoFocus
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. moved the blue cable from switch port 4 to port 3"
          />
        </label>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Button variant="secondary" size="lg" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button
            size="lg"
            disabled={!valid || busy}
            onClick={async () => {
              setBusy(true)
              const ok = await onConfirm(reason.trim())
              setBusy(false)
              if (ok) onCancel()
            }}
          >
            {busy && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />} Confirm change
          </Button>
        </div>
      </div>
    </div>
  )
}

/** Analysis in progress. Shows only what is actually known (elapsed time), never invented model progress. */
export function ProcessingCard({ startedAt, label, image }: { startedAt: number | null; label: string; image?: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const secs = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : null
  return (
    <CaptureFrame>
      {image && <img src={image} alt="" className="absolute inset-0 h-full w-full scale-105 object-cover opacity-30 blur-[2px]" />}
      <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/55 to-black/80" />
      <div role="status" aria-live="polite" className="relative flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
        <LoaderCircle className="h-8 w-8 animate-spin text-accent" strokeWidth={1.75} aria-hidden />
        <div>
          <p className="text-[17px] font-medium text-white">{label}</p>
          {secs !== null && <p className="mt-1 font-mono text-sm tabular-nums text-white/70">{secs} s elapsed</p>}
        </div>
        <p className="max-w-[30ch] text-[13px] leading-relaxed text-white/65">
          Reading the photo, outlining objects and checking the evidence usually takes under a minute. Keep this page open.
        </p>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-white/10" aria-hidden>
        <div className="h-full w-2/5 animate-indeterminate bg-accent/80" />
      </div>
    </CaptureFrame>
  )
}
