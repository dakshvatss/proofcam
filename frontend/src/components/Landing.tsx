import { ArrowRight, Check, Crosshair, LoaderCircle, Scale, ScanSearch } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { SPEC_ID, api } from '../api/client'
import type { SpecSummary } from '../api/types'
import { CONNECTOR_TEXT, TEMPLATE_NAME, cn } from '../lib/utils'
import { ConnectionDiagram } from './ConnectionDiagram'
import { Button } from './ui/button'
import { CardTitle } from './ui/card'

// Shown if the server cannot list its specifications (older server, or the list failed): the default spec.
const FALLBACK: SpecSummary = {
  spec_id: SPEC_ID, title: 'Router to switch', devices: ['Router', 'Switch'],
  requirements: [{
    id: 'R1', text: 'The blue Ethernet cable must connect Router LAN 1 to Switch Port 3.', connector: 'ethernet',
    endpoints: [{ device: 'Router', port: 'LAN 1', flexible: false }, { device: 'Switch', port: '3', flexible: false }],
  }],
}

const PILLARS = [
  { icon: ScanSearch, name: 'Muse Spark 1.3', text: 'Reads each photo and plans the next camera view the inspection needs.' },
  { icon: Crosshair, name: 'SAM 3.1', text: 'Segments equipment and cables, grounding each claim in the image.' },
  { icon: Scale, name: 'Deterministic policy', text: 'Decides every verdict from evidence alone, and says what is still unproven.' },
]

function links(s: SpecSummary) {
  return s.requirements.flatMap((r) => r.endpoints && r.endpoints.length === 2
    ? [{ id: r.id, from: r.endpoints[0].device, to: r.endpoints[1].device, connector: r.connector }] : [])
}

export function Landing({ onStart, starting, message }: { onStart: (specId: string) => void; starting: boolean; message?: ReactNode }) {
  const [specs, setSpecs] = useState<SpecSummary[] | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    api.listSpecs().then((s) => live && setSpecs(s)).catch(() => live && setSpecs([]))
    return () => {
      live = false
    }
  }, [])
  const options = specs && specs.length ? specs : [FALLBACK]
  const selected = options.find((s) => s.spec_id === chosen) ?? options.find((s) => s.spec_id === SPEC_ID) ?? options[0]
  const n = selected.requirements.length
  const diagramLinks = links(selected)

  return (
    <div className="grid gap-10 pb-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-14 lg:pt-6">
      {/* ------------------------------------------------------------------ introduction */}
      <section className="pt-4 lg:pt-10">
        <p className="text-sm font-semibold text-accent">Visual proof for physical work.</p>
        <h1 className="mt-3 text-[2.15rem] font-semibold leading-[1.08] tracking-[-0.025em] text-fg sm:text-5xl">
          Every installation deserves <span className="brand-text">evidence.</span>
        </h1>
        <p className="mt-4 max-w-[38ch] text-[17px] leading-relaxed text-fg-muted">
          Point your camera. Follow intelligent guidance. Get an evidence-backed inspection.
        </p>
        <p className="mt-6 max-w-[46ch] text-[15px] leading-relaxed text-fg">
          ProofCam doesn't just answer questions about photographs. It actively asks for the photographs needed to
          establish a claim, then decides only from what they prove.
        </p>
        <ul className="mt-7 space-y-3">
          {PILLARS.map(({ icon: Icon, name, text }) => (
            <li key={name} className="flex gap-3.5">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                <Icon className="h-5 w-5" strokeWidth={1.9} aria-hidden />
              </span>
              <span className="text-sm leading-relaxed">
                <span className="block font-semibold text-fg">{name}</span>
                <span className="text-fg-muted">{text}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* ------------------------------------------------------------------ choose + set up */}
      <section className="space-y-5 lg:pt-10">
        {message}

        <fieldset>
          <legend className="mb-3"><CardTitle>Inspection templates</CardTitle></legend>
          <div role="radiogroup" className="grid gap-3">
            {options.map((s) => {
              const on = s.spec_id === selected.spec_id
              const name = TEMPLATE_NAME[s.spec_id] ?? s.title
              return (
                <button key={s.spec_id} type="button" role="radio" aria-checked={on} onClick={() => setChosen(s.spec_id)}
                  className={cn('group flex w-full items-start gap-3.5 rounded-[var(--radius-panel)] border bg-surface p-4 text-left',
                    'shadow-[var(--shadow-card)] transition-[border-color,box-shadow] duration-200',
                    on ? 'border-accent shadow-[0_0_0_3px_rgb(8_102_255/0.12)]' : 'border-line hover:border-line-strong')}>
                  <span aria-hidden className={cn('mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border-2 transition-colors',
                    on ? 'border-accent bg-accent text-white' : 'border-line-strong')}>
                    {on && <Check className="h-3 w-3" strokeWidth={3.5} />}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-fg">{name}</span>
                    {name !== s.title && <span className="mt-0.5 block text-[13px] text-fg-muted">{s.title}</span>}
                    <span className="mt-1.5 block text-[13px] text-fg-subtle">
                      {s.devices.length} devices · {s.requirements.length} {s.requirements.length === 1 ? 'connection' : 'connections'}
                      {' · '}{s.requirements.map((r) => CONNECTOR_TEXT[r.connector] ?? r.connector).join(' + ')}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        </fieldset>

        <section aria-label="Inspection setup"
          className="overflow-hidden rounded-[var(--radius-panel)] border border-line bg-surface shadow-[var(--shadow-lift)]">
          <div className="border-b border-line px-5 py-4">
            <p className="text-[15px] font-semibold text-fg">
              One inspection · {n} {n === 1 ? 'connection' : 'connections'} to prove
            </p>
            <p className="mt-0.5 text-[13px] text-fg-subtle">
              Devices: {selected.devices.join(' · ')}{selected.max_photos ? ` · up to ${selected.max_photos} photos` : ''}
            </p>
          </div>
          {diagramLinks.length === n && (
            <ConnectionDiagram devices={selected.devices} links={diagramLinks} className="border-b border-line bg-canvas/60 px-5 py-5" />
          )}
          <ol className="divide-y divide-line">
            {selected.requirements.map((r, i) => (
              <li key={r.id} className="flex gap-3.5 px-5 py-3.5">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-strong">
                  {i + 1}
                </span>
                <p className="text-[15px] leading-relaxed text-fg">{r.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <div className="space-y-3">
          <Button size="lg" onClick={() => onStart(selected.spec_id)} disabled={starting} className="w-full">
            {starting ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden /> : null}
            Start inspection
            {!starting && <ArrowRight className="h-5 w-5" aria-hidden />}
          </Button>
          <p className="text-xs leading-relaxed text-fg-subtle">
            Photos are analysed by Meta Muse Spark 1.3 and SAM 3.1 on the server. ProofCam verifies visually observable
            conditions only; it does not certify electrical safety, operational connectivity or regulatory compliance.
          </p>
        </div>
      </section>
    </div>
  )
}
