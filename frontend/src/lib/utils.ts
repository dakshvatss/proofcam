import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { CameraAction, GapCode, RequirementStatus } from '../api/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const STATUS_TEXT: Record<RequirementStatus, string> = {
  VERIFIED: 'Verified',
  VIOLATED: 'Violated',
  INSUFFICIENT_EVIDENCE: 'Not enough evidence',
}

export const STOP_TEXT: Record<string, { title: string; detail: string; reopenable: boolean }> = {
  all_requirements_resolved: {
    title: 'Inspection complete',
    detail: 'Every requirement has a final verdict.',
    reopenable: true,
  },
  no_visually_resolvable_gaps: {
    title: 'No further photos can help',
    detail: 'The remaining evidence could not be obtained after the allowed attempts, so the requirement stays unresolved.',
    reopenable: true,
  },
  contradiction_requires_review: {
    title: 'Review needed',
    detail: 'The photos contradict each other. Another photo of the same setup cannot resolve this.',
    reopenable: true,
  },
  observation_budget_exhausted: {
    title: 'Photo limit reached',
    detail: 'This inspection used all of its photos. Start a new inspection to continue.',
    reopenable: false,
  },
  model_call_budget_exhausted: {
    title: 'Analysis limit reached',
    detail: 'This inspection used all of its model calls. Start a new inspection to continue.',
    reopenable: false,
  },
}

export function stopText(reason: string | null) {
  if (!reason) return null
  return STOP_TEXT[reason] ?? { title: 'Inspection stopped', detail: `Stop reason: ${reason}`, reopenable: false }
}

export const ACTION_TEXT: Record<CameraAction, string> = {
  move_closer: 'Move closer',
  move_to_rear: 'Go to the back',
  move_to_front: 'Go to the front',
  move_left: 'Move left',
  move_right: 'Move right',
  look_down_from_above: 'Look down from above',
  look_up_from_below: 'Look up from below',
  step_back_wide_view: 'Step back for a wide view',
  remove_obstruction: 'Clear the view',
  improve_lighting: 'Improve the lighting',
  hold_steady_refocus: 'Hold steady and refocus',
}

export const GAP_TEXT: Record<GapCode, string> = {
  CONTRADICTION: 'Photos disagree',
  DEVICE_NOT_SEEN: 'Device not identified',
  PORTS_NOT_VISIBLE: 'Ports not visible',
  LABEL_ILLEGIBLE: 'Port label not readable',
  PORT_NOT_FOUND: 'Target port not found',
  INSERTION_UNCLEAR: 'Plug not clearly seen',
  GROUNDING_MISSING: 'Cable not confirmed at the port',
  CABLE_CONTINUITY: 'Cable run not shown end to end',
}
