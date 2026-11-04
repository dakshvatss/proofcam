// Inspection session state and the capture protocol (docs/FRONTEND_HANDOFF.md, "Safe retry handling").
//
// One pending photo at a time. Each staged photo gets its own Idempotency-Key, kept until the server gives a final
// answer; a retry of that photo reuses the key, a new photo always gets a new one. If a capture produces no HTTP
// response (connection dropped, timeout) or the inspection is busy, the persisted state is read first: while the
// server is still processing we wait; if a step was committed meanwhile, resending the same key returns the stored
// response at no cost; otherwise the user decides whether to retry (which may use model calls) or discard.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, MAX_UPLOAD_BYTES, NetworkError, api, newIdempotencyKey } from '../api/client'
import type { InspectionState, StepResponse } from '../api/types'
import { currentGuidance } from '../lib/guidance'

export const STORAGE_KEY = 'proofcam.inspectionId'
// Mutable only so tests can poll quickly.
export const timing = { pollMs: 3000, maxPolls: 400 } // ~20 min, above the backend's theoretical worst case

export type Phase =
  | 'idle' // no inspection loaded
  | 'loading'
  | 'ready'
  | 'confirm' // a photo is staged, waiting for the user to send it
  | 'uploading'
  | 'recovering' // reading the saved state after a failed or busy capture
  | 'retry' // the photo was not analysed; user chooses retry or discard

export interface PendingPhoto {
  blob: Blob
  url: string
  sourceName: string
  key: string
  respondingTo: string | null
  baseVersion: number // inspection version when the photo was staged
}

export interface Notice {
  kind: 'info' | 'warn' | 'error'
  text: string
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export function readStoredId(): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get('inspection')
  return fromUrl || localStorage.getItem(STORAGE_KEY)
}

function rememberId(id: string | null) {
  const url = new URL(window.location.href)
  if (id) {
    localStorage.setItem(STORAGE_KEY, id)
    url.searchParams.set('inspection', id)
  } else {
    localStorage.removeItem(STORAGE_KEY)
    url.searchParams.delete('inspection')
  }
  window.history.replaceState(null, '', url)
}

