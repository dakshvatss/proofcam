// M3.2: access code, live/mock labelling, stale guidance after an installation change, evidence, rendered report,
// spending cap, camera interruptions and upload preparation. Mocked fetch + fixtures recorded from the real API.

import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import type { InspectionState } from './api/types'
import { currentGuidance, guidanceIsStale } from './lib/guidance'
import { prepareUpload } from './lib/image'
import { STORAGE_KEY } from './state/useInspection'
import created from './test/fixtures/created.json'
import stateAfterChange from './test/fixtures/state_after_change.json'
import stateAfterStep1 from './test/fixtures/state_after_step1.json'
import stateReview from './test/fixtures/state_review.json'
import stateVerified from './test/fixtures/state_verified.json'
import step1 from './test/fixtures/step1_guidance.json'
import reportMd from './test/fixtures/report_md.md?raw'
import { access, accessStatus, apiError, formField, installApi, json, text } from './test/mockApi'

const ID = (created as InspectionState).id
const inspectionPath = (id: string) => new RegExp(`/api/inspections/${id}$`)

async function addPhoto(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(screen.getByTestId('file-input'), new File([new Uint8Array([1, 2, 3])], 'p.jpg', { type: 'image/jpeg' }))
  return screen.findByRole('button', { name: /analyse photo/i })
}

describe('access code', () => {
  it('asks for the code, rejects a wrong one, then loads the saved inspection', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    const api = installApi([
      { method: 'GET', match: /\/api\/access$/, times: 1, reply: () => json(accessStatus({ auth_required: true, authenticated: false })) },
      access({ auth_required: true, model_source: 'live', global_call_limit: 50, global_remaining: 50, global_model_calls: 0 }),
      { method: 'POST', match: /\/api\/session$/, times: 1, reply: () => apiError(401, 'invalid_access_code', 'that access code is not correct') },
      { method: 'POST', match: /\/api\/session$/, reply: () => json(accessStatus({ auth_required: true, model_source: 'live', global_call_limit: 50, global_remaining: 50, global_model_calls: 0 })) },
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateAfterStep1) },
    ])
    const user = userEvent.setup()
    render(<App />)
    const input = await screen.findByLabelText(/access code/i)
    expect(api.calls.some((c) => c.path.includes('/inspections'))).toBe(false) // nothing loaded before login
    await user.type(input, 'wrong-code-123')
    await user.click(screen.getByRole('button', { name: /continue/i }))
    expect(await screen.findByText(/not correct/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText(/access code/i), 'correct-horse-battery-staple')
    await user.click(screen.getByRole('button', { name: /continue/i }))
    expect(await screen.findByTestId('instruction')).toBeInTheDocument()
    const login = api.calls.filter((c) => c.path.endsWith('/api/session')).at(-1)!
    expect(JSON.parse(login.body as string)).toEqual({ access_code: 'correct-horse-battery-staple' })
    // the code is never persisted by the app
    expect(JSON.stringify(localStorage)).not.toContain('correct-horse')
    expect(screen.getByRole('note')).toHaveTextContent(/live models/i)
  })

  it('returns to the access screen when the session expires mid-use', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    installApi([
      access({ auth_required: true }),
      { method: 'GET', match: inspectionPath(ID), reply: () => apiError(401, 'unauthorized', 'enter the access code') },
    ])
    render(<App />)
    expect(await screen.findByLabelText(/access code/i)).toBeInTheDocument()
  })
})

describe('model mode labelling', () => {
  it('labels live models with the remaining server cap', async () => {
    installApi([access({ model_source: 'live', global_model_calls: 8, global_call_limit: 50, global_remaining: 42 })])
    render(<App />)
    const note = await screen.findByRole('note')
    expect(note).toHaveTextContent(/live models/i)
    expect(note).toHaveTextContent('42 of 50 calls left')
  })

  it('labels mock models as scripted test data', async () => {
    installApi([access({ model_source: 'mock' })])
    render(<App />)
    expect(await screen.findByRole('note')).toHaveTextContent(/scripted test data/i)
  })
})

describe('guidance after an installation change', () => {
  it('helper: guidance issued after a superseded photo is stale; current guidance is kept', () => {
    expect(currentGuidance(stateAfterChange as InspectionState)).toBeNull()
    expect(guidanceIsStale(stateAfterChange as InspectionState)).toBe(true)
    expect(currentGuidance(stateAfterStep1 as InspectionState)?.id).toBe('nv1')
    expect(guidanceIsStale(stateAfterStep1 as InspectionState)).toBe(false)
    expect(currentGuidance(stateVerified as InspectionState)).toBeNull() // stopped: no guidance
  })

  it('hides the old instruction and sends the next photo without responding_to', async () => {
    const after = stateAfterChange as InspectionState
    localStorage.setItem(STORAGE_KEY, after.id)
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(after.id), reply: () => json(after) },
      { method: 'POST', match: /\/captures$/, reply: () => apiError(409, 'inspection_busy') },
    ])
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByLabelText('New configuration')).toHaveTextContent(/earlier guidance no longer applies/i)
    expect(screen.queryByTestId('instruction')).not.toBeInTheDocument()
    expect(after.next_view).not.toBeNull() // the server still returns it; the app hides it
    await user.click(await addPhoto(user))
    await waitFor(() => expect(api.captures()).toHaveLength(1))
    expect(formField(api.captures()[0], 'responding_to')).toBeNull()
  })
})

