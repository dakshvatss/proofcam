// M3.8 operator-assisted Home Entertainment presentation. Assessments are SYNTHETIC test data shaped like the
// backend's RequirementAssessment (not model output).

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { EvidenceItem, InspectionSpec, RequirementAssessment } from './api/types'
import { ProgressPanel, VerdictCard } from './components/Evidence'
import { verdictText } from './lib/utils'

const SPEC: InspectionSpec = {
  id: 'ps5_home_setup_assisted_v1', title: 'Home Entertainment Installation (operator-assisted)',
  assisted: { max_attempts_per_gap: 1 },
  devices: [
    { id: 'ps5', name: 'PlayStation 5', description: '', sam_concept: 'game console' },
    { id: 'tv', name: 'Samsung Television', description: '', sam_concept: 'television' },
  ],
  requirements: [{
    id: 'R2', kind: 'connection', text: 'PS5 HDMI OUT to a TV HDMI input.', cable_color: null, cable_type: 'hdmi cable',
    connector: 'hdmi', cable_identity: 'trace_or_operator_declaration',
    endpoints: [{ device_id: 'ps5', port_label: 'HDMI OUT port', label_aliases: [] },
      { device_id: 'tv', port_label: 'any HDMI input', label_aliases: [] }],
  }],
}
const STRICT: InspectionSpec = { ...SPEC, id: 'ps5_home_setup_v1', assisted: null }
const item = (seq: number, over: Partial<EvidenceItem> = {}): EvidenceItem => ({ seq, image_id: `img_${seq}`, claim: `c${seq}`, ...over })

function a(over: Partial<RequirementAssessment>): RequirementAssessment {
  return {
    requirement_id: 'R2', status: 'INSUFFICIENT_EVIDENCE', explanation: 't', identity_state: 'unknown',
    identity_evidence: [], gaps: [], contradictions: [], assumptions: [],
    endpoints: [
      { index: 0, device_id: 'ps5', port_label: 'HDMI OUT port', state: 'unknown', support: [], conflicts: [], inferred_only: [], gap: null },
      { index: 1, device_id: 'tv', port_label: 'any HDMI input', state: 'unknown', support: [], conflicts: [], inferred_only: [], gap: null },
    ],
    ...over,
  }
}

describe('assisted verdict labels', () => {
  it('names the provenance of VERIFIED only on the assisted template', () => {
    expect(verdictText('VERIFIED', 'operator_assisted', true)).toBe('Verified — operator-assisted')
    expect(verdictText('VERIFIED', 'visual', true)).toBe('Verified — visual evidence')
    expect(verdictText('VERIFIED', 'spec_assumption', true)).toBe('Verified — visual evidence')
    expect(verdictText('VERIFIED', 'operator_assisted', false)).toBe('Verified')
    expect(verdictText('INSUFFICIENT_EVIDENCE', null, true)).toBe('Not enough evidence')
  })

  it('shows VERIFIED — OPERATOR-ASSISTED on the card and the installation summary', () => {
    const v = a({ status: 'VERIFIED', identity_state: 'declared_by_operator', assurance: 'operator_assisted',
      operator_declarations: ['You confirmed the HDMI plug.'] })
    v.endpoints = v.endpoints.map((ep) => ({ ...ep, state: 'established' as const,
      support: [item(2, ep.index === 0 ? { insertion_basis: 'operator_confirmed' } : {})] }))
    render(<VerdictCard a={v} spec={SPEC} />)
    expect(screen.getByText('Verified — operator-assisted')).toBeInTheDocument()
    expect(screen.getAllByTestId('evidence-level')[0]).toHaveTextContent('plug confirmed by you (SAM did not corroborate)')
    render(<ProgressPanel spec={SPEC} assessments={[v]} overall={{ status: 'VERIFIED', explanation: '', requirement_statuses: { R2: 'VERIFIED' },
      review_required: [], assurance: 'operator_assisted' }} />)
    expect(screen.getAllByText('Verified — operator-assisted').length).toBe(2)
  })

  it('keeps the strict template wording unchanged', () => {
    const v = a({ status: 'VERIFIED', identity_state: 'established', assurance: 'visual' })
    render(<VerdictCard a={v} spec={STRICT} />)
    expect(screen.getByText('Verified')).toBeInTheDocument()
    expect(screen.queryByText(/Verified —/)).toBeNull()
  })
})

describe('confirming a plug SAM missed', () => {
  it('offers the confirmation only where the server permits it', () => {
    const gap = { requirement_id: 'R2', code: 'GROUNDING_MISSING' as const, endpoint_index: 0, target: 'ps5', missing_fact: 'm',
      context: { muse_only_photos: [5], declaration_permitted: true } }
    const onDeclare = vi.fn()
    const { unmount } = render(<VerdictCard a={a({ gaps: [{ ...gap, context: { declaration_permitted: false } }] })} spec={SPEC} onDeclare={onDeclare} />)
    expect(screen.queryByRole('button', { name: /plug is seated/ })).toBeNull()
    unmount()
    render(<VerdictCard a={a({ gaps: [gap] })} spec={SPEC} onDeclare={onDeclare} />)
    fireEvent.click(screen.getByRole('button', { name: /The plug is seated: I checked/ }))
    expect(onDeclare).toHaveBeenCalledWith({ type: 'endpoint_insertion', requirement_id: 'R2', endpoint_index: 0 },
      'The HDMI plug Muse saw at the PlayStation 5 HDMI OUT port is fully seated in that port.', expect.stringContaining('SAM did not corroborate'))
  })
})
