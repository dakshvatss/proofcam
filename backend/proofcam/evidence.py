"""Evidence ledger: what was observed, in which image, and how it was grounded."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .observation import CameraAction, ObservationExtraction


class SamObjectSummary(BaseModel):
    object_id: str
    box_px: tuple[float, float, float, float]
    confidence: float | None
    mask_area_px: int


class SamGrounding(BaseModel):
    concept: str
    status: Literal["ok", "error", "skipped"]
    objects: list[SamObjectSummary] = Field(default_factory=list)
    error: str | None = None
    diagnostics: list[str] = Field(default_factory=list)


class GroundingLink(BaseModel):
    """Relationship between one Muse claim and real SAM output on the same image."""

    concept: str
    sam_object_id: str | None
    iou: float | None = None
    overlap_px: int | None = None
    corroborated: bool
    note: str
    # No new fields here: stored ObservationRecords are compared byte-for-byte on commit. A generic-fallback link
    # (grounding.FALLBACK_CABLE_CONCEPT) is recognisable because it is stored under the requirement's own concept key
    # ('P3|hdmi cable') while its `concept` is the fallback concept ('cable').


class ObservationRecord(BaseModel):
    seq: int
    image_id: str
    source_name: str
    width: int
    height: int
    responding_to: str | None = Field(None, description="NextViewRequest id this capture answered.")
    # Installation configuration this photo belongs to. Incremented only by an explicit
    # InspectionAgent.mark_installation_changed(); the policy assesses the current epoch only.
    epoch: int = 0
    extraction: ObservationExtraction | None
    extraction_error: str | None = None
    sam: list[SamGrounding] = Field(default_factory=list)
    device_links: dict[str, GroundingLink] = Field(default_factory=dict)  # device_ref -> link
    port_links: dict[str, GroundingLink] = Field(default_factory=dict)    # "port_ref|concept" -> link

    @property
    def usable(self) -> bool:
        e = self.extraction
        return e is not None and e.image_usable and e.shows_inspection_subject


RequirementStatus = Literal["VERIFIED", "VIOLATED", "INSUFFICIENT_EVIDENCE"]
EndpointState = Literal["established", "violated", "contradicted", "unknown"]

GapCode = Literal[
    "CONTRADICTION",
    "DEVICE_NOT_SEEN",
    # Ports of the device were photographed, but only on a device whose identification was uncertain in that photo,
    # so they are not evidence; one photo must tie the device's identifying features to its ports.
    "DEVICE_UNCONFIRMED",
    "PORTS_NOT_VISIBLE",
    "LABEL_ILLEGIBLE",
    "PORT_NOT_FOUND",
    "INSERTION_UNCLEAR",
    "GROUNDING_MISSING",
    "CABLE_CONTINUITY",
]


PortIdentityBasis = Literal["direct_label", "layout_inference", "connector_shape"]


class EvidenceItem(BaseModel):
    seq: int
    image_id: str
    port_ref: str | None = None
    device_ref: str | None = None
    claim: str
    grounding: GroundingLink | None = None
    # How the port in this item was identified (None for non-port evidence such as a cable trace).
    port_basis: PortIdentityBasis | None = None
    # How the DEVICE was identified in this photo: None = Muse identified it with clear certainty (the default);
    # "operator_declared" = Muse was uncertain and the person inspecting confirmed it (an OperatorDeclaration).
    device_basis: Literal["operator_declared"] | None = None


class Gap(BaseModel):
    requirement_id: str
    code: GapCode
    endpoint_index: int | None
    target: str
    missing_fact: str
    context: dict = Field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.requirement_id}:{self.code}:{self.endpoint_index}"


class EndpointAssessment(BaseModel):
    index: int
    device_id: str
    port_label: str
    state: EndpointState
    support: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[EvidenceItem] = Field(default_factory=list)
    # Plug evidence at a port identified only by layout inference while the requirement does not permit
    # inference. Recorded for audit and guidance; never counted as support.
    inferred_only: list[EvidenceItem] = Field(default_factory=list)
    # Observed by Muse with every check met EXCEPT SAM corroboration at the port. Recorded so the report shows what
    # was seen; never support, never counted toward any verdict.
    candidates: list[EvidenceItem] = Field(default_factory=list)
    gap: Gap | None = None


class RequirementAssessment(BaseModel):
    requirement_id: str
    status: RequirementStatus
    explanation: str
    endpoints: list[EndpointAssessment]
    # established = traced in one photo; assumed_by_spec = spec asserts the cable is unique; declared_by_operator =
    # the person inspecting declared it (permitted by the spec, never against visible contrary evidence).
    identity_state: Literal["established", "assumed_by_spec", "declared_by_operator", "unknown", "not_evaluated"]
    identity_evidence: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    # What a VERIFIED / VIOLATED verdict rests on (None while INSUFFICIENT_EVIDENCE, and on records made before M3.7):
    #   visual            - photos alone (Muse claims grounded by SAM, labels read directly);
    #   spec_assumption   - also on assumptions the spec author made (socket shape, layout, unique cable, SAM's
    #                       generic 'cable' fallback); listed in `assumptions`;
    #   operator_assisted - also on statements by the person inspecting; listed in `operator_declarations`.
    # The verdict itself is unchanged by this field; it says how much of it was independently observed.
    assurance: Literal["visual", "spec_assumption", "operator_assisted"] | None = None
    operator_declarations: list[str] = Field(default_factory=list)


class OverallAssessment(BaseModel):
    """Installation-level verdict, derived by policy.overall_assessment from the requirement verdicts only."""

    status: RequirementStatus
    explanation: str
    requirement_statuses: dict[str, RequirementStatus]
    review_required: list[str] = Field(default_factory=list)  # requirement ids with unresolved contradictions


class NextViewRequest(BaseModel):
    id: str
    requirement_id: str
    gap_code: GapCode
    missing_fact: str
    target_region: str
    camera_action: CameraAction
    instruction: str
    rationale: str
    success_criteria: str
    planner: Literal["muse", "deterministic_fallback"]
    based_on_image_id: str | None = Field(description="Image shown to the planner (None for template plans).")
    after_image_id: str | None = Field(None, description="Photo after which this request was issued.")
    gap_key: str | None = None
    planner_error: str | None = None


ViewStatus = Literal["captured", "partial", "not_captured"]


class ViewCheck(BaseModel):
    """Did a photo show what the pending camera request asked for?

    Camera-guidance bookkeeping only. It is computed from the photo's structured observation claims and the
    request's structured gap (never from free text), and it is independent of evidence acceptance and of the
    verdict: a photo can show exactly the requested view and still contribute no accepted evidence (for example
    when the device's identity is not confirmed, or a plug sits in a port of unknown identity).
    """

    request_id: str
    gap_key: str | None
    requirement_id: str
    status: ViewStatus
    shown: list[str] = Field(default_factory=list)  # parts of the requested view this photo showed
    missing: list[str] = Field(default_factory=list)  # parts it did not show
    # Target device(s) identified with certainty in this photo (None: no target device shown). An uncertain
    # identification still makes the view relevant, but its ports are not used as evidence.
    identity_confirmed: bool | None = None
    unconfirmed_devices: list[str] = Field(default_factory=list)  # names of shown target devices not confirmed
    # Counted against the request's gap-attempt limit. False = off-target: refunded; the same request still applies.
    counted_as_attempt: bool


DeclarationKind = Literal["device_identity", "cable_identity"]


class OperatorDeclaration(BaseModel):
    """A statement made by the person inspecting, recorded verbatim with when it was made.

    Never model output and never proof. The policy uses it only where the spec permits it and only within the limits
    in policy.py (an uncertain device claim in that one photo; a cable identity between two endpoints that photos
    already support, with no contrary trace). Every verdict that relies on one says so (assurance
    "operator_assisted").
    """

    id: str
    kind: DeclarationKind
    epoch: int
    statement: str  # the exact sentence the person confirmed
    seq: int | None = None  # device_identity: the photo
    device_id: str | None = None  # device_identity: the spec device
    requirement_id: str | None = None  # cable_identity: the requirement
    created_at: float
