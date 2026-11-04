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

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .evidence import (DeclarationKind, Gap, NextViewRequest, ObservationRecord, OperatorDeclaration,
                       RequirementAssessment, ViewCheck)
from .grounding import (FALLBACK_CABLE_CONCEPT, GroundingRun, fallback_targets, link_devices, link_ports,
                        link_ports_fallback, run_sam)
from .images import NormalizedImage
from .meta_client import BudgetExhausted, MetaAPIError, MetaClient
from .muse import ModelOutputError, extract_observations, plan_next_view, summarize_extraction
from .observation import ObservationExtraction
from .policy import ambiguous_device_ids, assess_requirement, connector_match, label_matches, select_gap
from .spec import InspectionSpec

# contradiction_requires_review: every remaining open requirement is blocked by a contradiction, which no further
# photo of the unchanged installation can remove (all photos keep counting). Reopened by an installation change.
StopReason = Literal["all_requirements_resolved", "no_visually_resolvable_gaps",
                     "observation_budget_exhausted", "model_call_budget_exhausted",
                     "contradiction_requires_review"]
# Gaps whose target is a specific device's port row (the photo must show that device's ports to address them).
_PORT_GAPS = ("LABEL_ILLEGIBLE", "PORT_NOT_FOUND", "INSERTION_UNCLEAR", "GROUNDING_MISSING")
# Gaps whose request is about one device's ports, where showing the device (from any side) is already a genuine
# attempt: the person went to the device, so a view without its ports counts as an attempt that failed.
_DEVICE_PORT_GAPS = ("PORTS_NOT_VISIBLE", "DEVICE_UNCONFIRMED")
_PLUG_GAPS = ("INSERTION_UNCLEAR", "GROUNDING_MISSING")
_BUDGET_STOPS = ("observation_budget_exhausted", "model_call_budget_exhausted")
# Targeted photos allowed per gap code where the general Budget.max_attempts_per_gap is too many. GROUNDING_MISSING:
# the plug was already seen clearly by Muse; when SAM still does not corroborate it after one targeted view, further
# camera angles were not observed to help (recorded live run: three photos of one plug, SAM found nothing in any), so
# the photos go to the other open gaps instead. The plug stays on the record as observed but not corroborated.
_ATTEMPT_CEILING = {"GROUNDING_MISSING": 1}


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
    # Statements by the person inspecting (M3.7). Default empty: snapshots from earlier versions load unchanged.
    declarations: list[OperatorDeclaration] = Field(default_factory=list)


@dataclass
class StepResult:
    seq: int
    image_id: str
    assessments: list[RequirementAssessment]
    next_view: NextViewRequest | None
    stop_reason: StopReason | None
    notes: list[str] = field(default_factory=list)
    # Whether this photo showed the view the pending camera request asked for (None: no request was pending).
    view_check: ViewCheck | None = None


