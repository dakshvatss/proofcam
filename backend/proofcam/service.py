"""InspectionService: the M0 engine (InspectionAgent) + MetaClient + the SQLite Store (Milestone 1).

There is no in-memory agent cache: every operation rebuilds the agent from the database, so the code path after a
server restart is the normal one. Verdicts come only from the unchanged deterministic policy inside the agent.

Capture lifecycle (submit_capture):
  validate + normalize the upload (no lease held)
  -> Store.begin_capture: idempotency check + lease, atomically (stale leases recovered lazily, never active ones)
  -> under the lease: load_restore_bundle -> stop / stale-guidance checks -> InspectionAgent.restore
  -> agent.observe() with a MetaClient whose accounting hook reserves EVERY HTTP attempt in SQLite before it is
     sent and settles its outcome afterwards; a heartbeat task renews the lease meanwhile
  -> overlays rendered (with the SAM masks of this step) -> response built -> Store.commit_step (one transaction,
     lease released). Any failure: Store.fail_submission (nothing of the attempt is stored; its unsettled calls stay
     counted as outcome_unknown; lease released).
The step runs in a task owned by the service and awaited through asyncio.shield, so a disconnecting client does not
abort a paid step halfway. Process death is handled by lease expiry + recovery, not by shielding.

Deployment assumption (M1): one server process (one uvicorn worker). Correctness across processes rests on the
store's conditional lease, version checks and heartbeats; only throughput assumes a single worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
from pydantic import ValidationError

from .agent import InspectionAgent, StepResult
from .api_models import (InspectionState, PhotoInfo, SpecEndpointSummary, SpecRequirementSummary, SpecSummary,
                         StepResponse, Usage)
from .config import REPO_ROOT, Settings
from .images import ImageLoadError, NormalizedImage, normalize_image_bytes
from .meta_client import BudgetExhausted, MetaClient
from .overlay import render_overlay_jpeg
from .policy import overall_assessment
from .report import DISCLAIMER, build_report, render_markdown
from .spec import InspectionSpec
from .store import (AppendOnlyViolation, CaptureCompleted, CaptureStarted, IdempotencyConflict, InspectionBusy,
                    InspectionNotFound, LeaseLost, ModelCallBudgetExhausted, RecoveryReport, RestoreBundle, Store,
                    StoreCorruptionError, StoreError, UnsafeContent, VersionConflict, engine_version)
from .trace import Trace

log = logging.getLogger("proofcam.service")

_SPEC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{1,200}$")  # visible ASCII
_IMAGE_ID = re.compile(r"^img_[0-9a-f]{12}$")


@dataclass(frozen=True)
class ServiceConfig:
    specs_dir: Path = REPO_ROOT / "data" / "specs"
    max_upload_bytes: int = 15 * 1024 * 1024
    # Heartbeat while a step runs; a lease whose heartbeat is older than lease_stale_after_s is treated as
    # abandoned (crashed process). Must comfortably exceed the heartbeat interval; it does NOT need to exceed the
    # longest model call, because the heartbeat keeps running during calls.
    lease_heartbeat_s: float = 10.0
    lease_stale_after_s: float = 60.0
    # Trace provenance label for model calls made through this service ("mock" in tests).
    model_source: str = "live"
    require_grounding: bool = True
    # Spending cap: model calls reserved across ALL inspections in the database. None = no global cap. A new capture
    # is refused (429 spend_cap_reached, inspection untouched) unless at least `capture_call_reserve` calls remain;
    # the per-call reservation enforces the cap as a hard backstop.
    global_call_limit: int | None = None
    capture_call_reserve: int = 8

    def __post_init__(self) -> None:
        if self.lease_stale_after_s < 3 * self.lease_heartbeat_s:
            raise ValueError("lease_stale_after_s must be at least 3x lease_heartbeat_s")


class ServiceError(Exception):
    """Application-level error with an HTTP status and a stable error code (mapped by api.py)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _no_network(request: httpx.Request) -> httpx.Response:
    raise RuntimeError("read-only inspection access must not call the model API")


_READ_ONLY_TRANSPORT = httpx.MockTransport(_no_network)