export function useInspection() {
  const [inspection, setInspection] = useState<InspectionState | null>(null)
  const [lastStep, setLastStep] = useState<StepResponse | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [pending, setPending] = useState<PendingPhoto | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [uploadStartedAt, setUploadStartedAt] = useState<number | null>(null)
  const inFlight = useRef(false) // synchronous guard against double clicks / double submits
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const clearPending = useCallback(() => {
    setPending((p) => {
      if (p) URL.revokeObjectURL(p.url)
      return null
    })
  }, [])

  /** Poll the saved state until the server is no longer processing a capture for this inspection. */
  const waitUntilIdle = useCallback(async (id: string): Promise<InspectionState | null> => {
    for (let i = 0; i < timing.maxPolls && alive.current; i++) {
      try {
        const st = await api.getInspection(id)
        if (!alive.current) return null
        setInspection(st)
        if (!st.busy) return st
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) throw e
        // network trouble while polling: keep trying
      }
      await sleep(timing.pollMs)
    }
    return null
  }, [])

  const load = useCallback(async (id: string) => {
    setPhase('loading')
    setNotice(null)
    try {
      const st = await api.getInspection(id)
      setInspection(st)
      rememberId(st.id)
      if (st.busy) {
        setPhase('recovering')
        setNotice({ kind: 'info', text: 'A photo submitted earlier is still being analysed. Waiting for the result…' })
        const done = await waitUntilIdle(st.id)
        if (!alive.current) return
        setNotice(done ? null : { kind: 'warn', text: 'Still waiting for the server. Reload the page to check again.' })
      }
      setPhase('ready')
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        rememberId(null)
        setInspection(null)
        setPhase('idle')
        setNotice({ kind: 'warn', text: 'The saved inspection no longer exists on this server. Start a new one.' })
        return
      }
      setPhase('idle')
      setNotice({ kind: 'error', text: `Could not load the inspection: ${(e as Error).message}` })
    }
  }, [waitUntilIdle])

  const start = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setPhase('loading')
    setNotice(null)
    try {
      const st = await api.createInspection()
      setInspection(st)
      setLastStep(null)
      rememberId(st.id)
      setPhase('ready')
    } catch (e) {
      setPhase('idle')
      setNotice({ kind: 'error', text: `Could not start an inspection: ${(e as Error).message}` })
    } finally {
      inFlight.current = false
    }
  }, [])

  const leave = useCallback(() => {
    clearPending()
    rememberId(null)
    setInspection(null)
    setLastStep(null)
    setNotice(null)
    setPhase('idle')
  }, [clearPending])

  const stagePhoto = useCallback((blob: Blob, sourceName: string) => {
    if (!inspection || inFlight.current || pending) return
    if (blob.size > MAX_UPLOAD_BYTES) {
      setNotice({ kind: 'error', text: 'That photo is larger than 15 MB. Choose a smaller one.' })
      return
    }
    if (blob.type && !blob.type.startsWith('image/')) {
      setNotice({ kind: 'error', text: 'That file is not an image.' })
      return
    }
    setNotice(null)
    setPending({
      blob, url: URL.createObjectURL(blob), sourceName, key: newIdempotencyKey(),
      // Stale guidance (issued before an installation change) is not answered: the photo is sent as unguided.
      respondingTo: currentGuidance(inspection)?.id ?? null, baseVersion: inspection.version,
    })
    setPhase('confirm')
  }, [inspection, pending])

  const discardPhoto = useCallback(() => {
    if (inFlight.current) return
    clearPending()
    setNotice(null)
    setPhase('ready')
  }, [clearPending])

  // Sends `p` (always with its own key). `auto` marks a resend made only to fetch a step committed meanwhile.
  // Plain (non-memoized) functions: each render's versions see that render's inspection; the double-submit guard is
  // the inFlight ref, not referential identity.
  async function send(p: PendingPhoto, auto = false): Promise<void> {
    if (!inspection) return
    const id = inspection.id
    setPhase('uploading')
    setUploadStartedAt(Date.now())
    try {
      const step = await api.submitCapture(id, p.blob,
        { idempotencyKey: p.key, sourceName: p.sourceName, respondingTo: p.respondingTo })
      if (!alive.current) return
      setLastStep(step)
      clearPending()
      const notes: string[] = []
      if (step.replayed) notes.push('This result was already saved on the server; no new analysis was needed.')
      if (step.duplicate_of) notes.push(`This photo is identical to photo ${step.duplicate_of}; it added no evidence.`)
      setNotice(notes.length ? { kind: 'info', text: notes.join(' ') } : null)
      try {
        setInspection(await api.getInspection(id))
      } catch {
        // the step response already holds the verdict; the history refreshes on the next load
      }
      setPhase('ready')
    } catch (e) {
      if (!alive.current) return
      await handleCaptureError(e, p, auto)
    } finally {
      setUploadStartedAt(null)
    }
  }

  async function recover(p: PendingPhoto, auto: boolean, why: string) {
    if (!inspection) return
    setPhase('recovering')
    setNotice({ kind: 'info', text: `${why} Checking the saved inspection before doing anything else…` })
    let st: InspectionState | null = null
    try {
      st = await waitUntilIdle(inspection.id)
    } catch {
      st = null
    }
    if (!alive.current) return
    if (st && st.version > p.baseVersion && !auto) {
      // A step was committed while we were disconnected: the same key returns the stored response, free of charge.
      setNotice({ kind: 'info', text: 'The server finished a step meanwhile. Fetching its saved result…' })
      await send(p, true)
      return
    }
    setPhase('retry')
    setNotice({
      kind: 'warn',
      text: st
        ? 'This photo was not analysed. You can retry it (this may use model calls again) or discard it.'
        : 'The server could not be reached. Check that it is running, then retry or discard the photo.',
    })
  }

  async function handleCaptureError(e: unknown, p: PendingPhoto, auto: boolean) {
    if (e instanceof NetworkError) {
      await recover(p, auto, e.timedOut ? 'The analysis is taking unusually long.' : 'The connection was interrupted.')
      return
    }
    if (!(e instanceof ApiError)) {
      setPhase('retry')
      setNotice({ kind: 'error', text: `Unexpected error: ${(e as Error).message}` })
      return
    }
    const refresh = async () => {
      if (!inspection) return
      try {
        setInspection(await api.getInspection(inspection.id))
      } catch {
        /* keep the old state */
      }
    }
    switch (e.code) {
      case 'inspection_busy':
        await recover(p, auto, 'The server is still analysing a photo for this inspection.')
        return
      case 'stale_guidance':
        clearPending()
        await refresh()
        setPhase('ready')
        setNotice({ kind: 'warn', text: 'The guidance changed before this photo was sent, so it was not analysed. Follow the current instruction and take a new photo.' })
        return
      case 'inspection_stopped':
        clearPending()
        await refresh()
        setPhase('ready')
        setNotice({ kind: 'warn', text: 'This inspection has stopped, so the photo was not analysed.' })
        return
      case 'lease_lost':
      case 'conflict':
        await refresh()
        setPhase('retry')
        setNotice({ kind: 'warn', text: `${e.message} You can retry the same photo.` })
        return
      case 'spend_cap_reached':
        setPhase('retry')
        setNotice({ kind: 'error', text: `${e.message} The photo is kept; retry only after the cap has been raised.` })
        return
      case 'unauthorized':
        setPhase('retry')
        setNotice({ kind: 'warn', text: 'Your session ended before this photo was analysed. Enter the access code, then retry the photo.' })
        return
      case 'internal_error':
        await recover(p, auto, 'The server reported an unexpected error.')
        return
      case 'idempotency_conflict':
      default:
        clearPending()
        setPhase('ready')
        setNotice({ kind: 'error', text: e.message })
    }
  }

  async function sendPhoto() {
    const p = pending
    if (!p || inFlight.current) return
    inFlight.current = true
    try {
      await send(p)
    } finally {
      inFlight.current = false
    }
  }

  const declareChange = useCallback(async (reason: string): Promise<boolean> => {
    if (!inspection || inFlight.current) return false
    inFlight.current = true
    try {
      const st = await api.declareInstallationChanged(inspection.id, reason)
      setInspection(st)
      setLastStep(null)
      setNotice({ kind: 'info', text: 'Installation change recorded. Earlier photos are kept but no longer count; take new photos of the current setup.' })
      return true
    } catch (e) {
      setNotice({ kind: 'error', text: `Could not record the change: ${(e as Error).message}` })
      return false
    } finally {
      inFlight.current = false
    }
  }, [inspection])

  return {
    inspection, lastStep, phase, pending, notice, uploadStartedAt,
    start, load, leave, stagePhoto, discardPhoto, sendPhoto, declareChange,
  }
}

export type InspectionSession = ReturnType<typeof useInspection>
