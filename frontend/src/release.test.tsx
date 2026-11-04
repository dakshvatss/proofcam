// M3.5 release UI: model-source labelling, report summary, last-photo result, timeline, template setup.
// Mocked fetch + fixtures recorded from the real FastAPI app with MOCKED Meta models (not real inference).

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import type { InspectionState } from './api/types'
import { STORAGE_KEY } from './state/useInspection'
import created from './test/fixtures/created.json'
import reportMd from './test/fixtures/report_md.md?raw'
import stateAfterStep1 from './test/fixtures/state_after_step1.json'
import stateMulti from './test/fixtures/state_multi.json'
import step1 from './test/fixtures/step1_guidance.json'
import { access, installApi, json, text } from './test/mockApi'

const multi = stateMulti as InspectionState
const ID = (created as InspectionState).id
const path = (id: string) => new RegExp(`/api/inspections/${id}$`)

describe('model source labelling', () => {
  it('labels replayed output and never calls an unknown source live', async () => {
    installApi([access({ model_source: 'replay' })])
    const { unmount } = render(<App />)
    const note = await screen.findByRole('note')
    expect(note).toHaveTextContent(/replay/i)
    expect(note).not.toHaveTextContent(/live models/i)
    unmount()
    installApi([access({ model_source: 'something-new' })])
    render(<App />)
    const note2 = await screen.findByRole('note')
    expect(note2).toHaveTextContent(/mock models/i)
    expect(note2).not.toHaveTextContent(/live models/i)
  })
})

describe('report summary', () => {
  it('shows the server overall verdict, model source and which photo supports which claim', async () => {
    localStorage.setItem(STORAGE_KEY, multi.id)
    installApi([
      access({ model_source: 'mock' }),
      { method: 'GET', match: path(multi.id), reply: () => json(multi) },
      { method: 'GET', match: /\/report\?format=md$/, reply: () => text(reportMd) },
    ])
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /view report/i }))
    expect(await screen.findByText('Overall verdict')).toBeInTheDocument()
    expect(screen.getAllByText('Not enough evidence').length).toBeGreaterThan(0)
    expect(screen.getByText('Mock: scripted test data')).toBeInTheDocument()
    expect(screen.getAllByText(/supported by photo 1/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /download/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /json/i })).toHaveAttribute('href', `/api/inspections/${multi.id}/report?format=json`)
    expect(screen.getByText(/not a legal certification/i)).toBeInTheDocument()
  })
})

describe('after a photo', () => {
  it('summarises what the last step actually changed and keeps an audit timeline', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    let current: unknown = created
    installApi([
      access(),
      { method: 'GET', match: path(ID), reply: () => json(current) },
      { method: 'POST', match: /\/captures$/, reply: () => { current = stateAfterStep1; return json(step1) } },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: (created as InspectionState).title })
    await user.upload(screen.getByTestId('file-input'), new File([new Uint8Array([1])], 'p.jpg', { type: 'image/jpeg' }))
    await user.click(await screen.findByRole('button', { name: /analyse photo/i }))
    const result = await screen.findByLabelText('Last photo result')
    expect(within(result).getByText('Photo 1 result')).toBeInTheDocument()
    expect(within(result).getByText('Next view requested')).toBeInTheDocument()
    expect(within(result).getByText(/accepted by the policy/)).toBeInTheDocument()
    expect(screen.getByText(/Timeline \(1 event\)/)).toBeInTheDocument()
    expect(screen.getByText(`Next view ${step1.next_view!.id} requested`)).toBeInTheDocument()
  })
})

describe('template setup', () => {
  it('shows the connections and diagram of the chosen template before starting', async () => {
    installApi([
      access(),
      { method: 'GET', match: /\/api\/specs$/, reply: () => json([{
        spec_id: 'ps5_home_setup', title: 'Home Entertainment Installation', max_photos: 8,
        devices: ['Wi-Fi Router', 'PlayStation 5', 'Samsung Television'],
        requirements: [
          { id: 'R1', text: 'Ethernet text', connector: 'ethernet', cable_color: null,
            endpoints: [{ device: 'Wi-Fi Router', port: 'any LAN port', flexible: true }, { device: 'PlayStation 5', port: 'LAN port', flexible: true }] },
          { id: 'R2', text: 'HDMI text', connector: 'hdmi', cable_color: null,
            endpoints: [{ device: 'PlayStation 5', port: 'HDMI OUT port', flexible: true }, { device: 'Samsung Television', port: 'any HDMI input', flexible: true }] },
        ],
      }]) },
    ])
    render(<App />)
    const setup = await screen.findByLabelText('Inspection setup')
    expect(await within(setup).findByText('One inspection · 2 connections to prove')).toBeInTheDocument()
    expect(within(setup).getByText(/up to 8 photos/)).toBeInTheDocument()
    expect(within(setup).getByText('Ethernet')).toBeInTheDocument() // diagram link labels
    expect(within(setup).getByText('HDMI')).toBeInTheDocument()
    expect(within(setup).getByText('Samsung Television')).toBeInTheDocument()
  })
})
