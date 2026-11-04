// View relevance vs evidence vs verdict on the last-photo card. The step is the recorded mocked-model fixture with a
// SYNTHETIC view_check / gap added here (shapes match backend ViewCheck; values are test data, not model output).

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { InspectionState, StepResponse, ViewCheck } from './api/types'
import { LastPhotoCard } from './components/Timeline'
import state from './test/fixtures/state_after_step1.json'
import step1 from './test/fixtures/step1_guidance.json'

const base = step1 as StepResponse
const vc = (over: Partial<ViewCheck>): ViewCheck => ({
  request_id: 'nv1', gap_key: 'R1:PORTS_NOT_VISIBLE:0', requirement_id: 'R1', status: 'captured',
  shown: ['the Wi-Fi Router', "the Wi-Fi Router's connection ports"], missing: [], identity_confirmed: true,
  unconfirmed_devices: [], counted_as_attempt: true, ...over,
})

function withGap(code: 'LABEL_ILLEGIBLE' | 'DEVICE_UNCONFIRMED'): StepResponse['assessments'] {
  return base.assessments.map((a) => ({ ...a, gaps: [{ ...a.gaps[0], code }] }))
}

function show(step: StepResponse) {
  render(<LastPhotoCard step={step} state={state as InspectionState} />)
}

describe('last photo result', () => {
  it('says the requested view was captured even when nothing was accepted and the port is unidentified', () => {
    show({ ...base, view_check: vc({}), assessments: withGap('LABEL_ILLEGIBLE'), notes: [] })
    expect(screen.getByText('Requested view captured')).toBeInTheDocument()
    expect(screen.getByText('0 evidence items accepted by the policy from this photo')).toBeInTheDocument()
    expect(screen.getByText('R1: connection still needs evidence')).toBeInTheDocument()
    expect(screen.getByText('Port identity could not be established')).toBeInTheDocument()
    expect(screen.queryByText(/not captured|did not show/i)).toBeNull()
  })

  it('separates an unconfirmed device identity from the view itself', () => {
    show({ ...base, view_check: vc({ identity_confirmed: false, unconfirmed_devices: ['Wi-Fi Router'] }),
      assessments: withGap('DEVICE_UNCONFIRMED') })
    expect(screen.getByText('Requested view captured')).toBeInTheDocument()
    expect(screen.getByText(/Wi-Fi Router not identified with certainty: not used as evidence/)).toBeInTheDocument()
  })

  it('reports partial and missed views from the server result only', () => {
    const { unmount } = render(<LastPhotoCard step={{ ...base, view_check: vc({ status: 'partial' }) }} state={state as InspectionState} />)
    expect(screen.getByText('Requested area partially visible')).toBeInTheDocument()
    unmount()
    show({ ...base, view_check: vc({ status: 'not_captured', shown: [], counted_as_attempt: false }) })
    expect(screen.getByText('Requested view not captured')).toBeInTheDocument()
  })

  it('shows no view row when no request was pending', () => {
    show({ ...base, view_check: null })
    expect(screen.queryByText(/Requested (view|area)/)).toBeNull()
  })
})
