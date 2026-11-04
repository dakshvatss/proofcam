import { CircleAlert, KeyRound, LoaderCircle, LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { AccessStatus } from '../api/types'
import { Button } from './ui/button'

/** Access-code screen. The code is exchanged for an HttpOnly session cookie and is not stored by the app. */
export function AccessGate({ onSuccess }: { onSuccess: (status: AccessStatus) => void }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !code.trim()) return
    setBusy(true)
    setError(null)
    try {
      onSuccess(await api.login(code.trim()))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The server could not be reached.')
    } finally {
      setBusy(false)
      setCode('')
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col pt-10">
      <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-line-strong bg-surface">
        <LockKeyhole className="h-5 w-5 text-fg" aria-hidden />
      </span>
      <p className="mt-7 text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-subtle">Private server</p>
      <h1 className="mt-1.5 text-2xl font-semibold tracking-tight">Enter access code</h1>
      <p className="mt-2 text-fg-muted">This ProofCam server is private. Use the access code set on the server.</p>

      <form onSubmit={(e) => void submit(e)} className="mt-8 space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-fg">Access code</span>
          <span className="relative mt-2 block">
            <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <input
              type="password" autoComplete="current-password" autoCapitalize="none" autoCorrect="off" spellCheck={false}
              value={code} onChange={(e) => setCode(e.target.value)} aria-invalid={error ? true : undefined}
              className="h-12 w-full rounded-[var(--radius-control)] border border-line-strong bg-surface pl-10 pr-3 text-base text-fg
                transition-colors duration-150 placeholder:text-fg-subtle focus:border-accent focus:outline-none
                aria-[invalid=true]:border-bad/60"
            />
          </span>
        </label>
        {error && (
          <p role="alert" className="flex items-start gap-2 text-sm text-bad">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {error}
          </p>
        )}
        <Button type="submit" size="lg" className="w-full" disabled={busy || !code.trim()}>
          {busy && <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden />} Continue
        </Button>
      </form>
      <p className="mt-6 text-xs leading-relaxed text-fg-subtle">
        The code is exchanged for a secure session cookie. This app never stores the code itself.
      </p>
    </div>
  )
}
