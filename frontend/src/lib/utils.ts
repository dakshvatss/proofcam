import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { Assurance, CameraAction, GapCode, RequirementStatus, ViewStatus } from '../api/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const STATUS_TEXT: Record<RequirementStatus, string> = {
  VERIFIED: 'Verified',
  VIOLATED: 'Violated',
  INSUFFICIENT_EVIDENCE: 'Not enough evidence',
}

/** Display name of a requirement's connector family; older servers omit it (always Ethernet then). */
export const CONNECTOR_TEXT: Record<string, string> = {
  ethernet: 'Ethernet',
  hdmi: 'HDMI',
  usb: 'USB',
  power: 'Power',
  optical: 'Optical',
  coaxial: 'Coaxial',
}

export function connectionName(req: { connector?: string } | undefined) {
  return `${CONNECTOR_TEXT[req?.connector ?? 'ethernet'] ?? req?.connector} connection`
}

/** Progress wording for one connection (E): never a percentage, always the server's verdict or "Pending". */
export const PROGRESS_TEXT: Record<RequirementStatus | 'PENDING', string> = {
  PENDING: 'Pending',
  VERIFIED: 'Verified',
  VIOLATED: 'Violated',
  INSUFFICIENT_EVIDENCE: 'Needs evidence',
}

/** Friendly template names for known specification ids (the server title is still shown beneath). */
export const TEMPLATE_NAME: Record<string, string> = {
  my_setup: 'Network Connection Verification',
  ps5_home_setup: 'Home Entertainment Installation',
  ps5_home_setup_assisted: 'Home Entertainment · operator-assisted',
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

/** What a final verdict rests on (server field `assurance`); the verdict itself is unchanged by it. */
export const ASSURANCE_TEXT: Record<Assurance, string> = {
  visual: 'Rests on the photos alone',
  spec_assumption: 'Rests on the photos and disclosed spec assumptions',
  operator_assisted: 'Relies on your statements: not independently verified',
}

/** Verdict wording. Operator-assisted templates name the provenance of a VERIFIED verdict; others are unchanged. */
export function verdictText(status: RequirementStatus, assurance: Assurance | null | undefined, assisted: boolean) {
  if (!assisted || status !== 'VERIFIED' || !assurance) return STATUS_TEXT[status]
  return assurance === 'operator_assisted' ? 'Verified — operator-assisted' : 'Verified — visual evidence'
}

export const IDENTITY_TEXT: Record<string, string> = {
  established: 'traced in one photo',
  assumed_by_spec: 'assumed by the spec',
  declared_by_operator: 'declared by you · not traced',
}

export const VIEW_TEXT: Record<ViewStatus, string> = {
  captured: 'Requested view captured',
  partial: 'Requested area partially visible',
  not_captured: 'Requested view not captured',
}

export const GAP_TEXT: Record<GapCode, string> = {
  CONTRADICTION: 'Photos disagree',
  DEVICE_NOT_SEEN: 'Device not identified',
  DEVICE_UNCONFIRMED: 'Device identity not confirmed',
  PORTS_NOT_VISIBLE: 'Ports not visible',
  LABEL_ILLEGIBLE: 'Port label not readable',
  PORT_NOT_FOUND: 'Target port not found',
  INSERTION_UNCLEAR: 'Plug not clearly seen',
  GROUNDING_MISSING: 'Cable not confirmed at the port',
  CABLE_CONTINUITY: 'Cable run not shown end to end',
}
