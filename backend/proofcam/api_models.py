"""Wire schemas for the ProofCam HTTP API (Milestone 1).

Requirement statuses inside these responses are exactly what the deterministic policy produced and the store
committed; nothing here computes or alters a verdict.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import NextViewRequest, RequirementAssessment
from .spec import InspectionSpec


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(_Wire):
    error: str
    message: str


class CreateInspectionRequest(_Wire):
    """Exactly one of spec_id (an allow-listed file in data/specs/) or an inline spec."""

    spec_id: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    spec: InspectionSpec | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> CreateInspectionRequest:
        if (self.spec_id is None) == (self.spec is None):
            raise ValueError("give exactly one of spec_id or spec")
        return self


class EventRequest(_Wire):
    type: Literal["installation_changed"]
    reason: str = Field(min_length=1, max_length=500)


class Usage(_Wire):
    """Model-call accounting. `model_calls` counts every HTTP attempt reserved before it was sent (retries
    included, interrupted attempts included); `estimated_cost_usd` is computed from the committed trace only."""

    model_calls: int
    model_call_limit: int
    remaining: int
    calls_by_status: dict[str, int]
    estimated_cost_usd: float
    cost_basis: str = "list prices applied to committed trace events; excludes calls with unknown outcome"


class PhotoInfo(_Wire):
    seq: int
    image_id: str
    source_name: str
    width: int
    height: int
    epoch: int
    superseded: bool
    usable: bool
    responding_to: str | None
    photo_url: str
    overlay_url: str | None


class InspectionState(_Wire):
    id: str
    spec_id: str | None
    title: str
    status: Literal["open", "stopped"]
    stop_reason: str | None
    epoch: int
    version: int
    engine_version: str
    engine_changed: bool = Field(description="The verdict/guidance code differs from the one that recorded this "
                                             "inspection.")
    policy_drift: list[str] = Field(description="Requirement ids whose stored assessment the current policy would "
                                                "not reproduce. Stored verdicts are never silently replaced.")
    busy: bool
    spec: InspectionSpec
    photos: list[PhotoInfo]
    assessments: list[RequirementAssessment]
    next_view: NextViewRequest | None
    exhausted_gaps: dict[str, str]
    history: list[dict[str, Any]]
    usage: Usage
    disclaimer: str


class StepResponse(_Wire):
    inspection_id: str
    seq: int
    image_id: str
    duplicate_of: int | None
    notes: list[str]
    status: Literal["open", "stopped"]
    stop_reason: str | None
    assessments: list[RequirementAssessment]
    next_view: NextViewRequest | None
    version: int
    usage: Usage
    replayed: bool = Field(False, description="True when this is the stored response of an earlier request with "
                                              "the same Idempotency-Key (no new step, no model calls).")


class Health(_Wire):
    status: Literal["ok", "degraded"]
    schema_version: int
    integrity_problems: list[str]
    engine_version: str
    model_source: str
