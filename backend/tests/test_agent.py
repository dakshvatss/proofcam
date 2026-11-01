"""Agent loop tests with mocked Meta responses (NOT real inference)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from fakes import FakeMeta, cable, device, extraction, make_image, plan, port, sam_record, settings
from proofcam.agent import InspectionAgent
from proofcam.report import write_report
from proofcam.spec import InspectionSpec

SPEC = InspectionSpec.load(Path(__file__).resolve().parents[2] / "data" / "specs" / "router_switch.json")
OBS, PLAN = "ObservationExtraction", "NextViewPlan"

FRONT = extraction(devices=[device("D1", "router", side="front", ports=False, box=(50, 100, 450, 600)),
                            device("D2", "switch", side="front", ports=False, box=(550, 100, 950, 600))])
REAR_BOTH = extraction(
    devices=[device("D1", "router", box=(50, 100, 450, 600)), device("D2", "switch", box=(550, 100, 950, 600))],
    ports=[port("P1", "D1", "1", group="LAN", box=(200, 400, 260, 480)),
           port("P2", "D2", "3", box=(600, 400, 660, 480))],
    cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")])
UNRELATED = extraction(subject=False, summary="a kitchen table")
# SAM: one blue-cable mask spanning both port regions; router found where Muse said.
SAM_CABLE = sam_record(0, (80, 120, 270, 150))
SAM_ROUTER = sam_record(0, (20, 30, 180, 180))


def agent_with(fm: FakeMeta, **budget) -> InspectionAgent:
    s = settings(**budget)
    return InspectionAgent(SPEC, fm.client(s), s)


def observe(agent, name):
    # Colour derived from a stable digest of the name: distinct names give distinct photos in every run.
    # (Python's per-process str hash made two names collide ~1 run in 255, turning a photo into a duplicate.)
    color = tuple(hashlib.sha256(name.encode()).digest()[:3])
    return asyncio.run(agent.observe(make_image(name, color=color)))


def base_fake() -> FakeMeta:
    fm = FakeMeta()
    fm.sam["blue ethernet cable"] = SAM_CABLE
    fm.sam["router"] = SAM_ROUTER
    return fm


def test_two_photo_investigation_verifies_with_provenance():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm)

    s1 = observe(ag, "front.jpg")
    assert s1.assessments[0].status == "INSUFFICIENT_EVIDENCE"
    assert s1.next_view is not None and s1.next_view.planner == "muse"
    assert s1.next_view.gap_code == "PORTS_NOT_VISIBLE" and s1.next_view.camera_action == "move_to_rear"
    assert s1.stop_reason is None

    s2 = observe(ag, "rear.jpg")
    a = s2.assessments[0]
    assert a.status == "VERIFIED", a.explanation
    assert s2.stop_reason == "all_requirements_resolved" and s2.next_view is None
    assert {x.image_id for ep in a.endpoints for x in ep.support} == {s2.image_id}
    assert ag.observations[1].responding_to == "nv1"
    assert ag.observations[1].device_links["D1"].corroborated  # SAM router box ~ Muse box
    with pytest.raises(RuntimeError):
        observe(ag, "extra.jpg")
    # trace: every model call recorded as mock, never live
    assert {e.source for e in ag.trace.model_calls()} == {"mock"}


def test_unrelated_followup_does_not_change_findings_and_guidance_repeats():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, UNRELATED)
    fm.queue_chat(PLAN, plan(), plan("Go back to the router and walk around to its rear port panel."))
    ag = agent_with(fm)
    s1 = observe(ag, "front.jpg")
    s2 = observe(ag, "kitchen.jpg")
    assert s2.assessments[0].model_dump() == s1.assessments[0].model_dump()
    assert any("does not show" in n for n in s2.notes)
    assert s2.next_view.gap_code == s1.next_view.gap_code
    # SAM is not called on a photo that shows no subject
    sam_calls = [e for e in ag.trace.model_calls() if e.model == "sam-3.1"]
    assert {e.image_id for e in sam_calls} == {s1.image_id}


def test_bounded_no_progress_stops():
    fm = base_fake()
    fm.queue_chat(OBS, *[FRONT] * 6)
    fm.queue_chat(PLAN, *[plan()] * 6)
    ag = agent_with(fm, max_observations=10, max_attempts_per_gap=2)
    steps = []
    while not ag.done:
        steps.append(observe(ag, f"f{len(steps)}.jpg"))
        assert len(steps) <= 6, "loop failed to terminate"
    assert ag.stop_reason == "no_visually_resolvable_gaps"
    assert all(n <= 2 for n in ag.gap_attempts.values())
    assert steps[-1].assessments[0].status == "INSUFFICIENT_EVIDENCE"


def test_observation_budget_stops():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, FRONT)
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm, max_observations=2)
    observe(ag, "a.jpg")
    s = observe(ag, "b.jpg")
    assert s.stop_reason == "observation_budget_exhausted"
    assert s.assessments[0].status == "INSUFFICIENT_EVIDENCE"


def test_planner_says_unresolvable_gap_is_abandoned():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan(resolvable=False, reason="ports face a wall"),
                  plan(resolvable=False, reason="ports face a wall"),
                  plan(resolvable=False, reason="ports face a wall"))
    ag = agent_with(fm)
    s = observe(ag, "a.jpg")
    assert s.stop_reason == "no_visually_resolvable_gaps"
    assert all("not visually resolvable" in v for v in ag.exhausted.values())


def test_malformed_model_output_is_repaired_once():
    fm = base_fake()
    bad = json.loads(json.dumps(REAR_BOTH))
    bad["ports"][0]["device_ref"] = "D404"
    fm.queue_chat(OBS, bad, REAR_BOTH)
    ag = agent_with(fm)
    s = observe(ag, "rear.jpg")
    assert s.assessments[0].status == "VERIFIED"
    assert any(e.name == "muse_observe.invalid_output" for e in ag.trace.events)


def test_persistently_malformed_output_yields_no_facts():
    fm = base_fake()
    fm.queue_chat(OBS, "not json", "{\"still\": \"wrong\"}")
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm)
    s = observe(ag, "rear.jpg")
    assert ag.observations[0].extraction is None and ag.observations[0].extraction_error
    assert s.assessments[0].status == "INSUFFICIENT_EVIDENCE"
    assert any("no facts" in n for n in s.notes)


def test_api_failure_on_observe_is_insufficient_not_verified():
    fm = base_fake()
    fm.queue_chat(OBS, httpx.Response(401, json={"error": {"message": "bad key"}}))
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm)
    s = observe(ag, "a.jpg")
    assert s.assessments[0].status == "INSUFFICIENT_EVIDENCE"


def test_planner_failure_uses_deterministic_fallback():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, httpx.Response(500, json={"error": {"message": "boom"}}),
                  httpx.Response(500, json={"error": {"message": "boom"}}),
                  httpx.Response(500, json={"error": {"message": "boom"}}))
    ag = agent_with(fm)
    s = observe(ag, "a.jpg")
    nv = s.next_view
    assert nv.planner == "deterministic_fallback" and nv.planner_error
    assert nv.gap_code == "PORTS_NOT_VISIBLE" and "Router" in nv.instruction  # still specific


def test_sam_failure_blocks_grounded_verification():
    fm = FakeMeta()
    fm.sam["blue ethernet cable"] = httpx.Response(400, json={"error": {"message": "invalid prompt"}})
    fm.queue_chat(OBS, REAR_BOTH)
    fm.queue_chat(PLAN, plan("Move closer to the router's LAN 1 port so the plug is clearly visible."))
    ag = agent_with(fm)
    s = observe(ag, "rear.jpg")
    assert s.assessments[0].status == "INSUFFICIENT_EVIDENCE"
    assert {g.code for g in s.assessments[0].gaps} == {"GROUNDING_MISSING"}


def test_report_written(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm)
    observe(ag, "front.jpg")
    observe(ag, "rear.jpg")
    r = write_report(ag, tmp_path / "run1")
    assert r["requirements"][0]["status"] == "VERIFIED"
    assert (tmp_path / "run1" / "report.md").read_text(encoding="utf-8").count("Photo") >= 2
    assert len(list((tmp_path / "run1" / "overlays").glob("*.jpg"))) == 2
    lines = (tmp_path / "run1" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    assert all("base64" not in ln for ln in lines)


ROUTER_CLOSE = extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "1", group="LAN")])
SWITCH_CLOSE = extraction(devices=[device("D1", "switch")], ports=[port("P1", "D1", "3")])
WIDE_TRACE = extraction(  # labels legible, insertion only partial: identity evidence only
    devices=[device("D1", "router", box=(50, 100, 450, 600)), device("D2", "switch", box=(550, 100, 950, 600))],
    ports=[port("P1", "D1", "1", group="LAN", vis="partial"), port("P2", "D2", "3", vis="partial")],
    cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")])


@pytest.mark.parametrize("order", [(0, 1, 2), (1, 2, 0), (2, 0, 1)])
def test_live_path_accumulates_complementary_photos_in_any_order(order):
    photos = [("router.jpg", ROUTER_CLOSE), ("switch.jpg", SWITCH_CLOSE), ("wide.jpg", WIDE_TRACE)]
    fm = base_fake()
    fm.queue_chat(OBS, *[photos[i][1] for i in order])
    fm.queue_chat(PLAN, plan("Step back and photograph the next part of the installation clearly."),
                  plan("Step back and photograph the next part of the installation clearly."))
    ag = agent_with(fm)
    steps = [observe(ag, photos[i][0]) for i in order]
    a = steps[-1].assessments[0]
    assert [s.stop_reason for s in steps] == [None, None, "all_requirements_resolved"]
    assert a.status == "VERIFIED", a.explanation
    names = {o.seq: o.source_name for o in ag.observations}
    assert {names[s.seq] for s in a.endpoints[0].support} == {"router.jpg"}
    assert {names[s.seq] for s in a.endpoints[1].support} == {"switch.jpg"}
    assert {names[x.seq] for x in a.identity_evidence} == {"wide.jpg"}
    # The planner is told what is already established.
    plan_bodies = [json.loads(r.content) for r in fm.requests if r.url.path.endswith("/chat/completions")
                   and json.loads(r.content)["response_format"]["json_schema"]["name"] == PLAN]
    texts = [m["content"][0]["text"] for b in plan_bodies for m in b["messages"] if m["role"] == "user"]
    assert texts and all("evidence_already_established" in t for t in texts)


def test_planner_is_told_previous_failed_requests_for_the_same_gap():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, FRONT)
    fm.queue_chat(PLAN, plan("Walk around to the back of the router and frame its port row."),
                  plan("Kneel and look at the router rear from the left side instead."))
    ag = agent_with(fm)
    observe(ag, "a.jpg")
    observe(ag, "b.jpg")
    last = [r for r in fm.requests if r.url.path.endswith("/chat/completions")][-1]
    text = json.loads(last.content)["messages"][1]["content"][0]["text"]
    assert "Walk around to the back of the router" in json.loads(text)["previous_requests_for_this_gap"][0]
