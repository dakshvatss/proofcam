// Written attestation for an end the photos could not establish. Assessments are SYNTHETIC test data.

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { InspectionSpec, RequirementAssessment } from './api/types'
import { DeclareDialog } from './components/Dialogs'
import { VerdictCard } from './components/Evidence'
import { verdictText } from './lib/utils'

const SPEC: InspectionSpec = {
  id: 'ps5_home_setup_assisted_v2', title: 'Home Entertainment Installation (operator-assisted)', assisted: {},
  devices: [{ id: 'ps5', name: 'PlayStation 5', description: '', sam_concept: 'game console' },
    { id: 'tv', name: 'Television', description: '', sam_concept: 'television' }],
  requirements: [{ id: 'R2', kind: 'connection', text: 'PS5 to TV', cable_color: null, cable_type: 'hdmi cable', connector: 'hdmi',
    cable_identity: 'trace_or_operator_declaration',
    endpoints: [{ device_id: 'ps5', port_label: 'HDMI OUT port', label_aliases: [] }, { device_id: 'tv', port_label: 'any HDMI input', label_aliases: [] }] }],
}
const base = (over: Partial<RequirementAssessment>): RequirementAssessment => ({
  requirement_id: 'R2', status: 'INSUFFICIENT_EVIDENCE', explanation: 't', identity_state: 'unknown', identity_evidence: [],
  gaps: [], contradictions: [], assumptions: [],
  endpoints: [
    { index: 0, device_id: 'ps5', port_label: 'HDMI OUT port', state: 'unknown', support: [], conflicts: [], inferred_only: [], gap: null },
    { index: 1, device_id: 'tv', port_label: 'any HDMI input', state: 'unknown', support: [], conflicts: [], inferred_only: [], gap: null },
  ], ...over,
})

describe('written attestation', () => {
  it('is offered only where the server permits it, and asks for a note', () => {
    const gap = { requirement_id: 'R2', code: 'PORTS_NOT_VISIBLE' as const, endpoint_index: 1, target: 'tv', missing_fact: 'm', context: {} }
    const onDeclare = vi.fn()
    const { unmount } = render(<VerdictCard a={base({ gaps: [gap] })} spec={SPEC} onDeclare={onDeclare} />)
    expect(screen.queryByRole('button', { name: /I checked this end myself/ })).toBeNull()
    unmount()
    render(<VerdictCard a={base({ gaps: [{ ...gap, context: { attestation_permitted: true } }] })} spec={SPEC} onDeclare={onDeclare} />)
    fireEvent.click(screen.getByRole('button', { name: /I checked this end myself/ }))
    expect(onDeclare).toHaveBeenCalledWith({ type: 'endpoint_attestation', requirement_id: 'R2', endpoint_index: 1 },
      'I checked the Television any HDMI input end myself.', expect.stringContaining('operator-attested'), true)
  })

  it('cannot be confirmed without a real note, and sends the note', async () => {
    const onConfirm = vi.fn(async () => true)
    render(<DeclareDialog statement="s" detail="d" needsNote onCancel={vi.fn()} onConfirm={onConfirm} />)
    const ok = screen.getByRole('button', { name: 'I confirm' })
    expect(ok).toBeDisabled()
    fireEvent.change(screen.getByLabelText('What did you check yourself?'), { target: { value: 'HDMI cable pushed fully into the TV.' } })
    expect(ok).toBeEnabled()
    fireEvent.click(ok)
    await vi.waitFor(() => expect(onConfirm).toHaveBeenCalledWith('HDMI cable pushed fully into the TV.'))
  })

  it('labels an attested verdict as such and never as photo evidence', () => {
    expect(verdictText('VERIFIED', 'operator_attested', true)).toBe('Verified — operator-attested')
    const a = base({ status: 'VERIFIED', assurance: 'operator_attested', identity_state: 'declared_by_operator' })
    a.endpoints = a.endpoints.map((ep) => ({ ...ep, state: 'established' as const,
      support: [ep.index === 1 ? { seq: 0, image_id: 'operator_attestation', claim: 'attested', attested: true } : { seq: 2, image_id: 'img_2', claim: 'c' }] }))
    render(<VerdictCard a={a} spec={SPEC} />)
    expect(screen.getByText('Verified — operator-attested')).toBeInTheDocument()
    expect(screen.getAllByTestId('evidence-level')[1]).toHaveTextContent('attested by you in writing · no photo evidence')
    expect(screen.queryByText(/photo 0/)).toBeNull()
  })
})
