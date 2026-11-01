"""M1.4 acceptance: FastAPI -> service -> SQLite -> agent, end to end. Mocked Meta responses only (FakeMeta /
MockTransport, trace source 'mock'); temporary SQLite databases; no live or paid calls.

Every scenario finishes with check_invariants(): contiguous call reservations equal to the HTTP requests actually
sent, no unsettled reservation without a lease, contiguous trace/observation sequences, photo bytes hashing to their
ids, SQLite integrity, and no VERIFIED requirement without established, SAM-corroborated support.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from fakes import FakeMeta, cable, device, extraction, plan, port, settings
from proofcam import cli
from proofcam.agent import InspectionAgent
from proofcam.api import create_app
from proofcam.config import REPO_ROOT, Settings
from proofcam.images import normalize_image_bytes
from proofcam.service import ServiceConfig
from proofcam.store import Store
from proofcam.trace import Trace
from test_agent import FRONT, OBS, PLAN, REAR_BOTH, ROUTER_CLOSE, SPEC, SWITCH_CLOSE, WIDE_TRACE, base_fake
from test_api import upload
from test_persistence import STEP_BACK, comparable_trace
from test_service import Gate, photo

BACKEND = Path(__file__).resolve().parents[1]
VIOL = extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 1", occ="empty", color=None)])


# ---------------------------------------------------------------------------- harness

@contextlib.asynccontextmanager
async def server(tmp_path: Path, transport, budget: dict | None = None, **cfg):
    """One 'server process': app + Store on the database file under tmp_path. Leaving it = shutdown."""
    if isinstance(transport, FakeMeta):
        transport = httpx.MockTransport(transport.handler)
    store = Store(tmp_path / "var" / "proofcam.db")
    cfg.setdefault("model_source", "mock")
    app = create_app(settings(**(budget or {})), store, transport, config=ServiceConfig(**cfg))
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                         base_url="http://proofcam.test") as c:
                yield c, store, app
    finally:
        store.close()


async def create(c: httpx.AsyncClient, spec_id: str = "router_switch") -> str:
    r = await c.post("/api/inspections", json={"spec_id": spec_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def cap(c: httpx.AsyncClient, iid: str, name: str, key: str | None = None, data: bytes | None = None,
              **form) -> httpx.Response:
    headers = {"Idempotency-Key": key} if key else {}
    return await c.post(f"/api/inspections/{iid}/captures", **upload(name, data, **form), headers=headers)


def check_invariants(store: Store, iid: str, sent: int | None = None) -> None:
    b = store.load_restore_bundle(iid)
    rec, state = b.record, b.state
    calls = store.list_model_calls(iid)
    assert [c.ordinal for c in calls] == list(range(1, len(calls) + 1)), "call reservations not contiguous"
    assert rec.model_calls_reserved == len(calls) <= rec.model_call_limit
    if sent is not None:
        assert rec.model_calls_reserved == sent, "reservations != HTTP requests actually sent"
    if rec.lease_token is None:
        assert all(c.status != "reserved" for c in calls), "unsettled reservation without a lease"
    assert [e.seq for e in b.trace_events] == list(range(len(b.trace_events)))
    assert [o.seq for o in state.observations] == list(range(1, len(state.observations) + 1))
    images = {i.image_id: i for i in b.images}
    assert {o.image_id for o in state.observations} <= set(images)
    for i in images.values():
        assert "img_" + hashlib.sha256(i.jpeg_bytes).hexdigest()[:12] == i.image_id
    assert store.check_integrity() == []
    for a in state.assessments:
        if a.status == "VERIFIED":  # no false VERIFIED: every endpoint established with grounded support
            assert a.identity_state in ("established", "assumed_by_spec") and not a.contradictions
            for ep in a.endpoints:
                assert ep.state == "established" and ep.support
                assert all(s.grounding is not None and s.grounding.corroborated for s in ep.support)


def json_of(x):
    return json.loads(json.dumps(x, default=lambda m: m.model_dump(mode="json")))


# ---------------------------------------------------------------------------- scenarios

SCENARIOS = {
    "verified": dict(obs=[FRONT, REAR_BOTH], plans=[plan()], names=["front.jpg", "rear.jpg"], budget={},
                     expect=("VERIFIED", "all_requirements_resolved")),
    "violated": dict(obs=[VIOL], plans=[], names=["empty_port.jpg"], budget={},
                     expect=("VIOLATED", "all_requirements_resolved")),
    "insufficient": dict(obs=[FRONT] * 6, plans=[plan()] * 6, names=[f"f{i}.jpg" for i in range(6)],
                         budget={"max_observations": 10, "max_attempts_per_gap": 2},
                         expect=("INSUFFICIENT_EVIDENCE", "no_visually_resolvable_gaps")),
}


def fake_for(sc: dict) -> FakeMeta:
    fm = base_fake()
    fm.queue_chat(OBS, *sc["obs"])
    if sc["plans"]:
        fm.queue_chat(PLAN, *sc["plans"])
    return fm


def direct_m0(sc: dict, names: list[str] | None = None) -> InspectionAgent:
    """The same photos through the plain M0 engine: no API, no SQLite."""
    fm = fake_for(sc)
    s = settings(**sc["budget"])
    ag = InspectionAgent(SPEC, fm.client(s), s)
    for name in names or sc["names"]:
        if ag.done:
            break
        asyncio.run(ag.observe(normalize_image_bytes(photo(name), name)))
    return ag


# ============================================================================ 1. end to end

@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_verdicts_over_http_with_restart_between_photos_match_direct_m0(tmp_path, scenario):
    sc = SCENARIOS[scenario]
    ref = direct_m0(sc)
    fm = fake_for(sc)

    async def go():
        async with server(tmp_path, fm, sc["budget"]) as (c, _, _a):
            iid = await create(c)
        prev_remaining, seen = None, []
        for name in sc["names"]:
            async with server(tmp_path, fm, sc["budget"]) as (c, store, _a):  # a fresh server per photo
                state = (await c.get(f"/api/inspections/{iid}")).json()
                if state["status"] == "stopped":
                    break
                guidance = state["next_view"]["id"] if state["next_view"] else None
                r = await cap(c, iid, name, responding_to=guidance) if guidance else await cap(c, iid, name)
                assert r.status_code == 200, r.text
                seen.append(r.json()["next_view"]["id"] if r.json()["next_view"] else None)
                remaining = r.json()["usage"]["remaining"]
                assert prev_remaining is None or remaining <= prev_remaining  # budget never reset
                prev_remaining = remaining
        async with server(tmp_path, fm, sc["budget"]) as (c, store, _a):
            state = (await c.get(f"/api/inspections/{iid}")).json()
            status, stop = sc["expect"]
            assert state["assessments"][0]["status"] == status and state["stop_reason"] == stop
            # identical verdict, evidence, guidance and history to the direct M0 engine
            assert state["assessments"] == json_of(ref.assessments)
            assert state["history"] == json_of(ref.history)
            assert state["exhausted_gaps"] == ref.exhausted
            assert [x for x in seen if x] == [r.id for r in ref.requests]
            b = store.load_restore_bundle(iid)
            assert b.state.gap_attempts == ref.gap_attempts and b.state.epoch == ref.epoch == 0
            s = settings(**sc["budget"])
            restored = InspectionAgent.restore(b.state, fm.client(s, Trace.from_events(b.trace_events)), s, b.images)
            assert comparable_trace(restored) == comparable_trace(ref)
            assert state["usage"]["model_calls"] == ref.client.calls_started == len(fm.requests)
            # reports and stored images
            report = (await c.get(f"/api/inspections/{iid}/report")).json()
            assert report["requirements"] == json_of(ref.assessments)
            assert report["next_view_requests"] == json_of(ref.requests)
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert f"[{status.replace('_', ' ')}]" in md
            for p, name in zip(state["photos"], sc["names"]):
                img = (await c.get(p["photo_url"])).content
                assert img == normalize_image_bytes(photo(name), name).jpeg_bytes == ref.images[p["image_id"]].jpeg_bytes
                ov = await c.get(p["overlay_url"])
                assert ov.status_code == 200 and ov.content == store.load_overlay(iid, p["image_id"])
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


@pytest.mark.parametrize("order", [(0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)])
def test_photo_order_independence_over_http(tmp_path, order):
    photos = [("router.jpg", ROUTER_CLOSE), ("switch.jpg", SWITCH_CLOSE), ("wide.jpg", WIDE_TRACE)]
    sc = dict(obs=[photos[i][1] for i in order], plans=[plan(STEP_BACK)] * 2, budget={},
              names=[photos[i][0] for i in order])
    ref = direct_m0(sc)
    fm = fake_for(sc)

    async def go():
        async with server(tmp_path, fm) as (c, _, _a):
            iid = await create(c)
        for name in sc["names"]:
            async with server(tmp_path, fm) as (c, _, _a):
                assert (await cap(c, iid, name)).status_code == 200
        async with server(tmp_path, fm) as (c, store, _a):
            st = (await c.get(f"/api/inspections/{iid}")).json()
            a = st["assessments"][0]
            assert a["status"] == "VERIFIED" and st["assessments"] == json_of(ref.assessments)
            names = {p["seq"]: p["source_name"] for p in st["photos"]}
            # the same photos establish the same facts whatever the order
            assert {names[s["seq"]] for s in a["endpoints"][0]["support"]} == {"router.jpg"}
            assert {names[s["seq"]] for s in a["endpoints"][1]["support"]} == {"switch.jpg"}
            assert {names[x["seq"]] for x in a["identity_evidence"]} == {"wide.jpg"}
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


def test_violation_stop_installation_change_and_superseded_evidence(tmp_path):
    ref_fm = base_fake()
    ref_fm.queue_chat(OBS, VIOL, REAR_BOTH)
    ref = InspectionAgent(SPEC, ref_fm.client(settings()), settings())
    asyncio.run(ref.observe(normalize_image_bytes(photo("wrong.jpg"), "wrong.jpg")))
    ref.mark_installation_changed("moved the blue cable into LAN 1")
    asyncio.run(ref.observe(normalize_image_bytes(photo("fixed.jpg"), "fixed.jpg")))

    fm = base_fake()
    fm.queue_chat(OBS, VIOL, REAR_BOTH)

    async def go():
        async with server(tmp_path, fm) as (c, _, _a):
            iid = await create(c)
            r = await cap(c, iid, "wrong.jpg")
            assert r.json()["assessments"][0]["status"] == "VIOLATED" and r.json()["status"] == "stopped"
            n = len(fm.requests)
            r = await cap(c, iid, "late.jpg")
            assert (r.status_code, r.json()["error"]) == (409, "inspection_stopped") and len(fm.requests) == n
        async with server(tmp_path, fm) as (c, _, _a):
            r = await c.post(f"/api/inspections/{iid}/events",
                             json={"type": "installation_changed", "reason": "moved the blue cable into LAN 1"})
            assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["epoch"] == 1
        async with server(tmp_path, fm) as (c, store, _a):
            r = await cap(c, iid, "fixed.jpg")
            assert r.json()["assessments"][0]["status"] == "VERIFIED"
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert [(p["epoch"], p["superseded"]) for p in st["photos"]] == [(0, True), (1, False)]
            assert st["assessments"] == json_of(ref.assessments) and st["history"] == json_of(ref.history)
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert "SUPERSEDED" in md and "installation changed" in md
            assert [s.kind for s in store.load_steps(iid)] == ["photo", "installation_changed", "photo"]
            assert store.get_submission(iid, next(iter(  # the refused capture is audited, never evidence
                k for (k,) in store._conn.execute("SELECT idempotency_key FROM submissions WHERE status='failed'")
            ))).failures[0]["error"].startswith("inspection_stopped")
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


def test_budget_exhaustion_survives_restarts_without_reset(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, *[FRONT] * 4)
    fm.queue_chat(PLAN, *[plan()] * 4)
    budget = {"max_model_calls": 7, "max_observations": 10, "max_attempts_per_gap": 9}

    async def go():
        async with server(tmp_path, fm, budget) as (c, _, _a):
            iid = await create(c)
        used = []
        for i in range(4):
            async with server(tmp_path, fm, budget) as (c, store, _a):
                r = await cap(c, iid, f"p{i}.jpg")
                if r.status_code == 409:
                    assert r.json()["error"] == "inspection_stopped"
                    break
                used.append(r.json()["usage"]["model_calls"])
        async with server(tmp_path, fm, budget) as (c, store, _a):
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["stop_reason"] == "model_call_budget_exhausted"
            assert used == sorted(used) and st["usage"]["model_calls"] == len(fm.requests) <= 7
            assert st["assessments"][0]["status"] == "INSUFFICIENT_EVIDENCE"
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


# ============================================================================ 2. reliability

class FlakyMeta:
    """Fails the FIRST attempt of every logical call (503, or a read timeout), then answers normally; checks that
    each request arrives only after its reservation was written."""

    def __init__(self, fm: FakeMeta, failure: str = "503") -> None:
        self.fm, self.failure = fm, failure
        self.seen: set[tuple[str, str]] = set()
        self.store: Store | None = None
        self.iid: str | None = None
        self.sent = 0
        self.violations: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent += 1
        calls = self.store.list_model_calls(self.iid)
        if len(calls) != self.sent or calls[-1].status != "reserved":
            self.violations.append(f"request {self.sent} without its own fresh reservation")
        body = json.loads(request.content)
        k = (request.url.path, body.get("response_format", {}).get("json_schema", {}).get("name")
             or body["input"][0]["content"][0]["text"] if "input" in body else body["response_format"]["json_schema"]["name"])
        if k not in self.seen:
            self.seen.add(k)
            if self.failure == "timeout":
                raise httpx.ReadTimeout("simulated slow model", request=request)
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        self.seen.discard(k)  # the next logical call of this kind fails once again
        return self.fm.handler(request)


@pytest.mark.parametrize("failure", ["503", "timeout"])
def test_every_http_attempt_is_reserved_first_including_retries(tmp_path, failure):
    ref = direct_m0(SCENARIOS["verified"])
    flaky = FlakyMeta(fake_for(SCENARIOS["verified"]), failure)

    async def go():
        async with server(tmp_path, httpx.MockTransport(flaky.handler)) as (c, store, _a):
            iid = await create(c)
            flaky.store, flaky.iid = store, iid
            await cap(c, iid, "front.jpg")
            r = await cap(c, iid, "rear.jpg")
            assert r.json()["assessments"][0]["status"] == "VERIFIED"  # retries change cost, not the verdict
            assert r.json()["assessments"] == json_of(ref.assessments)
            calls = store.list_model_calls(iid)
            assert flaky.violations == [] and len(calls) == flaky.sent == 2 * len(flaky.fm.requests)
            # one failed first attempt + one successful "attempt 2" per logical call (SAM concepts run
            # concurrently, so their reservations interleave)
            errors = [c for c in calls if c.status == "error"]
            oks = [c for c in calls if c.status == "ok"]
            assert len(errors) == len(oks) == len(flaky.fm.requests)
            assert all("attempt" not in c.name for c in errors) and all("attempt 2" in c.name for c in oks)
            assert sorted(c.name.replace(" (attempt 2)", "") for c in oks) == sorted(c.name for c in errors)
            check_invariants(store, iid, sent=flaky.sent)

    asyncio.run(go())


@pytest.mark.parametrize("fault", ["sam_500", "muse_400", "muse_garbage"])
def test_meta_errors_never_produce_a_verdict_they_cannot_support(tmp_path, fault):
    fm = base_fake()
    if fault == "sam_500":
        fm.queue_chat(OBS, REAR_BOTH)  # Muse claims everything; SAM cannot corroborate
        fm.queue_chat(PLAN, plan())
        fm.sam["blue ethernet cable"] = httpx.Response(500, json={"error": {"message": "boom"}})
    elif fault == "muse_400":
        fm.queue_chat(OBS, httpx.Response(400, json={"error": {"message": "bad request"}}))
    else:
        fm.queue_chat(OBS, "not json at all", "{\"still\": \"wrong\"}")

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            r = await cap(c, iid, "a.jpg")
            assert r.status_code == 200
            assert r.json()["assessments"][0]["status"] == "INSUFFICIENT_EVIDENCE"
            assert r.json()["notes"]
            calls = store.list_model_calls(iid)
            if fault != "muse_garbage":
                assert "error" in {c.status for c in calls}
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


def test_long_model_call_keeps_the_lease_and_blocks_others_without_stealing(tmp_path):
    gate = Gate(fake_for(SCENARIOS["verified"]))

    async def go():
        async with server(tmp_path, gate.transport(), lease_heartbeat_s=0.05, lease_stale_after_s=0.2) as \
                (c, store, _a):
            iid = await create(c)
            other = await create(c)
            slow = asyncio.create_task(cap(c, iid, "front.jpg"))
            await gate.entered.wait()
            await asyncio.sleep(0.6)  # 3x the staleness threshold
            r = await asyncio.wait_for(cap(c, iid, "x.jpg"), 5)
            assert (r.status_code, r.json()["error"]) == (409, "inspection_busy")
            # other inspections are not blocked by this lease
            parallel = asyncio.create_task(cap(c, other, "front.jpg"))
            await asyncio.sleep(0.1)
            gate.release.set()
            assert (await slow).status_code == 200 and (await parallel).status_code == 200
            check_invariants(store, iid)
            check_invariants(store, other)
            assert store.get_submission(iid, "x") is None

    asyncio.run(go())


def test_server_shutdown_mid_step_then_restart_and_retry(tmp_path):
    gate = Gate(fake_for(SCENARIOS["verified"]))

    async def go():
        async with server(tmp_path, gate.transport()) as (c, store, app):
            iid = await create(c)
            req = asyncio.create_task(cap(c, iid, "front.jpg", key="k1"))
            await gate.entered.wait()
            await app.state.service.shutdown()  # what the lifespan does on SIGTERM
            with contextlib.suppress(BaseException):
                await req
        gate.release.set()
        async with server(tmp_path, gate.transport()) as (c, store, _a):
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["photos"] == [] and not st["busy"] and st["usage"]["calls_by_status"] == {"outcome_unknown": 1}
            r = await cap(c, iid, "front.jpg", key="k1")
            assert r.status_code == 200 and r.json()["seq"] == 1
            assert store.get_submission(iid, "k1").attempts == 2
            check_invariants(store, iid, sent=1 + len(gate.fm.requests))

    asyncio.run(go())


_CHILD = r'''
import asyncio, sys
sys.path[:0] = [sys.argv[3], sys.argv[4]]
import httpx
from fakes import settings
from test_service import photo
from proofcam.service import InspectionService, ServiceConfig
from proofcam.store import Store

async def hang(request):
    await asyncio.sleep(3600)  # a model call that never returns

async def main():
    svc = InspectionService(settings(), Store(sys.argv[1]), httpx.MockTransport(hang),
                            ServiceConfig(model_source="mock", lease_heartbeat_s=0.05, lease_stale_after_s=0.2))
    await svc.submit_capture(sys.argv[2], photo("front.jpg"), idempotency_key="k1")

asyncio.run(main())
'''


def test_real_process_kill_mid_step_is_recovered_and_counted_once(tmp_path):
    fm = fake_for(SCENARIOS["verified"])
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    dbfile = tmp_path / "var" / "proofcam.db"

    async def go():
        async with server(tmp_path, fm, lease_heartbeat_s=0.05, lease_stale_after_s=0.5) as (c, store, _a):
            iid = await create(c)
        child = subprocess.Popen([sys.executable, str(script), str(dbfile), iid, str(BACKEND),
                                  str(BACKEND / "tests")], cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            probe = Store(dbfile)
            deadline = time.time() + 30
            while not probe.list_model_calls(iid):  # child has reserved its first call and sent it
                assert child.poll() is None, child.stderr.read().decode()
                assert time.time() < deadline, "child never started its model call"
                await asyncio.sleep(0.05)
            child.kill()  # hard kill: no cleanup, no lease release, no failure record
            child.wait(10)
            rec = probe.get_inspection(iid)
            assert rec.lease_token is not None and rec.model_calls_reserved == 1
            probe.close()
        finally:
            if child.poll() is None:
                child.kill()
        await asyncio.sleep(0.8)  # heartbeat stopped with the process; lease becomes stale
        async with server(tmp_path, fm, lease_heartbeat_s=0.05, lease_stale_after_s=0.5) as (c, store, _a):
            # startup recovery reclaimed the dead lease; the retry with the same key runs attempt 2
            sub = store.get_submission(iid, "k1")
            assert sub.status == "interrupted" and sub.failures[-1]["status"] == "interrupted"
            r = await cap(c, iid, "front.jpg", key="k1")
            assert r.status_code == 200 and r.json()["seq"] == 1
            calls = store.list_model_calls(iid)
            assert calls[0].status == "outcome_unknown" and {x.status for x in calls[1:]} == {"ok"}
            check_invariants(store, iid, sent=1 + len(fm.requests))

    asyncio.run(go())


def test_commit_failure_rolls_back_and_the_retry_succeeds(tmp_path, monkeypatch):
    fm = fake_for(SCENARIOS["verified"])
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)

            def boom(*a, **k):
                raise OSError("disk I/O error")
            monkeypatch.setattr(Store, "_insert_trace", staticmethod(boom))
            r = await cap(c, iid, "front.jpg", key="k1")
            assert (r.status_code, r.json()["error"]) == (500, "internal_error") and "disk" not in r.text
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["photos"] == [] and st["version"] == 0 and not st["busy"]
            monkeypatch.undo()
            r = await cap(c, iid, "front.jpg", key="k1")
            assert r.status_code == 200 and r.json()["seq"] == 1
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


def test_version_conflict_is_refused_and_nothing_is_saved(tmp_path):
    gate = Gate(fake_for(SCENARIOS["verified"]))
    gate.fm.queue_chat(OBS, FRONT)
    gate.fm.queue_chat(PLAN, plan())

    async def go():
        async with server(tmp_path, gate.transport()) as (c, store, _a):
            iid = await create(c)
            req = asyncio.create_task(cap(c, iid, "front.jpg", key="k1"))
            await gate.entered.wait()
            store._conn.execute("UPDATE inspections SET version = version + 1 WHERE id = ?", (iid,))  # rogue writer
            gate.release.set()
            r = await req
            assert (r.status_code, r.json()["error"]) == (409, "conflict")
            assert store.load_restore_bundle(iid).state.observations == []
            assert store.get_inspection(iid).lease_token is None
            r = await cap(c, iid, "front.jpg", key="k1")
            assert r.status_code == 200
            check_invariants(store, iid, sent=len(gate.fm.requests))

    asyncio.run(go())


def test_corrupt_state_fails_safely_and_is_contained(tmp_path):
    fm = fake_for(SCENARIOS["verified"])

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            healthy = await create(c)
            await cap(c, iid, "front.jpg")
            store._conn.execute("UPDATE observations SET record_json = '{broken' WHERE inspection_id = ?", (iid,))
            n = len(fm.requests)
            for r in (await c.get(f"/api/inspections/{iid}"), await c.get(f"/api/inspections/{iid}/report"),
                      await cap(c, iid, "rear.jpg"),
                      await c.post(f"/api/inspections/{iid}/events",
                                   json={"type": "installation_changed", "reason": "x"})):
                assert (r.status_code, r.json()["error"]) == (500, "storage_corrupt"), r.text
                assert "broken" not in r.text
            assert len(fm.requests) == n and store.get_inspection(iid).lease_token is None
            assert (await c.get(f"/api/inspections/{healthy}")).status_code == 200  # other inspections unaffected

    asyncio.run(go())


def test_idempotency_matrix_across_restart_and_inspections(tmp_path):
    fm = fake_for(SCENARIOS["verified"])
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())

    async def go():
        async with server(tmp_path, fm) as (c, _, _a):
            a = await create(c)
            b = await create(c)
            first = (await cap(c, a, "front.jpg", key="same")).json()
        async with server(tmp_path, fm) as (c, store, _a):
            n = len(fm.requests)
            replay = (await cap(c, a, "front.jpg", key="same")).json()
            assert replay["replayed"] and {**replay, "replayed": False} == first and len(fm.requests) == n
            r = await cap(c, a, "rear.jpg", key="same")
            assert (r.status_code, r.json()["error"]) == (409, "idempotency_conflict")
            dup = (await cap(c, a, "front.jpg", key="other")).json()
            assert dup["duplicate_of"] == 1 and len(fm.requests) == n
            # the same key and the same photo in ANOTHER inspection are independent: new evidence there
            rb = (await cap(c, b, "front.jpg", key="same")).json()
            assert not rb["replayed"] and rb["duplicate_of"] is None and len(fm.requests) > n
            check_invariants(store, a)
            check_invariants(store, b)
            assert store.get_inspection(a).model_calls_reserved + store.get_inspection(b).model_calls_reserved \
                == len(fm.requests)

    asyncio.run(go())


def test_no_cross_inspection_leakage(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan(), plan())

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            a, b = await create(c), await create(c)
            await cap(c, a, "front.jpg")
            await cap(c, b, "front_b.jpg")
            ra = await cap(c, a, "rear.jpg")
            assert ra.json()["assessments"][0]["status"] == "VERIFIED"
            sb = (await c.get(f"/api/inspections/{b}")).json()
            assert sb["assessments"][0]["status"] == "INSUFFICIENT_EVIDENCE" and len(sb["photos"]) == 1
            a_photo = ra.json()["image_id"]
            for kind in ("photos", "overlays"):
                r = await c.get(f"/api/inspections/{b}/{kind}/{a_photo}")
                assert r.status_code == 404
            rep_b = (await c.get(f"/api/inspections/{b}/report")).json()
            assert a_photo not in json.dumps(rep_b) and rep_b["inspection_id"] == b
            assert {o["image_id"] for o in rep_b["observations"]} == {sb["photos"][0]["image_id"]}
            check_invariants(store, a)
            check_invariants(store, b)

    asyncio.run(go())


# ============================================================================ 3. security and deployment

def _git(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, **kw)


def test_no_secrets_databases_or_private_images_are_tracked():
    tracked = _git("ls-files").stdout.splitlines()
    bad = [f for f in tracked if f.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".env"))
           or f.startswith(("var/", "runs/", "backend/runs/")) or f == ".env"
           or (f.startswith("data/images/") and f != "data/images/README.md")]
    assert bad == []
    for path in (".env", "var/proofcam.db", "var/proofcam.db-wal", "var/proofcam.db-shm", "runs/x/report.md",
                 "data/images/m1_front.png", "backend/scratch.sqlite3"):
        assert _git("check-ignore", "-q", path).returncode == 0, f"{path} not ignored"


def test_the_configured_api_key_is_not_in_any_tracked_file():
    env = REPO_ROOT / ".env"
    key = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("MODEL_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if len(key) < 8:
        pytest.skip("no API key configured locally")
    found = _git("grep", "-q", "-F", "-f", "-", input=key + "\n").returncode == 0
    assert not found, "the configured MODEL_API_KEY appears in a tracked file"  # value never printed


def test_hostile_filenames_and_methods(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, FRONT)
    fm.queue_chat(PLAN, plan(), plan())

    async def go():
        async with server(tmp_path, fm) as (c, _, _a):
            iid = await create(c)
            r = await c.post(f"/api/inspections/{iid}/captures",
                             files={"file": ("../../etc/passwd", photo("p.jpg"), "image/jpeg")})
            assert r.status_code == 200
            r = await c.post(f"/api/inspections/{iid}/captures",
                             files={"file": ("C:\\Users\\me\\IMG_1.jpg", photo("q.jpg"), "image/jpeg")})
            names = [p["source_name"] for p in (await c.get(f"/api/inspections/{iid}")).json()["photos"]]
            assert names == ["passwd", "IMG_1.jpg"]
            r = await c.delete(f"/api/inspections/{iid}")
            assert (r.status_code, r.json()["error"]) == (405, "method_not_allowed")
            r = await c.post("/api/inspections", content=b"{not json", headers={"content-type": "application/json"})
            assert (r.status_code, r.json()["error"]) == (422, "invalid_request")

    asyncio.run(go())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_uvicorn_startup_single_worker_with_a_dummy_key(tmp_path):
    """Starts the documented command. A dummy key overrides .env (python-dotenv never overrides the environment),
    and no capture is made, so no model request can be sent."""
    port_no = _free_port()
    env = {**os.environ, "MODEL_API_KEY": "dummy-key-not-real-0000", "PROOFCAM_DB_PATH": str(tmp_path / "s.db")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "proofcam.api:app_from_env", "--factory",
                             "--workers", "1", "--port", str(port_no)], cwd=BACKEND, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{port_no}"
        deadline = time.time() + 30
        while True:
            try:
                h = httpx.get(f"{base}/api/health", timeout=1)
                break
            except httpx.TransportError:
                assert proc.poll() is None and time.time() < deadline, "server did not start"
                time.sleep(0.2)
        assert h.status_code == 200 and h.json()["status"] == "ok" and h.json()["model_source"] == "live"
        r = httpx.post(f"{base}/api/inspections", json={"spec_id": "my_setup"}, timeout=5)
        assert r.status_code == 201 and r.json()["usage"]["model_calls"] == 0
        assert httpx.get(f"{base}/api/inspections/{r.json()['id']}", timeout=5).status_code == 200
    finally:
        proc.terminate()
        out = proc.communicate(timeout=15)[0].decode(errors="replace")
    assert "dummy-key-not-real" not in out and "Bearer" not in out
    assert (tmp_path / "s.db").exists()


# ============================================================================ 4. API / CLI equivalence

def test_cli_and_api_produce_the_same_inspection(tmp_path, monkeypatch):
    sc = SCENARIOS["verified"]
    cli_fm, api_fm = fake_for(sc), fake_for(sc)
    paths = []
    for name in sc["names"]:
        p = tmp_path / "photos" / name
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(photo(name))
        paths.append(str(p))
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings()))
    monkeypatch.setattr(cli, "MetaClient", lambda s, t: cli_fm.client(s, t))
    out = tmp_path / "cli_runs"
    asyncio.run(cli.run(argparse.Namespace(spec=str(REPO_ROOT / "data" / "specs" / "router_switch.json"),
                                           image=paths, interactive=False, out=str(out),
                                           no_grounding_requirement=False)))
    (run_dir,) = list(out.iterdir())
    cli_report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    cli_trace = [json.loads(x) for x in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()]

    async def go():
        async with server(tmp_path / "api", api_fm) as (c, store, _a):
            iid = await create(c)
            for name in sc["names"]:
                await cap(c, iid, name)
            report = (await c.get(f"/api/inspections/{iid}/report")).json()
            trace = [e.model_dump(mode="json") for e in store.load_restore_bundle(iid).trace_events]
            return report, trace

    api_report, api_trace = asyncio.run(go())
    same = ("spec", "require_grounding", "stop_reason", "epoch", "photo_order", "history", "requirements",
            "observations", "next_view_requests", "exhausted_gaps", "disclaimer")
    for k in same:
        assert api_report[k] == cli_report[k], k
    assert api_report["usage"]["model_calls"] == cli_report["usage"]["model_calls"]
    strip = lambda evs: [{k: v for k, v in e.items() if k not in ("ts", "latency_ms")} for e in evs]  # noqa: E731
    assert strip(api_trace) == strip(cli_trace)
    assert len(api_fm.requests) == len(cli_fm.requests)
