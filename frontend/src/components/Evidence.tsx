import {
  ChevronRight, CircleCheck, CircleDashed, CircleDot, CircleX, Clock3, Crosshair, Flag, Navigation,
  OctagonX, ScanSearch, TriangleAlert, UserCheck,
} from 'lucide-react'
import type {
  DeclarationRequest, EndpointAssessment, EvidenceItem, Gap, InspectionSpec, NextViewRequest, OverallAssessment,
  RequirementAssessment, ReviewItem,
} from '../api/types'
import {
  ACTION_TEXT, ASSURANCE_TEXT, GAP_TEXT, IDENTITY_TEXT, PROGRESS_TEXT, STATUS_TEXT, cn, connectionName, stopText,
  verdictText,
} from '../lib/utils'
import { VERDICT } from '../lib/verdict'
import { ConnectionDiagram } from './ConnectionDiagram'
import { Button } from './ui/button'
import { Badge, CardTitle } from './ui/card'

type Status = RequirementAssessment['status']

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
  if (state === 'ok') return <CircleCheck className="h-[18px] w-[18px] shrink-0 text-ok" aria-hidden />
  if (state === 'bad') return <CircleX className="h-[18px] w-[18px] shrink-0 text-bad" aria-hidden />
  return <CircleDashed className="h-[18px] w-[18px] shrink-0 text-fg-subtle" aria-hidden />
}

const BASIS_TEXT: Record<string, string> = {
  layout_inference: 'port identified by layout inference',
  connector_shape: 'port identified by socket shape (spec assumption)',
}

