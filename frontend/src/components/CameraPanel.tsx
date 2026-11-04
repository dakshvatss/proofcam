import { Camera, CameraOff, ImageUp, LoaderCircle, ShieldAlert, SwitchCamera } from 'lucide-react'
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { isIOS, isStandalone, prepareUpload } from '../lib/image'
import { cn } from '../lib/utils'
import { Button } from './ui/button'

type Mode = 'off' | 'starting' | 'live' | 'error'

function permissionHelp(): string {
  if (isIOS())
    return isStandalone()
      ? 'Camera permission was denied. Open iPhone Settings → Apps → Safari → Camera and choose Ask or Allow, then reopen this app. Or upload a photo instead.'
      : 'Camera permission was denied. In Safari, tap the page-settings button (aA) in the address bar → Website Settings → Camera → Allow, then try again. Or upload a photo instead.'
  return 'Camera permission was denied. Allow camera access for this site in your browser settings, or upload a photo instead.'
}

function describeCameraError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return permissionHelp()
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No camera was found on this device. Upload a photo instead.'
  if (name === 'NotReadableError' || name === 'AbortError')
    return 'The camera is in use by another app or was interrupted. Close other camera apps and tap Open camera again.'
  return 'The camera could not be started. Upload a photo instead.'
}

/** Live camera preview with capture, plus an upload fallback. The stream runs only while `active` and only after
 * the user asks for it. It is stopped after each capture, when the panel is hidden or unmounted, and when the page
 * goes to the background (Safari ends camera tracks then anyway); the user simply taps Open camera again. */
