"""M1 Stage 3: InspectionService = M0 agent + MetaClient + SQLite store. Mocked Meta responses only.

A "restart" closes the Store and builds a new Store + service on the same database file. A "second process" is a
second Store + service on the same file used concurrently.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from fakes import FakeMeta, plan, settings
from proofcam.agent import InspectionAgent
from proofcam.images import normalize_image_bytes
from proofcam.meta_client import MetaClient
from proofcam.service import InspectionService, ServiceConfig, ServiceError
from proofcam.store import Store
from proofcam.trace import Trace
from test_agent import FRONT, OBS, PLAN, REAR_BOTH, SPEC, base_fake
from test_persistence import comparable_trace


# ---------------------------------------------------------------------------- helpers

def photo(name: str, size=(400, 300)) -> bytes:
    """Raw upload bytes (a synthetic JPEG; not a real photograph)."""
    buf = io.BytesIO()
    Image.new("RGB", size, tuple(hashlib.sha256(name.encode()).digest()[:3])).save(buf, "JPEG")
    return buf.getvalue()


def image_id_of(name: str) -> str:
    return normalize_image_bytes(photo(name), name).image_id


def db(tmp_path: Path) -> Path:
    return tmp_path / "var" / "proofcam.db"


def make_service(tmp_path: Path, transport: httpx.AsyncBaseTransport | FakeMeta, budget: dict | None = None,
                 **cfg) -> InspectionService:
    if isinstance(transport, FakeMeta):
        transport = httpx.MockTransport(transport.handler)
    cfg.setdefault("model_source", "mock")
    return InspectionService(settings(**(budget or {})), Store(db(tmp_path)), transport, ServiceConfig(**cfg))


def restart(svc: InspectionService, tmp_path: Path, transport=None, **cfg) -> InspectionService:
    svc.store.close()
    budget = dict(svc.settings.budget.__dict__)
    return make_service(tmp_path, transport or svc.transport, budget, **cfg)


def two_photo_fake() -> FakeMeta:
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    return fm


class Gate:
    """Async transport that holds every model request until released (to create overlap)."""

    def __init__(self, fm: FakeMeta) -> None:
        self.fm = fm
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.entered.set()
        await self.release.wait()
        return self.fm.handler(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


async def create(svc: InspectionService) -> str:
    return (await svc.create_inspection(spec_id="router_switch")).id


def run(coro):
    return asyncio.run(coro)


# ============================================================================ A. service workflow

def test_create_and_load_inspection(tmp_path):
    async def go():
        svc = make_service(tmp_path, base_fake())
        st = await svc.create_inspection(spec_id="router_switch")
        assert st.id.startswith("insp_") and st.status == "open" and st.version == 0
        assert st.spec == SPEC and st.photos == [] and st.assessments == [] and st.next_view is None
        assert (st.usage.model_calls, st.usage.model_call_limit, st.usage.remaining) == (0, 40, 40)
        assert st.policy_drift == [] and not st.engine_changed and not st.busy
        inline = await svc.create_inspection(spec=SPEC)
        assert inline.spec_id is None and inline.spec == SPEC
        assert (await svc.get_inspection(st.id)) == st
    run(go())


def test_two_photos_accumulate_evidence_and_guidance(tmp_path):
    async def go():
        fm = two_photo_fake()
        svc = make_service(tmp_path, fm)
        iid = await create(svc)
        s1 = await svc.submit_capture(iid, photo("front.jpg"), source_name="front.jpg")
        assert s1.seq == 1 and s1.status == "open" and s1.assessments[0].status == "INSUFFICIENT_EVIDENCE"
        assert s1.next_view.id == "nv1" and s1.next_view.planner == "muse"
        assert s1.next_view.gap_code == "PORTS_NOT_VISIBLE"
        s2 = await svc.submit_capture(iid, photo("rear.jpg"), source_name="rear.jpg", responding_to="nv1")
        a = s2.assessments[0]
        assert a.status == "VERIFIED" and s2.status == "stopped" and s2.stop_reason == "all_requirements_resolved"
        assert {x.image_id for ep in a.endpoints for x in ep.support} == {image_id_of("rear.jpg")}
        st = await svc.get_inspection(iid)
        assert [p.image_id for p in st.photos] == [image_id_of("front.jpg"), image_id_of("rear.jpg")]
        assert st.photos[1].responding_to == "nv1" and st.next_view is None
        assert all(p.overlay_url for p in st.photos)
        steps = svc.store.load_steps(iid)
        assert [s.assessments[0].status for s in steps] == ["INSUFFICIENT_EVIDENCE", "VERIFIED"]
        assert {e.source for e in svc.store.load_restore_bundle(iid).trace_events if e.kind == "model_call"} \
            == {"mock"}
    run(go())


def test_restart_between_photos_matches_an_uninterrupted_agent(tmp_path):
    # reference: plain M0 agent, same photos, no persistence
    ref_fm = two_photo_fake()
    ref = InspectionAgent(SPEC, ref_fm.client(settings()), settings())
    for name in ("front.jpg", "rear.jpg"):
        run(ref.observe(normalize_image_bytes(photo(name), name)))

    async def go():
        fm = two_photo_fake()
        svc = make_service(tmp_path, fm)
        iid = await create(svc)
        await svc.submit_capture(iid, photo("front.jpg"), source_name="front.jpg")
        usage1 = (await svc.get_inspection(iid)).usage
        svc = restart(svc, tmp_path)
        assert (await svc.get_inspection(iid)).usage == usage1  # budget restored, not reset
        await svc.submit_capture(iid, photo("rear.jpg"), source_name="rear.jpg")
        svc = restart(svc, tmp_path)
        b = svc.store.load_restore_bundle(iid)
        agent = InspectionAgent.restore(b.state, MetaClient(svc.settings, Trace.from_events(b.trace_events)),
                                        svc.settings, b.images)
        assert agent.snapshot().model_dump() == ref.snapshot().model_dump()  # evidence, requests, gaps, stop...
        assert comparable_trace(agent) == comparable_trace(ref)
        assert [e.seq for e in agent.trace.events] == list(range(len(agent.trace.events)))
        assert {i: im.jpeg_bytes for i, im in agent.images.items()} == \
               {i: im.jpeg_bytes for i, im in ref.images.items()}
        st = await svc.get_inspection(iid)
        assert st.usage.model_calls == ref.client.calls_started == len(fm.requests)
        assert st.stop_reason == "all_requirements_resolved"
    run(go())


def test_installation_change_and_budget_stop_behaviour(tmp_path):
    async def go():
        fm = two_photo_fake()
        svc = make_service(tmp_path, fm)
        iid = await create(svc)
        await svc.submit_capture(iid, photo("front.jpg"))
        st = await svc.declare_installation_changed(iid, "cable moved")
        assert st.epoch == 1 and st.photos[0].superseded and not st.busy
        assert st.history[-1]["event"] == "installation_changed"
        s2 = await svc.submit_capture(iid, photo("rear.jpg"))
        assert s2.assessments[0].status == "VERIFIED"
        assert [p.epoch for p in (await svc.get_inspection(iid)).photos] == [0, 1]
        assert [s.kind for s in svc.store.load_steps(iid)] == ["photo", "installation_changed", "photo"]

        fm2 = base_fake()
        fm2.queue_chat(OBS, FRONT)
        fm2.queue_chat(PLAN, plan())
        svc2 = make_service(tmp_path / "b", fm2, budget={"max_observations": 1})
        iid2 = await create(svc2)
        s = await svc2.submit_capture(iid2, photo("a.jpg"))
        assert s.stop_reason == "observation_budget_exhausted"
        with pytest.raises(ServiceError) as e:
            await svc2.declare_installation_changed(iid2, "moved")
        assert (e.value.status, e.value.code) == (409, "cannot_reopen")
        with pytest.raises(ServiceError) as e:
            await svc2.submit_capture(iid2, photo("b.jpg"))
        assert (e.value.status, e.value.code) == (409, "inspection_stopped")
        assert not (await svc2.get_inspection(iid2)).busy  # failed attempts never leave the lease held
    run(go())


def test_policy_drift_is_reported_without_replacing_the_stored_verdict(tmp_path):
    async def go():
        svc = make_service(tmp_path, two_photo_fake())
        iid = await create(svc)
        await svc.submit_capture(iid, photo("front.jpg"))
        conn = svc.store._conn
        ctl = conn.execute("SELECT control_json FROM inspections WHERE id = ?", (iid,)).fetchone()[0]
        conn.execute("UPDATE inspections SET control_json = ? WHERE id = ?",
                     (ctl.replace('"status":"INSUFFICIENT_EVIDENCE"', '"status":"VERIFIED"'), iid))
        st = await svc.get_inspection(iid)
        assert st.policy_drift == [SPEC.requirements[0].id]
        assert st.assessments[0].status == "VERIFIED"  # shown as stored, flagged, never silently replaced
        report = await svc.get_report(iid)
        assert report["policy_drift"] == [SPEC.requirements[0].id]
        assert "Policy drift" in await svc.get_report(iid, "md")
    run(go())


# ============================================================================ B. model-call accounting

def test_every_request_is_reserved_before_it_is_sent(tmp_path):
    seen: list[tuple[int, str | None]] = []
    holder: dict = {}

    async def go():
        fm = two_photo_fake()

        def checking(request: httpx.Request) -> httpx.Response:
            calls = holder["svc"].store.list_model_calls(holder["iid"])
            seen.append((len(calls), calls[-1].status if calls else None))
            return fm.handler(request)

        svc = make_service(tmp_path, httpx.MockTransport(checking))
        holder["svc"], holder["iid"] = svc, await create(svc)
        await svc.submit_capture(holder["iid"], photo("front.jpg"))
        await svc.submit_capture(holder["iid"], photo("rear.jpg"))
        calls = svc.store.list_model_calls(holder["iid"])
        assert seen == [(k, "reserved") for k in range(1, len(fm.requests) + 1)]
        assert [c.ordinal for c in calls] == list(range(1, len(fm.requests) + 1))  # no duplicates, no gaps
        assert {c.status for c in calls} == {"ok"}
        assert all(c.image_id for c in calls) and {c.attempt for c in calls} == {1}
        assert (await svc.get_inspection(holder["iid"])).usage.model_calls == len(fm.requests)
    run(go())


def test_retries_are_counted_per_attempt_and_failed_attempts_settled_as_errors(tmp_path):
    async def go():
        fm = two_photo_fake()
        fm.chat[OBS].appendleft(httpx.Response(503, json={"error": {"message": "overloaded"}}))
        svc = make_service(tmp_path, fm)
        iid = await create(svc)
        s = await svc.submit_capture(iid, photo("front.jpg"))
        calls = svc.store.list_model_calls(iid)
        assert s.usage.model_calls == len(calls) == len(fm.requests)
        assert (calls[0].status, calls[0].detail["http_status"]) == ("error", 503)
        assert calls[1].status == "ok" and "attempt 2" in calls[1].name
        assert s.usage.calls_by_status == {"error": 1, "ok": len(calls) - 1}
    run(go())


def test_store_budget_refuses_the_request_before_it_is_sent(tmp_path):
    async def go():
        fm = two_photo_fake()
        fm.chat[OBS].appendleft(httpx.Response(503, json={"error": {"message": "overloaded"}}))
        svc = make_service(tmp_path, fm, budget={"max_model_calls": 2})
        iid = await create(svc)
        s = await svc.submit_capture(iid, photo("front.jpg"))
        # Muse needed 2 HTTP attempts = the whole budget; SAM and the planner were refused before sending.
        assert len(fm.requests) == 2 and s.usage.model_calls == 2 and s.usage.remaining == 0
        assert any("SAM" in n and "budget" in n for n in s.notes)
        n = len(fm.requests)
        svc = restart(svc, tmp_path)  # the spent budget survives a restart
        s2 = await svc.submit_capture(iid, photo("rear.jpg"))
        assert s2.stop_reason == "model_call_budget_exhausted" and len(fm.requests) == n
        assert svc.store.get_inspection(iid).model_calls_reserved == 2
    run(go())


def test_cancelled_step_leaves_unknown_outcome_counted_once_and_unlocks(tmp_path):
    async def go():
        gate = Gate(two_photo_fake())
        svc = make_service(tmp_path, gate.transport())
        iid = await create(svc)
        task = asyncio.create_task(svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1"))
        await gate.entered.wait()  # the Muse request has been sent and is pending
        await svc.shutdown()  # server shutdown cancels the in-flight step
        with pytest.raises(asyncio.CancelledError):
            await task
        rec = svc.store.get_inspection(iid)
        assert rec.lease_token is None and rec.version == 0 and rec.model_calls_reserved == 1
        assert [(c.ordinal, c.status) for c in svc.store.list_model_calls(iid)] == [(1, "outcome_unknown")]
        sub = svc.store.get_submission(iid, "k1")
        assert sub.status == "failed" and sub.failures[-1]["unknown_outcome_calls"] == [1]
        assert svc.store.load_restore_bundle(iid).state.observations == []  # nothing partial committed
        # the same key can be retried; the unknown call stays counted once
        gate.release.set()
        s = await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        calls = svc.store.list_model_calls(iid)
        # the cancelled request never got past the gate, so the fake saw only the retry's requests
        assert s.seq == 1 and s.usage.model_calls == len(calls) == 1 + len(gate.fm.requests)
        assert calls[0].status == "outcome_unknown" and {c.status for c in calls[1:]} == {"ok"}
    run(go())


def test_dead_process_lease_is_recovered_and_its_late_result_is_never_committed(tmp_path):
    async def go():
        gate = Gate(two_photo_fake())
        # Process A: its heartbeat never fires during the test (as if the process had frozen or died).
        a = make_service(tmp_path, gate.transport(), lease_heartbeat_s=100, lease_stale_after_s=300)
        iid = await create(a)
        task = asyncio.create_task(a.submit_capture(iid, photo("front.jpg"), idempotency_key="k1"))
        await gate.entered.wait()
        # Process B on the same database, with a short staleness threshold.
        b = make_service(tmp_path, gate.transport(), lease_heartbeat_s=0.05, lease_stale_after_s=0.2)
        await asyncio.sleep(0.3)
        reports = b.recover_stale()
        assert [(r.inspection_id, r.interrupted_submissions, r.unknown_outcome_calls) for r in reports] == \
               [(iid, ["k1"], [1])]
        assert b.recover_stale() == []  # idempotent
        assert b.store.get_inspection(iid).model_calls_reserved == 1  # no worst-case or second charge
        gate.release.set()
        with pytest.raises(ServiceError) as e:  # A finishes late: it no longer owns the lease
            await task
        assert (e.value.status, e.value.code) == (409, "lease_lost")
        assert b.store.load_restore_bundle(iid).state.observations == []
        assert b.store.get_submission(iid, "k1").status == "interrupted"
        # B retries the same submission; the reservations continue without duplicates
        s = await b.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        calls = b.store.list_model_calls(iid)
        assert s.seq == 1 and [c.ordinal for c in calls] == list(range(1, len(calls) + 1))
        assert b.store.get_submission(iid, "k1").attempts == 2
        a.store.close()
    run(go())


def test_caller_disconnect_does_not_abort_the_step(tmp_path):
    async def go():
        gate = Gate(two_photo_fake())
        svc = make_service(tmp_path, gate.transport())
        iid = await create(svc)
        caller = asyncio.create_task(svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1"))
        await gate.entered.wait()
        caller.cancel()  # e.g. the phone dropped the HTTP connection
        with pytest.raises(asyncio.CancelledError):
            await caller
        gate.release.set()
        while svc._inflight:  # the step itself keeps running to completion
            await asyncio.sleep(0.01)
        rec = svc.store.get_inspection(iid)
        assert rec.version == 1 and rec.lease_token is None
        assert {c.status for c in svc.store.list_model_calls(iid)} == {"ok"}
        # the client's retry with the same key gets the committed result, with no new model calls
        n = len(gate.fm.requests)
        again = await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        assert again.replayed and again.seq == 1 and len(gate.fm.requests) == n
    run(go())


# ============================================================================ C. concurrency and leases

def test_concurrent_capture_is_rejected_and_heartbeat_keeps_the_lease(tmp_path):
    async def go():
        gate = Gate(two_photo_fake())
        svc = make_service(tmp_path, gate.transport(), lease_heartbeat_s=0.05, lease_stale_after_s=0.2)
        iid = await create(svc)
        first = asyncio.create_task(svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1"))
        await gate.entered.wait()
        acquired = svc.store.get_inspection(iid).lease_acquired_at
        await asyncio.sleep(0.5)  # longer than the staleness threshold: only the heartbeat keeps the lease
        rec = svc.store.get_inspection(iid)
        assert rec.lease_token is not None and rec.lease_heartbeat_at > acquired + 0.2
        # a second capture (another key) is refused; lazy recovery must not steal the active lease
        with pytest.raises(ServiceError) as e:
            await asyncio.wait_for(svc.submit_capture(iid, photo("other.jpg"), idempotency_key="k2"), 5)
        assert (e.value.status, e.value.code) == (409, "inspection_busy")
        other = make_service(tmp_path, gate.transport(), lease_heartbeat_s=0.05, lease_stale_after_s=0.2)
        assert other.recover_stale() == []
        assert svc.store.get_submission(iid, "k2") is None
        gate.release.set()
        s = await first
        assert s.seq == 1
        rec = svc.store.get_inspection(iid)
        assert rec.lease_token is None
        await asyncio.sleep(0.2)
        assert svc.store.get_inspection(iid).lease_heartbeat_at is None  # heartbeat stopped, nothing renewed
        assert svc._inflight == set()
        other.store.close()
    run(go())


def test_failed_capture_releases_the_lease_and_commits_nothing(tmp_path):
    async def go():
        fm = base_fake()
        fm.queue_chat(OBS, RuntimeError("bug in a dependency"), FRONT)
        fm.queue_chat(PLAN, plan())
        svc = make_service(tmp_path, fm)
        iid = await create(svc)
        with pytest.raises(RuntimeError, match="bug in a dependency"):
            await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        rec = svc.store.get_inspection(iid)
        assert rec.lease_token is None and rec.version == 0
        assert svc.store.load_restore_bundle(iid).state.observations == []
        sub = svc.store.get_submission(iid, "k1")
        assert sub.status == "failed" and sub.failures[0]["error"].startswith("RuntimeError")
        assert sub.failures[0]["detail"]["attempt_trace"][0]["kind"] == "agent_step"
        s = await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        assert s.seq == 1 and svc.store.get_submission(iid, "k1").attempts == 2
    run(go())


def test_failure_during_commit_leaves_no_partial_step(tmp_path, monkeypatch):
    async def go():
        svc = make_service(tmp_path, two_photo_fake())
        iid = await create(svc)

        def boom(*a, **k):
            raise RuntimeError("disk full")
        monkeypatch.setattr(Store, "_insert_trace", staticmethod(boom))
        with pytest.raises(RuntimeError, match="disk full"):
            await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        conn = svc.store._conn
        for table in ("photos", "observations", "next_view_requests", "steps", "trace_events"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        rec = svc.store.get_inspection(iid)
        assert rec.lease_token is None and rec.version == 0
        assert rec.model_calls_reserved == len(svc.store.list_model_calls(iid)) > 0  # spent calls stay counted
        assert svc.store.get_submission(iid, "k1").status == "failed"
    run(go())


# ============================================================================ D. idempotency

def test_idempotency_replay_conflict_and_duplicate_photo(tmp_path):
    async def go():
        fm = two_photo_fake()
        svc = make_service(tmp_path, fm)
        iid = await create(svc)
        s1 = await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        n_req, n_calls = len(fm.requests), svc.store.get_inspection(iid).model_calls_reserved
        svc = restart(svc, tmp_path)
        again = await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k1")
        assert again.replayed and not s1.replayed
        assert again.model_dump(exclude={"replayed"}) == s1.model_dump(exclude={"replayed"})
        assert len(fm.requests) == n_req and svc.store.get_inspection(iid).model_calls_reserved == n_calls
        assert len(svc.store.load_steps(iid)) == 1
        with pytest.raises(ServiceError) as e:
            await svc.submit_capture(iid, photo("rear.jpg"), idempotency_key="k1")
        assert (e.value.status, e.value.code) == (409, "idempotency_conflict")
        dup = await svc.submit_capture(iid, photo("front.jpg"), idempotency_key="k2")
        assert dup.duplicate_of == 1 and dup.seq == 1 and not dup.replayed
        assert len(fm.requests) == n_req and svc.store.get_inspection(iid).model_calls_reserved == n_calls
        assert [s.kind for s in svc.store.load_steps(iid)] == ["photo", "duplicate"]
    run(go())


def test_upload_validation(tmp_path):
    async def go():
        svc = make_service(tmp_path, base_fake(), max_upload_bytes=50_000)
        iid = await create(svc)
        cases = [(b"", 422, "empty_upload"), (b"not an image" * 10, 422, "image_not_decodable"),
                 (photo("a.jpg")[:200], 422, "image_not_decodable"), (b"\0" * 50_001, 413, "upload_too_large")]
        for data, status, code in cases:
            with pytest.raises(ServiceError) as e:
                await svc.submit_capture(iid, data)
            assert (e.value.status, e.value.code) == (status, code)
        with pytest.raises(ServiceError) as e:
            await svc.submit_capture(iid, photo("a.jpg"), idempotency_key="bad key with spaces")
        assert e.value.code == "invalid_idempotency_key"
        with pytest.raises(ServiceError) as e:
            await svc.submit_capture("insp_missing", photo("a.jpg"))
        assert (e.value.status, e.value.code) == (404, "not_found")
        assert svc.store.list_model_calls(iid) == [] and svc.store.get_submission(iid, "x") is None
    run(go())


# ============================================================================ F. M0 compatibility of the hook

def test_metaclient_without_accounting_behaves_as_before():
    async def go():
        fm = base_fake()
        fm.queue_chat(OBS, httpx.Response(503, json={"error": {}}), FRONT)
        c = MetaClient(settings(), Trace(), transport=httpx.MockTransport(fm.handler), source="mock")
        assert c.accounting is None
        await c.chat_structured(messages=[], schema_name=OBS, schema={}, image=None, purpose="p")
        assert c.calls_started == 1 and len(fm.requests) == 2  # one logical call, two HTTP attempts
        await c.aclose()
    run(go())
