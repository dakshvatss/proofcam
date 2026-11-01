"""M1 Stage 1: agent snapshot/restore, trace and image restoration, report refactor.

All model responses are mocked (FakeMeta) or replayed from recorded observations; no real inference.
A "restart" here means: serialize the state to JSON exactly as storage would, drop the agent and its
client, and rebuild both from the JSON alone.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from fakes import FakeMeta, make_image, plan, settings
from proofcam.agent import AgentState, InspectionAgent
from proofcam.config import Settings
from proofcam.evidence import ObservationRecord
from proofcam.images import ImageLoadError, NormalizedImage
from proofcam.meta_client import MetaClient
from proofcam.overlay import render_overlay, render_overlay_jpeg
from proofcam.report import build_report, write_report
from proofcam.trace import Trace, TraceEvent
from test_agent import (FRONT, OBS, PLAN, REAR_BOTH, ROUTER_CLOSE, SPEC, SWITCH_CLOSE, UNRELATED, WIDE_TRACE,
                        base_fake, observe)
from test_sequences import RECS, _no_network
from test_sequences import new_agent as new_replay_agent

ClientFactory = Callable[[Settings, Trace], MetaClient]


def mock_factory(fm: FakeMeta) -> ClientFactory:
    return lambda s, t: fm.client(s, t)


def replay_factory(s: Settings, t: Trace) -> MetaClient:
    return MetaClient(s, t, transport=httpx.MockTransport(_no_network), source="replay")


def stored_image(img: NormalizedImage) -> NormalizedImage:
    """What storage hands back: the persisted bytes and fields, rebuilt without re-encoding."""
    return NormalizedImage.from_stored(img.image_id, img.source_name, img.width, img.height,
                                       bytes(img.jpeg_bytes), tuple(img.original_size))


def restart(agent: InspectionAgent, make_client: ClientFactory) -> InspectionAgent:
    state_json = agent.snapshot().model_dump_json()
    trace_json = json.dumps([e.model_dump(mode="json") for e in agent.trace.events])
    images = [stored_image(i) for i in agent.images.values()]
    s = agent.settings
    client = make_client(s, Trace.from_events(json.loads(trace_json)))
    return InspectionAgent.restore(AgentState.model_validate_json(state_json), client, s, images)


def comparable_trace(agent: InspectionAgent) -> list[dict]:
    """Trace events without wall-clock fields (timestamps and latencies differ between runs)."""
    return [e.model_dump(exclude={"ts", "latency_ms"}) for e in agent.trace.events]


def agent_for(fm: FakeMeta, **budget) -> InspectionAgent:
    s = settings(**budget)
    return InspectionAgent(SPEC, fm.client(s), s)


# ------------------------------------------------------------------ Trace.from_events

def test_trace_from_events_continues_numbering_and_keeps_source():
    t = Trace()
    t.add("model_call", "muse.observe", source="mock", image_id="img_x")
    t.add("policy", "assess")
    restored = Trace.from_events(json.loads(json.dumps([e.model_dump(mode="json") for e in t.events])))
    assert [e.model_dump() for e in restored.events] == [e.model_dump() for e in t.events]
    assert restored.add("stop", "x").seq == 2
    assert restored.events[0].source == "mock"


def test_trace_from_events_copies_instead_of_sharing():
    t = Trace()
    t.add("policy", "assess", detail={"a": 1})
    restored = Trace.from_events(t.events)
    restored.events[0].detail["a"] = 2
    assert t.events[0].detail == {"a": 1}


@pytest.mark.parametrize("seqs", [[1, 2], [0, 2], [0, 0], [1, 0]])
def test_trace_from_events_rejects_incomplete_sequences(seqs):
    events = [TraceEvent(seq=s, ts=0.0, kind="policy", name="assess") for s in seqs]
    with pytest.raises(ValueError):
        Trace.from_events(events)


# ------------------------------------------------------------------ image identity

def test_stored_image_keeps_identity_and_bytes():
    img = make_image("a.jpg", color=(10, 200, 30))
    back = stored_image(img)
    assert back == img
    assert back.image_id == img.image_id and back.jpeg_bytes == img.jpeg_bytes


def test_stored_image_with_altered_bytes_is_rejected():
    img = make_image("a.jpg")
    with pytest.raises(ImageLoadError):
        NormalizedImage.from_stored(img.image_id, img.source_name, img.width, img.height,
                                    img.jpeg_bytes + b"\0", img.original_size)


# ------------------------------------------------------------------ snapshot serialization

def test_snapshot_json_roundtrip_is_lossless():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    observe(ag, "rear.jpg")
    snap = ag.snapshot()
    assert AgentState.model_validate_json(snap.model_dump_json()) == snap
    assert snap.stop_reason == "all_requirements_resolved"
    assert snap.trace_event_count == len(ag.trace.events)
    assert snap.model_calls_started == ag.client.calls_started > 0


def test_recorded_live_observations_roundtrip_exactly():
    # Real Muse/SAM text output recorded on 2026-10-31 (tuples, link keys with '|', nested extractions).
    for key, rec in RECS.items():
        assert ObservationRecord.model_validate_json(rec.model_dump_json()) == rec, key


def test_snapshot_is_a_copy():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    snap = ag.snapshot()
    before = snap.model_dump()
    ag.history[0]["notes"].append("mutated")
    ag.gap_attempts["x"] = 9
    ag.observations[0].source_name = "mutated"
    assert snap.model_dump() == before


# ------------------------------------------------------------------ restart equivalence (live code path, mocked)

PHOTOS = [("router.jpg", ROUTER_CLOSE), ("switch.jpg", SWITCH_CLOSE), ("wide.jpg", WIDE_TRACE)]
STEP_BACK = "Step back and photograph the next part of the installation clearly."


def _complementary_run(order, restart_each: bool) -> InspectionAgent:
    fm = base_fake()
    fm.queue_chat(OBS, *[PHOTOS[i][1] for i in order])
    fm.queue_chat(PLAN, plan(STEP_BACK), plan(STEP_BACK))
    ag = agent_for(fm)
    for i in order:
        observe(ag, PHOTOS[i][0])
        if restart_each:
            ag = restart(ag, mock_factory(fm))
    return ag


@pytest.mark.parametrize("order", [(0, 1, 2), (1, 2, 0), (2, 0, 1)])
def test_restart_between_every_photo_matches_uninterrupted_run(order):
    plain = _complementary_run(order, restart_each=False)
    resumed = _complementary_run(order, restart_each=True)
    assert resumed.assessments[0].status == "VERIFIED"
    assert resumed.snapshot().model_dump() == plain.snapshot().model_dump()
    assert comparable_trace(resumed) == comparable_trace(plain)
    assert [e.seq for e in resumed.trace.events] == list(range(len(resumed.trace.events)))
    assert [r.id for r in resumed.requests] == [r.id for r in plain.requests] == ["nv1", "nv2"]
    assert resumed.client.calls_started == plain.client.calls_started


def test_restart_preserves_gap_attempts_exhaustion_and_bounded_stop():
    def run(restart_each: bool) -> InspectionAgent:
        fm = base_fake()
        fm.queue_chat(OBS, *[FRONT] * 6)
        fm.queue_chat(PLAN, *[plan()] * 6)
        ag = agent_for(fm, max_observations=10, max_attempts_per_gap=2)
        n = 0
        while not ag.done:
            observe(ag, f"f{n}.jpg")
            n += 1
            assert n <= 6, "loop failed to terminate"
            if restart_each:
                ag = restart(ag, mock_factory(fm))
        return ag

    plain, resumed = run(False), run(True)
    assert resumed.stop_reason == plain.stop_reason == "no_visually_resolvable_gaps"
    assert resumed.gap_attempts == plain.gap_attempts and resumed.gap_attempts
    assert resumed.exhausted == plain.exhausted and resumed.exhausted
    assert resumed.snapshot().model_dump() == plain.snapshot().model_dump()


def test_model_call_budget_counter_survives_restart():
    # Budget of 8 calls: photo 1 uses Muse + 1 SAM + plan = 3; photo 2 the same = 6; photo 3 runs out.
    def run(restart_each: bool) -> InspectionAgent:
        fm = base_fake()
        fm.queue_chat(OBS, FRONT, FRONT, FRONT)
        fm.queue_chat(PLAN, plan(), plan())
        ag = agent_for(fm, max_model_calls=8, max_observations=10, max_attempts_per_gap=5)
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            if ag.done:
                break
            observe(ag, name)
            if restart_each:
                calls = ag.client.calls_started
                ag = restart(ag, mock_factory(fm))
                assert ag.client.calls_started == calls  # neither reset nor double-counted
        return ag

    plain, resumed = run(False), run(True)
    assert plain.stop_reason == "model_call_budget_exhausted"
    assert resumed.stop_reason == plain.stop_reason
    assert resumed.client.calls_started == plain.client.calls_started <= 8
    assert len(resumed.trace.model_calls()) == len(plain.trace.model_calls())


def test_restored_stopped_inspection_stays_stopped():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    observe(ag, "rear.jpg")
    ag = restart(ag, mock_factory(fm))
    assert ag.done and ag.stop_reason == "all_requirements_resolved"
    n_requests = len(fm.requests)
    with pytest.raises(RuntimeError, match="already stopped"):
        observe(ag, "extra.jpg")
    assert len(fm.requests) == n_requests


def test_restored_budget_stop_cannot_be_reopened():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, FRONT)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm, max_observations=2)
    observe(ag, "a.jpg")
    observe(ag, "b.jpg")
    ag = restart(ag, mock_factory(fm))
    assert ag.stop_reason == "observation_budget_exhausted"
    with pytest.raises(RuntimeError, match="cannot reopen"):
        ag.mark_installation_changed("moved cable")


def test_installation_change_survives_restart_and_inspection_continues():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    ag.mark_installation_changed("cable moved")
    ag = restart(ag, mock_factory(fm))
    assert ag.epoch == 1 and ag.gap_attempts == {}
    assert ag.history[-1] == {"event": "installation_changed", "epoch": 1, "reason": "cable moved",
                              "superseded_photos": [1]}
    s = observe(ag, "rear.jpg")
    assert s.assessments[0].status == "VERIFIED"
    assert [o.epoch for o in ag.observations] == [0, 1]
    assert ag.observations[1].responding_to == "nv1"


def test_duplicate_photo_detected_after_restart_without_model_calls():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    s1 = observe(ag, "front.jpg")
    ag = restart(ag, mock_factory(fm))
    n_requests = len(fm.requests)
    s2 = observe(ag, "front.jpg")  # same name -> same colour -> identical normalized bytes
    assert s2.image_id == s1.image_id and s2.seq == 1
    assert ag.history[-1]["duplicate_of"] == 1
    assert len(fm.requests) == n_requests and len(ag.observations) == 1


def test_planner_receives_restored_image_bytes():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, UNRELATED)
    fm.queue_chat(PLAN, plan(), plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    front = ag.images[ag.observations[0].image_id]
    ag = restart(ag, mock_factory(fm))
    observe(ag, "kitchen.jpg")  # unusable: the planner must be shown the latest usable (restored) photo
    last = [json.loads(r.content) for r in fm.requests if r.url.path.endswith("/chat/completions")][-1]
    assert last["response_format"]["json_schema"]["name"] == PLAN
    urls = [c["image_url"]["url"] for m in last["messages"] if isinstance(m["content"], list)
            for c in m["content"] if c.get("type") == "image_url"]
    assert urls == [front.data_url()]
    assert ag.requests[-1].based_on_image_id == front.image_id


def test_replay_restart_between_every_photo_matches_uninterrupted():
    keys = ["m2", "m3", "m7"]
    plain = new_replay_agent("label_or_layout")
    for k in keys:
        asyncio.run(plain.observe_recorded(RECS[k]))
    resumed = new_replay_agent("label_or_layout")
    for k in keys:
        asyncio.run(resumed.observe_recorded(RECS[k]))
        resumed = restart(resumed, replay_factory)
    assert resumed.snapshot().model_dump() == plain.snapshot().model_dump()
    assert comparable_trace(resumed) == comparable_trace(plain)
    assert {e.source for e in resumed.trace.events if e.name == "observe_recorded"} == {"replay"}


# ------------------------------------------------------------------ restore refuses inconsistent inputs

def _stopped_agent() -> tuple[InspectionAgent, FakeMeta]:
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    return ag, fm


def test_restore_rejects_client_that_already_made_calls():
    ag, fm = _stopped_agent()
    client = fm.client(ag.settings, Trace.from_events(ag.trace.events))
    client.calls_started = 1
    with pytest.raises(ValueError, match="fresh client"):
        InspectionAgent.restore(ag.snapshot(), client, ag.settings)


def test_restore_rejects_trace_that_does_not_match_snapshot():
    ag, fm = _stopped_agent()
    with pytest.raises(ValueError, match="trace has"):
        InspectionAgent.restore(ag.snapshot(), fm.client(ag.settings, Trace()), ag.settings)
    longer = Trace.from_events(ag.trace.events)
    longer.add("policy", "assess")
    with pytest.raises(ValueError, match="trace has"):
        InspectionAgent.restore(ag.snapshot(), fm.client(ag.settings, longer), ag.settings)


def test_restore_rejects_changed_budget():
    ag, fm = _stopped_agent()
    other = settings(max_observations=99)
    with pytest.raises(ValueError, match="budget"):
        InspectionAgent.restore(ag.snapshot(), fm.client(other, Trace.from_events(ag.trace.events)), other)


def test_restore_rejects_unknown_image_and_bad_sequence():
    ag, fm = _stopped_agent()
    fresh = lambda: fm.client(ag.settings, Trace.from_events(ag.trace.events))  # noqa: E731
    with pytest.raises(ValueError, match="matches no observation"):
        InspectionAgent.restore(ag.snapshot(), fresh(), ag.settings, [make_image("other.jpg", (1, 2, 3))])
    bad = ag.snapshot().model_copy(update={"observations": [ag.observations[0].model_copy(update={"seq": 2})]})
    with pytest.raises(ValueError, match="1..n"):
        InspectionAgent.restore(bad, fresh(), ag.settings)


def test_unknown_schema_version_is_rejected():
    ag, _ = _stopped_agent()
    d = json.loads(ag.snapshot().model_dump_json())
    d["schema_version"] = 2
    with pytest.raises(ValueError):
        AgentState.model_validate(d)


# ------------------------------------------------------------------ one step at a time

def test_snapshot_and_second_step_refused_while_a_step_is_in_progress():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        fm = base_fake()
        fm.queue_chat(OBS, FRONT)
        fm.queue_chat(PLAN, plan())

        async def gated(request: httpx.Request) -> httpx.Response:
            entered.set()
            await release.wait()
            return fm.handler(request)

        s = settings()
        ag = InspectionAgent(SPEC, MetaClient(s, Trace(), transport=httpx.MockTransport(gated), source="mock"), s)
        task = asyncio.create_task(ag.observe(make_image("a.jpg")))
        await entered.wait()
        with pytest.raises(RuntimeError, match="in progress"):
            ag.snapshot()
        with pytest.raises(RuntimeError, match="in progress"):
            await ag.observe(make_image("b.jpg", (9, 9, 9)))
        with pytest.raises(RuntimeError, match="in progress"):
            ag.mark_installation_changed("x")
        release.set()
        step = await task
        assert step.seq == 1 and len(ag.observations) == 1
        ag.snapshot()  # allowed again once the step has finished

    asyncio.run(scenario())


def test_busy_flag_cleared_after_a_failed_step():
    fm = base_fake()  # no OBS queued: the fake raises inside the request -> treated as an API failure
    fm.queue_chat(OBS, RuntimeError("boom"))
    ag = agent_for(fm)
    with pytest.raises(RuntimeError, match="boom"):
        observe(ag, "a.jpg")
    ag.snapshot()  # not stuck "in progress"


# ------------------------------------------------------------------ policy drift check

def test_policy_drift_is_empty_after_restore_and_has_no_side_effects():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    observe(ag, "rear.jpg")
    ag = restart(ag, mock_factory(fm))
    n_events = len(ag.trace.events)
    assert ag.policy_drift() == []
    assert len(ag.trace.events) == n_events


def test_policy_drift_flags_a_stored_verdict_the_policy_would_not_produce():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    state = ag.snapshot()
    state.assessments[0] = state.assessments[0].model_copy(update={"status": "VERIFIED"})
    restored = InspectionAgent.restore(state, fm.client(ag.settings, Trace.from_events(ag.trace.events)),
                                       ag.settings)
    assert restored.policy_drift() == [SPEC.requirements[0].id]
    assert restored.assessments[0].status == "VERIFIED"  # flagged, never silently replaced


def test_policy_drift_empty_before_any_photo():
    fm = base_fake()
    assert agent_for(fm).policy_drift() == []


# ------------------------------------------------------------------ report refactor

def _verified_agent() -> tuple[InspectionAgent, FakeMeta]:
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_for(fm)
    observe(ag, "front.jpg")
    observe(ag, "rear.jpg")
    return ag, fm


def test_build_report_matches_written_report_and_writes_nothing(tmp_path):
    ag, _ = _verified_agent()
    written = write_report(ag, tmp_path / "run")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    built = build_report(ag, "run", written["overlays"])
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    assert {k: v for k, v in built.items() if k != "generated_at"} == \
           {k: v for k, v in written.items() if k != "generated_at"}
    json.dumps(built)  # JSON-able as-is


def test_overlay_bytes_equal_the_written_overlay_file(tmp_path):
    ag, _ = _verified_agent()
    o = ag.observations[1]
    img, run = ag.images[o.image_id], ag.grounding_runs[o.seq]
    p = render_overlay(img, o, run, tmp_path / "o.jpg")
    assert p.read_bytes() == render_overlay_jpeg(img, o, run)


def test_restored_report_never_redraws_overlays_without_sam_masks(tmp_path):
    ag, fm = _verified_agent()
    rear = ag.observations[1]
    stored = render_overlay_jpeg(ag.images[rear.image_id], rear, ag.grounding_runs[rear.seq])
    ag = restart(ag, mock_factory(fm))
    assert ag.grounding_runs == {} and rear.seq in ag.masks_unavailable

    r = write_report(ag, tmp_path / "no_stored")
    assert rear.image_id not in r["overlays"]  # photo 2 had SAM masks; not re-rendered without them
    assert (tmp_path / "no_stored" / "images" / f"02_{rear.image_id}.jpg").read_bytes() == \
           ag.images[rear.image_id].jpeg_bytes

    r = write_report(ag, tmp_path / "stored", stored_overlays={rear.image_id: stored})
    assert (tmp_path / "stored" / r["overlays"][rear.image_id]).read_bytes() == stored
    assert r["requirements"][0]["status"] == "VERIFIED"
