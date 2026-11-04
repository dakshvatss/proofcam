import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import type { InspectionState, StepResponse } from './api/types'
import { STORAGE_KEY } from './state/useInspection'
import created from './test/fixtures/created.json'
import stateAfterChange from './test/fixtures/state_after_change.json'
import stateAfterStep1 from './test/fixtures/state_after_step1.json'
import stateReview from './test/fixtures/state_review.json'
import stateVerified from './test/fixtures/state_verified.json'
import step1 from './test/fixtures/step1_guidance.json'
import step2 from './test/fixtures/step2_verified.json'
import { access, apiError, deferred, formField, installApi, json, text } from './test/mockApi'
import reportMd from './test/fixtures/report_md.md?raw'

const ID = (created as InspectionState).id
const REVIEW_ID = (stateReview as InspectionState).id
const inspectionPath = (id: string) => new RegExp(`/api/inspections/${id}$`)
const capturePath = /\/captures$/

function photoFile(name = 'photo.jpg') {
  return new File([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], name, { type: 'image/jpeg' })
}

async function addPhoto(user: ReturnType<typeof userEvent.setup>, name?: string) {
  await user.upload(screen.getByTestId('file-input'), photoFile(name))
  return screen.findByRole('button', { name: /analyse photo/i })
}

function resumeWith(state: InspectionState) {
  localStorage.setItem(STORAGE_KEY, state.id)
}

describe('starting and resuming', () => {
  it('creates an inspection from my_setup and remembers it', async () => {
    const api = installApi([access(), { method: 'POST', match: /\/api\/inspections$/, reply: () => json(created, 201) }])
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /start inspection/i }))
    expect(await screen.findByRole('heading', { name: created.title })).toBeInTheDocument()
    expect(screen.getByText('0 photos')).toBeInTheDocument()
    const post = api.calls.find((c) => c.method === 'POST')!
    expect(JSON.parse(post.body as string)).toEqual({ spec_id: 'my_setup' })
    expect(localStorage.getItem(STORAGE_KEY)).toBe(ID)
    expect(window.location.search).toContain(ID)
    expect(screen.getByRole('note')).toHaveTextContent(/mock models/i)
  })

  it('a double click on Start creates only one inspection', async () => {
    const d = deferred<Response>()
    const api = installApi([access(), { method: 'POST', match: /\/api\/inspections$/, reply: () => d.promise }])
    render(<App />)
    const btn = screen.getByRole('button', { name: /start inspection/i })
    fireEvent.click(btn)
    fireEvent.click(btn)
    d.resolve(json(created, 201))
    await screen.findByRole('heading', { name: created.title })
    expect(api.calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('restores an inspection after a page refresh', async () => {
    resumeWith(stateVerified as InspectionState)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(stateVerified) }])
    render(<App />)
    expect(await screen.findByText('Photos (2)')).toBeInTheDocument()
    expect(screen.getAllByText('Verified').length).toBeGreaterThan(0)
    expect(screen.getByText('Inspection complete')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open camera/i })).not.toBeInTheDocument()
  })

  it('waits for a capture that was still processing when the page was reloaded', async () => {
    resumeWith(stateAfterStep1 as InspectionState)
    installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), times: 2, reply: () => json({ ...stateAfterStep1, busy: true }) },
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateVerified) },
    ])
    render(<App />)
    expect(await screen.findByText('Inspection complete')).toBeInTheDocument()
  })

  it('falls back to the landing page when the saved inspection no longer exists', async () => {
    localStorage.setItem(STORAGE_KEY, 'insp_gone')
    installApi([access(), { method: 'GET', match: inspectionPath('insp_gone'), reply: () => apiError(404, 'not_found') }])
    render(<App />)
    expect(await screen.findByText(/no longer exists/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start inspection/i })).toBeInTheDocument()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
})

