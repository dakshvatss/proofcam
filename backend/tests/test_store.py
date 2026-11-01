"""M1 Stage 2: SQLite store. Temporary databases; mocked Meta responses only (FakeMeta, source='mock').

`capture()` below is a test-only stand-in for the Stage 3 service flow, so the store is exercised with real
M1.1 AgentState snapshots: begin_capture (lease) -> load_restore_bundle -> restore -> observe -> commit_step.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import subprocess
import threading
from pathlib import Path

import httpx
import pytest

from fakes import FakeMeta, make_image, plan, settings
from proofcam import config, store as store_mod
from proofcam.agent import InspectionAgent
from proofcam.config import REPO_ROOT
from proofcam.images import NormalizedImage
from proofcam.meta_client import MetaClient
from proofcam.overlay import render_overlay_jpeg
from proofcam.report import write_report
from proofcam.store import (AppendOnlyViolation, CaptureCompleted, CaptureStarted, IdempotencyConflict,
                            InspectionBusy, InspectionExists, InspectionNotFound, LeaseLost,
                            ModelCallBudgetExhausted, SchemaVersionError, Store, StoreCorruptionError, StoreError,
                            UnsafeContent, VersionConflict)
from proofcam.trace import Trace, TraceEvent
from test_agent import FRONT, OBS, PLAN, REAR_BOTH, SPEC, base_fake
from test_persistence import comparable_trace

IID = "insp_test"


class Clock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def image_for(name: str) -> NormalizedImage:
    return make_image(name, color=tuple(hashlib.sha256(name.encode()).digest()[:3]))


def open_store(tmp_path: Path, clock: Clock | None = None) -> Store:
    return Store(tmp_path / "var" / "proofcam.db", clock=clock or Clock())


def new_inspection(st: Store, fm: FakeMeta, iid: str = IID, **budget) -> InspectionAgent:
    s = settings(**budget)
    ag = InspectionAgent(SPEC, fm.client(s), s)
    st.create_inspection(iid, ag.snapshot(), spec_id="router_switch")
    return ag


def overlays_for(ag: InspectionAgent, first_new: int) -> dict[str, bytes]:
    return {o.image_id: render_overlay_jpeg(ag.images[o.image_id], o, ag.grounding_runs.get(o.seq))
            for o in ag.observations[first_new:] if o.extraction is not None and o.image_id in ag.images}


class ReservingClient(MetaClient):
    """Test stand-in for the Stage 3 hook: every call is durably reserved in the store before it is sent."""

    def __init__(self, s, trace, fm: FakeMeta, st: Store, iid: str, token: str, key: str | None) -> None:
        super().__init__(s, trace, transport=httpx.MockTransport(fm.handler), source="mock")
        self.st, self.iid, self.token, self.key = st, iid, token, key

    def _reserve_call(self, name: str) -> None:
        super()._reserve_call(name)
        self.st.reserve_model_call(self.iid, self.token, name, idempotency_key=self.key)


def capture(st: Store, fm: FakeMeta, name: str, key: str | None = None, iid: str = IID, hooked: bool = False,
            settle: bool = True):
    """Returns (agent, new_version) or (None, CaptureCompleted)."""
    img = image_for(name)
    key = key or f"key-{name}"
    started = st.begin_capture(iid, key, img.image_id)
    if isinstance(started, CaptureCompleted):
        return None, started
    b = st.load_restore_bundle(iid)  # loaded UNDER the lease, so it is the latest committed state
    s = settings(**b.state.budget)
    trace = Trace.from_events(b.trace_events)
    client = (ReservingClient(s, trace, fm, st, iid, started.lease_token, key) if hooked else fm.client(s, trace))
    ag = InspectionAgent.restore(b.state, client, s, b.images)
    n_obs, n_trace = len(ag.observations), len(ag.trace.events)
    step = asyncio.run(ag.observe(img))
    if hooked and settle:  # one model_call trace event per reservation, in order
        reserved = [c for c in st.list_model_calls(iid) if c.status == "reserved"]
        done = [e for e in ag.trace.events[n_trace:] if e.kind == "model_call"]
        for c, e in zip(reserved, done):
            st.settle_model_call(iid, started.lease_token, c.ordinal, e.status, {"name": e.name})
    v = st.commit_step(iid, started.lease_token, b.version, ag.snapshot(), ag.trace.events, ag.images,
                       overlays_for(ag, n_obs), idempotency_key=key,
                       response={"seq": step.seq, "image_id": step.image_id,
                                 "statuses": [a.status for a in step.assessments],
                                 "next_view": step.next_view.id if step.next_view else None})
    return ag, v


def restored(st: Store, fm: FakeMeta, iid: str = IID) -> InspectionAgent:
    b = st.load_restore_bundle(iid)
    s = settings(**b.state.budget)
    return InspectionAgent.restore(b.state, fm.client(s, Trace.from_events(b.trace_events)), s, b.images)


def two_photo_fake() -> FakeMeta:
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    return fm


def count(st: Store, table: str) -> int:
    return st._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


TABLES = ("photos", "observations", "next_view_requests", "steps", "trace_events", "submissions", "model_calls")


def counts(st: Store) -> dict[str, int]:
    return {t: count(st, t) for t in TABLES}


# ============================================================================ schema, config, corruption

def test_schema_initialized_with_wal_and_foreign_keys(tmp_path):
    with open_store(tmp_path) as st:
        assert st.schema_version == store_mod.SCHEMA_VERSION == 1
        assert st._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert st._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        names = {r[0] for r in st._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"inspections", *TABLES} <= names
        assert st.check_integrity() == []
    with open_store(tmp_path) as st:  # reopening is a no-op migration
        assert st.schema_version == 1


def test_newer_schema_is_refused(tmp_path):
    open_store(tmp_path).close()
    raw = sqlite3.connect(tmp_path / "var" / "proofcam.db")
    raw.execute("PRAGMA user_version = 99")
    raw.close()
    with pytest.raises(SchemaVersionError, match="newer"):
        open_store(tmp_path)


def test_failed_migration_rolls_back_completely(tmp_path, monkeypatch):
    open_store(tmp_path).close()
    monkeypatch.setattr(store_mod, "MIGRATIONS", store_mod.MIGRATIONS + [
        (2, ["CREATE TABLE added_in_v2 (x INTEGER)", "THIS IS NOT SQL"])])
    with pytest.raises(SchemaVersionError, match="rolled back"):
        open_store(tmp_path)
    monkeypatch.undo()
    with open_store(tmp_path) as st:
        assert st.schema_version == 1
        assert st._conn.execute("SELECT name FROM sqlite_master WHERE name = 'added_in_v2'").fetchone() is None


def test_successful_migration_applies_in_one_step(tmp_path, monkeypatch):
    open_store(tmp_path).close()
    monkeypatch.setattr(store_mod, "MIGRATIONS", store_mod.MIGRATIONS + [
        (2, ["CREATE TABLE added_in_v2 (x INTEGER)"])])
    with open_store(tmp_path) as st:
        assert st.schema_version == 2
        assert st._conn.execute("SELECT name FROM sqlite_master WHERE name = 'added_in_v2'").fetchone()


def test_non_database_file_gives_controlled_error(tmp_path):
    p = tmp_path / "var" / "proofcam.db"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"this is not a database file" * 100)
    with pytest.raises(StoreCorruptionError):
        Store(p)


def test_database_path_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("PROOFCAM_DB_PATH", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    assert config.database_path() == REPO_ROOT / "var" / "proofcam.db"
    monkeypatch.setenv("PROOFCAM_DB_PATH", "data/other.db")
    assert config.database_path() == REPO_ROOT / "data" / "other.db"
    monkeypatch.setenv("PROOFCAM_DB_PATH", str(tmp_path / "x.db"))
    assert config.database_path() == tmp_path / "x.db"


@pytest.mark.parametrize("path", ["var/proofcam.db", "var/proofcam.db-wal", "var/proofcam.db-shm",
                                  "backend/x.db", "x.db-wal"])
def test_database_files_are_git_ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT)
    assert r.returncode == 0, f"{path} is not git-ignored"


# ============================================================================ create / load

def test_create_and_load_inspection(tmp_path):
    with open_store(tmp_path) as st:
        ag = new_inspection(st, base_fake())
        rec = st.get_inspection(IID)
        assert (rec.status, rec.version, rec.epoch, rec.stop_reason, rec.lease_token) == ("open", 0, 0, None, None)
        assert rec.title == SPEC.title and rec.spec_id == "router_switch"
        assert rec.model_call_limit == ag.client.call_limit and rec.model_calls_reserved == 0
        assert rec.engine_version.startswith("0.0.1+")
        b = st.load_restore_bundle(IID)
        assert b.state == ag.snapshot() and b.trace_events == [] and b.images == []


def test_create_rejects_duplicate_id_and_non_fresh_state(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        with pytest.raises(InspectionExists):
            new_inspection(st, fm)
        ag, _ = capture(st, fm, "front.jpg")
        with pytest.raises(StoreError, match="fresh agent"):
            st.create_inspection("insp_other", ag.snapshot())


def test_unknown_inspection(tmp_path):
    with open_store(tmp_path) as st:
        with pytest.raises(InspectionNotFound):
            st.get_inspection("nope")
        with pytest.raises(InspectionNotFound):
            st.load_restore_bundle("nope")
        with pytest.raises(InspectionNotFound):
            st.acquire_lease("nope")


# ============================================================================ restart persistence

def test_full_inspection_survives_reopen_and_matches_uninterrupted_run(tmp_path):
    # Reference: the same two photos through one in-memory agent (M0 path).
    ref_fm = two_photo_fake()
    ref = InspectionAgent(SPEC, ref_fm.client(settings()), settings())
    ref_imgs = [image_for("front.jpg"), image_for("rear.jpg")]
    for img in ref_imgs:
        asyncio.run(ref.observe(img))

    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg")
    with open_store(tmp_path) as st:  # "server restart" between photos
        ag, v = capture(st, fm, "rear.jpg")
        stored_overlays = overlays_for(ag, 1)
    with open_store(tmp_path) as st:
        rec = st.get_inspection(IID)
        assert (rec.status, rec.stop_reason, rec.version) == ("stopped", "all_requirements_resolved", v)
        back = restored(st, fm)
        assert back.snapshot().model_dump() == ref.snapshot().model_dump()
        assert comparable_trace(back) == comparable_trace(ref)
        assert [e.seq for e in back.trace.events] == list(range(len(back.trace.events)))
        assert back.client.calls_started == ref.client.calls_started == rec.model_calls_reserved
        assert back.done and back.assessments[0].status == "VERIFIED"
        assert [r.id for r in back.requests] == ["nv1"]
        assert [h["seq"] for h in back.history] == [1, 2]
        # photos: same ids, byte-identical JPEGs, never re-encoded
        for img in ref_imgs:
            p = st.load_photo(IID, img.image_id)
            assert p.image_id == img.image_id and p.jpeg_bytes == img.jpeg_bytes and p == img
        assert {i.image_id for i in back.images.values()} == {i.image_id for i in ref_imgs}
        # overlays: byte-identical to what was rendered (with SAM masks) at step time
        rear_id = ref_imgs[1].image_id
        assert st.load_overlay(IID, rear_id) == stored_overlays[rear_id]
        assert set(st.load_overlays(IID)) == {i.image_id for i in ref_imgs}
        # stored assessments and per-step snapshots
        assert st.load_assessments(IID) == back.assessments
        steps = st.load_steps(IID)
        assert [(s.step_no, s.kind) for s in steps] == [(1, "photo"), (2, "photo")]
        assert [s.assessments[0].status for s in steps] == ["INSUFFICIENT_EVIDENCE", "VERIFIED"]
        # the report built from a restored agent uses the stored overlays
        r = write_report(back, tmp_path / "report", stored_overlays=st.load_overlays(IID))
        assert (tmp_path / "report" / r["overlays"][rear_id]).read_bytes() == stored_overlays[rear_id]
        assert st.check_integrity() == []


def test_gap_attempts_exhausted_gaps_and_bounded_stop_survive_reopen(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, *[FRONT] * 6)
    fm.queue_chat(PLAN, *[plan()] * 6)
    ref_fm = base_fake()
    ref_fm.queue_chat(OBS, *[FRONT] * 6)
    ref_fm.queue_chat(PLAN, *[plan()] * 6)
    budget = {"max_observations": 10, "max_attempts_per_gap": 2}
    ref = InspectionAgent(SPEC, ref_fm.client(settings(**budget)), settings(**budget))
    n = 0
    while not ref.done:
        asyncio.run(ref.observe(image_for(f"f{n}.jpg")))
        n += 1

    with open_store(tmp_path) as st:
        new_inspection(st, fm, **budget)
    for i in range(n):
        with open_store(tmp_path) as st:
            capture(st, fm, f"f{i}.jpg")
    with open_store(tmp_path) as st:
        back = restored(st, fm)
        assert back.stop_reason == ref.stop_reason == "no_visually_resolvable_gaps"
        assert back.gap_attempts == ref.gap_attempts and back.gap_attempts
        assert back.exhausted == ref.exhausted and back.exhausted
        assert back.snapshot().model_dump() == ref.snapshot().model_dump()


def test_installation_change_epoch_survives_reopen(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg")
        token = st.acquire_lease(IID)
        b = st.load_restore_bundle(IID)
        ag = restored(st, fm)
        ag.mark_installation_changed("cable moved")
        st.commit_step(IID, token, b.version, ag.snapshot(), ag.trace.events, ag.images)
    with open_store(tmp_path) as st:
        rec = st.get_inspection(IID)
        assert rec.epoch == 1 and rec.lease_token is None
        assert [s.kind for s in st.load_steps(IID)] == ["photo", "installation_changed"]
        ag, _ = capture(st, fm, "rear.jpg")
        assert [o.epoch for o in ag.observations] == [0, 1]
        assert ag.assessments[0].status == "VERIFIED"


def test_model_call_counter_and_budget_stop_survive_reopen(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, FRONT, FRONT)
    fm.queue_chat(PLAN, plan(), plan())
    budget = {"max_model_calls": 8, "max_observations": 10, "max_attempts_per_gap": 5}
    with open_store(tmp_path) as st:
        new_inspection(st, fm, **budget)
    calls = []
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        with open_store(tmp_path) as st:
            if st.get_inspection(IID).status == "stopped":
                break
            ag, _ = capture(st, fm, name)
            calls.append(ag.client.calls_started)
    # Reference: the same photos through one uninterrupted agent.
    ref_fm = base_fake()
    ref_fm.queue_chat(OBS, FRONT, FRONT, FRONT)
    ref_fm.queue_chat(PLAN, plan(), plan())
    ref = InspectionAgent(SPEC, ref_fm.client(settings(**budget)), settings(**budget))
    ref_calls = []
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        asyncio.run(ref.observe(image_for(name)))
        ref_calls.append(ref.client.calls_started)
    with open_store(tmp_path) as st:
        rec = st.get_inspection(IID)
        assert rec.stop_reason == ref.stop_reason == "model_call_budget_exhausted"
        assert calls == ref_calls  # e.g. [5, 8, 8]: never reset; photo 3 is refused before any call
        assert rec.model_calls_reserved == calls[-1] <= 8
        assert restored(st, fm).client.calls_started == rec.model_calls_reserved


def test_trace_sequence_continues_after_reopen(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg")
        n1 = len(st.load_restore_bundle(IID).trace_events)
    with open_store(tmp_path) as st:
        ag, _ = capture(st, fm, "rear.jpg")
        events = st.load_restore_bundle(IID).trace_events
        assert [e.seq for e in events] == list(range(len(events))) and len(events) > n1
        assert events[n1].seq == n1 and events == ag.trace.events
        assert {e.source for e in events if e.kind == "model_call"} == {"mock"}


# ============================================================================ atomicity, versions, append-only

def test_stale_version_is_rejected_and_nothing_changes(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        img = image_for("front.jpg")
        started = st.begin_capture(IID, "k1", img.image_id)
        b = st.load_restore_bundle(IID)
        ag = restored(st, fm)
        asyncio.run(ag.observe(img))
        before = counts(st)
        with pytest.raises(VersionConflict):
            st.commit_step(IID, started.lease_token, b.version + 1, ag.snapshot(), ag.trace.events, ag.images,
                           idempotency_key="k1", response={})
        assert counts(st) == before and st.get_inspection(IID).version == 0
        assert st.get_submission(IID, "k1").status == "processing"


def test_commit_that_would_drop_stored_evidence_is_rejected(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        stale = restored(st, fm)  # loaded before photo 1 was committed
        capture(st, fm, "front.jpg")
        token = st.acquire_lease(IID)
        v = st.get_inspection(IID).version
        with pytest.raises(AppendOnlyViolation):
            st.commit_step(IID, token, v, stale.snapshot(), stale.trace.events, stale.images)
        # and a rewritten (not appended) observation is also refused
        ag = restored(st, fm)
        state = ag.snapshot()
        state.observations[0] = state.observations[0].model_copy(update={"source_name": "rewritten.jpg"})
        with pytest.raises(AppendOnlyViolation, match="observations"):
            st.commit_step(IID, token, v, state, ag.trace.events, ag.images)


def test_failure_mid_commit_rolls_back_everything(tmp_path, monkeypatch):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        img = image_for("front.jpg")
        started = st.begin_capture(IID, "k1", img.image_id)
        b = st.load_restore_bundle(IID)
        ag = restored(st, fm)
        asyncio.run(ag.observe(img))
        before, rec_before = counts(st), st.get_inspection(IID)

        def boom(*a, **k):  # fails after photos/observations/requests/steps were inserted
            raise RuntimeError("disk on fire")
        monkeypatch.setattr(Store, "_insert_trace", staticmethod(boom))
        with pytest.raises(RuntimeError, match="disk on fire"):
            st.commit_step(IID, started.lease_token, b.version, ag.snapshot(), ag.trace.events, ag.images,
                           overlays_for(ag, 0), idempotency_key="k1", response={"ok": True})
        assert counts(st) == before
        assert st.get_inspection(IID) == rec_before  # version, counter, status, lease all unchanged
        assert st.get_submission(IID, "k1").status == "processing"
        monkeypatch.undo()
        # the same step then commits cleanly under the still-held lease
        v = st.commit_step(IID, started.lease_token, b.version, ag.snapshot(), ag.trace.events, ag.images,
                           overlays_for(ag, 0), idempotency_key="k1", response={"ok": True})
        assert v == 1 and count(st, "observations") == 1 and count(st, "trace_events") == len(ag.trace.events)


def test_constraint_violation_rolls_back(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        img = image_for("front.jpg")
        started = st.begin_capture(IID, "k1", img.image_id)
        ag = restored(st, fm)
        asyncio.run(ag.observe(img))
        before = counts(st)
        with pytest.raises(StoreError, match="no photo"):
            st.commit_step(IID, started.lease_token, 0, ag.snapshot(), ag.trace.events, {})  # photo missing
        with pytest.raises(StoreError, match="unknown photo"):
            st.commit_step(IID, started.lease_token, 0, ag.snapshot(), ag.trace.events, ag.images,
                           {"img_000000000000": b"x"})
        assert counts(st) == before and st.get_inspection(IID).version == 0


def test_foreign_keys_are_enforced(tmp_path):
    with open_store(tmp_path) as st:
        with pytest.raises(sqlite3.IntegrityError):
            st._conn.execute("INSERT INTO trace_events VALUES ('ghost', 0, 'policy', 'x', 'local', '{}')")
        new_inspection(st, base_fake())
        with pytest.raises(sqlite3.IntegrityError):  # observation without its photo
            st._conn.execute("INSERT INTO observations VALUES (?, 1, 'img_aaaaaaaaaaaa', 0, NULL, '{}', 0)", (IID,))
        assert st.check_integrity() == []


# ============================================================================ leases and concurrency

def test_lease_is_exclusive_and_owned(tmp_path):
    with open_store(tmp_path) as st:
        new_inspection(st, base_fake())
        token = st.acquire_lease(IID)
        with pytest.raises(InspectionBusy) as e:
            st.acquire_lease(IID)
        assert e.value.since == st.get_inspection(IID).lease_acquired_at
        with pytest.raises(LeaseLost):
            st.release_lease(IID, "not-the-token")
        with pytest.raises(LeaseLost):
            st.renew_lease(IID, "not-the-token")
        st.release_lease(IID, token)
        with pytest.raises(LeaseLost):
            st.release_lease(IID, token)  # already released
        st.release_lease(IID, st.acquire_lease(IID))


def test_concurrent_lease_acquisition_has_exactly_one_winner(tmp_path):
    with open_store(tmp_path) as st:
        new_inspection(st, base_fake())
    n = 8
    barrier = threading.Barrier(n)
    results: list[str] = []

    def worker(i: int) -> None:
        s = open_store(tmp_path)  # separate connection per worker, like separate processes
        try:
            barrier.wait()
            try:
                started = s.begin_capture(IID, f"key-{i}", image_for(f"p{i}.jpg").image_id)
                results.append("started" if isinstance(started, CaptureStarted) else "other")
            except InspectionBusy:
                results.append("busy")
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["busy"] * (n - 1) + ["started"]
    with open_store(tmp_path) as st:
        assert count(st, "submissions") == 1  # losers left no submission behind


def test_stale_lease_recovery_is_idempotent_and_blocks_the_old_holder(tmp_path):
    clock = Clock(1_000.0)
    with open_store(tmp_path, clock) as st:
        new_inspection(st, base_fake())
        started = st.begin_capture(IID, "k1", image_for("a.jpg").image_id)
        clock.t = 1_010.0
        st.renew_lease(IID, started.lease_token)
        # not stale yet: heartbeat (1010) is not older than the threshold
        assert st.recover_interrupted(stale_before=1_005.0) == []
        assert st.get_inspection(IID).lease_token == started.lease_token
        clock.t = 2_000.0
        reports = st.recover_interrupted(stale_before=1_500.0)
        assert [(r.inspection_id, r.interrupted_submissions) for r in reports] == [(IID, ["k1"])]
        assert st.recover_interrupted(stale_before=1_500.0) == []  # idempotent
        assert st.get_inspection(IID).lease_token is None
        sub = st.get_submission(IID, "k1")
        assert sub.status == "interrupted" and sub.failures[-1]["status"] == "interrupted"
        with pytest.raises(LeaseLost):  # the old holder can no longer write
            st.commit_step(IID, started.lease_token, 0, restored(st, base_fake()).snapshot(), [], {})
        again = st.begin_capture(IID, "k1", image_for("a.jpg").image_id)
        assert isinstance(again, CaptureStarted) and again.attempt == 2


# ============================================================================ idempotency

def test_completed_key_returns_stored_response_without_a_new_step(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg", key="k1")
        before, n_requests = counts(st), len(fm.requests)
    with open_store(tmp_path) as st:  # status survives reopening
        _, done = capture(st, fm, "front.jpg", key="k1")
        assert isinstance(done, CaptureCompleted) and done.response["seq"] == 1
        assert counts(st) == before and len(fm.requests) == n_requests
        assert st.get_inspection(IID).lease_token is None
        assert st.get_submission(IID, "k1").status == "done"


def test_same_key_with_different_image_is_rejected(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        started = st.begin_capture(IID, "k1", image_for("front.jpg").image_id)
        with pytest.raises(IdempotencyConflict):  # while processing
            st.begin_capture(IID, "k1", image_for("other.jpg").image_id)
        with pytest.raises(InspectionBusy):  # same key, same image, still processing
            st.begin_capture(IID, "k1", image_for("front.jpg").image_id)
        st.fail_submission(IID, started.lease_token, "k1", "test failure")
        with pytest.raises(IdempotencyConflict):  # after failure
            st.begin_capture(IID, "k1", image_for("other.jpg").image_id)
        capture(st, fm, "front.jpg", key="k1")
        with pytest.raises(IdempotencyConflict):  # after completion
            st.begin_capture(IID, "k1", image_for("other.jpg").image_id)
        assert st.get_inspection(IID).lease_token is None


def test_failed_submission_can_be_retried_and_keeps_its_audit(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        started = st.begin_capture(IID, "k1", image_for("front.jpg").image_id)
        st.fail_submission(IID, started.lease_token, "k1", "observe raised", {"trace": [{"name": "x"}]})
        sub = st.get_submission(IID, "k1")
        assert (sub.status, sub.attempts, sub.lease_token) == ("failed", 1, started.lease_token)
        assert st.get_inspection(IID).lease_token is None and count(st, "observations") == 0
        ag, _ = capture(st, fm, "front.jpg", key="k1")
        sub = st.get_submission(IID, "k1")
        assert (sub.status, sub.attempts) == ("done", 2)
        assert sub.failures[0]["error"] == "observe raised" and sub.failures[0]["attempt"] == 1


def test_duplicate_photo_under_a_new_key_is_a_duplicate_step_without_model_calls(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg", key="k1")
        n_requests, calls = len(fm.requests), st.get_inspection(IID).model_calls_reserved
        ag, _ = capture(st, fm, "front.jpg", key="k2")
        assert len(fm.requests) == n_requests and st.get_inspection(IID).model_calls_reserved == calls
        assert count(st, "observations") == 1 and count(st, "photos") == 1
        assert [s.kind for s in st.load_steps(IID)] == ["photo", "duplicate"]
        assert st.get_submission(IID, "k2").response["seq"] == 1


# ============================================================================ model-call accounting and recovery

def test_reservations_are_counted_once_and_settled(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        ag, _ = capture(st, fm, "front.jpg", hooked=True)
        calls = st.list_model_calls(IID)
        rec = st.get_inspection(IID)
        assert [c.ordinal for c in calls] == list(range(1, len(calls) + 1))
        assert rec.model_calls_reserved == len(calls) == ag.client.calls_started == len(ag.trace.model_calls())
        assert {c.status for c in calls} == {"ok"} and {c.idempotency_key for c in calls} == {"key-front.jpg"}


def test_crash_mid_step_keeps_reserved_calls_counted_exactly_once(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, RuntimeError("process killed during the Muse call"), FRONT)
    fm.queue_chat(PLAN, plan())
    clock = Clock(1_000.0)
    st = open_store(tmp_path, clock)
    new_inspection(st, fm)
    with pytest.raises(RuntimeError, match="process killed"):
        capture(st, fm, "front.jpg", key="k1", hooked=True)  # dies after reserving the Muse call
    # The "dead process" never committed nor released anything. A new process opens the database:
    clock.t = 5_000.0
    st2 = open_store(tmp_path, clock)
    assert st2.get_inspection(IID).model_calls_reserved == 1
    assert st2.load_restore_bundle(IID).state.model_calls_started == 1  # authoritative, not the snapshot's 0
    reports = st2.recover_interrupted(stale_before=clock.t)
    assert reports[0].interrupted_submissions == ["k1"] and reports[0].unknown_outcome_calls == [1]
    assert st2.recover_interrupted(stale_before=clock.t) == []  # repeated recovery changes nothing
    assert st2.get_inspection(IID).model_calls_reserved == 1  # no worst-case charge, no second charge
    assert [(c.ordinal, c.status) for c in st2.list_model_calls(IID)] == [(1, "outcome_unknown")]

    ag, _ = capture(st2, fm, "front.jpg", key="k1", hooked=True)  # retry of the same submission
    calls = st2.list_model_calls(IID)
    rec = st2.get_inspection(IID)
    assert rec.model_calls_reserved == len(calls) == ag.client.calls_started
    assert calls[0].status == "outcome_unknown" and {c.status for c in calls[1:]} == {"ok"}
    assert {c.attempt for c in calls[1:]} == {2}
    # trace holds only committed attempts: no model_call event is invented for the unknown-outcome call
    assert len(ag.trace.model_calls()) == len(calls) - 1
    assert st2.recover_interrupted(stale_before=10_000.0) == []
    assert st2.get_inspection(IID).model_calls_reserved == rec.model_calls_reserved
    st.close()
    st2.close()


def test_store_refuses_reservations_beyond_the_budget_even_after_restart(tmp_path):
    with open_store(tmp_path) as st:
        new_inspection(st, base_fake(), max_model_calls=2)
        token = st.acquire_lease(IID)
        assert [st.reserve_model_call(IID, token, "muse"), st.reserve_model_call(IID, token, "sam")] == [1, 2]
    with open_store(tmp_path) as st:
        st.recover_interrupted(stale_before=1e12)
        token = st.acquire_lease(IID)
        with pytest.raises(ModelCallBudgetExhausted):
            st.reserve_model_call(IID, token, "muse")
        assert st.get_inspection(IID).model_calls_reserved == 2


def test_failed_attempt_keeps_its_calls_counted_and_unknown(tmp_path):
    with open_store(tmp_path) as st:
        new_inspection(st, base_fake())
        started = st.begin_capture(IID, "k1", image_for("a.jpg").image_id)
        st.reserve_model_call(IID, started.lease_token, "muse", idempotency_key="k1")
        o2 = st.reserve_model_call(IID, started.lease_token, "sam", idempotency_key="k1")
        st.settle_model_call(IID, started.lease_token, o2, "error", {"http_status": 500})
        st.fail_submission(IID, started.lease_token, "k1", "observe raised")
        assert [(c.ordinal, c.status) for c in st.list_model_calls(IID)] == [(1, "outcome_unknown"), (2, "error")]
        assert st.get_inspection(IID).model_calls_reserved == 2
        assert st.get_submission(IID, "k1").failures[0]["unknown_outcome_calls"] == [1]
        with pytest.raises(LeaseLost):  # a released lease can no longer reserve
            st.reserve_model_call(IID, started.lease_token, "muse")


def test_commit_never_lowers_or_double_adds_the_counter(tmp_path):
    # Without the hook (plain client), the agent's own count is recorded; with reservations, max() not sum.
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        ag, _ = capture(st, fm, "front.jpg")  # unhooked
        assert st.get_inspection(IID).model_calls_reserved == ag.client.calls_started > 0
        ag2, _ = capture(st, fm, "rear.jpg", hooked=True)
        assert st.get_inspection(IID).model_calls_reserved == ag2.client.calls_started


# ============================================================================ corruption and safety

def test_tampered_records_give_controlled_errors(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg")
        image_id = st.load_restore_bundle(IID).images[0].image_id
        st._conn.execute("UPDATE photos SET jpeg = ? WHERE inspection_id = ?", (b"\xff\xd8 not the photo", IID))
        with pytest.raises(StoreCorruptionError):
            st.load_restore_bundle(IID)
        with pytest.raises(StoreCorruptionError):
            st.load_photo(IID, image_id)
    with open_store(tmp_path) as st:
        st._conn.execute("UPDATE observations SET record_json = '{\"seq\": \"broken\"' WHERE inspection_id = ?",
                         (IID,))
        with pytest.raises(StoreCorruptionError):
            st.load_restore_bundle(IID)
    with open_store(tmp_path) as st:
        st._conn.execute("UPDATE inspections SET control_json = '{}' WHERE id = ?", (IID,))
        with pytest.raises(StoreCorruptionError):
            st.load_assessments(IID)


def test_trace_gap_in_storage_is_detected(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg")
        st._conn.execute("DELETE FROM trace_events WHERE inspection_id = ? AND seq = 1", (IID,))
        with pytest.raises(StoreCorruptionError, match="trace"):
            st.load_restore_bundle(IID)


def test_no_secrets_or_image_data_in_the_database(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        capture(st, fm, "front.jpg", hooked=True)
        capture(st, fm, "rear.jpg", hooked=True)
        assert len([r for r in fm.requests if r.headers.get("authorization") == "Bearer test-key"]) > 0
        st._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    blob = b"".join(p.read_bytes() for p in (tmp_path / "var").iterdir())
    assert b"test-key" not in blob and b"Bearer" not in blob and b"data:image/" not in blob


def test_unsafe_trace_content_is_refused(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        img = image_for("front.jpg")
        started = st.begin_capture(IID, "k1", img.image_id)
        ag = restored(st, fm)
        asyncio.run(ag.observe(img))
        ag.trace.events[-1].detail["leak"] = img.data_url()
        before = counts(st)
        with pytest.raises(UnsafeContent):
            st.commit_step(IID, started.lease_token, 0, ag.snapshot(), ag.trace.events, ag.images,
                           idempotency_key="k1", response={})
        assert counts(st) == before
        with pytest.raises(UnsafeContent):
            st.fail_submission(IID, started.lease_token, "k1", "x", {"auth": "Bearer abc"})


def test_hostile_identifiers_are_treated_as_data(tmp_path):
    iid = "x'); DROP TABLE inspections; --"
    with open_store(tmp_path) as st:
        new_inspection(st, base_fake(), iid=iid)
        token = st.acquire_lease(iid)
        st.release_lease(iid, token)
        assert st.get_inspection(iid).id == iid and count(st, "submissions") == 0
        assert st.get_submission(iid, "k'; --") is None


def test_save_overlay_requires_the_lease(tmp_path):
    fm = two_photo_fake()
    with open_store(tmp_path) as st:
        new_inspection(st, fm)
        ag, _ = capture(st, fm, "front.jpg")
        image_id = ag.observations[0].image_id
        with pytest.raises(LeaseLost):
            st.save_overlay(IID, "nope", image_id, b"jpeg")
        token = st.acquire_lease(IID)
        st.save_overlay(IID, token, image_id, b"new overlay")
        assert st.load_overlay(IID, image_id) == b"new overlay"
        with pytest.raises(StoreError):
            st.save_overlay(IID, token, "img_000000000000", b"x")


def test_release_lease_refuses_while_a_capture_is_processing(tmp_path):
    with open_store(tmp_path) as st:
        new_inspection(st, base_fake())
        started = st.begin_capture(IID, "k1", image_for("a.jpg").image_id)
        with pytest.raises(StoreError, match="in progress"):
            st.release_lease(IID, started.lease_token)
        assert st.get_submission(IID, "k1").status == "processing"


def test_trace_event_model_roundtrips_through_storage(tmp_path):
    ev = TraceEvent(seq=0, ts=1.5, kind="model_call", name="muse", source="mock", usage={"prompt_tokens": 3},
                    request={"messages": [{"role": "user", "content": "<img_x 100 chars>"}]}, detail={"a": [1]})
    assert TraceEvent.model_validate_json(ev.model_dump_json()) == ev
    assert json.loads(ev.model_dump_json())["source"] == "mock"