function EvidenceRow({ item, tone, onShowPhoto }: { item: EvidenceItem; tone: 'for' | 'against' | 'ignored'; onShowPhoto?: (seq: number) => void }) {
  const rail = tone === 'for' ? 'bg-ok' : tone === 'against' ? 'bg-bad' : 'bg-line-strong'
  return (
    <li className="relative pl-4">
      <span aria-hidden className={cn('absolute bottom-0.5 left-0 top-0.5 w-[3px] rounded-full', rail)} />
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {item.attested ? <span className="text-[13px] font-semibold text-accent">Your attestation</span> : (
          <button type="button" onClick={() => onShowPhoto?.(item.seq)} aria-label={`Show photo ${item.seq}`}
            className="inline-flex items-center gap-0.5 rounded-md text-[13px] font-semibold text-accent hover:underline underline-offset-2">
            Photo {item.seq}<ChevronRight className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
        <span className={cn('text-xs font-medium', tone === 'for' ? 'text-ok' : tone === 'against' ? 'text-bad' : 'text-fg-subtle')}>
          {tone === 'for' ? 'supports' : tone === 'against' ? 'contradicts' : 'not counted'}
        </span>
        {item.port_basis && BASIS_TEXT[item.port_basis] && <span className="text-xs text-warn">{BASIS_TEXT[item.port_basis]}</span>}
        {item.device_basis === 'operator_declared' && <span className="text-xs text-accent">device confirmed by you</span>}
        {item.insertion_basis === 'operator_confirmed' && <span className="text-xs text-accent">plug confirmed by you · not SAM-corroborated</span>}
        {item.attested && <span className="text-xs text-accent">your written attestation · no photo</span>}
      </div>
      <p className="mt-1 break-words text-[13px] leading-relaxed text-fg-muted">{item.claim}</p>
      {item.grounding && (
        <p className={cn('mt-1 font-mono text-[11.5px] leading-relaxed', item.grounding.corroborated ? 'text-ok' : 'text-fg-subtle')}>
          SAM: {item.grounding.note}{item.grounding.corroborated ? ' (corroborated)' : ' (not corroborated)'}
        </p>
      )}
    </li>
  )
}

function Disclosure({ summary, children, testId }: { summary: React.ReactNode; children: React.ReactNode; testId?: string }) {
  return (
    <details className="group border-t border-line" data-testid={testId}>
      <summary className="flex cursor-pointer select-none items-center justify-between gap-3 py-3.5 text-sm font-medium text-fg hover:text-accent">
        <span>{summary}</span>
        <ChevronRight className="h-4 w-4 text-fg-subtle transition-transform duration-200 group-open:rotate-90" aria-hidden />
      </summary>
      <div className="pb-5">{children}</div>
    </details>
  )
}

/** Every evidence item the policy used (or explicitly did not count) for this requirement, per endpoint. */
export function EvidenceDetails({ a, spec, onShowPhoto }: { a: RequirementAssessment; spec: InspectionSpec; onShowPhoto?: (seq: number) => void }) {
  const deviceName = (id: string) => spec.devices.find((d) => d.id === id)?.name ?? id
  const extra = (ep: EndpointAssessment) => ep.inferred_only.length + (ep.candidates?.length ?? 0)
  const n = a.endpoints.reduce((k, ep) => k + ep.support.length + ep.conflicts.length + extra(ep), 0) + a.identity_evidence.length
  return (
    <Disclosure testId="evidence" summary={`Evidence (${n} ${n === 1 ? 'item' : 'items'})`}>
      <p className="mb-4 text-xs leading-relaxed text-fg-subtle">
        Model observations the policy accepted (supports), held against the requirement (contradicts) or recorded
        without counting (for example a plug Muse saw that SAM did not corroborate). Overlays show everything the
        models reported; only supporting and contradicting items decide the verdict.
      </p>
      {n === 0 && <p className="text-sm text-fg-subtle">No photo has provided evidence for this requirement yet.</p>}
      <div className="space-y-5">
        {a.endpoints.map((ep) => (ep.support.length + ep.conflicts.length + extra(ep) > 0) && (
          <div key={ep.index}>
            <CardTitle className="mb-2.5">{deviceName(ep.device_id)} {ep.port_label}</CardTitle>
            <ul className="space-y-3.5">
              {ep.support.map((x, i) => <EvidenceRow key={`s${i}`} item={x} tone="for" onShowPhoto={onShowPhoto} />)}
              {ep.conflicts.map((x, i) => <EvidenceRow key={`c${i}`} item={x} tone="against" onShowPhoto={onShowPhoto} />)}
              {ep.inferred_only.map((x, i) => <EvidenceRow key={`n${i}`} item={x} tone="ignored" onShowPhoto={onShowPhoto} />)}
              {(ep.candidates ?? []).map((x, i) => <EvidenceRow key={`m${i}`} item={x} tone="ignored" onShowPhoto={onShowPhoto} />)}
            </ul>
          </div>
        ))}
        {a.identity_evidence.length > 0 && (
          <div>
            <CardTitle className="mb-2.5">Same cable at both ends</CardTitle>
            <ul className="space-y-3.5">
              {a.identity_evidence.map((x, i) => <EvidenceRow key={i} item={x} tone="for" onShowPhoto={onShowPhoto} />)}
            </ul>
          </div>
        )}
      </div>
    </Disclosure>
  )
}

const seqList = (items: EvidenceItem[]) => [...new Set(items.filter((s) => s.seq > 0).map((s) => s.seq))].join(', ')

/** How far the evidence for one endpoint got: accepted (and on what), seen by Muse only, or nothing yet. */
function endpointLevel(ep: EndpointAssessment): { text: string; tone: 'ok' | 'warn' | 'accent' } | null {
  if (ep.state === 'established') {
    if (ep.support.every((s) => s.attested)) return { text: 'attested by you in writing · no photo evidence', tone: 'accent' }
    if (ep.support.every((s) => s.insertion_basis === 'operator_confirmed')) {
      return { text: 'seen by Muse · plug confirmed by you (SAM did not corroborate)', tone: 'accent' }
    }
    return ep.support.every((s) => s.device_basis === 'operator_declared')
      ? { text: 'device confirmed by you', tone: 'accent' }
      : { text: 'seen by Muse · grounded by SAM', tone: 'ok' }
  }
  if (ep.state === 'unknown' && ep.candidates?.length) {
    return { text: `seen by Muse only (photo ${seqList(ep.candidates)}) · SAM did not corroborate it`, tone: 'warn' }
  }
  return null
}

export type DeclareHandler = (req: DeclarationRequest, statement: string, detail: string, needsNote?: boolean) => void

/** The statements a gap allows the person inspecting to make (only where the server says the spec permits them). */
type Offer = { req: DeclarationRequest; label: string; statement: string; detail: string; needsNote?: boolean }

/** Written attestation for an end the photos could not establish (server sets context.attestation_permitted). */
function attestation(g: Gap, spec: InspectionSpec): Offer[] {
  const r = spec.requirements.find((x) => x.id === g.requirement_id)
  if (g.context.attestation_permitted !== true || !r || g.endpoint_index === null) return []
  const e = r.endpoints[g.endpoint_index]
  const device = spec.devices.find((d) => d.id === e.device_id)?.name ?? e.device_id
  return [{
    req: { type: 'endpoint_attestation', requirement_id: r.id, endpoint_index: g.endpoint_index },
    label: 'I checked this end myself',
    statement: `I checked the ${device} ${e.port_label} end myself.`,
    detail: 'Use this only when the photos cannot show it but you have checked it in person. Your note is quoted in the app and the report, and the connection is labelled "Verified — operator-attested", not visually established. It is refused if any photo shows that socket empty or holding another plug.',
    needsNote: true,
  }]
}

function declarations(g: Gap, spec: InspectionSpec): Offer[] {
  const extra = attestation(g, spec)
  if (g.context.declaration_permitted !== true) return extra
  return [...declarationOffers(g, spec), ...extra]
}

function declarationOffers(g: Gap, spec: InspectionSpec): Offer[] {
  const r = spec.requirements.find((x) => x.id === g.requirement_id)
  if (g.code === 'DEVICE_UNCONFIRMED' && r && g.endpoint_index !== null) {
    const deviceId = r.endpoints[g.endpoint_index].device_id
    const device = spec.devices.find((d) => d.id === deviceId)?.name ?? deviceId
    return ((g.context.unconfirmed_port_photos as number[] | undefined) ?? []).map((seq) => ({
      req: { type: 'device_identity', seq, device_id: deviceId },
      label: `Photo ${seq} shows the ${device}`,
      statement: `Photo ${seq} shows the ${device}.`,
      detail: `Only confirm if you know this photo shows the ${device}. Muse could not identify it with certainty there; its ports in that photo will then count as evidence for the ${device}.`,
    }))
  }
  if (g.code === 'GROUNDING_MISSING' && r && g.endpoint_index !== null) {
    const e = r.endpoints[g.endpoint_index]
    const device = spec.devices.find((d) => d.id === e.device_id)?.name ?? e.device_id
    const connector = r.connector === 'hdmi' ? 'HDMI' : r.connector ?? 'ethernet'
    return [{
      req: { type: 'endpoint_insertion', requirement_id: r.id, endpoint_index: g.endpoint_index },
      label: 'The plug is seated: I checked',
      statement: `The ${connector} plug Muse saw at the ${device} ${e.port_label} is fully seated in that port.`,
      detail: 'Only confirm if you have checked the plug yourself. Muse saw it clearly but SAM did not corroborate it; the connection will be marked as relying on your statement. Photos showing that port empty would make this impossible.',
    }]
  }
  if (g.code === 'CABLE_CONTINUITY' && r) {
    const ends = r.endpoints.map((e) => `${spec.devices.find((d) => d.id === e.device_id)?.name ?? e.device_id} ${e.port_label}`)
    const cable = r.cable_color ? `${r.cable_color} ${r.cable_type}` : r.cable_type
    return [{
      req: { type: 'cable_identity', requirement_id: r.id },
      label: 'It is one cable: I checked',
      statement: `The ${cable} at the ${ends[0]} and at the ${ends[1]} is one and the same cable.`,
      detail: 'Only confirm if you have checked that a single cable joins both ports. No photo traced it end to end; the connection will be marked as relying on your statement.',
    }]
  }
  return []
}

/** One requirement's server verdict. Shown exactly as the policy produced it; nothing here upgrades a status. */
export function VerdictCard({ a, spec, onShowPhoto, onDeclare }: {
  a: RequirementAssessment; spec: InspectionSpec; onShowPhoto?: (seq: number) => void; onDeclare?: DeclareHandler
}) {
  const req = spec.requirements.find((r) => r.id === a.requirement_id)
  const multi = spec.requirements.length > 1
  const deviceName = (id: string) => spec.devices.find((d) => d.id === id)?.name ?? id
  const v = VERDICT[a.status]
  const Icon = v.icon
  const identityOk = a.identity_state === 'established' || a.identity_state === 'assumed_by_spec' || a.identity_state === 'declared_by_operator'
  const statements = a.operator_declarations ?? []
  return (
    <section aria-label={`Requirement ${a.requirement_id}${multi ? ` (${connectionName(req)})` : ''}`}
      className="animate-rise overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className={cn('flex items-start gap-3.5 border-b px-5 py-4', v.tint)}>
        <Icon className={cn('mt-0.5 h-7 w-7 shrink-0', v.text)} strokeWidth={2.1} aria-hidden />
        <div className="min-w-0">
          <p className={cn('text-xl font-semibold leading-tight tracking-[-0.01em]', v.text)}>{verdictText(a.status, a.assurance, !!spec.assisted)}</p>
          <p className="mt-0.5 text-sm text-fg-muted">{v.caption}</p>
          {a.assurance && a.status !== 'INSUFFICIENT_EVIDENCE' && (
            <p data-testid="assurance" className={cn('mt-1.5 text-[13px] font-medium',
              a.assurance === 'operator_assisted' ? 'text-accent' : a.assurance === 'spec_assumption' ? 'text-warn' : 'text-fg-muted')}>
              {ASSURANCE_TEXT[a.assurance]}
            </p>
          )}
        </div>
        <span className="ml-auto shrink-0 text-right text-xs leading-tight text-fg-subtle">
          {multi && <span className="block font-semibold text-fg-muted">{connectionName(req)}</span>}
          <span className="font-mono">{a.requirement_id}</span>
        </span>
      </div>

      <div className="px-5 pt-4">
        <p className="text-[15px] leading-relaxed text-fg">{req?.text ?? a.requirement_id}</p>

        <ul className="mt-4 divide-y divide-line rounded-[var(--radius-control)] border border-line">
          {a.endpoints.map((ep) => {
            const level = endpointLevel(ep)
            return (
              <li key={ep.index} className="flex items-center gap-3 px-3.5 py-3 text-sm">
                <StateIcon state={ep.state === 'established' ? 'ok' : ep.state === 'unknown' ? 'open' : 'bad'} />
                <span className="min-w-0 flex-1 text-fg">
                  {deviceName(ep.device_id)} {ep.port_label}
                  {level && (
                    <span data-testid="evidence-level" className={cn('mt-0.5 block text-xs leading-snug',
                      level.tone === 'ok' ? 'text-fg-subtle' : level.tone === 'accent' ? 'text-accent' : 'text-warn')}>{level.text}</span>
                  )}
                </span>
                <span className={cn('shrink-0 text-right text-[13px]', ep.state === 'established' ? 'text-ok' : ep.state === 'unknown' ? 'text-fg-subtle' : 'text-bad')}>
                  {ENDPOINT_STATE[ep.state] ?? ep.state}
                  {seqList(ep.support) && ` (photo ${seqList(ep.support)})`}
                </span>
              </li>
            )
          })}
          <li className="flex items-center gap-3 px-3.5 py-3 text-sm">
            <StateIcon state={identityOk ? 'ok' : 'open'} />
            <span className="min-w-0 flex-1 text-fg">Same cable at both ends</span>
            <span className={cn('shrink-0 text-right text-[13px]', a.identity_state === 'declared_by_operator' ? 'text-accent' : identityOk ? 'text-ok' : 'text-fg-subtle')}>
              {IDENTITY_TEXT[a.identity_state] ?? 'not yet established'}
            </span>
          </li>
        </ul>

        {a.status !== 'VERIFIED' && a.gaps.length > 0 && (
          <div className="mt-5">
            <CardTitle className="mb-2.5">{a.status === 'VIOLATED' ? 'Not observed (does not change this verdict)' : 'Missing evidence'}</CardTitle>
            <ul className="space-y-2.5 text-sm">
              {a.gaps.map((g) => (
                <li key={`${g.code}-${g.endpoint_index}`} className="flex gap-2.5">
                  <CircleDot className="mt-1 h-3.5 w-3.5 shrink-0 text-warn" aria-hidden />
                  <div className="min-w-0">
                    <p className="leading-relaxed text-fg-muted"><span className="font-semibold text-fg">{GAP_TEXT[g.code] ?? g.code}.</span> {g.missing_fact}</p>
                    {onDeclare && a.status === 'INSUFFICIENT_EVIDENCE' && declarations(g, spec).map((d) => (
                      <Button key={d.label} variant="secondary" size="sm" className="mt-2 h-auto whitespace-normal py-2 text-left"
                        onClick={() => (d.needsNote ? onDeclare(d.req, d.statement, d.detail, true) : onDeclare(d.req, d.statement, d.detail))}>
                        <UserCheck className="h-4 w-4 shrink-0" aria-hidden />{d.label}…
                      </Button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
        {a.status === 'VIOLATED' && (
          <p className="mt-5 rounded-[var(--radius-control)] border border-bad/20 bg-[#fff5f4] p-3.5 text-sm leading-relaxed text-fg">{a.explanation}</p>
        )}
        {statements.length > 0 && (
          <div data-testid="operator-statements" className="mt-5 rounded-[var(--radius-control)] border border-accent/20 bg-[#f3f8ff] p-3.5 text-sm">
            <p className="flex items-center gap-1.5 font-semibold text-accent"><UserCheck className="h-4 w-4" aria-hidden />Relies on your statements</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 leading-relaxed text-fg-muted">{statements.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}
        {a.assumptions.length > 0 && (
          <div className="mt-5 rounded-[var(--radius-control)] border border-warn/20 bg-[#fffaf2] p-3.5 text-sm">
            <p className="font-semibold text-warn">Relies on assumptions</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 leading-relaxed text-fg-muted">{a.assumptions.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}
      </div>

      <div className="mt-4 px-5">
        <EvidenceDetails a={a} spec={spec} onShowPhoto={onShowPhoto} />
        <Disclosure summary="Why (full explanation)">
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-fg-muted">{a.explanation}</p>
        </Disclosure>
      </div>
    </section>
  )
}

function sentence(s: string) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

/** The engine's current camera request, exactly as planned (Muse Spark or the deterministic fallback). */
export function GuidanceCard({ nv, spec }: { nv: NextViewRequest; spec?: InspectionSpec }) {
  const req = spec && spec.requirements.length > 1 ? spec.requirements.find((r) => r.id === nv.requirement_id) : undefined
  return (
    <section aria-label="Next photo"
      className="animate-rise overflow-hidden rounded-[var(--radius-panel)] border border-accent/20 bg-surface shadow-[var(--shadow-lift)]">
      <div className="brand-gradient h-1" aria-hidden />
      <div className="p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-accent">
            <Crosshair className="h-4 w-4" aria-hidden /> Next view
          </p>
          <Badge tone="accent"><Navigation aria-hidden /><span>{ACTION_TEXT[nv.camera_action] ?? nv.camera_action}</span></Badge>
        </div>
        {nv.target_region && (
          <h2 className="mt-3 text-lg font-semibold leading-snug tracking-[-0.01em] text-fg">Next: {sentence(nv.target_region)}</h2>
        )}
        <p className="mt-1.5 text-[17px] leading-snug text-fg" data-testid="instruction">{nv.instruction}</p>
        <p className="mt-3 flex gap-2 text-sm leading-relaxed text-fg-muted">
          <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
          <span><span className="font-semibold text-fg">Success when:</span> {nv.success_criteria}</span>
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
          {req ? (
            <p className="text-[13px] text-fg-muted">
              For <span className="font-mono">{req.id}</span> · {connectionName(req)}
            </p>
          ) : <span />}
          <details className="group">
            <summary className="inline-flex cursor-pointer items-center gap-1 text-[13px] text-fg-subtle hover:text-fg">
              Why this view <ChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-open:rotate-90" aria-hidden />
            </summary>
            <p className="mt-2 text-[13px] leading-relaxed text-fg-subtle">
              {nv.missing_fact} · Guidance {nv.planner === 'muse' ? 'planned by Muse Spark' : 'from a fixed template'} ·{' '}
              <span className="font-mono">{nv.id}</span>
            </p>
          </details>
        </div>
      </div>
    </section>
  )
}

/** Inspection progress across connections: each one's server verdict (or Pending before any photo), plus the
 * server's installation verdict. No percentages: the backend's assessments are the only source. */
export function ProgressPanel({ overall, assessments, spec }: {
  overall: OverallAssessment | null | undefined; assessments: RequirementAssessment[]; spec: InspectionSpec
}) {
  const by = new Map(assessments.map((a) => [a.requirement_id, a.status]))
  const status = (id: string) => by.get(id) ?? 'PENDING'
  const v = overall ? VERDICT[overall.status] : null
  const Icon = v?.icon ?? Clock3
  const name = (id: string) => spec.devices.find((d) => d.id === id)?.name ?? id
  const n = spec.requirements.length
  return (
    <section aria-label="Inspection summary" className="overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className={cn('flex items-center gap-3.5 border-b px-5 py-4', v ? v.tint : 'border-line bg-canvas')}>
        <Icon className={cn('h-6 w-6 shrink-0', v ? v.text : 'text-fg-subtle')} strokeWidth={2.1} aria-hidden />
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-fg-subtle">Installation</p>
          <p className={cn('text-lg font-semibold leading-tight', v ? v.text : 'text-fg')}>
            {overall ? verdictText(overall.status, overall.assurance, !!spec.assisted) : 'Pending'}
          </p>
        </div>
        <span className="ml-auto text-right text-[13px] font-medium text-fg-muted">{n} connections to inspect</span>
      </div>
      <ConnectionDiagram className="border-b border-line px-5 py-5" devices={spec.devices.map((d) => d.name)}
        links={spec.requirements.map((r) => ({ id: r.id, from: name(r.endpoints[0].device_id), to: name(r.endpoints[1].device_id),
          connector: r.connector ?? 'ethernet', status: status(r.id) }))} />
      <ul className="divide-y divide-line">
        {spec.requirements.map((r) => {
          const st = status(r.id)
          return (
            <li key={r.id} className="flex items-center gap-3 px-5 py-3 text-sm">
              <span className="w-7 shrink-0 font-mono text-xs text-fg-subtle">{r.id}</span>
              <span className="min-w-0 flex-1 font-medium text-fg">{connectionName(r)}</span>
              <span className={cn('rounded-full px-2.5 py-0.5 text-[13px] font-semibold',
                st === 'VERIFIED' ? 'bg-ok/10 text-ok' : st === 'VIOLATED' ? 'bg-bad/10 text-bad'
                  : st === 'INSUFFICIENT_EVIDENCE' ? 'bg-warn/10 text-warn' : 'bg-raised text-fg-muted')}>
                {PROGRESS_TEXT[st]}
              </span>
            </li>
          )
        })}
      </ul>
      <div className="space-y-1.5 border-t border-line bg-canvas/60 px-5 py-3.5 text-[13px] leading-relaxed text-fg-subtle">
        <p>Devices: {spec.devices.map((d) => d.name).join(' · ')}</p>
        {overall && overall.review_required.length > 0 && (
          <p className="font-medium text-bad">Contradictory evidence needs review: {overall.review_required.join(', ')}.</p>
        )}
        <p>The installation is verified only when every connection is verified; any violated connection makes it violated.</p>
      </div>
    </section>
  )
}

/** Shown instead of guidance when no photo is needed yet (first photo) or the guidance no longer applies. */
export function PromptCard({ title, children, label }: { title: string; children: React.ReactNode; label?: string }) {
  return (
    <section aria-label={label} className="animate-rise overflow-hidden rounded-[var(--radius-panel)] border border-accent/20 bg-surface shadow-[var(--shadow-lift)]">
      <div className="brand-gradient h-1" aria-hidden />
      <div className="p-5">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-accent">
          <ScanSearch className="h-4 w-4" aria-hidden /> {title}
        </p>
        <p className="mt-2.5 text-[17px] leading-snug text-fg">{children}</p>
      </div>
    </section>
  )
}

export function ReviewCard({ items, onDeclare, canDeclare }: { items: ReviewItem[]; onDeclare: () => void; canDeclare: boolean }) {
  return (
    <section role="alert" aria-label="Review required" className="rounded-[var(--radius-panel)] border border-bad/25 bg-[#fff6f5] p-5 shadow-[var(--shadow-card)]">
      <div className="flex items-center gap-2.5">
        <TriangleAlert className="h-5 w-5 text-bad" aria-hidden />
        <h2 className="text-[17px] font-semibold text-fg">Review the installation</h2>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-fg-muted">
        Some photos contradict each other. Taking another photo of the same setup will not fix this. Check the
        installation in person.
      </p>
      <div className="mt-3 space-y-3">
        {items.map((it) => (
          <div key={it.requirement_id} className="rounded-[var(--radius-control)] border border-line bg-surface p-3.5 text-sm">
            <p className="font-semibold text-fg">{it.requirement_id}: photos {it.photos.join(', ')} disagree.</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-fg-muted">
              {it.contradictions.map((c) => <li key={c} className="break-words">{c}</li>)}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-fg-muted">
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
    <section aria-label="Inspection stopped" className="flex gap-3.5 rounded-[var(--radius-panel)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-raised text-fg-muted">
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <div className="min-w-0 space-y-1">
        <h2 className="text-[17px] font-semibold text-fg">{t.title}</h2>
        <p className="text-sm leading-relaxed text-fg-muted">{t.detail}</p>
        {t.reopenable && reason !== 'contradiction_requires_review' && (
          <Button variant="ghost" size="sm" className="-ml-3.5 mt-1 h-auto whitespace-normal py-2 text-left text-accent hover:text-accent-strong" onClick={onDeclare}>
            The installation was changed — continue…
          </Button>
        )}
      </div>
    </section>
  )
}