class StoreAccounting:
    """MetaClient accounting hook: every HTTP attempt is reserved in SQLite before it is sent (store refusal ->
    BudgetExhausted, so the request is never sent) and its outcome is settled afterwards. An attempt interrupted
    before settlement stays 'reserved' and becomes 'outcome_unknown' on failure/recovery: counted once, never
    reported as completed."""

    def __init__(self, store: Store, inspection_id: str, lease_token: str, idempotency_key: str,
                 global_limit: int | None = None) -> None:
        self.store, self.iid, self.token, self.key = store, inspection_id, lease_token, idempotency_key
        self.global_limit = global_limit

    def before_request(self, name: str, attempt: int, image_id: str | None) -> int:
        label = name if attempt == 1 else f"{name} (attempt {attempt})"
        try:
            return self.store.reserve_model_call(self.iid, self.token, label, image_id=image_id,
                                                 idempotency_key=self.key, global_limit=self.global_limit)
        except ModelCallBudgetExhausted as e:
            raise BudgetExhausted(str(e)) from e

    def after_request(self, ticket: int, ok: bool, detail: dict[str, Any]) -> None:
        self.store.settle_model_call(self.iid, self.token, ticket, "ok" if ok else "error", detail)


class _Heartbeat:
    """Renews the lease every `interval` seconds until stopped; records loss of the lease."""

    def __init__(self, store: Store, inspection_id: str, token: str, interval: float) -> None:
        self.store, self.iid, self.token, self.interval = store, inspection_id, token, interval
        self.lost = False
        self.renewals = 0
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                self.store.renew_lease(self.iid, self.token)
                self.renewals += 1
            except LeaseLost:
                self.lost = True
                return
            except Exception:  # transient storage trouble: keep trying; expiry + commit checks stay safe
                log.warning("lease heartbeat failed for %s", self.iid, exc_info=True)

    async def stop(self) -> None:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


