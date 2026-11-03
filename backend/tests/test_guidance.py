"""M2.2 guidance: unread-label guard, off-target attempt accounting, contradictions -> installation review.

All model output is mocked (FakeMeta) or replayed from recorded observations; no real inference.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from fakes import FakeMeta, cable, device, extraction, plan, port, settings
from proofcam.agent import AgentState, InspectionAgent
from proofcam.api_models import StepResponse
from proofcam.evidence import Gap
from proofcam.muse import _FALLBACK, _HIDDEN_LABEL, presumes_unread_label
from proofcam.spec import InspectionSpec
from proofcam.trace import Trace
from test_acceptance import cap, check_invariants, create, server
from test_agent import FRONT, OBS, PLAN, REAR_BOTH, SPEC, UNRELATED, agent_with, base_fake, observe
from test_persistence import mock_factory, replay_factory, restart
from test_sequences import RECS, feed, new_agent
from test_verdict_correctness import rear

SMOKE_TEXT = ("Lower your phone to the tabletop in front of the blue cable and tilt up at the rear of the black TP-Link "
              "router from slightly to the left. Keep the blue plug in the leftmost port with the printed 'LAN 1' text "
              "beside its boot and 'LAN 2' next to it in sharp focus.")  # live M1 smoke test, 2026-11-02

R, S = (50, 100, 450, 600), (550, 100, 950, 600)
# Router rear: a blue plug in a port whose label is not readable -> LABEL_ILLEGIBLE (hidden by the plug).
HIDDEN = extraction(devices=[device("D1", "router", box=R)],
                    ports=[port("P1", "D1", None, legible="illegible", box=(200, 400, 260, 480))])
ROUTER_FRONT = extraction(devices=[device("D1", "router", side="front", ports=False, box=R)])
SWITCH_ONLY = extraction(devices=[device("D1", "switch", side="front", ports=False, box=S)])
UNKNOWN_DEVICE = extraction(devices=[device("D1", None, box=R)], summary="a printer")


def chat_calls(fm: FakeMeta, schema: str) -> int:
    return sum(1 for r in fm.requests if r.url.path.endswith("/chat/completions")
               and json.loads(r.content)["response_format"]["json_schema"]["name"] == schema)


def plan_payloads(fm: FakeMeta) -> list[dict]:
    out = []
    for r in fm.requests:
        body = json.loads(r.content)
        if r.url.path.endswith("/chat/completions") and body["response_format"]["json_schema"]["name"] == PLAN:
            out.append(json.loads(body["messages"][1]["content"][0]["text"]))
    return out


# ============================================================================ 1. unread-label guard

@pytest.mark.parametrize("text", [
    SMOKE_TEXT,
    "Get closer so the LAN 1 label just under the plug is readable.",
    "Read the 'LAN 1' text printed above the leftmost port.",
    "Tilt up to the spot where it says LAN1 next to the plug.",
    "Frame the port with the LAN-1 sticker in the middle of the photo.",
    "Keep the '3' label above the switch port in focus.",
])
def test_guard_flags_unread_label_presented_as_visible_text(text):
    assert presumes_unread_label(text, ["LAN 1", "3"])


@pytest.mark.parametrize("text", [
    "Find the port labelled LAN 1 and photograph it straight on.",
    "Photograph the port expected to be LAN 1 so any printed label can be read.",
    "Show which port is LAN 1 by including the whole port row.",
    "Move to the rear of the router and frame the LAN 1 port and its neighbours.",
    "Photograph the port labelled 'LAN 1' from a low angle.",
    "Show switch port 3 and the 3 labels to its left.",  # bare numbers only count when quoted
    "Move closer to the router's port row so any printed label beside each port can be read.",
])
def test_guard_allows_wording_that_only_names_the_target(text):
    assert not presumes_unread_label(text, ["LAN 1", "3"])


def test_every_deterministic_template_is_neutral_about_label_text():
    templates = [t for _, t in _FALLBACK.values()] + [_HIDDEN_LABEL[1]]
    for tmpl in templates:
        for label in ("LAN 1", "3", "WAN"):
            text = tmpl.format(target=f"Router port {label}", device="Router", device_description="black router",
                               port_label=label)
            assert not presumes_unread_label(text, [label]), text


def test_presumptuous_live_instruction_is_replaced_by_neutral_guidance():
    fm = base_fake()
    fm.queue_chat(OBS, HIDDEN)
    fm.queue_chat(PLAN, {**plan(SMOKE_TEXT), "success_criteria": "Plug and LAN 1 port in sharp focus."})
    ag = agent_with(fm)
    s = observe(ag, "rear.jpg")
    nv = s.next_view
    assert nv.gap_code == "LABEL_ILLEGIBLE"
    assert nv.planner == "deterministic_fallback" and "presented the expected label" in nv.planner_error
    assert "printed 'LAN 1'" not in nv.instruction and not presumes_unread_label(nv.instruction, ["LAN 1"])
    assert "not yet known whether this is LAN 1" in nv.instruction
    assert plan_payloads(fm)[0]["labels_never_read_in_any_photo"] == ["LAN 1"]
    assert any(e.name == "unread_label_guard" for e in ag.trace.events)


def test_presumptuous_success_criteria_rewritten_but_muse_instruction_kept():
    fm = base_fake()
    fm.queue_chat(OBS, HIDDEN)
    fm.queue_chat(PLAN, plan("Crouch to the left of the router and photograph the port row from below."))
    ag = agent_with(fm)  # default fake success_criteria: "LAN 1 label and plug readable"
    nv = observe(ag, "rear.jpg").next_view
    assert nv.planner == "muse" and nv.instruction.startswith("Crouch")
    assert nv.success_criteria.startswith("The printed label (if any)") and "rewrote success_criteria" in nv.planner_error


def test_guard_is_off_once_the_label_has_actually_been_read():
    rear_router = extraction(devices=[device("D1", "router", box=R)],
                             ports=[port("P1", "D1", "1", group="LAN", box=(200, 400, 260, 480))])
    fm = base_fake()
    fm.sam.pop("blue ethernet cable")  # no SAM grounding -> GROUNDING_MISSING; LAN 1 was legibly read
    fm.queue_chat(OBS, rear_router)
    fm.queue_chat(PLAN, plan("Move closer so the LAN 1 label and the plug under it are both sharp."))
    ag = agent_with(fm)
    nv = observe(ag, "rear.jpg").next_view
    assert nv.gap_code == "GROUNDING_MISSING" and nv.planner == "muse" and nv.planner_error is None
    assert plan_payloads(fm)[0]["labels_never_read_in_any_photo"] == []


def test_unresolvable_plan_is_not_overridden_by_the_guard():
    fm = base_fake()
    fm.queue_chat(OBS, HIDDEN)
    fm.queue_chat(PLAN, *[plan(SMOKE_TEXT, resolvable=False, reason="the label is under the plug")] * 3)
    ag = agent_with(fm)
    observe(ag, "rear.jpg")
    assert any("not visually resolvable" in v for v in ag.exhausted.values())


# ============================================================================ 2. attempt accounting (probe P4)

def test_probe_p4_unrelated_photos_do_not_exhaust_the_gap_or_replan():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, UNRELATED, UNRELATED, UNRELATED)
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm, max_observations=4)
    steps = [observe(ag, n) for n in ("front.jpg", "k1.jpg", "k2.jpg", "k3.jpg")]
    key = steps[0].next_view.gap_key
    assert [s.next_view.id if s.next_view else None for s in steps] == ["nv1", "nv1", "nv1", None]
    # attempts = on-target responses + the outstanding request: never above 1 here; the last off-target photo hit
    # the photo budget, so its refund stands and nothing is outstanding.
    assert ag.gap_attempts == {key: 0} and ag.exhausted == {}
    assert steps[-1].stop_reason == "observation_budget_exhausted"  # the photo budget still bounds it
    assert chat_calls(fm, PLAN) == 1  # no repeated planning while the original request stands
    assert all("no attempt was counted" in " ".join(s.notes) for s in steps[1:3])


@pytest.mark.parametrize("label,ext,reissued", [
    ("other spec device only: guidance moves to it", SWITCH_ONLY, False),
    ("irrelevant device: guidance stays", UNKNOWN_DEVICE, True),
    ("unusable photo: guidance stays", UNRELATED, True)])
def test_off_target_photos_refund_the_router_attempt(label, ext, reissued):
    fm = base_fake()
    fm.queue_chat(OBS, ROUTER_FRONT, ext)
    fm.queue_chat(PLAN, plan(), plan("Walk around to the back of the black switch and frame its ports."))
    ag = agent_with(fm)
    s1 = observe(ag, "router_front.jpg")
    assert s1.next_view.gap_code == "PORTS_NOT_VISIBLE" and s1.next_view.gap_key == "R1:PORTS_NOT_VISIBLE:0"
    s2 = observe(ag, "second.jpg")
    assert "R1:PORTS_NOT_VISIBLE:0" not in ag.exhausted
    if reissued:  # refunded, then the same request re-issued (counted once, outstanding), no new planner call
        assert s2.next_view.id == s1.next_view.id and ag.gap_attempts["R1:PORTS_NOT_VISIBLE:0"] == 1, label
        assert chat_calls(fm, PLAN) == 1
    else:  # refunded; the user is at the switch now, so its gap is planned
        assert ag.gap_attempts["R1:PORTS_NOT_VISIBLE:0"] == 0 and s2.next_view.gap_key.endswith(":1"), label


def test_partial_view_does_not_count_for_a_port_level_gap():
    fm = base_fake()
    fm.queue_chat(OBS, HIDDEN, ROUTER_FRONT)
    fm.queue_chat(PLAN, plan("Crouch to the left of the router and photograph the port row from below."))
    ag = agent_with(fm, max_attempts_per_gap=1)
    s1 = observe(ag, "rear.jpg")
    s2 = observe(ag, "front_again.jpg")  # router visible, its ports not: does not address LABEL_ILLEGIBLE
    assert s2.next_view.id == s1.next_view.id and ag.exhausted == {}


def test_partial_view_does_count_for_the_ports_not_visible_gap():
    fm = base_fake()
    fm.queue_chat(OBS, ROUTER_FRONT, ROUTER_FRONT)
    fm.queue_chat(PLAN, plan(), plan("Go around the left side of the router to its back panel."))
    ag = agent_with(fm, max_attempts_per_gap=1)
    observe(ag, "a.jpg")
    observe(ag, "b.jpg")  # showed the router again (front): a genuine, failed attempt
    assert "R1:PORTS_NOT_VISIBLE:0" in ag.exhausted


def test_useful_follow_up_counts_and_closes_the_gap():
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan())
    ag = agent_with(fm)
    observe(ag, "front.jpg")
    s = observe(ag, "rear.jpg")
    assert s.assessments[0].status == "VERIFIED" and not any("no attempt" in n for n in s.notes)


def test_attempt_accounting_is_identical_across_restarts():
    def run(restart_each: bool) -> InspectionAgent:
        fm = base_fake()
        fm.queue_chat(OBS, ROUTER_FRONT, UNRELATED, SWITCH_ONLY, ROUTER_FRONT)
        fm.queue_chat(PLAN, *[plan()] * 4)
        ag = agent_with(fm, max_observations=10)
        for n in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):
            observe(ag, n)
            if restart_each:
                ag = restart(ag, mock_factory(fm))
        return ag

    assert run(True).snapshot().model_dump() == run(False).snapshot().model_dump()


# ============================================================================ 3. contradictions (probe P5)

def test_probe_p5_endpoint_contradiction_stops_for_review_without_camera_requests():
    ag = new_agent("label_or_layout", max_observations=10)
    steps = feed(ag, ["m3", "m1"])
    assert ag.stop_reason == "contradiction_requires_review" and steps[-1].next_view is None
    assert all(r.gap_code != "CONTRADICTION" for r in ag.requests)
    (item,) = ag.review_items()
    assert item["photos"] == [1, 2] and item["action"] == "review_installation"
    msg = " ".join(steps[-1].notes)
    assert "cannot remove this conflict" in msg and "installation_changed" in msg
    assert "close" not in item["message"].lower()  # never promises that a closer photo will fix it
    with pytest.raises(RuntimeError):
        feed(ag, ["m2"])


def test_trace_contradiction_stops_for_review():
    ag = InspectionAgent(SPEC, replay_factory(settings(), Trace()), settings(),
                         plan_with_muse=False)
    from test_verdict_correctness import trace_photo
    asyncio.run(ag.observe_recorded(trace_photo(0, switch_label="4")))
    asyncio.run(ag.observe_recorded(trace_photo(0).model_copy(update={"image_id": "img_b"})))
    assert ag.stop_reason == "contradiction_requires_review"
    assert ag.review_items()[0]["photos"] == [1, 2] and ag.assessments[0].status == "INSUFFICIENT_EVIDENCE"


def test_installation_change_reopens_a_review_stop_and_keeps_history():
    ag = new_agent("label_or_layout", max_observations=10)
    feed(ag, ["m3", "m1"])
    ag.mark_installation_changed("re-seated the cable in switch port 3")
    assert ag.stop_reason is None and ag.epoch == 1 and ag.review_items() == []
    assert [o.seq for o in ag.observations] == [1, 2]  # nothing discarded, just superseded
    s = feed(ag, ["m2"])[0]
    assert s.stop_reason != "contradiction_requires_review" and ag.observations[-1].epoch == 1


def test_review_stop_survives_snapshot_restore_and_json():
    ag = new_agent("label_or_layout", max_observations=10)
    feed(ag, ["m3", "m1"])
    state = AgentState.model_validate_json(ag.snapshot().model_dump_json())
    assert state.stop_reason == "contradiction_requires_review"
    back = restart(ag, replay_factory)
    assert back.stop_reason == "contradiction_requires_review" and back.review_items() == ag.review_items()


def test_other_requirements_continue_while_one_is_blocked():
    d = json.loads(SPEC.model_dump_json())
    d["requirements"].append({**d["requirements"][0], "id": "R2", "text": "Yellow LAN 2 to switch 5",
                              "cable_color": "yellow",
                              "endpoints": [{"device_id": "router", "port_label": "LAN 2", "label_aliases": []},
                                            {"device_id": "switch", "port_label": "5", "label_aliases": []}]})
    spec2 = InspectionSpec.model_validate(d)
    from test_verdict_correctness import trace_photo
    ag = InspectionAgent(spec2, replay_factory(settings(), Trace()), settings(),
                         plan_with_muse=False)
    asyncio.run(ag.observe_recorded(trace_photo(0, switch_label="4")))
    s = asyncio.run(ag.observe_recorded(trace_photo(0).model_copy(update={"image_id": "img_b"})))
    assert [r["requirement_id"] for r in ag.review_items()] == ["R1"]
    assert s.stop_reason is None and s.next_view.requirement_id == "R2"  # R2 still pursued


def test_old_stored_step_response_without_the_new_field_still_validates():
    stored = {"inspection_id": "insp_x", "seq": 1, "image_id": "img_000000000000", "duplicate_of": None,
              "notes": [], "status": "open", "stop_reason": None, "assessments": [], "next_view": None,
              "version": 1, "usage": {"model_calls": 1, "model_call_limit": 40, "remaining": 39,
                                      "calls_by_status": {"ok": 1}, "estimated_cost_usd": 0.0}}
    assert StepResponse.model_validate(stored).review_required == []


# ============================================================================ 4. HTTP, report, restart

def test_review_stop_over_http_with_restart_and_reports(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, rear("4"), rear("3"), REAR_BOTH)
    fm.queue_chat(PLAN, plan())

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            await cap(c, iid, "to_port_4.jpg")
            r = await cap(c, iid, "to_port_3.jpg")
            body = r.json()
            assert body["stop_reason"] == "contradiction_requires_review" and body["next_view"] is None
            (item,) = body["review_required"]
            assert item["photos"] == [1, 2] and item["action"] == "review_installation"
            n = len(fm.requests)
            r = await cap(c, iid, "another.jpg")
            assert (r.status_code, r.json()["error"]) == (409, "inspection_stopped")
            assert "declare an installation change" in r.json()["message"] and len(fm.requests) == n
        async with server(tmp_path, fm) as (c, store, _a):  # restart
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["status"] == "stopped" and st["stop_reason"] == "contradiction_requires_review"
            assert st["review_required"][0]["photos"] == [1, 2] and st["policy_drift"] == []
            report = (await c.get(f"/api/inspections/{iid}/report")).json()
            assert report["stop_reason"] == "contradiction_requires_review" and report["review_required"]
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert "## Review required" in md and "STOP: contradiction_requires_review" in md
            r = await c.post(f"/api/inspections/{iid}/events",
                             json={"type": "installation_changed", "reason": "moved the cable to port 3"})
            assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["review_required"] == []
            r = await cap(c, iid, "fixed.jpg")
            assert r.json()["assessments"][0]["status"] == "VERIFIED"
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


def test_off_target_photos_over_http_keep_guidance_and_accounting(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, UNRELATED, REAR_BOTH)
    fm.queue_chat(PLAN, plan())

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            g1 = (await cap(c, iid, "front.jpg")).json()["next_view"]["id"]
        async with server(tmp_path, fm) as (c, store, _a):
            r = await cap(c, iid, "kitchen.jpg", responding_to=g1)
            assert r.json()["next_view"]["id"] == g1 and any("no attempt" in n for n in r.json()["notes"])
            r = await cap(c, iid, "rear.jpg", responding_to=g1)  # still the current guidance: not stale
            assert r.json()["assessments"][0]["status"] == "VERIFIED"
            assert chat_calls(fm, PLAN) == 1
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())
