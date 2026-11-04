// M3.7 evidence levels, operator statements and inspection limits. Assessments here are SYNTHETIC test data shaped
// like the backend's RequirementAssessment (values are not model output); the inspection state is the recorded
// mocked-model fixture with usage figures changed per test.

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { EvidenceItem, InspectionSpec, InspectionState, RequirementAssessment } from './api/types'
import { DeclareDialog } from './components/Dialogs'
import { VerdictCard } from './components/Evidence'
import { InspectionView } from './components/InspectionView'
import type { InspectionSession } from './state/useInspection'
import state from './test/fixtures/state_after_step1.json'

const SPEC: InspectionSpec = {
  id: 'home', title: 'Home Entertainment Installation', max_photos: 12, allow_device_identity_declarations: true,
  devices: [
    { id: 'ps5', name: 'PlayStation 5', description: '', sam_concept: 'game console' },
    { id: 'tv', name: 'Samsung Television', description: '', sam_concept: 'television' },
  ],
  requirements: [{
    id: 'R2', kind: 'connection', text: 'Connect the PS5 HDMI OUT port to any HDMI input on the TV.', cable_color: null,
    cable_type: 'hdmi cable', connector: 'hdmi', cable_identity: 'trace_or_operator_declaration',
    endpoints: [{ device_id: 'ps5', port_label: 'HDMI OUT port', label_aliases: [] },
      { device_id: 'tv', port_label: 'any HDMI input', label_aliases: [] }],
  }],
}

const item = (seq: number, over: Partial<EvidenceItem> = {}): EvidenceItem => ({ seq, image_id: `img_${seq}`, claim: `claim ${seq}`, ...over })

function assessment(over: Partial<RequirementAssessment>): RequirementAssessment {
  return {
    requirement_id: 'R2', status: 'INSUFFICIENT_EVIDENCE', explanation: 'test', identity_state: 'unknown',
    identity_evidence: [], gaps: [], contradictions: [], assumptions: [],
    endpoints: [
      { index: 0, device_id: 'ps5', port_label: 'HDMI OUT port', state: 'unknown', support: [], conflicts: [], inferred_only: [], gap: null },
      { index: 1, device_id: 'tv', port_label: 'any HDMI input', state: 'unknown', support: [], conflicts: [], inferred_only: [], gap: null },
    ],
    ...over,
  }
}

describe('evidence levels on a connection', () => {
  it('shows a plug seen by Muse only, never as confirmed', () => {
    const a = assessment({})
    a.endpoints[0] = { ...a.endpoints[0], candidates: [item(5), item(6)] }
    render(<VerdictCard a={a} spec={SPEC} />)
    expect(screen.getByText('seen by Muse only (photo 5, 6) · SAM did not corroborate it')).toBeInTheDocument()
    expect(screen.queryByText(/^confirmed/)).toBeNull()
  })

  it('marks an operator-assisted verdict and lists the statements it relies on', () => {
    const a = assessment({
      status: 'VERIFIED', identity_state: 'declared_by_operator', assurance: 'operator_assisted',
      operator_declarations: ['You confirmed that the device in photo 8 is the Samsung Television.'],
    })
    a.endpoints = a.endpoints.map((ep, i) => ({ ...ep, state: 'established' as const,
      support: [item(5 + i * 3, i === 1 ? { device_basis: 'operator_declared' } : {})] }))
    render(<VerdictCard a={a} spec={SPEC} />)
    expect(screen.getByTestId('assurance')).toHaveTextContent('Relies on your statements: not independently verified')
    expect(screen.getByText('declared by you · not traced')).toBeInTheDocument()
    expect(screen.getAllByTestId('evidence-level').map((e) => e.textContent))
      .toEqual(['seen by Muse · grounded by SAM', 'device confirmed by you'])
    expect(screen.getByTestId('operator-statements')).toHaveTextContent('photo 8 is the Samsung Television')
  })

  it('offers a statement only where the server says the spec permits it', () => {
    const gap = { requirement_id: 'R2', code: 'DEVICE_UNCONFIRMED' as const, endpoint_index: 1, target: 'tv', missing_fact: 'identity',
      context: { unconfirmed_port_photos: [8], declaration_permitted: false } }
    const onDeclare = vi.fn()
    const { unmount } = render(<VerdictCard a={assessment({ gaps: [gap] })} spec={SPEC} onDeclare={onDeclare} />)
    expect(screen.queryByRole('button', { name: /Photo 8 shows/ })).toBeNull()
    unmount()
    render(<VerdictCard a={assessment({ gaps: [{ ...gap, context: { ...gap.context, declaration_permitted: true } }] })}
      spec={SPEC} onDeclare={onDeclare} />)
    fireEvent.click(screen.getByRole('button', { name: /Photo 8 shows the Samsung Television/ }))
    expect(onDeclare).toHaveBeenCalledWith({ type: 'device_identity', seq: 8, device_id: 'tv' },
      'Photo 8 shows the Samsung Television.', expect.stringContaining('Only confirm'))
  })

  it('leads a violated connection with the evidence that ruled it out', () => {
    const gap = { requirement_id: 'R2', code: 'DEVICE_NOT_SEEN' as const, endpoint_index: 1, target: 'tv', missing_fact: 'not seen', context: {} }
    render(<VerdictCard a={assessment({ status: 'VIOLATED', assurance: 'visual', gaps: [gap] })} spec={SPEC} />)
    expect(screen.getByText('Not observed (does not change this verdict)')).toBeInTheDocument()
    expect(screen.getByTestId('assurance')).toHaveTextContent('Rests on the photos alone')
  })

  it('records a statement only after an explicit confirmation', async () => {
    const onConfirm = vi.fn(async () => true)
    const onCancel = vi.fn()
    render(<DeclareDialog statement="Photo 8 shows the Samsung Television." detail="d" onCancel={onCancel} onConfirm={onConfirm} />)
    expect(screen.getByText('“Photo 8 shows the Samsung Television.”')).toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'I confirm' }))
    await vi.waitFor(() => expect(onCancel).toHaveBeenCalled())
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })
})

function session(usage: Partial<InspectionState['usage']>): InspectionSession {
  const st = state as InspectionState
  return {
    inspection: { ...st, usage: { ...st.usage, ...usage } }, lastStep: null, phase: 'ready', pending: null, notice: null,
    uploadStartedAt: null, start: vi.fn(), load: vi.fn(), leave: vi.fn(), stagePhoto: vi.fn(), discardPhoto: vi.fn(),
    sendPhoto: vi.fn(), declareChange: vi.fn(), declare: vi.fn(),
  } as unknown as InspectionSession
}

describe('inspection limits', () => {
  it('turns the camera off with an explanation when too few model calls remain for a photo', () => {
    render(<InspectionView s={session({ remaining: 1, model_calls: 39, photo_min_calls: 2, photos_used: 1, max_photos: 12 })} onReport={() => {}} />)
    expect(screen.getByText('Model-call limit reached')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open camera/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Upload photo' })).toBeDisabled()
  })

  it('warns before the photo or call budget runs out, with the server figures', () => {
    render(<InspectionView s={session({ remaining: 20, photo_min_calls: 2, photos_used: 10, max_photos: 12 })} onReport={() => {}} />)
    expect(screen.getByText("Approaching this inspection's limits")).toBeInTheDocument()
    expect(screen.getByText(/2 of 12 photos and 20 of 40 model\s+calls left/)).toBeInTheDocument()
  })
})
