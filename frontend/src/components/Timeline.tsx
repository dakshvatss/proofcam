import { Camera, ChevronRight, CircleCheck, CircleDashed, Crosshair, Flag, RefreshCcw, TriangleAlert } from 'lucide-react'
import type { InspectionState, StepResponse, ViewCheck } from '../api/types'
import { cn, VIEW_TEXT } from '../lib/utils'
import { CardTitle } from './ui/card'

const WORD: Record<string, string> = { VERIFIED: 'verified', VIOLATED: 'violated', INSUFFICIENT_EVIDENCE: 'needs evidence' }

/** What the last analysed photo actually changed, from the server's step response only (no invented results). */
export function LastPhotoCard({ step, state }: { step: StepResponse; state: InspectionState }) {
  const photo = state.photos.find((p) => p.seq === step.seq)
  const accepted = step.assessments.reduce((k, a) => k + a.identity_evidence.filter((x) => x.seq === step.seq).length
    + a.endpoints.reduce((j, ep) => j + ep.support.filter((x) => x.seq === step.seq).length, 0), 0)
  const open = step.assessments.filter((a) => a.status === 'INSUFFICIENT_EVIDENCE').reduce((k, a) => k + a.gaps.length, 0)
  const rows: { ok: boolean | null; text: string }[] = []
  if (step.duplicate_of !== null) rows.push({ ok: null, text: `Identical to photo ${step.duplicate_of}: not analysed again` })
  else if (photo && !photo.usable) rows.push({ ok: false, text: 'Analysed, but the photo was not usable as evidence' })
  else rows.push({ ok: true, text: 'Received and analysed by the models' })
  // Three separate questions, each answered by the server: did the photo show the requested view (guidance), what
  // did the policy accept from it (evidence), and is the connection established (verdict).
  const vc = step.duplicate_of === null ? step.view_check : null
  if (vc) rows.push({ ok: vc.status === 'captured' ? true : vc.status === 'partial' ? null : false, text: VIEW_TEXT[vc.status] })
  if (vc?.identity_confirmed === false) rows.push({ ok: false, text: `${vc.unconfirmed_devices.join(', ')} not identified with certainty: not used as evidence` })
  rows.push({ ok: accepted > 0 ? true : null, text: `${accepted} evidence ${accepted === 1 ? 'item' : 'items'} accepted by the policy from this photo` })
  const museOnly = step.assessments.reduce((k, a) => k + a.endpoints.reduce((j, ep) => j
    + (ep.candidates ?? []).filter((x) => x.seq === step.seq).length, 0), 0)
  if (museOnly > 0) rows.push({ ok: false, text: `${museOnly} ${museOnly === 1 ? 'plug' : 'plugs'} seen by Muse only: SAM did not corroborate, not counted` })
  const target = vc ? step.assessments.find((a) => a.requirement_id === vc.requirement_id) : undefined
  if (target?.status === 'INSUFFICIENT_EVIDENCE') {
    rows.push({ ok: null, text: `${target.requirement_id}: connection still needs evidence` })
    if (target.gaps.some((g) => g.code === 'LABEL_ILLEGIBLE')) rows.push({ ok: null, text: 'Port identity could not be established' })
  }
  if (open > 0) rows.push({ ok: null, text: `${open} ${open === 1 ? 'fact' : 'facts'} still to establish` })
  rows.push(step.status === 'stopped'
    ? { ok: null, text: 'No further photo requested: the inspection has stopped' }
    : step.next_view ? { ok: true, text: 'Next view requested' } : { ok: null, text: 'No camera request: see the review notes' })
  return (
    <section aria-label="Last photo result" className="animate-rise rounded-[var(--radius-panel)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
      <CardTitle>Photo {step.seq} result{step.replayed ? ' (saved result)' : ''}</CardTitle>
      <ul className="mt-3 space-y-2">
        {rows.map((r) => (
          <li key={r.text} className="flex items-start gap-2.5 text-sm text-fg">
            {r.ok === true ? <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
              : r.ok === false ? <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
                : <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-fg-subtle" aria-hidden />}
            {r.text}
          </li>
        ))}
      </ul>
      {step.notes.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-line pt-3 text-[13px] leading-relaxed text-fg-muted">
          {step.notes.map((n) => <p key={n}>{n}</p>)}
        </div>
      )}
    </section>
  )
}

type Entry = Record<string, unknown>

/** Audit-friendly timeline of the inspection, from the history the server persisted (captures, camera requests,
 * verdict changes, declared installation changes). Nothing here is reconstructed or invented. */
export function Timeline({ history }: { history: Entry[] }) {
  if (!history.length) return null
  return (
    <details className="group rounded-[var(--radius-panel)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <summary className="flex cursor-pointer select-none items-center justify-between gap-3 px-5 py-4">
        <CardTitle>Timeline ({history.length} {history.length === 1 ? 'event' : 'events'})</CardTitle>
        <ChevronRight className="h-4 w-4 text-fg-subtle transition-transform duration-200 group-open:rotate-90" aria-hidden />
      </summary>
      <ol className="relative mx-5 mb-5 space-y-4 border-l border-line pl-5">
        {history.map((h, i) => {
          if (h.event === 'installation_changed') {
            return (
              <li key={i} className="relative">
                <span className="absolute -left-[29px] top-0.5 grid h-4 w-4 place-items-center rounded-full bg-surface text-warn">
                  <RefreshCcw className="h-3.5 w-3.5" aria-hidden />
                </span>
                <p className="text-sm font-semibold text-fg">Installation change recorded</p>
                <p className="text-[13px] text-fg-muted">“{String(h.reason ?? '')}” · earlier photos no longer count</p>
              </li>
            )
          }
          const reqs = (h.requirements as { id: string; status: string }[] | undefined) ?? []
          const vc = h.view_check as ViewCheck | undefined
          const stopped = typeof h.stop_reason === 'string' ? h.stop_reason : null
          return (
            <li key={i} className="relative">
              <span className="absolute -left-[29px] top-0.5 grid h-4 w-4 place-items-center rounded-full bg-surface text-accent">
                {stopped ? <Flag className="h-3.5 w-3.5" aria-hidden /> : <Camera className="h-3.5 w-3.5" aria-hidden />}
              </span>
              <p className="text-sm font-semibold text-fg">
                {`Photo ${String(h.seq)}`}
                {h.source_name ? <span className="font-normal text-fg-subtle"> · {String(h.source_name)}</span> : null}
              </p>
              {vc && <p className="mt-0.5 text-[13px] text-fg-muted">{`${VIEW_TEXT[vc.status]} (${vc.request_id})`}</p>}
              {reqs.length > 0 && (
                <p className="mt-0.5 flex flex-wrap gap-x-3 text-[13px]">
                  {reqs.map((r) => (
                    <span key={r.id} className={cn(r.status === 'VERIFIED' ? 'text-ok' : r.status === 'VIOLATED' ? 'text-bad' : 'text-warn')}>
                      {`${r.id} ${WORD[r.status] ?? r.status}`}
                    </span>
                  ))}
                </p>
              )}
              <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-fg-muted">
                {stopped ? `Stopped: ${stopped.replaceAll('_', ' ')}`
                  : h.next_view ? <><Crosshair className="h-3.5 w-3.5" aria-hidden />{`Next view ${String(h.next_view)} requested`}</>
                    : 'No camera request'}
              </p>
            </li>
          )
        })}
      </ol>
    </details>
  )
}
