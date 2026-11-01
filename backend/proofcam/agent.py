"""Bounded active-inspection loop.

    observe(image):  OBSERVE (Muse) -> GROUND (SAM) -> ASSESS (policy) -> IDENTIFY GAP -> PLAN NEXT VIEW
    The caller supplies the next image (camera capture, CLI file, ...) and calls observe() again.

Photos may arrive in ANY order: every photo is kept, and the policy re-assesses the whole set of
observations of the current installation configuration each time, so the assessment depends on the
evidence collected, not on its sequence. Only the guidance differs with what has been seen so far.

Static verification is the default: all photos are assumed to show one unchanged installation, and a
clear violation is terminal. If the equipment is physically changed during an inspection, the caller
must say so with mark_installation_changed(); earlier photos are then kept for the record but no
longer count as evidence for the current configuration.

Stops when every requirement is VERIFIED/VIOLATED, when no remaining gap can be advanced
(attempt limit reached or the planner says it is not visually resolvable), or on budget exhaustion.
"""

from __future__ import annotations

import copy
import dataclasses
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

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
_BUDGET_STOPS = ("observation_budget_exhausted", "model_call_budget_exhausted")


class AgentState(BaseModel):
    """Everything needed to resume an inspection between steps, as plain JSON-able data.

    Not included (held elsewhere): the trace events (owned by the client's Trace, persisted separately and
    checked by count), the normalized photos (persisted as bytes) and SAM masks (only overlays need them;
    overlays are rendered and stored when each photo is processed).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    spec: InspectionSpec
    require_grounding: bool
    plan_with_muse: bool
    budget: dict[str, int]
    observations: list[ObservationRecord]
    requests: list[NextViewRequest]
    gap_attempts: dict[str, int]
    exhausted: dict[str, str]
    assessments: list[RequirementAssessment]
    stop_reason: StopReason | None
    epoch: int
    history: list[dict[str, Any]]
    model_calls_started: int
    model_call_limit: int
    trace_event_count: int


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
                 require_grounding: bool = True, plan_with_muse: bool = True) -> None:
        self.spec = spec
        self.client = client
        self.trace = client.trace
        self.settings = settings
        self.budget = settings.budget
        self.require_grounding = require_grounding
        # False = next-view plans come from the deterministic templates only (offline replay, no API calls).
        self.plan_with_muse = plan_with_muse
        self.observations: list[ObservationRecord] = []
        self.images: dict[str, NormalizedImage] = {}
        self.grounding_runs: dict[int, GroundingRun] = {}
        self.requests: list[NextViewRequest] = []
        self.gap_attempts: dict[str, int] = {}
        self.exhausted: dict[str, str] = {}  # gap key -> reason
        self.assessments: list[RequirementAssessment] = []
        self.stop_reason: StopReason | None = None
        self.epoch = 0
        self.history: list[dict[str, Any]] = []  # one entry per submitted photo or inspection event
        # Photos whose SAM masks were not restored (see restore()); their overlays must come from storage.
        self.masks_unavailable: set[int] = set()
        self._busy = False  # a step is in progress; state is mid-update and must not be read or advanced

    @property
    def done(self) -> bool:
        return self.stop_reason is not None

    # ------------------------------------------------------------------ persistence

    def snapshot(self) -> AgentState:
        """Copy of the resumable state. Only valid between steps (never while observe() is awaiting)."""
        if self._busy:
            raise RuntimeError("cannot snapshot while a step is in progress")
        return AgentState(
            spec=self.spec, require_grounding=self.require_grounding, plan_with_muse=self.plan_with_muse,
            budget=dataclasses.asdict(self.budget),
            observations=[o.model_copy(deep=True) for o in self.observations],
            requests=[r.model_copy(deep=True) for r in self.requests],
            gap_attempts=dict(self.gap_attempts), exhausted=dict(self.exhausted),
            assessments=[a.model_copy(deep=True) for a in self.assessments],
            stop_reason=self.stop_reason, epoch=self.epoch, history=copy.deepcopy(self.history),
            model_calls_started=self.client.calls_started, model_call_limit=self.client.call_limit,
            trace_event_count=len(self.trace.events))

    @classmethod
    def restore(cls, state: AgentState, client: MetaClient, settings: Settings,
                images: Iterable[NormalizedImage] = ()) -> InspectionAgent:
        """Rebuild an agent from a snapshot so the next step behaves as if it had never been interrupted.

        `client` must be fresh (no calls made) and its trace must already hold exactly the persisted events
        (Trace.from_events); its call counter is set from the snapshot, so calls are neither lost nor counted
        twice. `images` are the stored normalized photos (NormalizedImage.from_stored); photos may be omitted
        (as in offline replay), but an image that matches no observation is rejected. No model calls, no
        policy re-assessment, no trace events.
        """
        if dataclasses.asdict(settings.budget) != state.budget:
            raise ValueError(f"budget differs from the inspection's stored budget {state.budget}")
        if client.call_limit != state.model_call_limit:
            raise ValueError(f"client call limit {client.call_limit} != stored {state.model_call_limit}")
        if client.calls_started != 0:
            raise ValueError("restore needs a fresh client (it has already started model calls)")
        if len(client.trace.events) != state.trace_event_count:
            raise ValueError(f"trace has {len(client.trace.events)} events, snapshot expects "
                             f"{state.trace_event_count}")
        seqs = [o.seq for o in state.observations]
        if seqs != list(range(1, len(seqs) + 1)):
            raise ValueError(f"observation sequence numbers are not 1..n: {seqs}")
        if any(o.epoch > state.epoch for o in state.observations):
            raise ValueError("an observation belongs to a future epoch")
        req_ids = [r.id for r in state.requests]
        if len(set(req_ids)) != len(req_ids):
            raise ValueError(f"duplicate next-view request ids: {req_ids}")

        agent = cls(state.spec, client, settings, require_grounding=state.require_grounding,
                    plan_with_muse=state.plan_with_muse)
        agent.observations = [o.model_copy(deep=True) for o in state.observations]
        agent.requests = [r.model_copy(deep=True) for r in state.requests]
        agent.gap_attempts = dict(state.gap_attempts)
        agent.exhausted = dict(state.exhausted)
        agent.assessments = [a.model_copy(deep=True) for a in state.assessments]
        agent.stop_reason = state.stop_reason
        agent.epoch = state.epoch
        agent.history = copy.deepcopy(state.history)
        client.calls_started = state.model_calls_started
        known = {o.image_id for o in agent.observations}
        for img in images:
            if img.image_id not in known:
                raise ValueError(f"image {img.image_id} matches no observation")
            agent.images[img.image_id] = img
        agent.masks_unavailable = {o.seq for o in agent.observations if any(g.objects for g in o.sam)}
        return agent

    def policy_drift(self) -> list[str]:
        """Requirement ids whose stored assessment differs from a fresh policy run over the same evidence.

        Pure check (no trace events, nothing changed). Non-empty means the policy code changed since the
        assessment was made; the caller must surface this rather than silently replace a verdict.
        """
        obs = self.current_observations
        fresh = {r.id: assess_requirement(self.spec, r, obs, self.require_grounding)
                 for r in self.spec.requirements}
        stored = {a.requirement_id: a for a in self.assessments}
        if not stored:  # nothing assessed yet (no photo, no event)
            return []
        return sorted(rid for rid in fresh.keys() | stored.keys()
                      if rid not in fresh or rid not in stored or fresh[rid] != stored[rid])

    @property
    def current_observations(self) -> list[ObservationRecord]:
        """Observations of the current installation configuration: the only ones the policy may use."""
        return [o for o in self.observations if o.epoch == self.epoch]

    def _assess(self) -> list[RequirementAssessment]:
        obs = self.current_observations
        self.assessments = [assess_requirement(self.spec, r, obs, self.require_grounding)
                            for r in self.spec.requirements]
        for a in self.assessments:
            self.trace.add("policy", "assess", detail={"requirement": a.requirement_id, "status": a.status,
                                                        "gaps": [g.key for g in a.gaps], "epoch": self.epoch,
                                                        "observations": [o.seq for o in obs]})
        return self.assessments

    def _record(self, seq: int, image_id: str, source_name: str, next_view: NextViewRequest | None,
                notes: list[str], **extra: Any) -> None:
        self.history.append({
            "event": "photo", "seq": seq, "image_id": image_id, "source_name": source_name, "epoch": self.epoch,
            "requirements": [{
                "id": a.requirement_id, "status": a.status, "identity_state": a.identity_state,
                "endpoints": [{"device_id": ep.device_id, "port_label": ep.port_label, "state": ep.state,
                               "support_photos": sorted({s.seq for s in ep.support})} for ep in a.endpoints],
                "gaps": [g.key for g in a.gaps]} for a in self.assessments],
            "next_view": next_view.id if next_view else None,
            "stop_reason": self.stop_reason, "notes": list(notes), **extra})

    def _step(self, seq: int, rec_or_img_id: str, source_name: str, next_view: NextViewRequest | None,
              notes: list[str], **extra: Any) -> StepResult:
        self._record(seq, rec_or_img_id, source_name, next_view, notes, **extra)
        return StepResult(seq, rec_or_img_id, self.assessments, next_view, self.stop_reason, notes)

    def _stop(self, reason: StopReason, seq: int, image_id: str, source_name: str,
              notes: list[str]) -> StepResult:
        self.stop_reason = reason
        self.trace.add("stop", reason)
        return self._step(seq, image_id, source_name, None, notes)

    # ------------------------------------------------------------------ inspection events

    def mark_installation_changed(self, reason: str) -> None:
        """Explicitly declare that the physical installation changed (e.g. a cable was moved).

        Earlier photos stay in the record but stop counting as evidence; gap attempts reset; a stop caused
        by a verdict or by exhausted gaps is reopened. Budget stops are never reopened.
        """
        self._check_idle()
        if self.stop_reason in _BUDGET_STOPS:
            raise RuntimeError(f"cannot reopen an inspection stopped by {self.stop_reason}")
        self.epoch += 1
        self.stop_reason = None
        self.gap_attempts.clear()
        self.exhausted.clear()
        self.trace.add("agent_step", "installation_changed", detail={"epoch": self.epoch, "reason": reason})
        self._assess()
        self.history.append({"event": "installation_changed", "epoch": self.epoch, "reason": reason,
                             "superseded_photos": [o.seq for o in self.observations if o.epoch < self.epoch]})

    # ------------------------------------------------------------------ main entry points

    async def observe(self, image: NormalizedImage) -> StepResult:
        """Live path: perceive the photo with Muse + SAM, then integrate it."""
        self._check_idle()
        self._busy = True
        try:
            return await self._observe(image)
        finally:
            self._busy = False

    async def _observe(self, image: NormalizedImage) -> StepResult:
        if self.done:
            raise RuntimeError(f"inspection already stopped: {self.stop_reason}")
        dup = self._duplicate(image.image_id, image.source_name)
        if dup:
            return dup
        seq = len(self.observations) + 1
        self.images[image.image_id] = image
        t0 = time.perf_counter()
        rec, run, notes, budget_hit = await self._perceive(image, seq)
        self.trace.add("agent_step", "perceive.done", image_id=image.image_id,
                       latency_ms=(time.perf_counter() - t0) * 1000)
        return await self._integrate(rec, image, run, notes, budget_hit)

    async def observe_recorded(self, recorded: ObservationRecord, image: NormalizedImage | None = None,
                               run: GroundingRun | None = None) -> StepResult:
        """Integrate a previously recorded observation (offline replay / re-ordering experiments).

        Perception of one photo does not depend on inspection state, so a recorded Muse extraction and its
        SAM links can be replayed in any order. No Muse/SAM perception calls are made.
        """
        self._check_idle()
        self._busy = True
        try:
            return await self._observe_recorded(recorded, image, run)
        finally:
            self._busy = False

    async def _observe_recorded(self, recorded: ObservationRecord, image: NormalizedImage | None,
                                run: GroundingRun | None) -> StepResult:
        if self.done:
            raise RuntimeError(f"inspection already stopped: {self.stop_reason}")
        dup = self._duplicate(recorded.image_id, recorded.source_name)
        if dup:
            return dup
        seq = len(self.observations) + 1
        if image is not None:
            self.images[image.image_id] = image
        rec = recorded.model_copy(deep=True, update={
            "seq": seq, "epoch": self.epoch,
            "responding_to": self.requests[-1].id if self.requests else None})
        self.trace.add("agent_step", "observe_recorded", source="replay", image_id=rec.image_id,
                       detail={"seq": seq, "source_name": rec.source_name})
        notes = [] if rec.usable or rec.extraction is None else [self._unusable_note(rec)]
        return await self._integrate(rec, image, run, notes, False)

    # ------------------------------------------------------------------ internals

    def _check_idle(self) -> None:
        # One step at a time: seq, responding_to and gap attempts are read before awaiting model calls,
        # so overlapping steps on one agent would corrupt them.
        if self._busy:
            raise RuntimeError("another step is in progress for this inspection")

    def _duplicate(self, image_id: str, source_name: str) -> StepResult | None:
        prev = next((o for o in self.observations if o.image_id == image_id), None)
        if prev is None:
            return None
        note = (f"Duplicate of photo {prev.seq} (identical image {image_id}); it adds no new evidence and was "
                "not sent to the models.")
        self.trace.add("agent_step", "duplicate_photo", image_id=image_id, detail={"duplicate_of": prev.seq})
        nv = self.requests[-1] if self.requests else None
        self._record(prev.seq, image_id, source_name, nv, [note], duplicate_of=prev.seq)
        return StepResult(prev.seq, image_id, self.assessments, nv, self.stop_reason, [note])

    @staticmethod
    def _unusable_note(rec: ObservationRecord) -> str:
        ext = rec.extraction
        if ext is not None and not ext.shows_inspection_subject:
            return "This photo does not show the specified equipment; it contributed no evidence."
        issues = ", ".join(ext.image_issues) if ext else ""
        return f"Photo not usable: {issues or 'unspecified'}"

    async def _perceive(self, image: NormalizedImage, seq: int
                        ) -> tuple[ObservationRecord, GroundingRun | None, list[str], bool]:
        responding_to = self.requests[-1].id if self.requests else None
        notes: list[str] = []
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
                                epoch=self.epoch, extraction=ext, extraction_error=err)
        # GROUND (only photos that show the subject; SAM cannot help otherwise)
        run = None
        if ext is not None and rec.usable:
            dev_concepts = {d.id: d.sam_concept for d in self.spec.devices}
            seen_ids = {d.spec_device_id for d in ext.devices if d.spec_device_id}
            cable_concepts = sorted({r.cable_concept() for r in self.spec.requirements})
            concepts = cable_concepts + sorted({dev_concepts[i] for i in seen_ids})
            concepts = list(dict.fromkeys(concepts))[: self.budget.max_sam_calls_per_image]
            run = await run_sam(self.client, image, concepts)
            rec.sam = run.groundings
            rec.device_links = link_devices(ext, run, dev_concepts, image.width, image.height)
            rec.port_links = link_ports(ext, run, cable_concepts, image.width, image.height)
            for g in run.groundings:
                if g.status == "error":
                    notes.append(f"SAM '{g.concept}' failed: {g.error}")
        elif ext is not None:
            notes.append(self._unusable_note(rec))
        return rec, run, notes, budget_hit

    async def _integrate(self, rec: ObservationRecord, image: NormalizedImage | None, run: GroundingRun | None,
                         notes: list[str], budget_hit: bool) -> StepResult:
        seq, image_id, name = rec.seq, rec.image_id, rec.source_name
        if run is not None:
            self.grounding_runs[seq] = run
        self.observations.append(rec)

        # ASSESS (whole current-configuration evidence set, order-independent)
        self._assess()
        if all(a.status != "INSUFFICIENT_EVIDENCE" for a in self.assessments):
            return self._stop("all_requirements_resolved", seq, image_id, name, notes)
        if budget_hit:
            return self._stop("model_call_budget_exhausted", seq, image_id, name, notes)

        # Attempt accounting: a gap targeted by an earlier request that is still open has used an attempt.
        open_keys = {g.key for a in self.assessments for g in a.gaps}
        for k, n in self.gap_attempts.items():
            if k in open_keys and n >= self.budget.max_attempts_per_gap and k not in self.exhausted:
                self.exhausted[k] = f"still unresolved after {n} targeted views"
                notes.append(f"Giving up on gap {k}: {self.exhausted[k]}")

        if seq >= self.budget.max_observations:
            return self._stop("observation_budget_exhausted", seq, image_id, name, notes)

        # SELECT NEXT VIEW
        while True:
            gap = select_gap(self.assessments, set(self.exhausted), self._devices_in_latest_view())
            if gap is None:
                return self._stop("no_visually_resolvable_gaps", seq, image_id, name, notes)
            # plan_next_view falls back to a deterministic plan on any API failure, incl. budget.
            plan_img = image if (rec.usable and image is not None) else self._latest_usable_image()
            req, plan = await self._plan(gap, plan_img if self.plan_with_muse else None, image_id)
            if not plan.visually_resolvable:
                self.exhausted[gap.key] = f"planner: not visually resolvable ({plan.unresolvable_reason})"
                notes.append(f"Gap {gap.key} judged not visually resolvable: {plan.unresolvable_reason}")
                continue
            self.gap_attempts[gap.key] = self.gap_attempts.get(gap.key, 0) + 1
            self.requests.append(req)
            self.trace.add("plan", "next_view", image_id=image_id, detail=req.model_dump())
            return self._step(seq, image_id, name, req, notes)

    def _devices_in_latest_view(self) -> set[str]:
        for o in reversed(self.current_observations):
            if o.usable:
                return {d.spec_device_id for d in o.extraction.devices  # type: ignore[union-attr]
                        if d.spec_device_id and d.identification_certainty == "clear"}
        return set()

    def _latest_usable_image(self) -> NormalizedImage | None:
        for o in reversed(self.current_observations):
            if o.usable and o.image_id in self.images:
                return self.images[o.image_id]
        return None

    def evidence_state(self) -> list[str]:
        """Plain-text summary of what the policy has (not) established; given to the planner."""
        out = []
        for a in self.assessments:
            eps = "; ".join(f"{self.spec.device(ep.device_id).name} {ep.port_label}: {ep.state}"
                            + (f" (from photo {', '.join(str(s) for s in sorted({x.seq for x in ep.support}))})"
                               if ep.support else "")
                            for ep in a.endpoints)
            out.append(f"{a.requirement_id} {a.status}. Endpoints: {eps}. Cable identity: {a.identity_state}.")
        return out

    async def _plan(self, gap: Gap, image: NormalizedImage | None, latest_image_id: str):
        obs = self.current_observations
        recent = [summarize_extraction(o.seq, o.extraction, o.extraction_error) for o in obs[-3:]]
        if obs and not obs[-1].usable:
            recent.append("The latest photo did not show usable evidence; repeat the guidance precisely.")
        previous = [f"{r.instruction} (based on {r.based_on_image_id}; gap still open)"
                    for r in self.requests if r.gap_key == gap.key]
        return await plan_next_view(self.client, self.spec, gap, image, recent, f"nv{len(self.requests) + 1}",
                                    evidence_state=self.evidence_state(), previous_requests=previous,
                                    latest_image_id=latest_image_id)