def _source_name(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()[:120]
    return base or "capture.jpg"


class InspectionService:
    def __init__(self, settings: Settings, store: Store, transport: httpx.AsyncBaseTransport | None = None,
                 config: ServiceConfig | None = None) -> None:
        self.settings = settings
        self.store = store
        self.transport = transport
        self.config = config or ServiceConfig()
        self._inflight: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ lifecycle

    def recover_stale(self) -> list[RecoveryReport]:
        """Recover leases abandoned by a dead process (heartbeat older than lease_stale_after_s). Never touches a
        lease that is being renewed. Idempotent."""
        reports = self.store.recover_interrupted(stale_before=time.time() - self.config.lease_stale_after_s)
        for r in reports:
            log.warning("recovered stale lease on %s: interrupted %s, unknown-outcome calls %s",
                        r.inspection_id, r.interrupted_submissions, r.unknown_outcome_calls)
        return reports

    async def shutdown(self) -> None:
        """Cancel in-flight steps; each records its failure and releases its lease before finishing."""
        tasks = list(self._inflight)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------ helpers

    @contextlib.asynccontextmanager
    async def _read_only_agent(self, bundle: RestoreBundle) -> AsyncIterator[InspectionAgent]:
        client = MetaClient(self.settings, Trace.from_events(bundle.trace_events), transport=_READ_ONLY_TRANSPORT,
                            source=self.config.model_source)
        try:
            yield InspectionAgent.restore(bundle.state, client, self.settings, bundle.images)
        finally:
            await client.aclose()

    def _bundle(self, inspection_id: str) -> RestoreBundle:
        try:
            return self.store.load_restore_bundle(inspection_id)
        except InspectionNotFound as e:
            raise ServiceError(404, "not_found", f"inspection {inspection_id} not found") from e
        except StoreCorruptionError as e:
            log.error("corrupt inspection %s: %s", inspection_id, e)
            raise ServiceError(500, "storage_corrupt", "stored inspection data is unreadable") from e

    def _usage(self, inspection_id: str, counter: int, limit: int, trace: Trace) -> Usage:
        by_status = Counter(c.status for c in self.store.list_model_calls(inspection_id))
        return Usage(model_calls=counter, model_call_limit=limit, remaining=max(0, limit - counter),
                     calls_by_status=dict(by_status), estimated_cost_usd=trace.summary()["estimated_cost_usd"])

    def list_specs(self) -> list[SpecSummary]:
        """Specifications that can be started now (free; no model calls). Files that do not validate (for example
        drafts still holding TODO placeholders) are left out, never offered."""
        out = []
        for p in sorted(self.config.specs_dir.glob("*.json")):
            if not (p.is_file() and _SPEC_ID.match(p.stem)):
                continue
            try:
                spec = InspectionSpec.load(p)
            except (ValidationError, ValueError, OSError):
                continue
            out.append(SpecSummary(
                spec_id=p.stem, title=spec.title, devices=[d.name for d in spec.devices],
                max_photos=spec.max_photos,
                requirements=[SpecRequirementSummary(
                    id=r.id, text=r.text, connector=r.connector, cable_color=r.cable_color,
                    endpoints=[SpecEndpointSummary(device=spec.device(e.device_id).name, port=e.port_label,
                                                   flexible=e.flexible) for e in r.endpoints])
                              for r in spec.requirements]))
        return out

    def _load_spec(self, spec_id: str) -> InspectionSpec:
        if not _SPEC_ID.match(spec_id):
            raise ServiceError(422, "invalid_spec_id", "spec_id must be a plain name like 'router_switch'")
        allowed = {p.stem: p for p in self.config.specs_dir.glob("*.json") if p.is_file()}
        if spec_id not in allowed:
            raise ServiceError(404, "spec_not_found", f"no specification named {spec_id!r}")
        try:
            return InspectionSpec.load(allowed[spec_id])
        except (ValidationError, ValueError) as e:
            log.error("invalid spec file %s: %s", spec_id, e)
            raise ServiceError(500, "spec_invalid", f"specification {spec_id!r} is invalid on the server") from e

    def _acquire(self, inspection_id: str) -> str:
        for first in (True, False):
            try:
                return self.store.acquire_lease(inspection_id)
            except InspectionNotFound as e:
                raise ServiceError(404, "not_found", f"inspection {inspection_id} not found") from e
            except InspectionBusy as e:
                if first and self.recover_stale():
                    continue
                raise ServiceError(409, "inspection_busy", "another operation is in progress for this "
                                                           "inspection; retry shortly") from e
        raise AssertionError("unreachable")

    def _begin(self, inspection_id: str, key: str, image_id: str) -> CaptureStarted | CaptureCompleted:
        for first in (True, False):
            try:
                return self.store.begin_capture(inspection_id, key, image_id)
            except InspectionNotFound as e:
                raise ServiceError(404, "not_found", f"inspection {inspection_id} not found") from e
            except IdempotencyConflict as e:
                raise ServiceError(409, "idempotency_conflict",
                                   "this Idempotency-Key was already used with a different photo") from e
            except InspectionBusy as e:
                if first and self.recover_stale():
                    continue
                raise ServiceError(409, "inspection_busy", "another capture is being processed for this "
                                                           "inspection; retry shortly") from e
        raise AssertionError("unreachable")

    # ------------------------------------------------------------------ inspections

    async def create_inspection(self, *, spec_id: str | None = None,
                                spec: InspectionSpec | None = None) -> InspectionState:
        if (spec_id is None) == (spec is None):
            raise ServiceError(422, "invalid_request", "give exactly one of spec_id or spec")
        if spec_id is not None:
            spec = self._load_spec(spec_id)
        inspection_id = "insp_" + uuid.uuid4().hex
        client = MetaClient(self.settings, Trace(), transport=_READ_ONLY_TRANSPORT, source=self.config.model_source)
        try:
            state = InspectionAgent(spec, client, self.settings,  # type: ignore[arg-type]
                                    require_grounding=self.config.require_grounding).snapshot()
        finally:
            await client.aclose()
        self.store.create_inspection(inspection_id, state, spec_id=spec_id)
        return await self.get_inspection(inspection_id)

    async def get_inspection(self, inspection_id: str) -> InspectionState:
        bundle = self._bundle(inspection_id)
        async with self._read_only_agent(bundle) as agent:
            return self._state(bundle, agent)

    def _state(self, bundle: RestoreBundle, agent: InspectionAgent) -> InspectionState:
        rec, iid = bundle.record, bundle.record.id
        overlays = set(self.store.load_overlays(iid))
        photos = [PhotoInfo(seq=o.seq, image_id=o.image_id, source_name=o.source_name, width=o.width,
                            height=o.height, epoch=o.epoch, superseded=o.epoch != agent.epoch, usable=o.usable,
                            responding_to=o.responding_to,
                            photo_url=f"/api/inspections/{iid}/photos/{o.image_id}",
                            overlay_url=(f"/api/inspections/{iid}/overlays/{o.image_id}"
                                         if o.image_id in overlays else None))
                  for o in agent.observations]
        return InspectionState(
            id=iid, spec_id=rec.spec_id, title=rec.title, status=rec.status, stop_reason=rec.stop_reason,
            epoch=rec.epoch, version=rec.version, engine_version=rec.engine_version,
            engine_changed=rec.engine_version != engine_version(), policy_drift=agent.policy_drift(),
            busy=rec.lease_token is not None, created_at=rec.created_at, spec=agent.spec, photos=photos, assessments=agent.assessments,
            overall=overall_assessment(agent.assessments),
            next_view=agent.requests[-1] if agent.requests and not agent.done else None,
            review_required=agent.review_items(), exhausted_gaps=dict(agent.exhausted), history=agent.history,
            usage=self._usage(iid, rec.model_calls_reserved, rec.model_call_limit, agent.trace),
            disclaimer=DISCLAIMER)

    # ------------------------------------------------------------------ captures

    async def submit_capture(self, inspection_id: str, data: bytes, *, idempotency_key: str | None = None,
                             source_name: str | None = None, responding_to: str | None = None) -> StepResponse:
        if len(data) > self.config.max_upload_bytes:
            raise ServiceError(413, "upload_too_large",
                               f"photo exceeds {self.config.max_upload_bytes // (1024 * 1024)} MB")
        if not data:
            raise ServiceError(422, "empty_upload", "the uploaded file is empty")
        if idempotency_key is not None and not _IDEMPOTENCY_KEY.match(idempotency_key):
            raise ServiceError(422, "invalid_idempotency_key", "Idempotency-Key must be 1-200 visible ASCII chars")
        if responding_to is not None and not (0 < len(responding_to) <= 64):
            raise ServiceError(422, "invalid_request", "responding_to must be a next-view request id")
        key = idempotency_key or f"auto-{uuid.uuid4().hex}"
        try:
            img = await asyncio.to_thread(normalize_image_bytes, data, _source_name(source_name),
                                          self.settings.image_max_side)
        except ImageLoadError as e:
            raise ServiceError(422, "image_not_decodable", "the upload is not a decodable image") from e
        except Image.DecompressionBombError as e:
            raise ServiceError(422, "image_too_large", "the image has too many pixels") from e

        started = self._begin(inspection_id, key, img.image_id)
        if isinstance(started, CaptureCompleted):
            return StepResponse.model_validate({**started.response, "replayed": True})
        task = asyncio.create_task(self._run_capture(inspection_id, key, started, img, responding_to))
        self._inflight.add(task)
        task.add_done_callback(self._task_done)
        return await asyncio.shield(task)

    def _task_done(self, task: asyncio.Task) -> None:
        self._inflight.discard(task)
        if not task.cancelled():
            task.exception()  # retrieved here so a step whose caller went away is not reported as unobserved

    async def _run_capture(self, iid: str, key: str, started: CaptureStarted, img: NormalizedImage,
                           responding_to: str | None) -> StepResponse:
        token = started.lease_token
        heartbeat = _Heartbeat(self.store, iid, token, self.config.lease_heartbeat_s)
        agent: InspectionAgent | None = None
        n_trace = 0
        try:
            bundle = self.store.load_restore_bundle(iid)  # under the lease: the latest committed state
            state = bundle.state
            if state.stop_reason is not None:
                raise ServiceError(409, "inspection_stopped",
                                   f"inspection stopped ({state.stop_reason}); declare an installation change to "
                                   "continue" if state.stop_reason not in ("observation_budget_exhausted",
                                                                           "model_call_budget_exhausted")
                                   else f"inspection stopped ({state.stop_reason}); its budget cannot be reopened")
            limit = self.config.global_call_limit
            if limit is not None and self.store.total_model_calls() + self.config.capture_call_reserve > limit:
                raise ServiceError(429, "spend_cap_reached",
                                   f"the server's model-call cap ({limit} calls across all inspections) does not "
                                   "leave enough for another photo; nothing was sent to the models")
            current = state.requests[-1].id if state.requests else None
            if responding_to is not None and responding_to != current:
                raise ServiceError(409, "stale_guidance",
                                   f"this photo answers {responding_to!r}, but the current guidance is "
                                   f"{current!r}")
            client = MetaClient(self.settings, Trace.from_events(bundle.trace_events), transport=self.transport,
                                source=self.config.model_source,
                                accounting=StoreAccounting(self.store, iid, token, key,
                                                           self.config.global_call_limit))
            try:
                agent = InspectionAgent.restore(state, client, self.settings, bundle.images)
                n_obs, n_trace = len(agent.observations), len(agent.trace.events)
                step = await agent.observe(img)
            finally:
                await client.aclose()
            if heartbeat.lost:
                raise LeaseLost(f"inspection {iid}: lease lost during processing")
            overlays = {o.image_id: render_overlay_jpeg(agent.images[o.image_id], o, agent.grounding_runs.get(o.seq))
                        for o in agent.observations[n_obs:] if o.extraction is not None and o.image_id in agent.images}
            snapshot = agent.snapshot()
            counter = max(self.store.get_inspection(iid).model_calls_reserved, snapshot.model_calls_started)
            response = self._step_response(iid, step, agent, bundle.version + 1, counter, snapshot.model_call_limit)
            self.store.commit_step(iid, token, bundle.version, snapshot, agent.trace.events, agent.images, overlays,
                                   idempotency_key=key, response=response.model_dump(mode="json"))
            return response
        except BaseException as e:
            self._fail(iid, token, key, e, agent, n_trace)
            if isinstance(e, LeaseLost):
                raise ServiceError(409, "lease_lost", "the inspection lease expired while this photo was being "
                                                      "processed; nothing was saved, retry the capture") from e
            if isinstance(e, (VersionConflict, AppendOnlyViolation)):
                raise ServiceError(409, "conflict", "the inspection changed concurrently; nothing was saved, "
                                                    "retry the capture") from e
            if isinstance(e, StoreCorruptionError):
                log.error("corrupt inspection %s: %s", iid, e)
                raise ServiceError(500, "storage_corrupt", "stored inspection data is unreadable") from e
            raise
        finally:
            await heartbeat.stop()

    def _fail(self, iid: str, token: str, key: str, e: BaseException, agent: InspectionAgent | None,
              n_trace: int) -> None:
        """Record the failed attempt (audit only; nothing of it enters the evidence) and release the lease."""
        code = e.code if isinstance(e, ServiceError) else type(e).__name__
        error = f"{code}: {e}"[:500] if str(e) else code
        detail: dict[str, Any] = {"error_type": type(e).__name__}
        if agent is not None:
            detail["attempt_trace"] = [{"seq": ev.seq, "kind": ev.kind, "name": ev.name, "status": ev.status,
                                        "source": ev.source, "error": (ev.error or "")[:300] or None}
                                       for ev in agent.trace.events[n_trace:]]
        try:
            try:
                self.store.fail_submission(iid, token, key, error, detail)
            except UnsafeContent:
                self.store.fail_submission(iid, token, key, code, None)
        except LeaseLost:
            pass  # lease was recovered meanwhile; recovery already marked the submission interrupted
        except StoreError:
            log.exception("could not record failed capture on %s; the lease will expire and be recovered", iid)

    def _step_response(self, iid: str, step: StepResult, agent: InspectionAgent, version: int, counter: int,
                       limit: int) -> StepResponse:
        last = agent.history[-1] if agent.history else {}
        return StepResponse(
            inspection_id=iid, seq=step.seq, image_id=step.image_id, duplicate_of=last.get("duplicate_of"),
            notes=step.notes, status="stopped" if agent.done else "open", stop_reason=agent.stop_reason,
            assessments=step.assessments, overall=overall_assessment(step.assessments), next_view=step.next_view,
            review_required=agent.review_items(),
            version=version,
            usage=self._usage(iid, counter, limit, agent.trace))

    # ------------------------------------------------------------------ events

    async def declare_installation_changed(self, inspection_id: str, reason: str) -> InspectionState:
        token = self._acquire(inspection_id)
        try:
            bundle = self._bundle(inspection_id)
            async with self._read_only_agent(bundle) as agent:
                try:
                    agent.mark_installation_changed(reason)
                except RuntimeError as e:
                    raise ServiceError(409, "cannot_reopen", str(e)) from e
                self.store.commit_step(inspection_id, token, bundle.version, agent.snapshot(), agent.trace.events,
                                       agent.images)
        except BaseException:
            with contextlib.suppress(StoreError):
                self.store.release_lease(inspection_id, token)
            raise
        return await self.get_inspection(inspection_id)

    # ------------------------------------------------------------------ reports and images

    async def get_report(self, inspection_id: str, fmt: str = "json") -> dict[str, Any] | str:
        bundle = self._bundle(inspection_id)
        overlays = {i: f"/api/inspections/{inspection_id}/overlays/{i}" for i in self.store.load_overlays(inspection_id)}
        async with self._read_only_agent(bundle) as agent:
            drift = agent.policy_drift()
            usage = self._usage(inspection_id, bundle.record.model_calls_reserved, bundle.record.model_call_limit,
                                agent.trace)
            if fmt == "md":
                md = render_markdown(agent, overlays, agent.trace.summary())
                if drift:
                    md = (f"> **Policy drift:** the current policy would not reproduce the stored assessment of "
                          f"{', '.join(drift)}. Stored verdicts are shown unchanged.\n\n") + md
                return md
            report = build_report(agent, inspection_id, overlays)
        report.update({"policy_drift": drift, "persistent_usage": usage.model_dump(),
                       "engine_version": {"recorded": bundle.record.engine_version, "current": engine_version()},
                       "version": bundle.record.version})
        return report

    def get_photo(self, inspection_id: str, image_id: str) -> bytes:
        self._check_image_request(inspection_id, image_id)
        try:
            return self.store.load_photo(inspection_id, image_id).jpeg_bytes
        except StoreCorruptionError as e:
            raise ServiceError(500, "storage_corrupt", "stored photo is unreadable") from e
        except StoreError as e:
            raise ServiceError(404, "photo_not_found", f"photo {image_id} not found") from e

    def get_overlay(self, inspection_id: str, image_id: str) -> bytes:
        self._check_image_request(inspection_id, image_id)
        try:
            data = self.store.load_overlay(inspection_id, image_id)
        except StoreError as e:
            raise ServiceError(404, "photo_not_found", f"photo {image_id} not found") from e
        if data is None:
            raise ServiceError(404, "overlay_not_found", f"no stored overlay for {image_id}")
        return data

    def _check_image_request(self, inspection_id: str, image_id: str) -> None:
        if not _IMAGE_ID.match(image_id):
            raise ServiceError(404, "photo_not_found", "unknown image id")
        try:
            self.store.get_inspection(inspection_id)
        except InspectionNotFound as e:
            raise ServiceError(404, "not_found", f"inspection {inspection_id} not found") from e

    def spend(self) -> dict[str, Any]:
        limit = self.config.global_call_limit
        used = self.store.total_model_calls()
        return {"global_model_calls": used, "global_call_limit": limit,
                "global_remaining": None if limit is None else max(0, limit - used)}

    def health(self) -> dict[str, Any]:
        problems = self.store.check_integrity()
        return {"status": "ok" if not problems else "degraded", "schema_version": self.store.schema_version,
                "integrity_problems": problems, "engine_version": engine_version(),
                "model_source": self.config.model_source}