describe('capturing and guidance', () => {
  it('uploads, shows guidance and overlay, then verifies with responding_to and a new key', async () => {
    let current: unknown = created
    const api = installApi([
      access(),
      { method: 'POST', match: /\/api\/inspections$/, reply: () => json(created, 201) },
      { method: 'GET', match: inspectionPath(ID), reply: () => json(current) },
      { method: 'POST', match: capturePath, times: 1, reply: () => { current = stateAfterStep1; return json(step1) } },
      { method: 'POST', match: capturePath, times: 1, reply: () => { current = stateVerified; return json(step2) } },
    ])
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /start inspection/i }))
    await user.click(await addPhoto(user, 'front.jpg'))

    expect(await screen.findByTestId('instruction')).toHaveTextContent((step1 as StepResponse).next_view!.instruction)
    expect(screen.getByText('Go to the back')).toBeInTheDocument() // camera_action move_to_rear
    expect(screen.getByText(/success when:/i)).toBeInTheDocument()
    expect(screen.getAllByText('Not enough evidence').length).toBeGreaterThan(0)
    expect(screen.queryByText('Verified')).not.toBeInTheDocument()
    expect(screen.getByText(/missing evidence/i)).toBeInTheDocument()
    const overlay = screen.getByAltText('Analysis overlay for photo 1') as HTMLImageElement
    expect(overlay.getAttribute('src')).toBe(stateAfterStep1.photos[0].overlay_url)
    expect(screen.getByText('Photos (1)')).toBeInTheDocument()

    await user.click(await addPhoto(user, 'rear.jpg'))
    expect(await screen.findByText('Inspection complete')).toBeInTheDocument()
    expect(screen.getAllByText('Verified').length).toBeGreaterThan(0)

    const [c1, c2] = api.captures()
    expect(c1.headers['Idempotency-Key']).toMatch(/^photo-/)
    expect(c2.headers['Idempotency-Key']).toMatch(/^photo-/)
    expect(c1.headers['Idempotency-Key']).not.toBe(c2.headers['Idempotency-Key'])
    expect(formField(c1, 'responding_to')).toBeNull()
    expect(formField(c2, 'responding_to')).toBe('nv1')
    expect(formField(c1, 'file')).toBeInstanceOf(File)
  })

  it('a double click on Analyse sends the photo once', async () => {
    resumeWith(created as InspectionState)
    const d = deferred<Response>()
    let current: unknown = created
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), reply: () => json(current) },
      { method: 'POST', match: capturePath, reply: () => d.promise.then((r) => { current = stateAfterStep1; return r }) },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: created.title })
    const analyse = await addPhoto(user)
    fireEvent.click(analyse)
    fireEvent.click(analyse)
    expect(await screen.findByText(/analysing your photo/i)).toBeInTheDocument()
    d.resolve(json(step1))
    await screen.findByTestId('instruction')
    expect(api.captures()).toHaveLength(1)
  })

  it('stale guidance discards the photo and shows the current instruction', async () => {
    resumeWith(stateAfterStep1 as InspectionState)
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateAfterStep1) },
      { method: 'POST', match: capturePath, reply: () => apiError(409, 'stale_guidance', 'stale') },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByTestId('instruction')
    await user.click(await addPhoto(user))
    expect(await screen.findByText(/guidance changed/i)).toBeInTheDocument()
    expect(screen.queryByAltText('Photo to analyse')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open camera/i })).toBeInTheDocument()
    expect(api.captures()).toHaveLength(1)
  })
})

describe('network failures and retries', () => {
  it('after a dropped connection it reads the saved state, then fetches the committed step with the same key', async () => {
    resumeWith(created as InspectionState)
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), times: 1, reply: () => json(created) },
      { method: 'GET', match: inspectionPath(ID), times: 1, reply: () => json({ ...stateAfterStep1, busy: true }) },
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateAfterStep1) },
      { method: 'POST', match: capturePath, times: 1, reply: () => 'network-error' },
      { method: 'POST', match: capturePath, reply: () => json({ ...step1, replayed: true }) },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: created.title })
    await user.click(await addPhoto(user))
    expect(await screen.findByText(/already saved on the server/i)).toBeInTheDocument()
    expect(screen.getByTestId('instruction')).toBeInTheDocument()
    const [first, second] = api.captures()
    expect(second.headers['Idempotency-Key']).toBe(first.headers['Idempotency-Key'])
    // the saved state was read between the failed attempt and the resend
    const idxFirst = api.calls.indexOf(first)
    const idxSecond = api.calls.indexOf(second)
    expect(api.calls.slice(idxFirst, idxSecond).some((c) => c.method === 'GET')).toBe(true)
  })

  it('when nothing was saved it asks before retrying, retries with the same key, and a new photo gets a new key', async () => {
    resumeWith(created as InspectionState)
    let current: unknown = created
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), reply: () => json(current) },
      { method: 'POST', match: capturePath, times: 1, reply: () => 'network-error' },
      { method: 'POST', match: capturePath, times: 1, reply: () => { current = stateAfterStep1; return json(step1) } },
      { method: 'POST', match: capturePath, times: 1, reply: () => { current = stateVerified; return json(step2) } },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: created.title })
    await user.click(await addPhoto(user))
    const retry = await screen.findByRole('button', { name: /retry/i })
    expect(screen.getByText(/was not analysed/i)).toBeInTheDocument()
    expect(api.captures()).toHaveLength(1) // no automatic paid retry
    await user.click(retry)
    await screen.findByTestId('instruction')
    await user.click(await addPhoto(user, 'second.jpg'))
    await screen.findByText('Inspection complete')
    const [a, b, c] = api.captures().map((x) => x.headers['Idempotency-Key'])
    expect(b).toBe(a)
    expect(c).not.toBe(a)
  })

  it('a busy inspection is polled until free, then the stored result is fetched', async () => {
    resumeWith(created as InspectionState)
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), times: 1, reply: () => json(created) },
      { method: 'GET', match: inspectionPath(ID), times: 2, reply: () => json({ ...created, busy: true }) },
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateAfterStep1) },
      { method: 'POST', match: capturePath, times: 1, reply: () => apiError(409, 'inspection_busy') },
      { method: 'POST', match: capturePath, reply: () => json({ ...step1, replayed: true }) },
    ])
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: created.title })
    await user.click(await addPhoto(user))
    await screen.findByTestId('instruction')
    const keys = api.captures().map((x) => x.headers['Idempotency-Key'])
    expect(keys).toHaveLength(2)
    expect(keys[1]).toBe(keys[0])
  })
})

