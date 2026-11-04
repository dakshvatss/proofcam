import { ArrowLeft, Braces, Download, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, reportJsonUrl } from '../api/client'
import type { InspectionState, RequirementAssessment } from '../api/types'
import { ASSURANCE_TEXT, GAP_TEXT, IDENTITY_TEXT, STATUS_TEXT, TEMPLATE_NAME, cn, connectionName } from '../lib/utils'
import { VERDICT } from '../lib/verdict'
import { VerdictBadge } from './Evidence'
import { Button } from './ui/button'
import { CardTitle } from './ui/card'
import { Callout } from './ui/callout'

// Element styles for the server's Markdown report (raw HTML in the Markdown is not rendered).
const MD: Components = {
  h1: (p) => <h1 className="mb-4 text-xl font-semibold leading-snug tracking-[-0.01em] text-fg" {...p} />,
  h2: (p) => <h2 className="mb-2 mt-8 border-b border-line pb-2 text-xs font-semibold uppercase tracking-[0.08em] text-fg-subtle" {...p} />,
  h3: (p) => <h3 className="mb-1 mt-5 font-semibold text-fg" {...p} />,
  p: (p) => <p className="my-2.5 leading-relaxed" {...p} />,
  strong: (p) => <strong className="font-semibold text-fg" {...p} />,
  ul: (p) => <ul className="my-2.5 list-disc space-y-1.5 pl-5 marker:text-fg-subtle" {...p} />,
  ol: (p) => <ol className="my-2.5 list-decimal space-y-1.5 pl-5 marker:text-fg-subtle" {...p} />,
  a: ({ href, ...p }) => <a href={href} target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2" {...p} />,
  code: (p) => <code className="break-words rounded bg-raised px-1 py-0.5 font-mono text-[0.85em] text-fg" {...p} />,
  pre: (p) => <pre className="my-3 overflow-x-auto rounded-[var(--radius-control)] border border-line bg-canvas p-3 text-xs" {...p} />,
  blockquote: (p) => <blockquote className="my-3 border-l-2 border-warn/60 pl-3 text-fg-muted" {...p} />,
  table: (p) => (
    <div className="my-4 overflow-x-auto rounded-[var(--radius-control)] border border-line">
      <table className="w-full border-collapse text-left text-xs" {...p} />
    </div>
  ),
  thead: (p) => <thead className="bg-raised" {...p} />,
  th: (p) => <th className="border-b border-line px-3 py-2 font-semibold text-fg" {...p} />,
  td: (p) => <td className="border-b border-line/70 px-3 py-2 align-top" {...p} />,
  img: ({ src, alt }) => <img src={typeof src === 'string' ? src : undefined} alt={alt ?? ''} className="my-3 max-w-full rounded-[var(--radius-control)] border border-line" />,
  hr: () => <hr className="my-6 border-line" />,
}

const SOURCE: Record<string, string> = { live: 'Live: Meta Muse Spark 1.3 + SAM 3.1', mock: 'Mock: scripted test data', replay: 'Replay: recorded model output' }

