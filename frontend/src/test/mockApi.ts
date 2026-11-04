// A fetch-level fake of the ProofCam API for frontend tests. Response bodies come from fixtures recorded from the real
// FastAPI app with mocked Meta models (backend/experiments/dev_mock_server.py --export-fixtures); no network is used.

import { vi } from 'vitest'

export interface Call {
  method: string
  path: string
  headers: Record<string, string>
  body: unknown
}

type Reply = Response | 'network-error' | Promise<Response | 'network-error'>
type Route = { method: string; match: RegExp; reply: (call: Call) => Reply; times?: number }

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
export const apiError = (status: number, error: string, message = error) => json({ error, message }, status)
export const text = (body: string) => new Response(body, { status: 200, headers: { 'content-type': 'text/markdown; charset=utf-8' } })

export function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

/** Install a fake fetch. Routes are matched in order; a route with `times` is used that many times, then skipped. */
export function installApi(routes: Route[]) {
  const calls: Call[] = []
  const used = new Map<Route, number>()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === 'string' ? input : input.toString()
    const method = (init.method ?? 'GET').toUpperCase()
    const call: Call = { method, path: url, headers: { ...(init.headers as Record<string, string> | undefined) }, body: init.body }
    calls.push(call)
    const route = routes.find((r) => r.method === method && r.match.test(url) && (r.times === undefined || (used.get(r) ?? 0) < r.times))
    if (!route) throw new Error(`unexpected request ${method} ${url}`)
    used.set(route, (used.get(route) ?? 0) + 1)
    const out = await route.reply(call)
    if (out === 'network-error') throw new TypeError('Failed to fetch')
    return out
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock, captures: () => calls.filter((c) => c.method === 'POST' && c.path.endsWith('/captures')) }
}

export const accessStatus = (over: Partial<Record<string, unknown>> = {}) => ({
  auth_required: false, authenticated: true, model_source: 'mock',
  global_model_calls: null, global_call_limit: null, global_remaining: null, ...over,
})

/** GET /api/access, which the app calls at start-up (and after each analysed photo). */
export const access = (over: Partial<Record<string, unknown>> = {}) => ({
  method: 'GET', match: /\/api\/access$/, reply: () => json(accessStatus(over)),
})

export function formField(call: Call, name: string): FormDataEntryValue | null {
  return call.body instanceof FormData ? call.body.get(name) : null
}
