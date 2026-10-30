"""Bounded active-inspection loop.

    observe(image):  OBSERVE (Muse) -> GROUND (SAM) -> ASSESS (policy) -> IDENTIFY GAP -> PLAN NEXT VIEW
    The caller supplies the next image (camera capture, CLI file, ...) and calls observe() again.

Stops when every requirement is VERIFIED/VIOLATED, when no remaining gap can be advanced
(attempt limit reached or the planner says it is not visually resolvable), or on budget exhaustion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from .config import Settings
from .evidence import Gap, NextViewRequest, ObservationRecord, RequirementAssessment
from .grounding import GroundingRun, link_devices, link_ports, run_sam
from .images import NormalizedImage
from .meta_client import BudgetExhausted, MetaAPIError, MetaClient
from .muse import ModelOutputError, extract_observations, plan_next_view, summarize_extraction
from .policy import assess_requirement, select_gap
from .spec import InspectionSpec

StopReason = Literal["all_requirements_resolved", "no_visually_resolvable_gaps",
                     "observation_budget_exhausted", "model_call_budget_exhausted"]


@dataclass
class StepResult:
    seq: int
    image_id: str
    assessments: list[RequirementAssessment]
    next_view: NextViewRequest | None
    stop_reason: StopReason | None
    notes: list[str] = field(default_factory=list)


class InspectionAgent:
    def __init__(self, spec: InspectionSpec, client: MetaClient, settings: Settings,
                 require_grounding: bool = True) -> None:
        self.spec = spec
        self.client = client
        self.trace = client.trace
        self.settings = settings
        self.budget = settings.budget
        self.require_grounding = require_grounding
        self.observations: list[ObservationRecord] = []
        self.images: dict[str, NormalizedImage] = {}
        self.grounding_runs: dict[int, GroundingRun] = {}
        self.requests: list[NextViewRequest] = []
        self.gap_attempts: dict[str, int] = {}
        self.exhausted: dict[str, str] = {}  # gap key -> reason
        self.assessments: list[RequirementAssessment] = []
        self.stop_reason: StopReason | None = None

    @property
    def done(self) -> bool:
        return self.stop_reason is not None

    def _assess(self) -> list[RequirementAssessment]:
        self.assessments = [assess_requirement(self.spec, r, self.observations, self.require_grounding)
                            for r in self.spec.requirements]
        for a in self.assessments:
            self.trace.add("policy", "assess", detail={"requirement": a.requirement_id, "status": a.status,
                                                        "gaps": [g.key for g in a.gaps]})
        return self.assessments

    def _stop(self, reason: StopReason, seq: int, image_id: str, notes: list[str]) -> StepResult:
        self.stop_reason = reason
        self.trace.add("stop", reason)
        return StepResult(seq, image_id, self.assessments, None, reason, notes)

    async def observe(self, image: NormalizedImage) -> StepResult:
        if self.done:
            raise RuntimeError(f"inspection already stopped: {self.stop_reason}")
        seq = len(self.observations) + 1
        responding_to = self.requests[-1].id if self.requests else None
        notes: list[str] = []
        self.images[image.image_id] = image
        t0 = time.perf_counter()
        self.trace.add("agent_step", "observe", image_id=image.image_id,
                       detail={"seq": seq, "responding_to": responding_to, "size": [image.width, image.height]})

        # OBSERVE
        ext, err, budget_hit = None, None, False
        try:
            ext = await extract_observations(self.client, self.spec, image)
        except BudgetExhausted as e:
            err, budget_hit = str(e), True
        except (MetaAPIError, ModelOutputError) as e:
            err = str(e)
            notes.append(f"Observation extraction failed; no facts were taken from this photo: {e}")
        rec = ObservationRecord(seq=seq, image_id=image.image_id, source_name=image.source_name,
                                width=image.width, height=image.height, responding_to=responding_to,
                                extraction=ext, extraction_error=err)

        # GROUND (only photos that show the subject; SAM cannot help otherwise)
        if ext is not None and rec.usable:
            dev_concepts = {d.id: d.sam_concept for d in self.spec.devices}
            seen_ids = {d.spec_device_id for d in ext.devices if d.spec_device_id}
            cable_concepts = sorted({r.cable_concept() for r in self.spec.requirements})
            concepts = cable_concepts + sorted({dev_concepts[i] for i in seen_ids})
            concepts = list(dict.fromkeys(concepts))[: self.budget.max_sam_calls_per_image]
            run = await run_sam(self.client, image, concepts)
            self.grounding_runs[seq] = run
            rec.sam = run.groundings
            rec.device_links = link_devices(ext, run, dev_concepts, image.width, image.height)
            rec.port_links = link_ports(ext, run, cable_concepts, image.width, image.height)
            for g in run.groundings:
                if g.status == "error":
                    notes.append(f"SAM '{g.concept}' failed: {g.error}")
        elif ext is not None and not ext.shows_inspection_subject:
            notes.append("This photo does not show the specified equipment; it contributed no evidence.")
        elif ext is not None and not ext.image_usable:
            notes.append(f"Photo not usable: {', '.join(ext.image_issues) or 'unspecified'}")
        self.observations.append(rec)

        # ASSESS
        self._assess()
        self.trace.add("agent_step", "observe.done", image_id=image.image_id,
                       latency_ms=(time.perf_counter() - t0) * 1000)
        if all(a.status != "INSUFFICIENT_EVIDENCE" for a in self.assessments):
            return self._stop("all_requirements_resolved", seq, image.image_id, notes)
        if budget_hit:
            return self._stop("model_call_budget_exhausted", seq, image.image_id, notes)

        # Attempt accounting: a gap targeted by the last request that is still open has used an attempt.
        open_keys = {g.key for a in self.assessments for g in a.gaps}
        for k, n in self.gap_attempts.items():
            if k in open_keys and n >= self.budget.max_attempts_per_gap and k not in self.exhausted:
                self.exhausted[k] = f"still unresolved after {n} targeted views"
                notes.append(f"Giving up on gap {k}: {self.exhausted[k]}")

        if seq >= self.budget.max_observations:
            return self._stop("observation_budget_exhausted", seq, image.image_id, notes)

        # SELECT NEXT VIEW
        while True:
            gap = select_gap(self.assessments, set(self.exhausted))
            if gap is None:
                return self._stop("no_visually_resolvable_gaps", seq, image.image_id, notes)
            # plan_next_view falls back to a deterministic plan on any API failure, incl. budget.
            req, plan = await self._plan(gap, image if rec.usable else self._latest_usable_image())
            if not plan.visually_resolvable:
                self.exhausted[gap.key] = f"planner: not visually resolvable ({plan.unresolvable_reason})"
                notes.append(f"Gap {gap.key} judged not visually resolvable: {plan.unresolvable_reason}")
                continue
            self.gap_attempts[gap.key] = self.gap_attempts.get(gap.key, 0) + 1
            self.requests.append(req)
            self.trace.add("plan", "next_view", image_id=image.image_id, detail=req.model_dump())
            return StepResult(seq, image.image_id, self.assessments, req, None, notes)

    def _latest_usable_image(self) -> NormalizedImage | None:
        for o in reversed(self.observations):
            if o.usable:
                return self.images[o.image_id]
        return None

    async def _plan(self, gap: Gap, image: NormalizedImage | None):
        recent = [summarize_extraction(o.seq, o.extraction, o.extraction_error) for o in self.observations[-3:]]
        if self.observations and not self.observations[-1].usable:
            recent.append("The latest photo did not show usable evidence; repeat the guidance precisely.")
        return await plan_next_view(self.client, self.spec, gap, image, recent, f"nv{len(self.requests) + 1}")
