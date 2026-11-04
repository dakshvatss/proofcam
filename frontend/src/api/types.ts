// Mirrors backend/proofcam/api_models.py and evidence.py (see docs/FRONTEND_HANDOFF.md). Verdicts are produced
// only by the server's deterministic policy; the UI displays them and never derives one.

export type RequirementStatus = 'VERIFIED' | 'VIOLATED' | 'INSUFFICIENT_EVIDENCE'
export type EndpointState = 'established' | 'violated' | 'contradicted' | 'unknown'
export type GapCode =
  | 'CONTRADICTION'
  | 'DEVICE_NOT_SEEN'
  | 'DEVICE_UNCONFIRMED'
  | 'PORTS_NOT_VISIBLE'
  | 'LABEL_ILLEGIBLE'
  | 'PORT_NOT_FOUND'
  | 'INSERTION_UNCLEAR'
  | 'GROUNDING_MISSING'
  | 'CABLE_CONTINUITY'
export type CameraAction =
  | 'move_closer'
  | 'move_to_rear'
  | 'move_to_front'
  | 'move_left'
  | 'move_right'
  | 'look_down_from_above'
  | 'look_up_from_below'
  | 'step_back_wide_view'
  | 'remove_obstruction'
  | 'improve_lighting'
  | 'hold_steady_refocus'

export interface GroundingLink {
  concept: string
  sam_object_id: string | null
  iou?: number | null
  overlap_px?: number | null
  corroborated: boolean
  note: string
}

export interface EvidenceItem {
  seq: number
  image_id: string
  port_ref?: string | null
  device_ref?: string | null
  claim: string
  grounding?: GroundingLink | null
  port_basis?: 'direct_label' | 'layout_inference' | 'connector_shape' | null
  /** null: Muse identified the device with certainty. operator_declared: the person inspecting confirmed it. */
  device_basis?: 'operator_declared' | null
}

export interface Gap {
  requirement_id: string
  code: GapCode
  endpoint_index: number | null
  target: string
  missing_fact: string
  context: Record<string, unknown>
}

export interface EndpointAssessment {
  index: number
  device_id: string
  port_label: string
  state: EndpointState
  support: EvidenceItem[]
  conflicts: EvidenceItem[]
  inferred_only: EvidenceItem[]
  /** Seen by Muse with every check met except SAM corroboration: recorded, never counted (absent before M3.7). */
  candidates?: EvidenceItem[]
  gap: Gap | null
}

export interface RequirementAssessment {
  requirement_id: string
  status: RequirementStatus
  explanation: string
  endpoints: EndpointAssessment[]
  identity_state: 'established' | 'assumed_by_spec' | 'declared_by_operator' | 'unknown' | 'not_evaluated'
  identity_evidence: EvidenceItem[]
  gaps: Gap[]
  contradictions: string[]
  assumptions: string[]
  /** What a final verdict rests on (null while not enough evidence, and on records before M3.7). */
  assurance?: Assurance | null
  /** Statements by the person inspecting that this verdict relies on. */
  operator_declarations?: string[]
}

export type Assurance = 'visual' | 'spec_assumption' | 'operator_assisted'

/** A statement made by the person inspecting, recorded verbatim. Never model output, never proof. */
export interface OperatorDeclaration {
  id: string
  kind: 'device_identity' | 'cable_identity'
  epoch: number
  statement: string
  seq?: number | null
  device_id?: string | null
  requirement_id?: string | null
  created_at: number
}

export type DeclarationRequest =
  | { type: 'device_identity'; seq: number; device_id: string }
  | { type: 'cable_identity'; requirement_id: string }

/** Did a photo show the view the previous camera request asked for? Guidance bookkeeping only: independent of
 * the evidence the policy accepted and of every verdict. */
export type ViewStatus = 'captured' | 'partial' | 'not_captured'
export interface ViewCheck {
  request_id: string
  gap_key: string | null
  requirement_id: string
  status: ViewStatus
  shown: string[]
  missing: string[]
  identity_confirmed: boolean | null
  unconfirmed_devices: string[]
  counted_as_attempt: boolean
}

