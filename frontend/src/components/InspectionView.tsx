import { FileText, LoaderCircle, LogOut, RotateCcw, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { currentGuidance, guidanceIsStale } from '../lib/guidance'
import { cn } from '../lib/utils'
import type { InspectionSession } from '../state/useInspection'
import { CameraPanel, CaptureFrame, ControlBar } from './CameraPanel'
import { ChangeDialog, ProcessingCard } from './Dialogs'
import { GuidanceCard, PromptCard, ReviewCard, StopCard, VerdictBadge, VerdictCard } from './Evidence'
import { PhotoHistory, PhotoViewer } from './Photos'
import { Button } from './ui/button'
import { Badge } from './ui/card'
import { Callout } from './ui/callout'

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function InspectionView({ s, onReport }: { s: InspectionSession; onReport: () => void }) {
  const st = s.inspection!
  // A photo the user picked stays shown until a newer photo arrives; then the newest is shown.
  const [picked, setPicked] = useState<{ seq: number; whenLatest: number | null } | null>(null)
  const [changeOpen, setChangeOpen] = useState(false)
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
  const canCapture = open && s.phase === 'ready' && !st.busy
  const overall = st.assessments.length ? st.assessments : null
  const reopenable = st.stop_reason !== 'observation_budget_exhausted' && st.stop_reason !== 'model_call_budget_exhausted'

  const verdicts = overall?.map((a) => <VerdictCard key={a.requirement_id} a={a} spec={st.spec} onShowPhoto={showPhoto} />)

  return (
    <div className="space-y-5">
      <header>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-fg-subtle">Inspection</p>
            <h1 className="mt-1 text-[17px] font-semibold leading-snug tracking-tight text-fg">{st.title}</h1>
          </div>
          <div className="-mr-2 -mt-1 flex shrink-0">
            <Button variant="ghost" size="icon" aria-label="View report" onClick={onReport}><FileText className="h-5 w-5" /></Button>
            <Button variant="ghost" size="icon" aria-label="Leave inspection" onClick={s.leave} disabled={working}><LogOut className="h-5 w-5" /></Button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {overall?.map((a) => <VerdictBadge key={a.requirement_id} status={a.status} />)}
          <Badge>
            <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', open ? 'bg-accent' : 'bg-fg-subtle')} />
            {open ? 'In progress' : 'Stopped'}
          </Badge>
          <Badge><span>{st.photos.length} {st.photos.length === 1 ? 'photo' : 'photos'}</span></Badge>
          {st.epoch > 0 && <Badge tone="warn">Configuration {st.epoch + 1}</Badge>}
        </div>
      </header>

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

      {/* Stopped: the outcome leads. */}
      {!open && verdicts}
      {!open && st.stop_reason && st.stop_reason !== 'contradiction_requires_review' && (
        <StopCard reason={st.stop_reason} onDeclare={() => setChangeOpen(true)} />
      )}

      {/* Open: the next action and the camera lead; results follow. */}
      {guidance && !working && <GuidanceCard nv={guidance} />}
      {guidanceIsStale(st) && !working && (
        <PromptCard title="New configuration" label="New configuration">
          The installation was changed, so earlier guidance no longer applies. Take a photo of the current setup;
          ProofCam will then decide which view it needs next.
        </PromptCard>
      )}
      {open && !st.next_view && st.photos.length === 0 && !working && (
        <PromptCard title="First photo">
          Start with a photo that shows the router and the switch. ProofCam will then tell you exactly which view it needs next.
        </PromptCard>
      )}

      {s.phase === 'uploading' && <ProcessingCard startedAt={s.uploadStartedAt} label="Analysing your photo…" image={s.pending?.url} />}
      {s.phase === 'recovering' && <ProcessingCard startedAt={null} label="Checking the saved inspection…" />}
      {(s.phase === 'confirm' || s.phase === 'retry') && s.pending && (
        <div className="space-y-3">
          <CaptureFrame>
            <img src={s.pending.url} alt="Photo to analyse" className="h-full w-full object-contain" />
          </CaptureFrame>
          <ControlBar>
            <p className="mb-3 text-center text-xs text-fg-subtle">
              {s.phase === 'retry' ? 'Retrying sends this same photo again with the same request key.'
                : 'Sending this photo runs a paid analysis on the server (unless it is using mock models).'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Button variant="secondary" size="lg" onClick={s.discardPhoto}><Trash2 className="h-4 w-4" />{s.phase === 'retry' ? 'Discard' : 'Retake'}</Button>
              <Button size="lg" onClick={() => void s.sendPhoto()}>
                {s.phase === 'retry' ? <><RotateCcw className="h-4 w-4" /> Retry</> : <><Send className="h-4 w-4" /> Analyse photo</>}
              </Button>
            </div>
          </ControlBar>
        </div>
      )}
      {open && (s.phase === 'ready' || s.phase === 'loading') && (
        <CameraPanel active={canCapture} onPhoto={s.stagePhoto} />
      )}
      {s.phase === 'loading' && (
        <p className="flex items-center justify-center gap-2 text-sm text-fg-subtle">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> Loading…
        </p>
      )}

      {s.lastStep && s.lastStep.notes.length > 0 && (
        <Callout aria-label="Notes on the last photo" title="Notes on the last photo">
          <div className="space-y-1">{s.lastStep.notes.map((n) => <p key={n}>{n}</p>)}</div>
        </Callout>
      )}

      {open && verdicts}

      <div id="photo-viewer" className="scroll-mt-20">{shown && <PhotoViewer key={shown.seq} photo={shown} />}</div>
      <PhotoHistory photos={st.photos} selected={selected} onSelect={setSelected} />

      <footer className="space-y-1.5 border-t border-line pt-4 text-xs leading-relaxed text-fg-subtle">
        <p className="tabular-nums">
          {st.usage.model_calls} of {st.usage.model_call_limit} model calls used · est. ${st.usage.estimated_cost_usd.toFixed(3)}
        </p>
        <p>{st.disclaimer}</p>
      </footer>

      {changeOpen && <ChangeDialog open onCancel={() => setChangeOpen(false)} onConfirm={s.declareChange} />}
    </div>
  )
}