describe('review and installation change', () => {
  it('shows a review state without camera guidance and records a confirmed change', async () => {
    resumeWith(stateReview as InspectionState)
    let current: unknown = stateReview
    const api = installApi([
      access(),
      { method: 'GET', match: inspectionPath(REVIEW_ID), reply: () => json(current) },
      { method: 'POST', match: /\/events$/, reply: () => { current = stateAfterChange; return json(stateAfterChange) } },
    ])
    const user = userEvent.setup()
    render(<App />)
    const review = await screen.findByRole('alert', { name: /review required/i })
    expect(within(review).getByText(/photos 1, 2 disagree/i)).toBeInTheDocument()
    expect(screen.queryByTestId('instruction')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open camera/i })).not.toBeInTheDocument()
    expect(screen.queryByText('Verified')).not.toBeInTheDocument()

    await user.click(within(review).getByRole('button', { name: /i changed the installation/i }))
    const dialog = screen.getByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: /confirm change/i })
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByRole('textbox'), 'moved the cable to port 3')
    await user.click(confirm)

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const ev = api.calls.find((c) => c.path.endsWith('/events'))!
    expect(JSON.parse(ev.body as string)).toEqual({ type: 'installation_changed', reason: 'moved the cable to port 3' })
    expect(screen.queryByRole('alert', { name: /review required/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open camera/i })).toBeInTheDocument()
    expect(screen.getByText(/configuration 2/i)).toBeInTheDocument()
  })

  it('cancelling the confirmation sends nothing', async () => {
    resumeWith(stateReview as InspectionState)
    const api = installApi([access(), { method: 'GET', match: inspectionPath(REVIEW_ID), reply: () => json(stateReview) }])
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /i changed the installation/i }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: /cancel/i }))
    expect(api.calls.some((c) => c.path.endsWith('/events'))).toBe(false)
  })
})

describe('report', () => {
  it('shows the saved report', async () => {
    resumeWith(stateVerified as InspectionState)
    installApi([
      access(),
      { method: 'GET', match: inspectionPath(ID), reply: () => json(stateVerified) },
      { method: 'GET', match: /\/report\?format=md$/, reply: () => text(reportMd) },
    ])
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /view report/i }))
    const report = await screen.findByLabelText('Saved report')
    await waitFor(() => expect(report).toHaveTextContent('ProofCam inspection:'))
    expect(screen.getByRole('link', { name: /json/i })).toHaveAttribute('href', `/api/inspections/${ID}/report?format=json`)
  })
})

describe('camera', () => {
  it('explains a denied permission and keeps the upload fallback', async () => {
    resumeWith(created as InspectionState)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(created) }])
    vi.stubGlobal('isSecureContext', true)
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([]) } })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /open camera/i }))
    expect(await screen.findByText(/permission was denied/i)).toBeInTheDocument()
    expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({ video: expect.objectContaining({ facingMode: { ideal: 'environment' } }) }))
    expect(screen.getByRole('button', { name: /upload photo/i })).toBeEnabled()
  })

  it('stops the camera stream after capturing', async () => {
    resumeWith(created as InspectionState)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(created) }])
    vi.stubGlobal('isSecureContext', true)
    const stopTrack = vi.fn()
    const stream = { getTracks: () => [{ stop: stopTrack }], getVideoTracks: () => [] } as unknown as MediaStream
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia: vi.fn().mockResolvedValue(stream), enumerateDevices: vi.fn().mockResolvedValue([{ kind: 'videoinput' }]),
    } })
    Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: vi.fn().mockResolvedValue(undefined) })
    Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', { configurable: true, get: () => 640 })
    Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', { configurable: true, get: () => 480 })
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { configurable: true, value: () => ({ drawImage: vi.fn() }) })
    Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', { configurable: true, value(cb: BlobCallback) { cb(new Blob(['x'], { type: 'image/jpeg' })) } })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: /open camera/i }))
    await user.click(await screen.findByRole('button', { name: /capture/i }))
    expect(stopTrack).toHaveBeenCalled()
    expect(await screen.findByAltText('Photo to analyse')).toBeInTheDocument()
  })

  it('explains that the camera needs a secure context', async () => {
    resumeWith(created as InspectionState)
    installApi([access(), { method: 'GET', match: inspectionPath(ID), reply: () => json(created) }])
    vi.stubGlobal('isSecureContext', false)
    render(<App />)
    expect(await screen.findByText(/camera access needs a secure page/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open camera/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /upload photo/i })).toBeEnabled()
  })
})