export function CameraPanel({ active, onPhoto }: { active: boolean; onPhoto: (photo: Blob, name: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<Mode>('off')
  const [error, setError] = useState<string | null>(null)
  const [paused, setPaused] = useState(false)
  const [facing, setFacing] = useState<'environment' | 'user'>('environment')
  const [canSwitch, setCanSwitch] = useState(false)
  const [preparing, setPreparing] = useState(false)

  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  const secure = typeof window !== 'undefined' && window.isSecureContext

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => {
      t.onended = null
      t.stop()
    })
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setMode((m) => (m === 'error' ? m : 'off'))
  }, [])

  const open = useCallback(async (which: 'environment' | 'user') => {
    stop()
    setError(null)
    setPaused(false)
    setMode('starting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        // Rear camera preferred; 4:3 matches iPhone photos. `ideal` never fails on devices that cannot match.
        video: { facingMode: { ideal: which }, width: { ideal: 1920 }, height: { ideal: 1440 } },
      })
      streamRef.current = stream
      stream.getVideoTracks().forEach((t) => {
        t.onended = () => { // e.g. a phone call, another app took the camera, or iOS backgrounded the page
          stop()
          setPaused(true)
        }
      })
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play().catch(() => undefined)
      }
      const devices = await navigator.mediaDevices.enumerateDevices().catch(() => [])
      setCanSwitch(devices.filter((d) => d.kind === 'videoinput').length > 1)
      setMode('live')
    } catch (e) {
      streamRef.current = null
      setError(describeCameraError(e))
      setMode('error')
    }
  }, [stop])

  useEffect(() => {
    if (!active) stop()
  }, [active, stop])
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden' && streamRef.current) {
        stop()
        setPaused(true)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      stop()
    }
  }, [stop])

  const capture = () => {
    const v = videoRef.current
    if (!v || !v.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = v.videoWidth
    canvas.height = v.videoHeight
    canvas.getContext('2d')?.drawImage(v, 0, 0)
    canvas.toBlob((blob) => {
      if (!blob) {
        setError('The photo could not be captured. Try again or upload a photo.')
        return
      }
      stop() // the camera is not needed while the photo is reviewed and analysed
      onPhoto(blob, `camera-${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`)
    }, 'image/jpeg', 0.92)
  }

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    stop()
    setPreparing(true)
    try {
      const { blob, name } = await prepareUpload(f)
      onPhoto(blob, name)
    } finally {
      setPreparing(false)
    }
  }

  const status = mode === 'starting' ? (
    <FrameMessage icon={<LoaderCircle className="h-6 w-6 animate-spin text-white/80" aria-hidden />}>
      <p className="text-white/75">Starting the camera…</p>
    </FrameMessage>
  ) : mode === 'error' ? (
    <FrameMessage icon={<CameraOff className="h-6 w-6 text-[#ffc078]" aria-hidden />}>
      <p role="alert" className="text-white">{error}</p>
    </FrameMessage>
  ) : !supported || !secure ? (
    <FrameMessage icon={<ShieldAlert className="h-6 w-6 text-white/70" aria-hidden />}>
      <p className="text-white/80">
        Camera access needs a secure page (HTTPS, or http://localhost on this computer). A phone opening this
        app through a plain http:// network address will block the camera. Upload a photo instead.
      </p>
    </FrameMessage>
  ) : paused ? (
    <FrameMessage icon={<Camera className="h-6 w-6 text-[#7fb2ff]" aria-hidden />}>
      <p role="status" className="text-white">The camera stopped (the app was in the background or the camera was interrupted). Tap Open camera to continue.</p>
    </FrameMessage>
  ) : (
    <FrameMessage icon={<Camera className="h-6 w-6 text-white/80" aria-hidden />}>
      <p className="text-white/80">The preview is only for aiming. ProofCam analyses the photo you capture.</p>
    </FrameMessage>
  )

  return (
    <div className="space-y-3">
      <CaptureFrame>
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          aria-label="Live camera preview"
          className={mode === 'live' ? 'h-full w-full object-cover' : 'hidden'}
        />
        {mode === 'live' ? (
          <>
            <div className="viewfinder-corners pointer-events-none absolute inset-5" aria-hidden />
            <span className="pointer-events-none absolute left-3.5 top-3.5 rounded-full bg-black/50 px-2.5 py-1 text-xs font-medium text-white/90 backdrop-blur-md">
              Preview · aim only
            </span>
          </>
        ) : status}
      </CaptureFrame>

      {/* Thumb-reachable controls, kept above the iPhone home indicator. */}
      <ControlBar>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          <button
            type="button" aria-label="Upload photo" onClick={() => fileRef.current?.click()} disabled={!active || preparing}
            className="flex h-14 min-w-14 flex-col items-center justify-center gap-1 justify-self-start rounded-[var(--radius-control)] px-3 text-fg-muted
              transition-colors duration-150 hover:bg-raised hover:text-fg disabled:pointer-events-none disabled:opacity-40"
          >
            {preparing ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden /> : <ImageUp className="h-5 w-5" aria-hidden />}
            <span className="text-xs font-medium">{preparing ? 'Preparing…' : 'Upload'}</span>
          </button>

          {mode === 'live' ? (
            <button
              type="button" aria-label="Capture" onClick={capture} disabled={!active}
              className="group grid h-[78px] w-[78px] place-items-center rounded-full border-[3px] border-accent bg-surface shadow-[var(--shadow-lift)]
                transition-transform duration-150 active:scale-95 disabled:opacity-40"
            >
              <span className="brand-gradient h-[60px] w-[60px] rounded-full transition-[filter] duration-150 group-hover:brightness-110" />
            </button>
          ) : (
            <Button size="lg" className="h-14 min-w-44 rounded-full px-7" onClick={() => void open(facing)}
              disabled={!active || !supported || !secure || mode === 'starting'}>
              <Camera className="h-5 w-5" aria-hidden /> Open camera
            </Button>
          )}

          {mode === 'live' && canSwitch ? (
            <button
              type="button" aria-label="Switch camera"
              className="grid h-12 w-12 place-items-center justify-self-end rounded-full border border-line-strong bg-surface text-fg shadow-[var(--shadow-card)] transition-colors duration-150 hover:bg-raised"
              onClick={() => { const next = facing === 'environment' ? 'user' : 'environment'; setFacing(next); void open(next) }}
            >
              <SwitchCamera className="h-5 w-5" aria-hidden />
            </button>
          ) : <span aria-hidden />}
        </div>
      </ControlBar>
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => void onFile(e)} data-testid="file-input" />
    </div>
  )
}

function FrameMessage({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center text-sm leading-relaxed">
      <span className="grid h-14 w-14 place-items-center rounded-full border border-white/15 bg-white/[0.06]">{icon}</span>
      <div className="max-w-[32ch]">{children}</div>
    </div>
  )
}

/** The fixed 3:4 (portrait) / 4:3 (wide) frame shared by the camera, the photo awaiting analysis and the
 * analysing state, so the capture area never jumps between states. Dark on purpose, like a viewfinder. */
export function CaptureFrame({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn('relative mx-auto aspect-[3/4] max-h-[58dvh] w-full overflow-hidden rounded-[var(--radius-panel)] bg-viewport shadow-[var(--shadow-lift)]',
      'sm:aspect-[4/3] phone-landscape:aspect-[4/3] phone-landscape:h-[74dvh] phone-landscape:max-h-none phone-landscape:w-auto phone-landscape:max-w-full', className)}>
      {children}
    </div>
  )
}

/** Sticky bottom bar for the primary capture actions, padded for the home indicator. */
export function ControlBar({ children }: { children: ReactNode }) {
  return (
    <div className="sticky bottom-0 z-20 -mx-4 border-t border-line bg-surface/90 px-4 pt-3 backdrop-blur-xl pb-[max(0.75rem,env(safe-area-inset-bottom))]
      sm:mx-0 sm:rounded-[var(--radius-panel)] sm:border sm:shadow-[var(--shadow-card)]">
      {children}
    </div>
  )
}
