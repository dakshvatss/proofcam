// M3.4: one inspection with three devices and two connection requirements (Ethernet + HDMI). The state fixture was
// recorded from the real FastAPI app with MOCKED Meta models and a synthetic test spec (not real hardware).

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import type { InspectionState } from './api/types'
import { STORAGE_KEY } from './state/useInspection'
import created from './test/fixtures/created.json'
import stateMulti from './test/fixtures/state_multi.json'
import stateVerified from './test/fixtures/state_verified.json'
import { access, installApi, json } from './test/mockApi'

const multi = stateMulti as InspectionState
const inspectionPath = (id: string) => new RegExp(`/api/inspections/${id}$`)

const SPECS = [
  { spec_id: 'my_setup', title: 'Router to switch', devices: ['Router', 'Switch'],
    requirements: [{ id: 'R1', text: 'The blue Ethernet cable must connect Router LAN 1 to Switch Port 3.', connector: 'ethernet' }] },
  { spec_id: 'home_test', title: 'Home Entertainment Installation', devices: ['Test Router', 'Test Console', 'Test TV'],
    requirements: [{ id: 'R1', text: 'Ethernet requirement text', connector: 'ethernet' },
                   { id: 'R2', text: 'HDMI requirement text', connector: 'hdmi' }] },
]

describe('choosing a specification', () => {
  it('lists the server specs and starts the chosen one', async () => {
    const api = installApi([
      access(),
      { method: 'GET', match: /\/api\/specs$/, reply: () => json(SPECS) },
      { method: 'POST', match: /\/api\/inspections$/, reply: () => json(multi, 201) },
      { method: 'GET', match: inspectionPath(multi.id), reply: () => json(multi) },
    ])
    const user = userEvent.setup()
    render(<App />)
    const group = await screen.findByRole('radiogroup')
    expect(within(group).getByRole('radio', { name: /router to switch/i })).toHaveAttribute('aria-checked', 'true')
    await user.click(within(group).getByRole('radio', { name: /home entertainment installation/i }))
    expect(screen.getByText('HDMI requirement text')).toBeInTheDocument()
    expect(screen.getByText(/Test Router · Test Console · Test TV/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /start inspection/i }))
    await screen.findByRole('heading', { name: multi.title })
    const post = api.calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(post.body as string)).toEqual({ spec_id: 'home_test' })
  })
})

describe('three devices, two connections', () => {
  it('shows the server overall verdict, each connection, and guidance for the unresolved one', async () => {
    localStorage.setItem(STORAGE_KEY, multi.id)
    installApi([access(), { method: 'GET', match: inspectionPath(multi.id), reply: () => json(multi) }])
    render(<App />)
    const summary = await screen.findByLabelText('Inspection summary')
    expect(multi.overall?.status).toBe('INSUFFICIENT_EVIDENCE')
    expect(within(summary).getAllByText('Not enough evidence').length).toBeGreaterThan(0)
    expect(within(summary).getByText('Ethernet connection')).toBeInTheDocument()
    expect(within(summary).getByText('HDMI connection')).toBeInTheDocument()
    expect(within(summary).getByText('Verified')).toBeInTheDocument() // R1 only
    expect(within(summary).getByText(/Test Router · Test Console · Test TV/)).toBeInTheDocument()

    // each requirement keeps its own card and its own evidence
    const r1 = screen.getByLabelText('Requirement R1 (Ethernet connection)')
    const r2 = screen.getByLabelText('Requirement R2 (HDMI connection)')
    expect(within(r1).getByText('Verified')).toBeInTheDocument()
    expect(within(r2).getByText('Not enough evidence')).toBeInTheDocument()
    expect(within(r1).getByTestId('evidence')).toHaveTextContent(/Evidence \([1-9]/)
    expect(within(r2).getByTestId('evidence')).toHaveTextContent('Evidence (0 items)')

    // guidance targets the unresolved HDMI requirement
    const guidance = screen.getByLabelText('Next photo')
    expect(guidance).toHaveTextContent(/For R2 · HDMI connection/)
    expect(within(guidance).getByTestId('instruction')).toHaveTextContent(multi.next_view!.instruction)
  })

  it('before the first photo: the prompt names every device and both connections are pending', async () => {
    const fresh = { ...multi, photos: [], assessments: [], overall: null, next_view: null, history: [] }
    localStorage.setItem(STORAGE_KEY, fresh.id)
    installApi([access(), { method: 'GET', match: inspectionPath(fresh.id), reply: () => json(fresh) }])
    render(<App />)
    expect(await screen.findByText(/overview photo that shows the Test Router, Test Console and Test TV/)).toBeInTheDocument()
    const summary = screen.getByLabelText('Inspection summary')
    expect(within(summary).getAllByText('Pending')).toHaveLength(3) // installation + both connections
    expect(within(summary).queryByText('Verified')).not.toBeInTheDocument()
    expect(within(summary).getByText('2 connections to inspect')).toBeInTheDocument()
  })

  it('single-requirement inspections are unchanged: no summary card, no connection labels', async () => {
    localStorage.setItem(STORAGE_KEY, (created as InspectionState).id)
    installApi([access(), { method: 'GET', match: inspectionPath((created as InspectionState).id), reply: () => json(stateVerified) }])
    render(<App />)
    await screen.findByText('Inspection complete')
    expect(screen.queryByLabelText('Inspection summary')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Requirement R1')).toBeInTheDocument()
  })
})
