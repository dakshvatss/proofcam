import { RefreshCw } from 'lucide-react'
import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { UNAUTHORIZED_EVENT, api } from './api/client'
import type { AccessStatus } from './api/types'
import { AccessGate } from './components/AccessGate'
import { InspectionView } from './components/InspectionView'
import { Landing } from './components/Landing'
import { Button } from './components/ui/button'
import { Callout } from './components/ui/callout'
import { Wordmark } from './components/ui/logo'
import { cn } from './lib/utils'
import { readStoredId, useInspection } from './state/useInspection'

// The report (Markdown renderer) loads on demand, keeping the camera workflow's first load small.
const ReportView = lazy(() => import('./components/ReportView').then((m) => ({ default: m.ReportView })))

const MODE: Record<string, { label: string; sub: string; text: string; dot: string; ring: string; sr: string }> = {
  live: { label: 'Live models', sub: 'Paid analysis', text: 'text-accent-strong', dot: 'bg-accent', ring: 'border-accent/25 bg-accent-soft',
    sr: 'Every analysed photo makes paid Meta API calls.' },
  mock: { label: 'Mock models', sub: 'Scripted test data', text: 'text-mock', dot: 'bg-mock', ring: 'border-mock/25 bg-[#f4efff]',
    sr: 'results are scripted test data, not real analysis of your photos.' },
  replay: { label: 'Replay', sub: 'Recorded model output', text: 'text-replay', dot: 'bg-replay', ring: 'border-replay/25 bg-[#fff8e6]',
    sr: 'results are replayed from recorded model output, not a new analysis of your photos.' },
}

/** Which models answer this server: always visible in the app bar so mock or replayed output is never mistaken for
 * live inference (also in screen recordings). Unknown sources are shown as mock-style warnings, never as live. */
function ModeIndicator({ access }: { access: AccessStatus }) {
  const m = MODE[access.model_source] ?? MODE.mock
  const live = access.model_source === 'live'
  const capped = live && access.global_call_limit !== null && access.global_remaining !== null
  return (
    <div role="note" className={cn('flex items-center gap-2.5 rounded-full border py-1.5 pl-3 pr-3.5', m.ring)}>
      <span aria-hidden className={cn('h-2 w-2 shrink-0 rounded-full', m.dot, live && 'shadow-[0_0_0_3px_rgb(8_102_255/0.18)]')} />
      <div className="text-right leading-tight sm:flex sm:items-baseline sm:gap-2 sm:text-left">
        <p className={cn('text-xs font-semibold', m.text)}>{m.label}</p>
        <p className="text-[11px] tabular-nums text-fg-muted sm:text-xs">
          {capped ? `${access.global_remaining} of ${access.global_call_limit} calls left` : m.sub}
        </p>
        <span className="sr-only">{live ? m.sr : `(${access.model_source}): ${m.sr}`}</span>
      </div>
    </div>
  )
}

export default function App() {
  const s = useInspection()
  const [view, setView] = useState<'inspection' | 'report'>('inspection')
  const [access, setAccess] = useState<AccessStatus | null>(null)
  const [locked, setLocked] = useState(false)
  const [offline, setOffline] = useState<string | null>(null)
  const { load } = s
  const inspectionId = s.inspection?.id
  const usedCalls = s.inspection?.usage.model_calls

  const boot = useCallback(async () => {
    try {
      const st = await api.access()
      setAccess(st)
      setOffline(null)
      if (st.auth_required && !st.authenticated) {
        setLocked(true)
        return
      }
      setLocked(false)
      const id = readStoredId()
      if (id) await load(id)
    } catch (e) {
      setOffline(`The ProofCam server could not be reached (${(e as Error).message}). Check that it is running.`)
    }
  }, [load])

  useEffect(() => {
    void boot()
    const onUnauthorized = () => setLocked(true)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [boot])

  // Keep the spending-cap figure current after each analysed photo.
  useEffect(() => {
    if (usedCalls === undefined || locked) return
    api.access().then(setAccess).catch(() => undefined)
  }, [usedCalls, locked])

  let body
  let width = 'max-w-6xl'
  if (locked) {
    width = 'max-w-md'
    body = <AccessGate onSuccess={(st) => {
      setAccess(st)
      setLocked(false)
      const id = inspectionId ?? readStoredId()
      if (id) void load(id)
    }} />
  } else if (!s.inspection) {
    body = (
      <Landing
        onStart={(specId) => void s.start(specId)}
        starting={s.phase === 'loading'}
        message={offline ? (
          <Callout tone="error" title="Server unreachable"
            action={<Button variant="secondary" size="sm" onClick={() => void boot()}><RefreshCw className="h-4 w-4" /> Try again</Button>}>
            {offline}
          </Callout>
        ) : s.notice ? (
          <Callout tone={s.notice.kind}>{s.notice.text}</Callout>
        ) : null}
      />
    )
  } else if (view === 'report') {
    width = 'max-w-3xl'
    body = (
      <Suspense fallback={<p className="py-10 text-center text-sm text-fg-subtle">Loading report…</p>}>
        <ReportView state={s.inspection} modelSource={access?.model_source ?? null} onBack={() => setView('inspection')} />
      </Suspense>
    )
  } else {
    body = <InspectionView s={s} modelSource={access?.model_source ?? null} onReport={() => setView('report')} />
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <header className={cn('sticky top-0 z-30 border-b bg-surface/85 pt-[env(safe-area-inset-top)] backdrop-blur-xl backdrop-saturate-150',
        access && !locked && access.model_source !== 'live' ? 'border-mock/30' : 'border-line')}>
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] sm:pl-[max(1.5rem,env(safe-area-inset-left))] sm:pr-[max(1.5rem,env(safe-area-inset-right))]">
          <Wordmark />
          {access && !locked && <ModeIndicator access={access} />}
        </div>
      </header>
      <main className={cn('mx-auto w-full flex-1 pb-[max(1.5rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-6 sm:pl-[max(1.5rem,env(safe-area-inset-left))] sm:pr-[max(1.5rem,env(safe-area-inset-right))]', width)}>
        {body}
      </main>
      <footer className="mx-auto w-full max-w-6xl px-6 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-2 text-center text-xs text-fg-subtle">
        Built with Meta Muse Spark 1.3 and SAM 3.1. ProofCam is an independent project, not affiliated with or endorsed by Meta.
      </footer>
    </div>
  )
}