export interface NextViewRequest {
  id: string
  requirement_id: string
  gap_code: GapCode
  missing_fact: string
  target_region: string
  camera_action: CameraAction
  instruction: string
  rationale: string
  success_criteria: string
  planner: 'muse' | 'deterministic_fallback'
  based_on_image_id: string | null
  after_image_id?: string | null
  gap_key?: string | null
  planner_error?: string | null
}

export interface ReviewItem {
  requirement_id: string
  photos: number[]
  contradictions: string[]
  action: 'review_installation'
  message: string
}

export interface Usage {
  model_calls: number
  model_call_limit: number
  remaining: number
  calls_by_status: Record<string, number>
  estimated_cost_usd: number
  cost_basis: string
  /** Photo budget, separate from the call budget (absent on responses stored before M3.7). */
  photos_used?: number | null
  max_photos?: number | null
  /** Fewer calls left than this: a photo could not be analysed and grounded, so capture is disabled. */
  photo_min_calls?: number | null
}

export interface PhotoInfo {
  seq: number
  image_id: string
  source_name: string
  width: number
  height: number
  epoch: number
  superseded: boolean
  usable: boolean
  responding_to: string | null
  photo_url: string
  overlay_url: string | null
}

export type Connector = 'ethernet' | 'hdmi' | 'usb' | 'power' | 'optical' | 'coaxial'

/** Installation verdict derived by the server's policy from all requirement verdicts (never by the UI). */
export interface OverallAssessment {
  status: RequirementStatus
  explanation: string
  requirement_statuses: Record<string, RequirementStatus>
  review_required: string[]
}

/** A specification the server can start now (GET /api/specs). Drafts with unconfirmed facts are never listed. */
export interface SpecSummary {
  spec_id: string
  title: string
  devices: string[]
  requirements: {
    id: string
    text: string
    connector: string
    cable_color?: string | null
    endpoints?: { device: string; port: string; flexible: boolean }[]
  }[]
  max_photos?: number | null
}

export interface ConnectionRequirement {
  id: string
  kind: 'connection'
  text: string
  /** null = any colour accepted (identity and continuity still required). */
  cable_color: string | null
  cable_type: string
  /** Connector family at both ends (absent from servers before M3.4: then ethernet). */
  connector?: Connector
  endpoints: { device_id: string; port_label: string; label_aliases: string[]; selector?: Record<string, unknown> | null }[]
  cable_identity: string
  port_identity?: string
}

export interface InspectionSpec {
  id: string
  title: string
  devices: { id: string; name: string; description: string; sam_concept: string }[]
  requirements: ConnectionRequirement[]
  max_photos?: number | null
  allow_device_identity_declarations?: boolean
}

export type StopReason =
  | 'all_requirements_resolved'
  | 'no_visually_resolvable_gaps'
  | 'observation_budget_exhausted'
  | 'model_call_budget_exhausted'
  | 'contradiction_requires_review'

export interface InspectionState {
  id: string
  spec_id: string | null
  title: string
  status: 'open' | 'stopped'
  stop_reason: string | null
  epoch: number
  version: number
  engine_version: string
  engine_changed: boolean
  policy_drift: string[]
  busy: boolean
  created_at?: number | null
  spec: InspectionSpec
  photos: PhotoInfo[]
  assessments: RequirementAssessment[]
  overall?: OverallAssessment | null
  next_view: NextViewRequest | null
  review_required: ReviewItem[]
  exhausted_gaps: Record<string, string>
  history: Record<string, unknown>[]
  declarations?: OperatorDeclaration[]
  usage: Usage
  disclaimer: string
}

export interface StepResponse {
  inspection_id: string
  seq: number
  image_id: string
  duplicate_of: number | null
  notes: string[]
  status: 'open' | 'stopped'
  stop_reason: string | null
  assessments: RequirementAssessment[]
  overall?: OverallAssessment | null
  next_view: NextViewRequest | null
  review_required: ReviewItem[]
  view_check?: ViewCheck | null
  version: number
  usage: Usage
  replayed: boolean
}

export interface Health {
  status: 'ok' | 'degraded'
  schema_version: number
  integrity_problems: string[]
  engine_version: string
  model_source: string
}

export interface AccessStatus {
  auth_required: boolean
  authenticated: boolean
  model_source: string
  global_model_calls: number | null
  global_call_limit: number | null
  global_remaining: number | null
}
