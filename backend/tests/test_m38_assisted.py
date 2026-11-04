"""M3.8: operator-assisted Home Entertainment usability (spec.assisted), and that no other template changed.

Hand-built mocked model claims plus the recorded live Report B observations (fixtures/live_home_report_b.json).
No network, no paid calls.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from fakes import FakeMeta, device, extraction, make_image, plan, settings
from proofcam.evidence import ObservationRecord
from proofcam.muse import plan_next_view
from proofcam.policy import assess_requirement, overall_assessment
from proofcam.report import render_markdown, verdict_label
from proofcam.spec import InspectionSpec
from test_acceptance import cap, create, server
from test_m37_evidence import (ASSISTED, EXACT, ETH, HDMI, HOME, a_of, assess_all, decl, feed, live_b, ps5_rear,
                               replay_agent, router_lan, tv_panel)
from test_multi_requirement import cport, rec

OBS, PLAN = "ObservationExtraction", "NextViewPlan"


def with_colours(spec: InspectionSpec, **colours) -> InspectionSpec:
    d = json.loads(spec.model_dump_json())
    for r in d["requirements"]:
        if r["id"] in colours:
            r["cable_color"] = colours[r["id"]]
    return InspectionSpec.model_validate(d)


def ps5_plugs(seq, lan_color="grey", hdmi_color="white", grounded=(ETH, HDMI), hdmi_conn="hdmi"):
    ports = [cport("P1", "D1", None, "ethernet", color=lan_color, legible="no_label"),
             cport("P2", "D1", None, hdmi_conn, color=hdmi_color, legible="no_label", box=(200, 600, 260, 680))]
    links = {"P1": ETH} if ETH in grounded else {}
    if HDMI in grounded:
        links["P2"] = HDMI
    return rec(seq, extraction(devices=[device("D1", "ps5")], ports=ports), links)


def tv_clear(seq, color="white"):
    return rec(seq, extraction(devices=[device("D1", "tv")], ports=[cport("P1", "D1", "HDMI 2", "hdmi", color=color)]),
               {"P1": HDMI})


# ======================================================================================== 0. scope isolation
def test_only_the_assisted_template_has_assisted_rules():
    assert ASSISTED.assisted is not None and ASSISTED.id == "ps5_home_setup_assisted_v1"
    assert HOME.assisted is None and EXACT.assisted is None
    assert ASSISTED.assisted.max_attempts_per_gap == 1 and ASSISTED.assisted.ignore_cable_color


# ============================================================================== 1-3. cable colour
def test_non_blue_ethernet_and_non_black_hdmi_are_accepted_in_assisted_mode():
    # An assisted spec that ignores colour cannot name one (it would still steer SAM and the wording).
    with pytest.raises(ValueError, match="ignore_cable_color"):
        with_colours(ASSISTED, R1="blue")
    out = assess_all(ASSISTED, [router_lan(1), ps5_plugs(2, lan_color="grey", hdmi_color="white"), tv_clear(3)])
    assert a_of(out, "R1").endpoints[1].state == "established"  # grey Ethernet plug
    assert a_of(out, "R2").endpoints[0].state == "established"  # white HDMI plug
    assert a_of(out, "R2").endpoints[1].state == "established"


def test_colour_mismatch_is_unchanged_in_strict_templates():
    strict = with_colours(HOME, R1="blue")
    assert a_of(assess_all(strict, [ps5_plugs(1, lan_color="grey")]), "R1").endpoints[1].state != "established"
    wrong = rec(1, extraction(devices=[device("D1", "router")],
                              ports=[cport("P1", "D1", "LAN 1", "ethernet", color="black")]))
    assert assess_requirement(EXACT, EXACT.requirements[0], [wrong]).status == "VIOLATED"  # black, not blue


def test_hdmi_plug_in_an_ethernet_socket_is_never_accepted_in_assisted_mode():
    lan_holds_hdmi = rec(1, extraction(devices=[device("D1", "ps5")],
                                       ports=[cport("P1", "D1", None, "hdmi", color="black", legible="no_label")]),
                         {"P1": ETH})
    a = a_of(assess_all(ASSISTED, [lan_holds_hdmi]), "R1")
    assert a.endpoints[1].state == "unknown" and not a.endpoints[1].candidates


# =================================================================== 4, 8. observant: hidden labels, one photo many facts
def test_clear_plug_in_an_unlabelled_ps5_socket_is_identified_by_shape_and_disclosed():
    a = a_of(assess_all(ASSISTED, [router_lan(1), ps5_plugs(2)]), "R1")
    assert a.endpoints[1].state == "established" and a.endpoints[1].support[0].port_basis == "connector_shape"
    assert not any(g.code == "LABEL_ILLEGIBLE" for g in a.gaps)


def test_one_ps5_rear_photo_establishes_both_ps5_endpoints():
    out = assess_all(ASSISTED, [ps5_plugs(4)])
    assert [x.seq for x in a_of(out, "R1").endpoints[1].support] == [4]
    assert [x.seq for x in a_of(out, "R2").endpoints[0].support] == [4]


# ======================================================== 5, 11. SAM misses the HDMI cable; explicit confirmation
def test_muse_only_hdmi_insertion_is_provisional_and_confirmable_only_in_assisted_mode():
    obs = [ps5_plugs(2, grounded=(ETH,))]
    for spec, permitted in ((ASSISTED, True), (HOME, False)):
        ep = a_of(assess_all(spec, obs), "R2").endpoints[0]
        assert ep.state == "unknown" and [x.seq for x in ep.candidates] == [2]
        assert ep.gap.code == "GROUNDING_MISSING" and ep.gap.context["declaration_permitted"] is permitted


def test_operator_confirmed_insertion_completes_an_operator_assisted_verdict():
    ag = replay_agent(ASSISTED)
    feed(ag, router_lan(1), ps5_plugs(2, grounded=(ETH,)), tv_clear(3))
    n = len(ag.trace.model_calls())
    d = asyncio.run(ag.declare("endpoint_insertion", requirement_id="R2", endpoint_index=0))
    assert d.statement == "The hdmi plug seen in photo 2 is fully seated in the PlayStation 5 HDMI OUT port."
    ep = a_of(ag.assessments, "R2").endpoints[0]
    assert ep.state == "established" and ep.support[0].insertion_basis == "operator_confirmed"
    for rid in ("R1", "R2"):
        asyncio.run(ag.declare("cable_identity", requirement_id=rid))
    r2 = a_of(ag.assessments, "R2")
    assert r2.status == "VERIFIED" and r2.assurance == "operator_assisted"
    assert any("SAM did not corroborate" in x for x in r2.operator_declarations)
    assert overall_assessment(ag.assessments).assurance == "operator_assisted"
    assert ag.stop_reason == "all_requirements_resolved" and len(ag.trace.model_calls()) == n


def test_insertion_confirmation_is_refused_in_strict_mode_and_for_unclear_connectors():
    seated = [decl("endpoint_insertion", requirement_id="R2", endpoint_index=0)]
    ag = replay_agent(HOME)
    feed(ag, ps5_plugs(1, grounded=(ETH,)))
    with pytest.raises(ValueError, match="does not permit"):
        asyncio.run(ag.declare("endpoint_insertion", requirement_id="R2", endpoint_index=0))
    # injected anyway into the strict template: ignored by the policy
    assert a_of(assess_all(HOME, [ps5_plugs(1, grounded=(ETH,))], seated), "R2").endpoints[0].state == "unknown"
    # A port identified by its printed label, but whose connector family Muse did not report: not confirmable.
    labelled_unclear = rec(1, extraction(devices=[device("D1", "ps5")],
                                         ports=[cport("P2", "D1", "HDMI OUT", "unclear", color="black")]))
    ag = replay_agent(ASSISTED)
    feed(ag, labelled_unclear)
    assert a_of(ag.assessments, "R2").endpoints[0].candidates  # seen by Muse, only SAM missing
    with pytest.raises(ValueError, match="no photo shows a plug"):
        asyncio.run(ag.declare("endpoint_insertion", requirement_id="R2", endpoint_index=0))
    assert a_of(assess_all(ASSISTED, [labelled_unclear], seated), "R2").endpoints[0].state == "unknown"


# ============================================================== 12-14. statements never beat visible evidence
def test_confirmation_contradicted_by_a_visibly_empty_socket_is_refused_and_ignored():
    plug = ps5_plugs(1, grounded=())  # Muse-only plug in the PS5's single LAN socket
    empty = rec(2, extraction(devices=[device("D1", "ps5")],
                              ports=[cport("P1", "D1", None, "ethernet", occ="empty", color=None, legible="no_label")]))
    ag = replay_agent(ASSISTED)
    feed(ag, plug, empty)
    with pytest.raises(ValueError, match="contrary evidence"):
        asyncio.run(ag.declare("endpoint_insertion", requirement_id="R1", endpoint_index=1))
    ep = a_of(assess_all(ASSISTED, [plug, empty], [decl("endpoint_insertion", requirement_id="R1", endpoint_index=1)]),
              "R1").endpoints[1]
    assert ep.state == "contradicted" and not any(x.insertion_basis for x in ep.support)


def test_wrong_port_violation_stays_violated_under_assisted_rules():
    d = json.loads(EXACT.model_dump_json())
    d["assisted"] = {"ignore_cable_color": False}  # the exact spec names a colour
    exact_assisted = InspectionSpec.model_validate(d)
    empty_lan1 = rec(1, extraction(devices=[device("D1", "router")],
                                   ports=[cport("P1", "D1", None, "ethernet", color="blue", legible="no_label"),
                                          cport("P2", "D1", "LAN 1", "ethernet", occ="empty", color=None)]))
    a = assess_requirement(exact_assisted, exact_assisted.requirements[0], [empty_lan1],
                           declarations=[decl("endpoint_insertion", requirement_id="R1", endpoint_index=0)])
    assert a.status == "VIOLATED" and a.assurance == "visual"


def test_same_cable_is_never_inferred_from_matching_colours():
    a = a_of(assess_all(ASSISTED, [router_lan(1), ps5_rear(2)]), "R1")  # blue at both ends, separate photos
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"


# ================================================================= 6-7. guidance: fulfilled views, no re-framing loops
def test_requested_view_is_fulfilled_even_though_the_connection_stays_unresolved():
    ag = replay_agent(ASSISTED)
    steps = feed(ag, *[live_b(n) for n in range(1, 9)])
    assert steps[7].view_check.status == "captured"
    assert a_of(steps[7].assessments, "R2").status == "INSUFFICIENT_EVIDENCE"


def _hidden_label_router(seq):
    r = live_b(2).model_copy(deep=True)
    return r.model_copy(update={"image_id": f"img_hidden{seq}", "seq": seq})


def test_same_view_is_requested_once_in_assisted_mode_but_twice_in_strict_mode():
    for spec, repeats in ((ASSISTED, False), (HOME, True)):
        ag = replay_agent(spec)
        steps = feed(ag, live_b(1), _hidden_label_router(2), _hidden_label_router(3))
        assert steps[1].next_view.gap_code == "LABEL_ILLEGIBLE"
        assert (steps[2].next_view.gap_code == "LABEL_ILLEGIBLE") is repeats
        assert ("R1:LABEL_ILLEGIBLE:0" in ag.exhausted) is not repeats


@pytest.mark.parametrize("instruction,action", [
    ("Shift about 3 inches to the left of the plug and retake.", "move_left"),
    ("Step back 6 to 8 inches and tilt slightly down toward the HDMI plug.", "step_back_wide_view"),
])
def test_micro_adjustment_guidance_is_replaced_only_in_assisted_mode(instruction, action):
    gap = a_of(assess_all(ASSISTED, [ps5_plugs(2, grounded=(ETH,))]), "R2").endpoints[0].gap
    for spec, suppressed in ((ASSISTED, True), (HOME, False)):
        fm = FakeMeta()
        fm.queue_chat(PLAN, plan(instruction, action=action))
        req, _ = asyncio.run(plan_next_view(fm.client(settings()), spec, gap, make_image("p.jpg"), [], "nv1"))
        assert (req.planner == "deterministic_fallback") is suppressed
        assert (req.instruction == instruction) is not suppressed
        if suppressed:
            assert "inches" not in req.instruction and "slightly" not in req.instruction


def test_assisted_planner_is_told_to_seek_new_facts():
    gap = a_of(assess_all(ASSISTED, [ps5_plugs(2, grounded=(ETH,))]), "R2").endpoints[0].gap
    fm = FakeMeta()
    fm.queue_chat(PLAN, plan("Photograph the television's HDMI panel from beside the TV.", action="move_to_rear"))
    req, _ = asyncio.run(plan_next_view(fm.client(settings()), ASSISTED, gap, make_image("p.jpg"), [], "nv1"))
    system = json.loads(fm.requests[0].content)["messages"][0]["content"]
    assert "Operator-assisted template" in system and req.planner == "muse"


# ===================================================================== 16-17. persistence, report, labels
def test_insertion_confirmation_over_http_persists_and_is_reported(tmp_path):
    fm = FakeMeta()
    fm.queue_chat(OBS, extraction(devices=[device("D1", "ps5")],
                                  ports=[cport("P2", "D1", "HDMI", "hdmi", color="white", box=(400, 400, 500, 500))]))
    fm.queue_chat(PLAN, plan("Photograph the television's HDMI panel.", action="move_to_rear"))

    async def go():
        async with server(tmp_path, fm) as (c, _store, _a):
            iid = await create(c, "ps5_home_setup_assisted")
            assert (await cap(c, iid, "ps5.jpg")).status_code == 200
            sent = len(fm.requests)
            r = await c.post(f"/api/inspections/{iid}/events", json={
                "type": "endpoint_insertion", "requirement_id": "R2", "endpoint_index": 0, "confirm": True})
            assert r.status_code == 200, r.text
            assert len(fm.requests) == sent
        async with server(tmp_path, fm) as (c, _store, _a):
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert [(d["kind"], d["endpoint_index"]) for d in st["declarations"]] == [("endpoint_insertion", 0)]
            ep = st["assessments"][1]["endpoints"][0]
            assert ep["state"] == "established" and ep["support"][0]["insertion_basis"] == "operator_confirmed"
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert "NOT SAM-corroborated; insertion confirmed by the operator" in md
            assert "is fully seated in the PlayStation 5 HDMI OUT port" in md

    asyncio.run(go())


def test_verdict_labels_follow_evidence_provenance_and_strict_reports_are_unchanged():
    assert verdict_label("VERIFIED", "operator_assisted") == "[VERIFIED — OPERATOR-ASSISTED]"
    assert verdict_label("VERIFIED", "visual") == verdict_label("VERIFIED", "spec_assumption") == \
        "[VERIFIED — VISUAL EVIDENCE]"
    assert verdict_label("VERIFIED", "visual", assisted=False) == "[VERIFIED]"
    assert verdict_label("VIOLATED", "visual") == "[VIOLATED]"
    ag = replay_agent(ASSISTED)
    feed(ag, router_lan(1), ps5_rear(2))
    asyncio.run(ag.declare("cable_identity", requirement_id="R1"))
    md = render_markdown(ag, {}, ag.trace.summary())
    assert "[VERIFIED — OPERATOR-ASSISTED] R1" in md and "SAM corroboration" in md and "socket shape assumption" in md
    strict = replay_agent(EXACT)
    assert "VERIFIED —" not in render_markdown(strict, {}, strict.trace.summary())


def test_report_b_observations_are_unchanged_by_assisted_rules_except_guidance():
    # Same evidence, same verdicts: assisted mode changes guidance and what may be confirmed, never what photos show.
    obs = [ObservationRecord.model_validate(live_b(n).model_dump()) for n in range(1, 9)]
    strict = [(a.status, [ep.state for ep in a.endpoints]) for a in assess_all(HOME, obs)]
    assisted = [(a.status, [ep.state for ep in a.endpoints]) for a in assess_all(ASSISTED, obs)]
    assert strict == assisted
