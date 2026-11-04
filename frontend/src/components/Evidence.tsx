import {
  ChevronRight, CircleCheck, CircleDashed, CircleDot, CircleX, Crosshair, Flag, type LucideIcon, Navigation, OctagonX,
  ScanSearch, TriangleAlert,
} from 'lucide-react'
import type { EvidenceItem, InspectionSpec, NextViewRequest, RequirementAssessment, ReviewItem } from '../api/types'
import { ACTION_TEXT, GAP_TEXT, STATUS_TEXT, cn, stopText } from '../lib/utils'
import { Button } from './ui/button'
import { Badge, CardTitle } from './ui/card'

type Status = RequirementAssessment['status']

/** Visual language of the three verdicts. Distinct by colour, icon AND wording, so they never depend on colour
 * alone. Insufficient evidence is presented as an inspection outcome with a next step, not as an error. */
const VERDICT: Record<Status, { icon: LucideIcon; text: string; tint: string; badge: 'ok' | 'bad' | 'warn'; caption: string }> = {
  VERIFIED: { icon: CircleCheck, text: 'text-ok', tint: 'bg-ok/[0.07] border-ok/30', badge: 'ok', caption: 'Proven by the photos.' },
  VIOLATED: { icon: CircleX, text: 'text-bad', tint: 'bg-bad/[0.08] border-bad/35', badge: 'bad', caption: 'Clearly observed not to meet the requirement.' },
  INSUFFICIENT_EVIDENCE: {
    icon: CircleDashed, text: 'text-warn', tint: 'bg-warn/[0.06] border-warn/30', badge: 'warn',
    caption: 'Not proven yet. The facts below are still unobserved.',
  },
}

export function VerdictBadge({ status }: { status: Status }) {
  const v = VERDICT[status]
  const Icon = v.icon
  return <Badge tone={v.badge} data-testid="verdict"><Icon aria-hidden />{STATUS_TEXT[status]}</Badge>
}

const ENDPOINT_STATE: Record<string, string> = {
  established: 'confirmed',
  violated: 'clearly wrong',
  contradicted: 'photos disagree',
  unknown: 'not yet established',
}

function StateIcon({ state }: { state: 'ok' | 'bad' | 'open' }) {
  if (state === 'ok') return <CircleCheck className="h-4 w-4 shrink-0 text-ok" aria-hidden />
  if (state === 'bad') return <CircleX className="h-4 w-4 shrink-0 text-bad" aria-hidden />
  return <CircleDashed className="h-4 w-4 shrink-0 text-fg-subtle" aria-hidden />
}

function EvidenceRow({ item, tone, onShowPhoto }: { item: EvidenceItem; tone: 'for' | 'against' | 'ignored'; onShowPhoto?: (seq: number) => void }) {
  const rail = tone === 'for' ? 'bg-ok/70' : tone === 'against' ? 'bg-bad/80' : 'bg-line-strong'
  return (
    <li className="relative pl-3.5">
      <span aria-hidden className={cn('absolute bottom-0.5 left-0 top-0.5 w-0.5 rounded-full', rail)} />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button type="button" onClick={() => onShowPhoto?.(item.seq)} aria-label={`Show photo ${item.seq}`}
          className="inline-flex items-center gap-0.5 rounded text-xs font-semibold text-accent-strong hover:underline underline-offset-2">
          Photo {item.seq}<ChevronRight className="h-3 w-3" aria-hidden />
        </button>
        <span className="text-[11px] uppercase tracking-wider text-fg-subtle">
          {tone === 'for' ? 'supports' : tone === 'against' ? 'contradicts' : 'not counted'}
        </span>
        {item.port_basis === 'layout_inference' && <span className="text-[11px] text-warn">port identified by layout inference</span>}
      </div>
      <p className="mt-1 break-words text-[13px] leading-relaxed text-fg-muted">{item.claim}</p>
      {item.grounding && (
        <p className={cn('mt-1 font-mono text-[11px] leading-relaxed', item.grounding.corroborated ? 'text-ok/90' : 'text-fg-subtle')}>
          SAM: {item.grounding.note}{item.grounding.corroborated ? ' (corroborated)' : ' (not corroborated)'}
        </p>
      )}
    </li>
  )
}