describe('evidence and report', () => {
  it('shows the supporting evidence for a verdict and jumps to its photo', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(stateVerified) }])
    const user = userEvent.setup()
    render(<App />)
    const evidence = await screen.findByTestId('evidence')
    await user.click(within(evidence).getByText(/^Evidence \(/))
    const claim = stateVerified.assessments[0].endpoints[0].support[0].claim
    expect(within(evidence).getByText(claim)).toBeVisible()
    expect(within(evidence).getAllByText(/SAM: .*corroborated/).length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: /show photo 1/i, hidden: false }))
    expect(await screen.findByAltText('Analysis overlay for photo 1')).toBeInTheDocument()
  })

  it('renders the Markdown report as headings and tables', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateVerified) },
      { method: 'GET', match: /\/report\?format=md$/, reply: () => text(reportMd) },
    ])
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /view report/i }))
    expect(await screen.findByRole('heading', { level: 1, name: /ProofCam inspection:/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: /final verdict/i })).toBeInTheDocument()
    expect(screen.getAllByRole('table').length).toBeGreaterThan(0)
    expect(screen.queryByText(/^## /)).not.toBeInTheDocument() // no raw Markdown syntax left
  })
})

describe('spending cap', () => {
  it('keeps the photo and explains when the server cap is reached', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    const api = installApi([
      access({ model_source: 'live' }),
      { method: 'GET', match: inspectionPath(ID), reply: () => json(created) },
      { method: 'POST', match: /\/captures$/, reply: () => apiError(429, 'spend_cap_reached', "the server's model-call cap (50 calls across all inspections) does not leave enough for another photo; nothing was sent to the models") },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: created.title })
    await user.click(await addPhoto(user))
    expect(await screen.findByText(/model-call cap/i)).toBeInTheDocument()
    expect(screen.getByAltText('Photo to analyse')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(api.captures()).toHaveLength(1) // never retried automatically
  })
})

describe('camera on the phone', () => {
  function stubCamera() {
    vi.stubGlobal('isSecureContext', true)
    const track = { stop: vi.fn(), onended: null as null | (() => void) }
    const stream = { getTracks: () => [track], getVideoTracks: () => [track] } as unknown as MediaStream
    const getUserMedia = vi.fn().mockResolvedValue(stream)
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([]) } })
    Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: vi.fn().mockResolvedValue(undefined) })
    return { track, getUserMedia }
  }

  it('prefers the rear camera and recovers from an interruption', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(created) }])
    const { track, getUserMedia } = stubCamera()
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /open camera/i }))
    await screen.findByRole('button', { name: /^capture$/i })
    expect(getUserMedia.mock.calls[0][0].video.facingMode).toEqual({ ideal: 'environment' })
    act(() => track.onended?.())
    expect(await screen.findByText(/camera stopped/i)).toBeInTheDocument()
    expect(track.stop).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /open camera/i })).toBeEnabled()
  })

  it('releases the camera when the page goes to the background', async () => {
    localStorage.setItem(STORAGE_KEY, ID)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(created) }])
    const { track } = stubCamera()
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /open camera/i }))
    await screen.findByRole('button', { name: /^capture$/i })
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })
    expect(track.stop).toHaveBeenCalled()
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
    expect(await screen.findByText(/camera stopped/i)).toBeInTheDocument()
  })

  it('re-encodes gallery uploads (e.g. HEIC) to a downscaled JPEG', async () => {
    const close = vi.fn()
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 6000, height: 4000, close }))
    const draw = vi.fn()
    const orig = HTMLCanvasElement.prototype.getContext
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { configurable: true, value: () => ({ drawImage: draw }) })
    Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', { configurable: true, value(this: HTMLCanvasElement, cb: BlobCallback, type: string) { cb(new Blob([`${this.width}x${this.height}`], { type })) } })
    const out = await prepareUpload(new File(['x'], 'IMG_0001.HEIC', { type: 'image/heic' }))
    expect(out.name).toBe('IMG_0001.jpg')
    expect(out.blob.type).toBe('image/jpeg')
    expect(await out.blob.text()).toBe('2400x1600')
    expect(close).toHaveBeenCalled()
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { configurable: true, value: orig })
  })

  it('falls back to the original file when the browser cannot decode it', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('cannot decode')))
    const f = new File(['x'], 'odd.heic', { type: 'image/heic' })
    const out = await prepareUpload(f)
    expect(out.blob).toBe(f)
  })
})

it('review fixture still shows the review card (regression)', async () => {
  localStorage.setItem(STORAGE_KEY, (stateReview as InspectionState).id)
  installApi([access(), { method: 'GET', match: inspectionPath((stateReview as InspectionState).id), reply: () => json(stateReview) }])
  render(<App />)
  expect(await screen.findByRole('alert', { name: /review required/i })).toBeInTheDocument()
  expect(step1).toBeTruthy()
})
