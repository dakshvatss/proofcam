// Thin client for the ProofCam HTTP API. Relative /api URLs only (Vite proxies them to FastAPI in development);
// no credentials of any kind live in the browser.

import type { AccessStatus, Health, InspectionState, StepResponse } from './types'

export const SPEC_ID = 'my_setup'
// Captures are synchronous and slow (25-48 s observed; much longer in the worst case). After this the client stops
// waiting and recovers from the persisted state instead; the server keeps processing the step.
export const CAPTURE_TIMEOUT_MS = 6 * 60 * 1000
export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024
export const UNAUTHORIZED_EVENT = 'proofcam:unauthorized'

/** An error response from the API: {"error": code, "message": text}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** The request did not produce an HTTP response (offline, connection dropped, timed out). Outcome unknown. */
export class NetworkError extends Error {
  readonly timedOut: boolean
  constructor(message: string, timedOut = false) {
    super(message)
    this.timedOut = timedOut
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const ctrl = new AbortController()
  const timer = timeoutMs ? setTimeout(() => ctrl.abort(), timeoutMs) : undefined
  let res: Response
  try {
    res = await fetch(path, { ...init, signal: ctrl.signal })
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === 'AbortError'
    throw new NetworkError(aborted ? 'The server took too long to answer.' : 'The connection to the server failed.',
      aborted)
  } finally {
    if (timer) clearTimeout(timer)
  }
  const type = res.headers.get('content-type') ?? ''
  if (!res.ok) {
    let code = 'http_error'
    let message = `HTTP ${res.status}`
    if (type.includes('application/json')) {
      const body = await res.json().catch(() => null)
      if (body && typeof body.error === 'string') {
        code = body.error
        message = typeof body.message === 'string' ? body.message : message
      }
    }
    // A missing/expired session anywhere sends the app back to the access-code screen.
    if (res.status === 401 && code === 'unauthorized') window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    throw new ApiError(res.status, code, message)
  }
  return (type.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/health'),

  /** Whether this server needs an access code, whether this browser has a session, model mode, spending cap. */
  access: () => request<AccessStatus>('/api/access'),

  /** Exchanges the access code for an HttpOnly session cookie; the code is not stored by the app. */
  login: (accessCode: string) =>
    request<AccessStatus>('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_code: accessCode }),
    }),

  logout: () => request<string>('/api/session', { method: 'DELETE' }),

  createInspection: (specId: string = SPEC_ID) =>
    request<InspectionState>('/api/inspections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec_id: specId }),
    }),

  getInspection: (id: string) => request<InspectionState>(`/api/inspections/${encodeURIComponent(id)}`),

  /** Paid on the real server. `idempotencyKey` must be unique per photo and reused only to retry that photo. */
  submitCapture: (id: string, photo: Blob, opts: { idempotencyKey: string; sourceName: string; respondingTo?: string | null }) => {
    const form = new FormData()
    form.append('file', photo, opts.sourceName)
    form.append('source_name', opts.sourceName)
    if (opts.respondingTo) form.append('responding_to', opts.respondingTo)
    return request<StepResponse>(`/api/inspections/${encodeURIComponent(id)}/captures`, {
      method: 'POST',
      headers: { 'Idempotency-Key': opts.idempotencyKey },
      body: form,
    }, CAPTURE_TIMEOUT_MS)
  },

  declareInstallationChanged: (id: string, reason: string) =>
    request<InspectionState>(`/api/inspections/${encodeURIComponent(id)}/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'installation_changed', reason }),
    }),

  reportMarkdown: (id: string) => request<string>(`/api/inspections/${encodeURIComponent(id)}/report?format=md`),
}

export const reportJsonUrl = (id: string) => `/api/inspections/${encodeURIComponent(id)}/report?format=json`

/** A new random key per photo. crypto.randomUUID needs a secure context; fall back to getRandomValues. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return `photo-${crypto.randomUUID()}`
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  return `photo-${Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')}`
}