function Disclosure({ summary, children, testId }: { summary: React.ReactNode; children: React.ReactNode; testId?: string }) {
  return (
    <details className="group border-t border-line" data-testid={testId}>
      <summary className="flex cursor-pointer select-none items-center justify-between gap-3 py-3 text-sm text-fg hover:text-accent-strong">
        <span>{summary}</span>
        <ChevronRight className="h-4 w-4 text-fg-subtle transition-transform duration-200 group-open:rotate-90" aria-hidden />
      </summary>
      <div className="pb-4">{children}</div>
    </details>
  )
}

/** Every evidence item the policy used (or explicitly did not count) for this requirement, per endpoint. */
export function EvidenceDetails({ a, spec, onShowPhoto }: { a: RequirementAssessment; spec: InspectionSpec; onShowPhoto?: (seq: number) => void }) {
  const deviceName = (id: string) => spec.devices.find((d) => d.id === id)?.name ?? id
  const n = a.endpoints.reduce((k, ep) => k + ep.support.length + ep.conflicts.length + ep.inferred_only.length, 0) + a.identity_evidence.length
  return (
    <Disclosure testId="evidence" summary={`Evidence (${n} ${n === 1 ? 'item' : 'items'})`}>
      {n === 0 && <p className="text-sm text-fg-subtle">No photo has provided evidence for this requirement yet.</p>}
      <div className="space-y-5">
        {a.endpoints.map((ep) => (ep.support.length + ep.conflicts.length + ep.inferred_only.length > 0) && (
          <div key={ep.index}>
            <CardTitle className="mb-2">{deviceName(ep.device_id)} {ep.port_label}</CardTitle>
            <ul className="space-y-3">
              {ep.support.map((x, i) => <EvidenceRow key={`s${i}`} item={x} tone="for" onShowPhoto={onShowPhoto} />)}
              {ep.conflicts.map((x, i) => <EvidenceRow key={`c${i}`} item={x} tone="against" onShowPhoto={onShowPhoto} />)}
              {ep.inferred_only.map((x, i) => <EvidenceRow key={`n${i}`} item={x} tone="ignored" onShowPhoto={onShowPhoto} />)}
            </ul>
          </div>
        ))}
        {a.identity_evidence.length > 0 && (
          <div>
            <CardTitle className="mb-2">Same cable at both ends</CardTitle>
            <ul className="space-y-3">
              {a.identity_evidence.map((x, i) => <EvidenceRow key={i} item={x} tone="for" onShowPhoto={onShowPhoto} />)}
            </ul>
          </div>
        )}
      </div>
    </Disclosure>
  )
}

