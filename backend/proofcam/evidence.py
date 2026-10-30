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


class ObservationRecord(BaseModel):
    seq: int
    image_id: str
    source_name: str
    width: int
    height: int
    responding_to: str | None = Field(None, description="NextViewRequest id this capture answered.")
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
    "PORTS_NOT_VISIBLE",
    "LABEL_ILLEGIBLE",
    "PORT_NOT_FOUND",
    "INSERTION_UNCLEAR",
    "GROUNDING_MISSING",
    "CABLE_CONTINUITY",
]


class EvidenceItem(BaseModel):
    seq: int
    image_id: str
    port_ref: str | None = None
    device_ref: str | None = None
    claim: str
    grounding: GroundingLink | None = None


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
    gap: Gap | None = None


class RequirementAssessment(BaseModel):
    requirement_id: str
    status: RequirementStatus
    explanation: str
    endpoints: list[EndpointAssessment]
    identity_state: Literal["established", "assumed_by_spec", "unknown", "not_evaluated"]
    identity_evidence: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


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
    based_on_image_id: str | None
    planner_error: str | None = None
