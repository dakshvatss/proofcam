import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { UNAUTHORIZED_EVENT, api } from './api/client'
import type { AccessStatus } from './api/types'
import { AccessGate } from './components/AccessGate'
import { InspectionView } from './components/InspectionView'
import { Landing } from './components/Landing'
import { ReportView } from './components/ReportView'
import { Button } from './components/ui/button'
import { Callout } from './components/ui/callout'
import { Wordmark } from './components/ui/logo'
import { cn } from './lib/utils'
import { readStoredId, useInspection } from './state/useInspection'

/** Which models answer this server: always visible in the app bar so mock output is never mistaken for real
 * inference (also in screen recordings). */
function ModeIndicator({ access }: { access: AccessStatus }) {
  const live = access.model_source === 'live'
  const capped = live && access.global_call_limit !== null && access.global_remaining !== null
  return (
    <div role="note" className="flex items-center gap-2 text-right">
      <div className="leading-tight">
        <p className={cn('text-[11px] font-semibold uppercase tracking-[0.12em]', live ? 'text-accent-strong' : 'text-mock')}>
          {live ? 'Live models' : 'Mock models'}
        </p>
        <p className="text-[11px] tabular-nums text-fg-muted">
          {live ? (capped ? `${access.global_remaining} of ${access.global_call_limit} calls left` : 'Paid analysis')
            : 'Scripted test data'}
        </p>
        <span className="sr-only">
          {live ? 'Every analysed photo makes paid Meta API calls.'
            : `(${access.model_source}): results are scripted test data, not real analysis of your photos.`}
        </span>
      </div>
      <span aria-hidden className={cn('h-2 w-2 shrink-0 rounded-full', live ? 'bg-accent' : 'bg-mock')} />
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
  if (locked) {
    body = <AccessGate onSuccess={(st) => {
      setAccess(st)
      setLocked(false)
      const id = inspectionId ?? readStoredId()
      if (id) void load(id)
    }} />
  } else if (!s.inspection) {
    body = (
      <Landing
        onStart={() => void s.start()}
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
    body = <ReportView inspectionId={s.inspection.id} onBack={() => setView('inspection')} />
  } else {
    body = <InspectionView s={s} onReport={() => setView('report')} />
  }

  return (
    <div className="min-h-dvh">
      <header className={cn('sticky top-0 z-30 border-b bg-canvas/85 pt-[env(safe-area-inset-top)] backdrop-blur-md',
        access && !locked && access.model_source !== 'live' ? 'border-mock/40' : 'border-line')}>
        <div className="mx-auto flex h-14 max-w-xl items-center justify-between gap-3 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
          <Wordmark />
          {access && !locked && <ModeIndicator access={access} />}
        </div>
      </header>
      <main className="mx-auto max-w-xl pb-[max(1.5rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-5">
        {body}
      </main>
    </div>
  )
}