/** One requirement's server verdict. Shown exactly as the policy produced it; nothing here upgrades a status. */
export function VerdictCard({ a, spec, onShowPhoto }: { a: RequirementAssessment; spec: InspectionSpec; onShowPhoto?: (seq: number) => void }) {
  const req = spec.requirements.find((r) => r.id === a.requirement_id)
  const deviceName = (id: string) => spec.devices.find((d) => d.id === id)?.name ?? id
  const v = VERDICT[a.status]
  const Icon = v.icon
  const identityOk = a.identity_state === 'established' || a.identity_state === 'assumed_by_spec'
  return (
    <section aria-label={`Requirement ${a.requirement_id}`} className="overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface">
      <div className={cn('flex items-start gap-3 border-b px-4 py-4', v.tint)}>
        <Icon className={cn('mt-0.5 h-6 w-6 shrink-0', v.text)} strokeWidth={2.25} aria-hidden />
        <div className="min-w-0">
          <p className={cn('text-lg font-semibold leading-tight tracking-tight', v.text)}>{STATUS_TEXT[a.status]}</p>
          <p className="mt-0.5 text-sm text-fg-muted">{v.caption}</p>
        </div>
        <span className="ml-auto shrink-0 font-mono text-[11px] text-fg-subtle">{a.requirement_id}</span>
      </div>

      <div className="px-4 pt-4">
        <p className="text-fg">{req?.text ?? a.requirement_id}</p>

        <ul className="mt-4 divide-y divide-line rounded-[var(--radius-control)] border border-line">
          {a.endpoints.map((ep) => (
            <li key={ep.index} className="flex items-center gap-3 px-3 py-2.5 text-sm">
              <StateIcon state={ep.state === 'established' ? 'ok' : ep.state === 'unknown' ? 'open' : 'bad'} />
              <span className="min-w-0 flex-1 text-fg">{deviceName(ep.device_id)} {ep.port_label}</span>
              <span className={cn('text-right text-[13px]', ep.state === 'established' ? 'text-ok' : ep.state === 'unknown' ? 'text-fg-subtle' : 'text-bad')}>
                {ENDPOINT_STATE[ep.state] ?? ep.state}
                {ep.support.length > 0 && ` (photo ${[...new Set(ep.support.map((s) => s.seq))].join(', ')})`}
              </span>
            </li>
          ))}
          <li className="flex items-center gap-3 px-3 py-2.5 text-sm">
            <StateIcon state={identityOk ? 'ok' : 'open'} />
            <span className="min-w-0 flex-1 text-fg">Same cable at both ends</span>
            <span className={cn('text-right text-[13px]', identityOk ? 'text-ok' : 'text-fg-subtle')}>
              {a.identity_state === 'established' ? 'traced in one photo'
                : a.identity_state === 'assumed_by_spec' ? 'assumed by the spec' : 'not yet established'}
            </span>
          </li>
        </ul>

        {a.status !== 'VERIFIED' && a.gaps.length > 0 && (
          <div className="mt-5">
            <CardTitle className="mb-2">Missing evidence</CardTitle>
            <ul className="space-y-2.5 text-sm">
              {a.gaps.map((g) => (
                <li key={`${g.code}-${g.endpoint_index}`} className="flex gap-2.5">
                  <CircleDot className="mt-1 h-3 w-3 shrink-0 text-warn" aria-hidden />
                  <p className="text-fg-muted"><span className="font-medium text-fg">{GAP_TEXT[g.code] ?? g.code}.</span> {g.missing_fact}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {a.status === 'VIOLATED' && (
          <p className="mt-5 rounded-[var(--radius-control)] border border-bad/30 bg-bad/[0.06] p-3 text-sm text-fg">{a.explanation}</p>
        )}
        {a.assumptions.length > 0 && (
          <div className="mt-5 rounded-[var(--radius-control)] border border-warn/30 bg-warn/[0.05] p-3 text-sm">
            <p className="font-medium text-warn">Relies on assumptions</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-fg-muted">{a.assumptions.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}
      </div>

      <div className="mt-4 px-4">
        <EvidenceDetails a={a} spec={spec} onShowPhoto={onShowPhoto} />
        <Disclosure summary="Why (full explanation)">
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-fg-muted">{a.explanation}</p>
        </Disclosure>
      </div>
    </section>
  )
}

export function GuidanceCard({ nv }: { nv: NextViewRequest }) {
  return (
    <section aria-label="Next photo" className="rounded-[var(--radius-panel)] border border-accent/30 bg-accent/[0.05] p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-accent-strong">
          <Crosshair className="h-3.5 w-3.5" aria-hidden /> Next photo
        </p>
        <Badge tone="accent"><Navigation aria-hidden /><span>{ACTION_TEXT[nv.camera_action] ?? nv.camera_action}</span></Badge>
      </div>
      <p className="mt-3 text-[17px] font-medium leading-snug text-fg" data-testid="instruction">{nv.instruction}</p>
      <p className="mt-2.5 flex gap-2 text-sm text-fg-muted">
        <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
        <span><span className="font-medium text-fg">Success when:</span> {nv.success_criteria}</span>
      </p>
      <details className="group mt-3">
        <summary className="inline-flex cursor-pointer items-center gap-1 text-xs text-fg-subtle hover:text-fg-muted">
          Why this view <ChevronRight className="h-3 w-3 transition-transform duration-200 group-open:rotate-90" aria-hidden />
        </summary>
        <p className="mt-2 text-xs leading-relaxed text-fg-subtle">
          {nv.missing_fact} · Guidance {nv.planner === 'muse' ? 'planned by Muse' : 'from a fixed template'} ·{' '}
          <span className="font-mono">{nv.id}</span>
        </p>
      </details>
    </section>
  )
}

/** Shown instead of guidance when no photo is needed yet (first photo) or the guidance no longer applies. */
export function PromptCard({ title, children, label }: { title: string; children: React.ReactNode; label?: string }) {
  return (
    <section aria-label={label} className="rounded-[var(--radius-panel)] border border-line bg-surface p-4">
      <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-accent-strong">
        <ScanSearch className="h-3.5 w-3.5" aria-hidden /> {title}
      </p>
      <p className="mt-2.5 text-fg">{children}</p>
    </section>
  )
}

export function ReviewCard({ items, onDeclare, canDeclare }: { items: ReviewItem[]; onDeclare: () => void; canDeclare: boolean }) {
  return (
    <section role="alert" aria-label="Review required" className="rounded-[var(--radius-panel)] border border-bad/40 bg-bad/[0.06] p-4">
      <div className="flex items-center gap-2.5">
        <TriangleAlert className="h-5 w-5 text-bad" aria-hidden />
        <h2 className="font-semibold text-fg">Review the installation</h2>
      </div>
      <p className="mt-2 text-sm text-fg-muted">
        Some photos contradict each other. Taking another photo of the same setup will not fix this. Check the
        installation in person.
      </p>
      <div className="mt-3 space-y-3">
        {items.map((it) => (
          <div key={it.requirement_id} className="rounded-[var(--radius-control)] border border-line bg-surface/70 p-3 text-sm">
            <p className="font-medium text-fg">{it.requirement_id}: photos {it.photos.join(', ')} disagree.</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[13px] text-fg-muted">
              {it.contradictions.map((c) => <li key={c} className="break-words">{c}</li>)}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm text-fg-muted">
        If you physically changed the installation between photos (for example moved a cable), record that change.
        Earlier photos are kept but stop counting. If nothing changed, this requirement cannot be verified from these photos.
      </p>
      {canDeclare && <Button variant="secondary" className="mt-4 w-full" onClick={onDeclare}>I changed the installation…</Button>}
    </section>
  )
}

export function StopCard({ reason, onDeclare }: { reason: string; onDeclare: () => void }) {
  const t = stopText(reason)!
  const Icon = reason === 'all_requirements_resolved' ? Flag : OctagonX
  return (
    <section aria-label="Inspection stopped" className="flex gap-3 rounded-[var(--radius-panel)] border border-line bg-surface p-4">
      <Icon className="mt-0.5 h-5 w-5 shrink-0 text-fg-muted" aria-hidden />
      <div className="min-w-0 space-y-1">
        <h2 className="font-semibold text-fg">{t.title}</h2>
        <p className="text-sm text-fg-muted">{t.detail}</p>
        {t.reopenable && reason !== 'contradiction_requires_review' && (
          <Button variant="ghost" size="sm" className="-ml-3 mt-1 h-auto whitespace-normal py-2 text-left text-accent-strong hover:text-accent-strong" onClick={onDeclare}>
            The installation was changed — continue…
          </Button>
        )}
      </div>
    </section>
  )
}
