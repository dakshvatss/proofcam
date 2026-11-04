import { Crosshair, LoaderCircle, Scale, ScanSearch } from 'lucide-react'
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
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0d1820]/40 backdrop-blur-[3px] sm:items-center sm:p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="change-title"
        className="animate-rise w-full max-w-md rounded-t-[1.5rem] border border-line bg-surface px-6 pt-5 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-[var(--shadow-lift)] sm:rounded-[var(--radius-panel)]">
        <span aria-hidden className="mx-auto mb-4 block h-1 w-10 rounded-full bg-line-strong sm:hidden" />
        <h2 id="change-title" className="text-xl font-semibold tracking-[-0.01em]">Record an installation change?</h2>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">
          Only do this if the equipment was physically changed (for example, a cable was moved). All earlier photos are
          kept in the report but will <strong className="font-semibold text-fg">no longer count</strong> as evidence.
          You will need to photograph the current setup again.
        </p>
        <label className="mt-5 block">
          <span className="text-sm font-semibold text-fg">What changed?</span>
          <textarea
            className="mt-2 w-full resize-none rounded-[var(--radius-control)] border border-line-strong bg-surface p-3 text-base text-fg
              transition-[border-color,box-shadow] duration-150 placeholder:text-fg-subtle focus:border-accent
              focus:shadow-[0_0_0_3px_rgb(8_102_255/0.15)] focus:outline-none"
            rows={3}
            maxLength={500}
            value={reason}
            autoFocus
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. moved the cable to another port"
          />
        </label>
        <div className="mt-5 grid grid-cols-2 gap-3">
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

/** Explicit confirmation of a statement by the person inspecting (device identity in one photo, or one cable between
 * two supported ends). Shows the exact sentence that will be recorded and what it does and does not prove. */
export function DeclareDialog({ statement, detail, onCancel, onConfirm, needsNote = false }: {
  statement: string
  detail: string
  onCancel: () => void
  onConfirm: (note?: string) => Promise<boolean>
  /** Written attestation: the person must describe what they checked (10-500 characters). */
  needsNote?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const noteOk = !needsNote || (note.trim().length >= 10 && note.length <= 500)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onCancel])
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#0d1820]/40 backdrop-blur-[3px] sm:items-center sm:p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="declare-title"
        className="animate-rise w-full max-w-md rounded-t-[1.5rem] border border-line bg-surface px-6 pt-5 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-[var(--shadow-lift)] sm:rounded-[var(--radius-panel)]">
        <span aria-hidden className="mx-auto mb-4 block h-1 w-10 rounded-full bg-line-strong sm:hidden" />
        <h2 id="declare-title" className="text-xl font-semibold tracking-[-0.01em]">Confirm this yourself?</h2>
        <p className="mt-3 rounded-[var(--radius-control)] border border-line bg-canvas p-3.5 text-[15px] font-medium leading-snug text-fg">
          “{statement}”
        </p>
        <p className="mt-3 text-sm leading-relaxed text-fg-muted">{detail}</p>
        {needsNote && (
          <label className="mt-4 block">
            <span className="text-sm font-semibold text-fg">What did you check yourself?</span>
            <textarea
              className="mt-2 w-full resize-none rounded-[var(--radius-control)] border border-line-strong bg-surface p-3 text-base text-fg
                transition-[border-color,box-shadow] duration-150 placeholder:text-fg-subtle focus:border-accent
                focus:shadow-[0_0_0_3px_rgb(8_102_255/0.15)] focus:outline-none"
              rows={3} maxLength={500} value={note} autoFocus aria-label="What did you check yourself?"
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Looked behind the TV: the HDMI cable is pushed fully into an HDMI input."
            />
          </label>
        )}
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">
          It is recorded as <strong className="font-semibold text-fg">your statement</strong>, not as something the
          models saw. Any verdict that relies on it is marked as relying on your statement in the app and the report.
        </p>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <Button variant="secondary" size="lg" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button size="lg" disabled={busy || !noteOk} onClick={async () => {
            setBusy(true)
            const ok = await onConfirm(needsNote ? note.trim() : undefined)
            setBusy(false)
            if (ok) onCancel()
          }}>
            {busy && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />} I confirm
          </Button>
        </div>
      </div>
    </div>
  )
}

const STAGES = (live: boolean) => [
  { icon: ScanSearch, text: `${live ? 'Muse Spark 1.3' : 'The perception model (mock)'} describes the devices, ports and cables it can see` },
  { icon: Crosshair, text: `${live ? 'SAM 3.1' : 'The segmentation model (mock)'} outlines the equipment and cables to ground those claims` },
  { icon: Scale, text: 'The policy re-checks every requirement and picks the next view' },
]

/** Analysis in progress. The server runs the whole step as one request, so this shows only what is actually
 * known (elapsed time) and describes the stages, without inventing per-stage progress. */
export function ProcessingCard({ startedAt, label, image, live = false }: {
  startedAt: number | null; label: string; image?: string; live?: boolean
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const secs = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : null
  return (
    <CaptureFrame>
      {image && <img src={image} alt="" className="absolute inset-0 h-full w-full scale-105 object-cover opacity-35 blur-[2px]" />}
      <div className="absolute inset-0 bg-gradient-to-b from-[#0d1820]/40 via-[#0d1820]/65 to-[#0d1820]/90" />
      <div role="status" aria-live="polite" className="relative flex h-full flex-col items-center justify-center gap-5 px-7 text-center">
        <span className="grid h-14 w-14 place-items-center rounded-full bg-white/10 backdrop-blur-md">
          <LoaderCircle className="h-7 w-7 animate-spin text-white" strokeWidth={1.9} aria-hidden />
        </span>
        <div>
          <p className="text-lg font-semibold text-white">{label}</p>
          {secs !== null && <p className="mt-1 text-sm tabular-nums text-white/70">{secs} s elapsed · usually under a minute</p>}
        </div>
        {image && (
          <ul className="max-w-[34ch] space-y-2 text-left text-[13px] leading-snug text-white/75">
            {STAGES(live).map(({ icon: Icon, text }) => (
              <li key={text} className="flex gap-2.5"><Icon className="mt-0.5 h-4 w-4 shrink-0 text-[#7fd3ff]" aria-hidden />{text}</li>
            ))}
          </ul>
        )}
        <p className="text-xs text-white/55">Sent as one request; results appear when the server finishes. Keep this page open.</p>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-[3px] overflow-hidden bg-white/10" aria-hidden>
        <div className="brand-gradient h-full w-2/5 animate-indeterminate" />
      </div>
    </CaptureFrame>
  )
}