function when(ts: number | null | undefined) {
  return ts ? new Date(ts * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

/** Claims and the photographs that support them, per requirement, from the server's assessment. */
function RequirementSummary({ a, st }: { a: RequirementAssessment; st: InspectionState }) {
  const req = st.spec.requirements.find((r) => r.id === a.requirement_id)
  const device = (id: string) => st.spec.devices.find((d) => d.id === id)?.name ?? id
  const photo = (seq: number) => st.photos.find((p) => p.seq === seq)
  // A violated requirement leads with what ruled it out; otherwise the photos that support it.
  const against = a.status === 'VIOLATED'
    ? a.endpoints.flatMap((ep) => ep.conflicts.map((x) => ({ seq: x.seq, label: `${device(ep.device_id)} ${ep.port_label}`, claim: x.claim, tone: 'against' as const })))
    : []
  const claims = [
    ...against,
    ...a.endpoints.flatMap((ep) => ep.support.map((x) => ({ seq: x.seq, label: `${device(ep.device_id)} ${ep.port_label}`, claim: x.claim, tone: 'for' as const }))),
    ...a.identity_evidence.map((x) => ({ seq: x.seq, label: 'Same cable at both ends', claim: x.claim, tone: 'for' as const })),
  ]
  const statements = a.operator_declarations ?? []
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-fg-muted">
          <span className="font-mono">{a.requirement_id}</span>{st.spec.requirements.length > 1 && ` · ${connectionName(req)}`}
        </p>
        <VerdictBadge status={a.status} />
      </div>
      <p className="mt-2 text-[15px] leading-relaxed text-fg">{req?.text}</p>
      {a.assurance && a.status !== 'INSUFFICIENT_EVIDENCE' && (
        <p className={cn('mt-1.5 text-[13px] font-medium', a.assurance === 'operator_assisted' ? 'text-accent' : a.assurance === 'spec_assumption' ? 'text-warn' : 'text-fg-muted')}>
          {ASSURANCE_TEXT[a.assurance]}
        </p>
      )}
      <p className="mt-1.5 text-[13px] text-fg-muted">Same cable at both ends: {IDENTITY_TEXT[a.identity_state] ?? 'not established'}</p>
      {claims.length > 0 && (
        <ul className="mt-4 space-y-3">
          {claims.map((c, i) => {
            const p = photo(c.seq)
            return (
              <li key={i} className="flex gap-3">
                {p && <img src={p.overlay_url ?? p.photo_url} alt={`Photo ${c.seq}`} className="h-14 w-[74px] shrink-0 rounded-lg border border-line bg-viewport object-cover" />}
                <div className="min-w-0 text-[13px] leading-relaxed">
                  <p className="font-semibold text-fg">{c.label} <span className={cn('font-normal', c.tone === 'for' ? 'text-ok' : 'text-bad')}>· {c.tone === 'for' ? 'supported' : 'ruled out'} by photo {c.seq}</span></p>
                  <p className="break-words text-fg-muted">{c.claim}</p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {statements.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-accent">
          {statements.map((x) => <li key={x}>Relies on your statement: {x}</li>)}
        </ul>
      )}
      {a.status !== 'VERIFIED' && a.gaps.length > 0 && (
        <ul className="mt-4 space-y-1.5 border-t border-line pt-3 text-[13px] leading-relaxed text-fg-muted">
          {a.status === 'VIOLATED' && <li className="font-semibold text-fg-subtle">Not observed (does not change this verdict):</li>}
          {a.gaps.map((g) => <li key={`${g.code}-${g.endpoint_index}`}><span className="font-semibold text-warn">{GAP_TEXT[g.code] ?? g.code}:</span> {g.missing_fact}</li>)}
        </ul>
      )}
      {a.contradictions.length > 0 && (
        <p className="mt-3 flex gap-2 text-[13px] text-bad"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />Contradictory evidence: review required.</p>
      )}
      {a.assumptions.length > 0 && <p className="mt-3 text-[13px] text-warn">Relies on {a.assumptions.length} disclosed {a.assumptions.length === 1 ? 'assumption' : 'assumptions'} (see the audit record).</p>}
    </section>
  )
}

/** Supervisor-facing summary of the inspection plus the saved audit record exactly as the server wrote it. */
export function ReportView({ state: st, modelSource, onBack }: { state: InspectionState; modelSource: string | null; onBack: () => void }) {
  const [md, setMd] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [generated] = useState(() => Date.now() / 1000)
  useEffect(() => {
    let live = true
    api.reportMarkdown(st.id)
      .then((t) => live && setMd(t))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [st.id])

  const download = () => {
    if (md === null) return
    const url = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `proofcam-${st.id}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const single = st.assessments.length === 1 ? st.assessments[0].status : null
  const status = st.overall?.status ?? single
  const v = status ? VERDICT[status] : null
  const Icon = v?.icon
  const facts: [string, string][] = [
    ['Inspection', st.id],
    ['Started', when(st.created_at)],
    ['Summary generated', when(generated)],
    ['Photos', `${st.photos.length}${st.spec.max_photos ? ` of up to ${st.spec.max_photos}` : ''}`],
    ['Model source', modelSource ? (SOURCE[modelSource] ?? modelSource) : 'unknown'],
    ['Model calls', `${st.usage.model_calls} · est. $${st.usage.estimated_cost_usd.toFixed(3)}`],
  ]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" size="sm" className="-ml-3" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Back to inspection</Button>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={download} disabled={md === null}><Download className="h-4 w-4" /> Download</Button>
          <a href={reportJsonUrl(st.id)} target="_blank" rel="noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-control)] border border-line-strong bg-surface px-3.5 text-[13px] font-medium text-fg shadow-[var(--shadow-card)] transition-colors duration-150 hover:bg-raised">
            <Braces className="h-4 w-4" aria-hidden /> JSON
          </a>
        </div>
      </div>

      <section className="overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface shadow-[var(--shadow-lift)]">
        <div className="brand-gradient h-1" aria-hidden />
        <div className="p-5 sm:p-6">
          <p className="text-sm font-semibold text-accent">
            Inspection report{st.spec_id && TEMPLATE_NAME[st.spec_id] && TEMPLATE_NAME[st.spec_id] !== st.title ? ` · ${TEMPLATE_NAME[st.spec_id]}` : ''}
          </p>
          <h2 className="mt-1 text-xl font-semibold leading-snug tracking-[-0.01em] text-fg">{st.title}</h2>
          <div className={cn('mt-4 flex items-center gap-3 rounded-[var(--radius-control)] border px-4 py-3', v ? v.tint : 'border-line bg-canvas')}>
            {Icon && <Icon className={cn('h-6 w-6 shrink-0', v!.text)} strokeWidth={2.1} aria-hidden />}
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-fg-subtle">Overall verdict</p>
              <p className={cn('text-lg font-semibold', v ? v.text : 'text-fg')}>{status ? STATUS_TEXT[status] : 'No photos analysed yet'}</p>
            </div>
          </div>
          {st.overall && <p className="mt-2 text-[13px] leading-relaxed text-fg-muted">{st.overall.explanation}</p>}
          <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-[13px] sm:grid-cols-3">
            {facts.map(([k, val]) => (
              <div key={k} className="min-w-0">
                <dt className="text-fg-subtle">{k}</dt>
                <dd className={cn('font-medium text-fg', k === 'Inspection' ? 'truncate font-mono text-xs leading-5' : 'break-words')} title={val}>{val}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {st.review_required.length > 0 && (
        <Callout tone="error" title="Review required">
          {st.review_required.map((r) => `${r.requirement_id}: photos ${r.photos.join(', ')} disagree.`).join(' ')}
        </Callout>
      )}

      {st.assessments.length > 0 && (
        <div className="space-y-4">
          <CardTitle>Requirements and supporting photographs</CardTitle>
          {st.assessments.map((a) => <RequirementSummary key={a.requirement_id} a={a} st={st} />)}
        </div>
      )}

      <p className="px-1 text-xs leading-relaxed text-fg-subtle">{st.disclaimer} This report is not a legal certification.</p>

      <div className="space-y-3">
        <CardTitle>Full audit record</CardTitle>
        <article aria-label="Saved report" className="rounded-[var(--radius-panel)] border border-line bg-surface px-5 py-6 text-sm text-fg-muted shadow-[var(--shadow-card)] sm:px-7">
          {error ? <Callout tone="error" title="Could not load the report">{error}</Callout>
            : md === null ? <p className="flex items-center gap-2 text-fg-subtle"><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Loading report…</p>
            : <Markdown remarkPlugins={[remarkGfm]} components={MD}>{md}</Markdown>}
        </article>
      </div>
    </div>
  )
}
