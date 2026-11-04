import { FileText, LoaderCircle, LogOut, RotateCcw, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { currentGuidance, guidanceIsStale } from '../lib/guidance'
import { TEMPLATE_NAME, cn } from '../lib/utils'
import type { InspectionSession } from '../state/useInspection'
import { CameraPanel, CaptureFrame, ControlBar } from './CameraPanel'
import type { DeclarationRequest } from '../api/types'
import { ChangeDialog, DeclareDialog, ProcessingCard } from './Dialogs'
import { GuidanceCard, ProgressPanel, PromptCard, ReviewCard, StopCard, VerdictBadge, VerdictCard } from './Evidence'
import { PhotoHistory, PhotoViewer } from './Photos'
import { LastPhotoCard, Timeline } from './Timeline'
import { Button } from './ui/button'
import { Badge } from './ui/card'
import { Callout } from './ui/callout'

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** The inspection workspace. Phones: one column ordered task -> camera -> result -> progress -> evidence.
 * Desktop: camera and photos on the left, guidance, progress and verdicts on the right. The column wrappers are
 * `display: contents` on phones, so a single DOM (no duplicated elements) serves both layouts. */
export function InspectionView({ s, onReport, modelSource = null }: { s: InspectionSession; onReport: () => void; modelSource?: string | null }) {
  const st = s.inspection!
  // A photo the user picked stays shown until a newer photo arrives; then the newest is shown.
  const [picked, setPicked] = useState<{ seq: number; whenLatest: number | null } | null>(null)
  const [changeOpen, setChangeOpen] = useState(false)
  const [declaring, setDeclaring] = useState<{ req: DeclarationRequest; statement: string; detail: string } | null>(null)
  const latest = st.photos.length ? st.photos[st.photos.length - 1].seq : null
  const selected = picked && picked.whenLatest === latest ? picked.seq : latest
  const setSelected = (seq: number) => setPicked({ seq, whenLatest: latest })
  const shown = st.photos.find((p) => p.seq === selected) ?? null
  const guidance = currentGuidance(st)
  const showPhoto = (seq: number) => {
    setSelected(seq)
    document.getElementById('photo-viewer')?.scrollIntoView?.({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }

  const open = st.status === 'open'
  const working = s.phase === 'uploading' || s.phase === 'recovering' || s.phase === 'loading'
  // Limits (server figures only). Photos and model calls are separate budgets; whichever runs out first ends the
  // inspection. Below photo_min_calls a photo could not be analysed AND grounded, so capture is switched off.
  const u = st.usage
  const minCalls = u.photo_min_calls ?? 2
  const photosLeft = u.max_photos != null && u.photos_used != null ? Math.max(0, u.max_photos - u.photos_used) : null
  const callsLow = open && u.remaining < minCalls
  const nearLimit = open && !callsLow && st.photos.length > 0
    && ((photosLeft !== null && photosLeft <= 2) || u.remaining < minCalls * 4)
  const canCapture = open && s.phase === 'ready' && !st.busy && !callsLow
  const assessed = st.assessments.length ? st.assessments : null
  const reopenable = st.stop_reason !== 'observation_budget_exhausted' && st.stop_reason !== 'model_call_budget_exhausted'
  const multi = st.spec.requirements.length > 1
  const deviceNames = st.spec.devices.map((d) => d.name)
  const deviceList = deviceNames.length > 1 ? `${deviceNames.slice(0, -1).join(', ')} and ${deviceNames.at(-1)}` : deviceNames[0]
  const template = st.spec_id && TEMPLATE_NAME[st.spec_id] !== st.title ? TEMPLATE_NAME[st.spec_id] : undefined
  const step = s.lastStep && s.lastStep.inspection_id === st.id && !working ? s.lastStep : null
  const showCapture = s.phase === 'uploading' || s.phase === 'recovering'
    || ((s.phase === 'confirm' || s.phase === 'retry') && !!s.pending) || (open && (s.phase === 'ready' || s.phase === 'loading'))
  const showTask = !working && (!!guidance || guidanceIsStale(st) || (open && !st.next_view && st.photos.length === 0))
  const showStop = !open && !!st.stop_reason && st.stop_reason !== 'contradiction_requires_review'
  // Mobile order: the next task first while open; the outcome first once stopped.
  const o = open
    ? { task: 'order-1', capture: 'order-2', result: 'order-3', progress: 'order-4', verdicts: 'order-5', photos: 'order-6', timeline: 'order-7' }
    : { task: 'order-1', capture: 'order-4', result: 'order-4', progress: 'order-1', verdicts: 'order-2', photos: 'order-6', timeline: 'order-7' }

  return (
    <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)] lg:items-start lg:gap-x-8 lg:gap-y-6">
      <header className="order-first lg:col-span-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-accent">{template ?? 'Inspection'}</p>
            <h1 className="mt-1 text-xl font-semibold leading-snug tracking-[-0.015em] text-fg sm:text-2xl">{st.title}</h1>
          </div>
          <div className="-mr-2 flex shrink-0 items-center gap-1">
            <Button variant="secondary" size="sm" aria-label="View report" onClick={onReport} className="h-10 px-3">
              <FileText className="h-4 w-4" /><span className="hidden sm:inline">Report</span>
            </Button>
            <Button variant="ghost" size="icon" aria-label="Leave inspection" onClick={s.leave} disabled={working}><LogOut className="h-5 w-5" /></Button>
          </div>
        </div>
        <div className="mt-3.5 flex flex-wrap items-center gap-2">
          {assessed?.map((a) => <VerdictBadge key={a.requirement_id} status={a.status} />)}
          <Badge tone={open ? 'accent' : 'neutral'}>
            <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', open ? 'bg-accent' : 'bg-fg-subtle')} />
            {open ? 'In progress' : 'Stopped'}
          </Badge>
          <Badge><span>{st.photos.length} {st.photos.length === 1 ? 'photo' : 'photos'}</span></Badge>
          {st.epoch > 0 && <Badge tone="warn">Configuration {st.epoch + 1}</Badge>}
        </div>
      </header>

      {(st.engine_changed || st.policy_drift.length > 0 || s.notice || st.review_required.length > 0) && (
        <div className="order-first space-y-3 lg:col-span-2">
          {(st.engine_changed || st.policy_drift.length > 0) && (
            <Callout tone="warn">
              This inspection was recorded by an earlier version of the verification engine.
              {st.policy_drift.length > 0 && ` The current rules would assess ${st.policy_drift.join(', ')} differently.`} Stored
              verdicts are shown unchanged.
            </Callout>
          )}
          {s.notice && <Callout tone={s.notice.kind}>{s.notice.text}</Callout>}
          {st.review_required.length > 0 && (
            <ReviewCard items={st.review_required} canDeclare={reopenable && !working} onDeclare={() => setChangeOpen(true)} />
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- left: camera, result, photos */}
      <div className="contents lg:flex lg:flex-col lg:gap-5">
        {showCapture && (
          <div className={cn(o.capture, 'space-y-3')}>
            {callsLow && (
              <Callout tone="error" title="Model-call limit reached">
                This inspection has {u.remaining} of its {u.model_call_limit} model calls left, fewer than the {minCalls} a
                photo needs to be analysed and grounded, so the camera is off. The verdicts below stand as they are; open
                the report, or start a new inspection.
              </Callout>
            )}
            {nearLimit && (
              <Callout tone="warn" title="Approaching this inspection's limits">
                {photosLeft !== null ? `${photosLeft} of ${u.max_photos} photos and ` : ''}{u.remaining} of {u.model_call_limit} model
                calls left. Take the view requested below first.
              </Callout>
            )}
            {s.phase === 'uploading' && (
              <ProcessingCard startedAt={s.uploadStartedAt} label="Analysing your photo…" image={s.pending?.url} live={modelSource === 'live'} />
            )}
            {s.phase === 'recovering' && <ProcessingCard startedAt={null} label="Checking the saved inspection…" />}
            {(s.phase === 'confirm' || s.phase === 'retry') && s.pending && (
              <>
                <CaptureFrame>
                  <img src={s.pending.url} alt="Photo to analyse" className="h-full w-full object-contain" />
                </CaptureFrame>
                <ControlBar>
                  <p className="mb-3 text-center text-[13px] text-fg-subtle">
                    {s.phase === 'retry' ? 'Retrying sends this same photo again with the same request key.'
                      : modelSource === 'live' ? 'Sending this photo runs a paid analysis with Meta Muse Spark and SAM.'
                        : 'Sending this photo runs an analysis on the server (paid when it uses live models).'}
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <Button variant="secondary" size="lg" onClick={s.discardPhoto}><Trash2 className="h-4 w-4" />{s.phase === 'retry' ? 'Discard' : 'Retake'}</Button>
                    <Button size="lg" onClick={() => void s.sendPhoto()}>
                      {s.phase === 'retry' ? <><RotateCcw className="h-4 w-4" /> Retry</> : <><Send className="h-4 w-4" /> Analyse photo</>}
                    </Button>
                  </div>
                </ControlBar>
              </>
            )}
            {open && (s.phase === 'ready' || s.phase === 'loading') && (
              <CameraPanel active={canCapture} onPhoto={s.stagePhoto} />
            )}
            {s.phase === 'loading' && (
              <p className="flex items-center justify-center gap-2 text-sm text-fg-subtle">
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Loading…
              </p>
            )}
          </div>
        )}

        {step && <div className={o.result}><LastPhotoCard step={step} state={st} /></div>}

        <div className={cn(o.photos, 'space-y-5')}>
          <div id="photo-viewer" className="scroll-mt-24">{shown && <PhotoViewer key={shown.seq} photo={shown} />}</div>
          <PhotoHistory photos={st.photos} selected={selected} onSelect={setSelected} />
        </div>
      </div>

      {/* -------------------------------------------------------------- right: task, progress, verdicts */}
      <div className="contents lg:flex lg:flex-col lg:gap-5">
        {showTask && (
          <div className={o.task}>
            {guidance && <GuidanceCard nv={guidance} spec={st.spec} />}
            {guidanceIsStale(st) && (
              <PromptCard title="New configuration" label="New configuration">
                The installation was changed, so earlier guidance no longer applies. Take a photo of the current setup;
                ProofCam will then decide which view it needs next.
              </PromptCard>
            )}
            {open && !st.next_view && st.photos.length === 0 && (
              <PromptCard title="First photo">
                Start with an overview photo that shows the {deviceList}. ProofCam will then tell you exactly which view it needs next.
              </PromptCard>
            )}
          </div>
        )}

        {multi && <div className={o.progress}><ProgressPanel overall={st.overall} assessments={st.assessments} spec={st.spec} /></div>}

        {(assessed || showStop) && (
          <div className={cn(o.verdicts, 'space-y-5')}>
            {assessed?.map((a) => (
              <VerdictCard key={a.requirement_id} a={a} spec={st.spec} onShowPhoto={showPhoto}
                onDeclare={working ? undefined : (req, statement, detail) => setDeclaring({ req, statement, detail })} />
            ))}
            {showStop && <StopCard reason={st.stop_reason!} onDeclare={() => setChangeOpen(true)} />}
          </div>
        )}

        <div className={cn(o.timeline, 'space-y-4')}>
          <Timeline history={st.history} />
          <footer className="space-y-1.5 px-1 text-xs leading-relaxed text-fg-subtle">
            <p className="tabular-nums">
              {st.usage.model_calls} of {st.usage.model_call_limit} model calls used · est. ${st.usage.estimated_cost_usd.toFixed(3)}
              {u.max_photos ? ` · ${st.photos.length} of ${u.max_photos} photos` : st.spec.max_photos ? ` · up to ${st.spec.max_photos} photos` : ''}
            </p>
            <p>{st.disclaimer}</p>
          </footer>
        </div>
      </div>

      {changeOpen && <ChangeDialog open onCancel={() => setChangeOpen(false)} onConfirm={s.declareChange} />}
      {declaring && (
        <DeclareDialog statement={declaring.statement} detail={declaring.detail} onCancel={() => setDeclaring(null)}
          onConfirm={() => s.declare(declaring.req)} />
      )}
    </div>
  )
}