class InspectionAgent:
    def __init__(self, spec: InspectionSpec, client: MetaClient, settings: Settings,
                 require_grounding: bool = True, plan_with_muse: bool = True) -> None:
        self.spec = spec
        self.client = client
        self.trace = client.trace
        self.settings = settings
        self.budget = settings.budget
        # The spec may set its own photo budget (bounded by spec.MAX_PHOTOS_LIMIT); otherwise the server default.
        self.max_observations = spec.max_photos or self.budget.max_observations
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
        self.declarations: list[OperatorDeclaration] = []  # all epochs; the policy sees the current one only
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
            trace_event_count=len(self.trace.events),
            declarations=[d.model_copy(deep=True) for d in self.declarations])

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
        agent.declarations = [d.model_copy(deep=True) for d in state.declarations]
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
        fresh = {r.id: assess_requirement(self.spec, r, obs, self.require_grounding, self.current_declarations)
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

    @property
    def current_declarations(self) -> list[OperatorDeclaration]:
        """Operator declarations about the current configuration (an installation change retires earlier ones)."""
        return [d for d in self.declarations if d.epoch == self.epoch]

    def _assess(self) -> list[RequirementAssessment]:
        obs = self.current_observations
        self.assessments = [assess_requirement(self.spec, r, obs, self.require_grounding, self.current_declarations)
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
              notes: list[str], view_check: ViewCheck | None = None, **extra: Any) -> StepResult:
        if view_check is not None:
            extra["view_check"] = view_check.model_dump()
        self._record(seq, rec_or_img_id, source_name, next_view, notes, **extra)
        return StepResult(seq, rec_or_img_id, self.assessments, next_view, self.stop_reason, notes, view_check)

    def _stop(self, reason: StopReason, seq: int, image_id: str, source_name: str,
              notes: list[str], view_check: ViewCheck | None = None) -> StepResult:
        self.stop_reason = reason
        self.trace.add("stop", reason)
        return self._step(seq, image_id, source_name, None, notes, view_check)

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

    async def declare(self, kind: DeclarationKind, *, seq: int | None = None, device_id: str | None = None,
                      requirement_id: str | None = None, now: float | None = None) -> OperatorDeclaration:
        """Record a statement by the person inspecting and re-assess (no model calls, no photo used).

        Refused (ValueError, nothing recorded) unless the spec permits that kind of declaration and the evidence it
        refers to exists: device_identity needs a current-configuration photo in which exactly one device was claimed
        as that spec device, with UNCERTAIN identification (never a device Muse matched to another spec device);
        cable_identity needs a requirement whose spec allows it and whose two endpoints photos already support. The
        policy applies further limits (connector families, no contrary trace). If the current camera request no
        longer applies, the next one comes from the fixed templates, so declaring never costs a model call.
        """
        self._check_idle()
        self._busy = True
        try:
            return await self._declare(kind, seq, device_id, requirement_id, now)
        finally:
            self._busy = False

    async def _declare(self, kind: DeclarationKind, seq: int | None, device_id: str | None,
                       requirement_id: str | None, now: float | None) -> OperatorDeclaration:
        if kind == "device_identity":
            if not self.spec.allow_device_identity_declarations:
                raise ValueError("this specification does not permit device-identity declarations")
            if seq is None or device_id is None or device_id not in {d.id for d in self.spec.devices}:
                raise ValueError("a device-identity declaration needs a photo number and a spec device")
            o = next((o for o in self.current_observations if o.seq == seq), None)
            if o is None or not o.usable:
                raise ValueError(f"photo {seq} is not a usable photo of the current configuration")
            claims = [d for d in o.extraction.devices if d.spec_device_id == device_id]  # type: ignore[union-attr]
            name = self.spec.device(device_id).name
            if len(claims) != 1:
                raise ValueError(f"in photo {seq} {'no device' if not claims else 'more than one device'} was "
                                 f"matched to the {name}, so a declaration cannot say which one it is")
            if claims[0].identification_certainty == "clear":
                raise ValueError(f"the {name} was already identified with certainty in photo {seq}")
            statement = f"Photo {seq} shows the {name}."
            existing = next((d for d in self.current_declarations
                             if d.kind == kind and d.seq == seq and d.device_id == device_id), None)
        else:
            req = next((r for r in self.spec.requirements if r.id == requirement_id), None)
            if req is None or req.cable_identity != "trace_or_operator_declaration":
                raise ValueError("this requirement's specification does not permit a cable-identity declaration")
            a = next((a for a in self.assessments if a.requirement_id == req.id), None)
            if a is None or not all(ep.state == "established" for ep in a.endpoints):
                raise ValueError("both ends of the connection must first be supported by photos")
            ends = " and at the ".join(f"{self.spec.device(e.device_id).name} {e.port_label}" for e in req.endpoints)
            statement = f"The {req.cable_desc()} at the {ends} is one and the same cable."
            existing = next((d for d in self.current_declarations
                             if d.kind == kind and d.requirement_id == req.id), None)
        if existing is not None:
            return existing  # idempotent: the same statement is recorded once
        decl = OperatorDeclaration(id=f"od{len(self.declarations) + 1}", kind=kind, epoch=self.epoch,
                                   statement=statement, seq=seq if kind == "device_identity" else None,
                                   device_id=device_id if kind == "device_identity" else None,
                                   requirement_id=requirement_id if kind == "cable_identity" else None,
                                   created_at=time.time() if now is None else now)
        self.declarations.append(decl)
        self.trace.add("agent_step", "operator_declaration", detail=decl.model_dump())
        self._assess()
        if not self.done:
            if all(a.status != "INSUFFICIENT_EVIDENCE" for a in self.assessments):
                self.stop_reason = "all_requirements_resolved"
                self.trace.add("stop", self.stop_reason)
            else:
                await self._replan_from_templates()
        return decl

    async def _replan_from_templates(self) -> None:
        """After a declaration: if the current camera request targets a gap that is now closed, issue the next one
        from the fixed templates (no model call). Leaves a still-valid request untouched."""
        open_keys = {g.key for a in self.assessments for g in a.gaps}
        current = self.requests[-1] if self.requests else None
        if current is None or current.gap_key in open_keys:
            return
        blocked = {r["requirement_id"] for r in self.review_items()}
        gap = select_gap([a for a in self.assessments if a.requirement_id not in blocked], set(self.exhausted),
                         self._devices_in_latest_view())
        if gap is None:
            self.stop_reason = "contradiction_requires_review" if blocked else "no_visually_resolvable_gaps"
            self.trace.add("stop", self.stop_reason)
            return
        latest = self.current_observations[-1].image_id if self.current_observations else ""
        req, _plan = await self._plan(gap, None, latest)
        self.gap_attempts[gap.key] = self.gap_attempts.get(gap.key, 0) + 1
        self.requests.append(req)
        self.trace.add("plan", "next_view", image_id=latest or None, detail=req.model_dump())

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
            # A cable concept no occupied port in this photo could use is never sent (grounding is only read at
            # occupied ports whose connector family is not clearly another one), so it cannot add evidence.
            concepts = self._prioritize_concepts(
                ext, cable_concepts, list(dict.fromkeys(cable_concepts + sorted({dev_concepts[i] for i in seen_ids}))))
            concepts = concepts[: self.budget.max_sam_calls_per_image]
            run = await run_sam(self.client, image, concepts)
            rec.device_links = link_devices(ext, run, dev_concepts, image.width, image.height)
            rec.port_links = link_ports(ext, run, cable_concepts, image.width, image.height)
            # Generic fallback, at most one extra call and only within the per-photo SAM cap (see grounding.py).
            by_connector = {r.connector: r.cable_concept() for r in self.spec.requirements}
            targets = fallback_targets(ext, run, by_connector)
            if (targets and FALLBACK_CABLE_CONCEPT not in concepts
                    and len(concepts) < self.budget.max_sam_calls_per_image):
                extra = await run_sam(self.client, image, [FALLBACK_CABLE_CONCEPT])
                run.groundings.extend(extra.groundings)
                run.masks.update(extra.masks)
                rec.port_links.update(link_ports_fallback(ext, run, targets, image.width, image.height))
                self.trace.add("agent_step", "sam_fallback", image_id=image.image_id,
                               detail={"concept": FALLBACK_CABLE_CONCEPT, "ports": targets})
            rec.sam = run.groundings
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
        # VIEW RELEVANCE (A), judged against the gap as it stood when the request was issued, i.e. before this
        # photo is assessed. Independent of evidence acceptance (B) and of the verdict (C), which the policy decides.
        pending = self.requests[-1] if self.requests and rec.responding_to == self.requests[-1].id else None
        check = self._view_check(rec, pending) if pending is not None else None
        if pending is not None and check is not None:
            notes.append(self._view_note(seq, pending, check))
            self.trace.add("agent_step", "view_check", image_id=image_id, detail=check.model_dump())
        self.observations.append(rec)

        # ASSESS (whole current-configuration evidence set, order-independent)
        self._assess()
        if all(a.status != "INSUFFICIENT_EVIDENCE" for a in self.assessments):
            return self._stop("all_requirements_resolved", seq, image_id, name, notes, check)
        if budget_hit:
            return self._stop("model_call_budget_exhausted", seq, image_id, name, notes, check)

        # Attempt accounting. An attempt is counted when a request is issued; if the photo answering it did not
        # show what the request targeted (unusable, wrong device, or the device without its ports for a port-level
        # gap), that attempt is refunded and the same request is re-issued below without a new planner call. A
        # photo that DID show the requested view counts, whether or not the policy accepted anything from it: an
        # unverified connection is not a failed camera instruction. The photo budget and the model-call budget
        # still bound everything; an off-target photo never earns more than its own analysis.
        open_keys = {g.key for a in self.assessments for g in a.gaps}
        reissue: NextViewRequest | None = None
        if (pending is not None and check is not None and pending.gap_key in open_keys
                and pending.gap_key not in self.exhausted
                and self.gap_attempts.get(pending.gap_key, 0) > 0 and not check.counted_as_attempt):
            self.gap_attempts[pending.gap_key] -= 1
            reissue = pending
            notes.append(f"Request {pending.id} still applies: no attempt was counted for it.")
            self.trace.add("agent_step", "off_target_photo", image_id=image_id,
                           detail={"request": pending.id, "gap": pending.gap_key})
        for k, n in self.gap_attempts.items():
            code = k.split(":")[1] if k.count(":") >= 2 else ""
            if (k in open_keys and n >= _ATTEMPT_CEILING.get(code, self.budget.max_attempts_per_gap)
                    and k not in self.exhausted):
                self.exhausted[k] = (
                    f"SAM still did not corroborate the plug Muse reported after {n} targeted "
                    f"{'view' if n == 1 else 'views'}; another camera angle is unlikely to help. The plug stays on "
                    "the record as observed by Muse but not corroborated." if code == "GROUNDING_MISSING"
                    else f"still unresolved after {n} targeted views")
                notes.append(f"Giving up on gap {k}: {self.exhausted[k]}")

        if seq >= self.max_observations:
            return self._stop("observation_budget_exhausted", seq, image_id, name, notes, check)

        # CONTRADICTIONS: never answered with a camera request. A requirement blocked by one needs installation
        # review; the others keep being pursued.
        review = self.review_items()
        blocked = {r["requirement_id"] for r in review}
        notes.extend(r["message"] for r in review)

        # SELECT NEXT VIEW
        while True:
            gap = select_gap([a for a in self.assessments if a.requirement_id not in blocked],
                             set(self.exhausted), self._devices_in_latest_view())
            if gap is None:
                return self._stop("contradiction_requires_review" if blocked else "no_visually_resolvable_gaps",
                                  seq, image_id, name, notes, check)
            if reissue is not None and gap.key == reissue.gap_key:
                self.gap_attempts[gap.key] = self.gap_attempts.get(gap.key, 0) + 1
                self.trace.add("plan", "next_view_reissued", image_id=image_id, detail={"request": reissue.id})
                return self._step(seq, image_id, name, reissue, notes, check)
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
            return self._step(seq, image_id, name, req, notes, check)

    def _prioritize_concepts(self, ext: ObservationExtraction, cable_concepts: list[str],
                             concepts: list[str]) -> list[str]:
        """Skip a cable concept that no port in this photo could use. Grounding is only ever read at OCCUPIED ports
        whose connector family is not clearly another one, so such a concept cannot add evidence; the call is
        saved (or, at the per-photo cap, goes to the next concept, a device mask)."""
        useful = set()
        for r in self.spec.requirements:
            if any(p.occupancy == "cable_inserted" and connector_match(p.connector_type, r.connector) != "mismatch"
                   for p in ext.ports):
                useful.add(r.cable_concept())
        return [c for c in concepts if c not in cable_concepts or c in useful]

    def _view_check(self, rec: ObservationRecord, req: NextViewRequest) -> ViewCheck:
        """A. VIEW RELEVANCE: did this photo show what `req` asked for?

        Uses only structured data: the request's requirement, gap code and endpoint, the gap's context as it stood
        when the request was issued, and the photo's validated observation claims (never free-text matching). A
        device claimed with UNCERTAIN identification still counts as shown here (it was photographed); whether its
        observations are evidence (B) and what the verdict is (C) are decided by the policy alone.
        """
        r = self.spec.requirement(req.requirement_id)
        idx = _endpoint_index(req.gap_key)
        device_ids = list(dict.fromkeys(e.device_id for e in (r.endpoints if idx is None else [r.endpoints[idx]])))
        code = req.gap_code
        prior = next((g for a in self.assessments for g in a.gaps if g.key == req.gap_key), None)
        need_ports = code in _PORT_GAPS or code in _DEVICE_PORT_GAPS
        need_plug = code in _PLUG_GAPS or (code == "LABEL_ILLEGIBLE" and prior is not None
                                           and bool(prior.context.get("label_hidden_by_plug")))
        ext = rec.extraction if rec.usable else None
        amb = ambiguous_device_ids(ext) if ext is not None else set()
        shown: list[str] = []
        missing: list[str] = []
        core = True
        confirmed: list[bool] = []
        unconfirmed: list[str] = []
        for dev_id in device_ids:
            name = self.spec.device(dev_id).name
            dev_part, ports_part = f"the {name}", f"the {name}'s connection ports"
            plug_part, id_part = f"the {name} port holding the {r.connector} plug", f"features confirming it is the {name}"
            parts = [dev_part]
            if need_ports:
                parts.append(ports_part)
            if need_plug:
                parts.append(plug_part)
            if code == "DEVICE_UNCONFIRMED":
                parts.append(id_part)
            d = None
            if ext is not None and dev_id not in amb:
                d = next((x for x in ext.devices if x.spec_device_id == dev_id), None)
            got = {part: False for part in parts}
            if d is not None and ext is not None:
                ports = [p for p in ext.ports if p.device_ref == d.ref]
                clear = d.identification_certainty == "clear"
                confirmed.append(clear)
                if not clear:
                    unconfirmed.append(name)
                got[dev_part] = True
                got[ports_part] = d.ports_visible or bool(ports)
                got[plug_part] = any(p.occupancy == "cable_inserted"
                                     and connector_match(p.connector_type, r.connector) != "mismatch" for p in ports)
                got[id_part] = clear
            for part in parts:
                (shown if got[part] else missing).append(part)
            # What makes the photo a genuine attempt at the request (the earlier accounting rule, minus requiring a
            # certain identification): the device, plus its ports for port-level gaps.
            core = core and got[dev_part] and (code not in _PORT_GAPS or got[ports_part])
        status = "captured" if not missing else ("not_captured" if not shown else "partial")
        return ViewCheck(request_id=req.id, gap_key=req.gap_key, requirement_id=req.requirement_id, status=status,
                         shown=shown, missing=missing, identity_confirmed=all(confirmed) if confirmed else None,
                         unconfirmed_devices=unconfirmed, counted_as_attempt=core)

    @staticmethod
    def _view_note(seq: int, req: NextViewRequest, c: ViewCheck) -> str:
        if c.status == "captured":
            out = f"Photo {seq} showed the view requested in {req.id}: {', '.join(c.shown)}."
        elif c.status == "partial":
            out = (f"Photo {seq} partly showed the view requested in {req.id}: it showed {', '.join(c.shown)}, "
                   f"but not {', '.join(c.missing)}.")
        else:
            out = (f"Photo {seq} did not show the view requested in {req.id} ({req.target_region}): "
                   f"{', '.join(c.missing)} not seen.")
        if c.unconfirmed_devices and req.gap_code != "DEVICE_UNCONFIRMED":
            out += (f" The {' and the '.join(c.unconfirmed_devices)} was not identified with certainty in this "
                    "photo, so what the photo shows of it is not used as evidence.")
        return out

    def review_items(self) -> list[dict[str, Any]]:
        """Open requirements blocked by a contradiction, with the conflicting evidence and its photos.

        A contradiction cannot be removed by another photo of the unchanged installation (every photo keeps
        counting), so it calls for review of the installation, not a camera instruction.
        """
        seq_of = {o.image_id: o.seq for o in self.observations}
        out = []
        for a in self.assessments:
            gaps = [g for g in a.gaps if g.code == "CONTRADICTION"]
            if a.status != "INSUFFICIENT_EVIDENCE" or not gaps:
                continue
            photos = sorted({seq_of[i] for g in gaps for i in g.context.get("images", []) if i in seq_of}
                            | {x.seq for ep in a.endpoints if ep.state == "contradicted"
                               for x in ep.support + ep.conflicts})
            listed = ", ".join(f"photo {s}" for s in photos) or "earlier photos"
            out.append({
                "requirement_id": a.requirement_id, "photos": photos, "contradictions": list(a.contradictions),
                "action": "review_installation",
                "message": (f"Review needed for {a.requirement_id}: {listed} disagree "
                            f"({'; '.join(g.target for g in gaps)}). Another photo of the unchanged installation "
                            "cannot remove this conflict, because every photo keeps counting. Check the installation "
                            "in person. If it was physically changed between photos, declare the change "
                            "(installation_changed): earlier photos then stop counting and the inspection continues. "
                            "If nothing changed, this requirement cannot be verified from these photos.")})
        return out

    def _unread_labels(self, gap: Gap) -> list[str]:
        """Spec labels for the gap's target port(s) that no photo of the current configuration has legibly shown on
        an unambiguously identified spec device."""
        req = self.spec.requirement(gap.requirement_id)
        idx = [gap.endpoint_index] if gap.endpoint_index is not None else [0, 1]
        out: list[str] = []
        for i in idx:
            e = req.endpoints[i]
            seen = False
            for o in self.current_observations:
                if not o.usable:
                    continue
                ext = o.extraction
                if e.device_id in ambiguous_device_ids(ext):  # type: ignore[arg-type]
                    continue
                refs = {d.ref for d in ext.devices if d.spec_device_id == e.device_id}  # type: ignore[union-attr]
                if any(p.device_ref in refs and label_matches(p, e) for p in ext.ports):  # type: ignore[union-attr]
                    seen = True
                    break
            if not seen:
                # Exact endpoints: the expected label. Flexible ones: only their listed labels (never a group word
                # or the display name, which are not claims about printed text).
                out += [e.port_label, *e.label_aliases] if not e.flexible else list(e.selector.allowed_labels)  # type: ignore[union-attr]
        return out

    def _devices_in_latest_view(self) -> set[str]:
        """Spec devices shown in the latest photo that showed any: where the person is now. Used only to order
        gaps, never as evidence, so an uncertain identification counts here (an ambiguous one does not). Photos
        showing none of them (unusable, or only unrelated equipment) do not move the guidance away from where the
        user last was."""
        for o in reversed(self.current_observations):
            if o.usable:
                amb = ambiguous_device_ids(o.extraction)  # type: ignore[arg-type]
                seen = {d.spec_device_id for d in o.extraction.devices  # type: ignore[union-attr]
                        if d.spec_device_id and d.spec_device_id not in amb}
                if seen:
                    return seen
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
                                    latest_image_id=latest_image_id, unread_labels=self._unread_labels(gap))


def _endpoint_index(gap_key: str | None) -> int | None:
    """'R1:PORTS_NOT_VISIBLE:0' -> 0; requirement-level gaps ('R1:CABLE_CONTINUITY:None') -> None."""
    tail = (gap_key or "").rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None
