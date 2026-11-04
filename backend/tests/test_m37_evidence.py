"""M3.7: evidence levels, SAM recall fallback, operator declarations, single-socket contradictions, limits.

Regression for the live Home Entertainment inspection of 2026-11-04 ("Report B", insp_c3ff04e1…): eight photos, call
39 of 40, overall INSUFFICIENT_EVIDENCE. Its eight recorded live observations are replayed from
fixtures/live_home_report_b.json (Muse/SAM output copied verbatim; no photographs). Confirmed from that record:
  - SAM 'hdmi cable' segmented NOTHING in every photo it ran on, so the PS5 HDMI plug Muse saw clearly in photos 5-7
    was never grounded, and three photos were spent re-framing it;
  - photo 4 reports a blue plug in the PS5's LAN socket while photos 5-7 report that socket clearly EMPTY; the policy
    called the endpoint "confirmed (photo 4)" because shape-identified sockets were never cross-matched;
  - photo 8 shows the TV's HDMI panel on a device Muse could not identify with certainty.
Everything else is hand-built mocked model claims. No network, no paid calls.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fakes import FakeMeta, device, extraction, make_image, plan, sam_record, settings
from proofcam.agent import AgentState, InspectionAgent
from proofcam.evidence import GroundingLink, ObservationRecord, OperatorDeclaration
from proofcam.policy import assess_requirement, overall_assessment
from proofcam.report import build_report, render_markdown
from proofcam.spec import InspectionSpec
from proofcam.trace import Trace
from test_acceptance import cap, create, server
from test_multi_requirement import ccable, cport, rec
from test_persistence import replay_factory

ROOT = Path(__file__).resolve().parents[2]
HOME = InspectionSpec.load(ROOT / "data" / "specs" / "ps5_home_setup.json")
ASSISTED = InspectionSpec.load(ROOT / "data" / "specs" / "ps5_home_setup_assisted.json")
EXACT = InspectionSpec.load(ROOT / "data" / "specs" / "router_switch.json")
B = json.loads((Path(__file__).parent / "fixtures" / "live_home_report_b.json").read_text(encoding="utf-8"))
ETH, HDMI = "ethernet cable", "hdmi cable"
OBS, PLAN = "ObservationExtraction", "NextViewPlan"


def live_b(n: int) -> ObservationRecord:
    return ObservationRecord.model_validate(B[f"photo_{n}"])


def replay_agent(spec: InspectionSpec, **budget) -> InspectionAgent:
    s = settings(**budget)
    return InspectionAgent(spec, replay_factory(s, Trace()), s, plan_with_muse=False)


def feed(ag: InspectionAgent, *records: ObservationRecord):
    return [asyncio.run(ag.observe_recorded(r)) for r in records]


def a_of(assessments, rid):
    return next(a for a in assessments if a.requirement_id == rid)


def decl(kind, epoch=0, **kw) -> OperatorDeclaration:
    return OperatorDeclaration(id="od1", kind=kind, epoch=epoch, statement="test", created_at=0.0, **kw)


# ------------------------------------------------------------------------------------------- hand-built photos
def router_lan(seq, label="LAN 2", grounded=True):
    return rec(seq, extraction(devices=[device("D1", "router")],
                               ports=[cport("P1", "D1", label, "ethernet", color="blue")]),
               {"P1": ETH} if grounded else None)


def ps5_rear(seq, lan="cable_inserted", hdmi="cable_inserted", grounded=(ETH, HDMI)):
    ports = [cport("P1", "D1", None, "ethernet", occ=lan, color="blue" if lan == "cable_inserted" else None,
                   legible="no_label"),
             cport("P2", "D1", "HDMI", "hdmi", occ=hdmi, color="black" if hdmi == "cable_inserted" else None,
                   box=(200, 600, 260, 680))]
    links = {}
    if ETH in grounded and lan == "cable_inserted":
        links["P1"] = ETH
    if HDMI in grounded and hdmi == "cable_inserted":
        links["P2"] = HDMI
    return rec(seq, extraction(devices=[device("D1", "ps5")], ports=ports), links)


def tv_overview(seq):
    return rec(seq, extraction(devices=[device("D1", "tv", side="front", ports=False)]))


def tv_panel(seq, certainty="uncertain", label="HDMI 1", grounded=True, devices=None):
    devs = devices or [device("D1", "tv", certainty=certainty)]
    return rec(seq, extraction(devices=devs, ports=[cport("P1", "D1", label, "hdmi", color="black")]),
               {"P1": HDMI} if grounded else None)


def full_set():
    return [router_lan(1), ps5_rear(2), tv_overview(3), tv_panel(4)]


def assess_all(spec, obs, declarations=()):
    return [assess_requirement(spec, r, obs, True, list(declarations)) for r in spec.requirements]


# ======================================================================== 1. Muse sees HDMI, SAM misses the cable
def test_muse_only_hdmi_plug_is_a_labelled_candidate_never_support():
    a = a_of(assess_all(HOME, [live_b(5), live_b(6)]), "R2")
    ep = a.endpoints[0]
    assert a.status == "INSUFFICIENT_EVIDENCE" and ep.state == "unknown" and not ep.support
    assert sorted({x.seq for x in ep.candidates}) == [5, 6]  # recorded as observed, not corroborated
    assert all(x.grounding is not None and not x.grounding.corroborated for x in ep.candidates)
    assert ep.gap.code == "GROUNDING_MISSING"
    assert ep.gap.context["sam_segmented_nothing_in"] == [5, 6]
    assert "another camera angle may not change this" in ep.gap.missing_fact


# ======================================================== 2. SAM finds a cable at the plug, not the 'hdmi cable'
def _ps5_hdmi_agent(sam: dict[str, str], extra_ports=(), **budget):
    fm = FakeMeta()
    fm.sam.update(sam)
    ports = [cport("P2", "D1", "HDMI", "hdmi", color="black", box=(400, 400, 500, 500)), *extra_ports]
    fm.queue_chat(OBS, extraction(devices=[device("D1", "ps5")], ports=ports))
    fm.queue_chat(PLAN, plan("Go to the television's HDMI panel.", action="move_to_rear"))
    s = settings(**budget)
    ag = InspectionAgent(HOME, fm.client(s), s)
    step = asyncio.run(ag.observe(make_image("ps5.jpg")))
    concepts = [json.loads(r.content)["input"][0]["content"][0]["text"] for r in fm.requests
                if r.url.path.endswith("/responses")]
    return ag, step, concepts


def test_generic_cable_fallback_grounds_the_plug_when_the_hdmi_concept_finds_nothing():
    # 'hdmi cable' returns no object at all; the generic 'cable' mask covers the port (pixels 160-200 x 120-150).
    ag, step, concepts = _ps5_hdmi_agent({"cable": sam_record(0, (160, 120, 200, 150))})
    assert concepts.count("cable") == 1 and "hdmi cable" in concepts and ETH not in concepts  # no occupied RJ45
    link = ag.observations[0].port_links["P2|hdmi cable"]
    assert link.corroborated and link.concept == "cable" and link.note.startswith("fallback:")
    ep = a_of(step.assessments, "R2").endpoints[0]
    assert ep.state == "established" and ep.support[0].grounding.concept == "cable"
    assert any("generic 'cable' mask" in x and "Muse's reading" in x for x in a_of(step.assessments, "R2").assumptions)


def test_fallback_mask_reaching_a_neighbouring_port_of_another_connector_is_ambiguous():
    rj45 = cport("P1", "D1", None, "ethernet", color="blue", legible="no_label", box=(250, 400, 350, 500))
    ag, step, _ = _ps5_hdmi_agent({ETH: sam_record(0, (0, 0, 20, 20)),  # an Ethernet mask, far from both ports
                                   "cable": sam_record(0, (100, 120, 200, 150))}, extra_ports=[rj45])
    link = ag.observations[0].port_links["P2|hdmi cable"]
    assert not link.corroborated and "ambiguous" in link.note
    assert a_of(step.assessments, "R2").endpoints[0].state == "unknown"


def test_no_fallback_when_the_concept_found_a_cable_elsewhere_or_the_sam_cap_is_full():
    _, _, concepts = _ps5_hdmi_agent({HDMI: sam_record(0, (0, 0, 20, 20)), "cable": sam_record(0, (160, 120, 200, 150))})
    assert "cable" not in concepts  # SAM saw an HDMI cable, just not at this port: not a recall failure
    _, step, concepts = _ps5_hdmi_agent({"cable": sam_record(0, (160, 120, 200, 150))}, max_sam_calls_per_image=2)
    assert "cable" not in concepts and len(concepts) == 2  # never beyond the per-photo SAM cap
    assert a_of(step.assessments, "R2").endpoints[0].state == "unknown"


def test_fallback_grounding_alone_is_disclosed_as_a_spec_assumption_on_a_verified_verdict():
    obs = full_set()
    obs[1].port_links["P2|hdmi cable"] = GroundingLink(concept="cable", sam_object_id="0", overlap_px=900,
                                                       corroborated=True, note="fallback: test")
    a = a_of(assess_all(ASSISTED, obs, [decl("device_identity", seq=4, device_id="tv"),
                                        decl("cable_identity", requirement_id="R2")]), "R2")
    assert a.status == "VERIFIED" and a.assurance == "operator_assisted"
    assert any("generic 'cable' mask" in x for x in a.assumptions)


# =========================================================== 3. TV overview, then a close-up of its HDMI panel
def test_tv_overview_is_not_reused_for_a_later_uncertain_close_up():
    a = a_of(assess_all(ASSISTED, full_set()), "R2")
    tv = a.endpoints[1]
    assert tv.state == "unknown" and tv.gap.code == "DEVICE_UNCONFIRMED"
    assert tv.gap.context["unconfirmed_port_photos"] == [4] and tv.gap.context["declaration_permitted"] is True
    assert a_of(assess_all(HOME, full_set()), "R2").endpoints[1].gap.context["declaration_permitted"] is False


def test_operator_declared_device_identity_supports_only_that_photo_and_is_disclosed():
    decls = [decl("device_identity", seq=4, device_id="tv"), decl("cable_identity", requirement_id="R2")]
    a = a_of(assess_all(ASSISTED, full_set(), decls), "R2")
    tv = a.endpoints[1]
    assert tv.state == "established" and [x.seq for x in tv.support] == [4]
    assert tv.support[0].device_basis == "operator_declared"
    assert a.status == "VERIFIED" and a.identity_state == "declared_by_operator" and a.assurance == "operator_assisted"
    assert any("You confirmed that the device in photo 4 is the Samsung Television" in x
               for x in a.operator_declarations)
    assert any("one cable" in x for x in a.operator_declarations)


def test_agent_declare_validates_the_photo_and_never_calls_a_model():
    ag = replay_agent(ASSISTED)
    feed(ag, *full_set())
    n = len(ag.trace.model_calls())
    with pytest.raises(ValueError, match="already identified with certainty"):
        asyncio.run(ag.declare("device_identity", seq=3, device_id="tv"))
    with pytest.raises(ValueError, match="not a usable photo"):
        asyncio.run(ag.declare("device_identity", seq=9, device_id="tv"))
    d = asyncio.run(ag.declare("device_identity", seq=4, device_id="tv"))
    assert d.statement == "Photo 4 shows the Samsung Television." and d.epoch == 0
    assert asyncio.run(ag.declare("device_identity", seq=4, device_id="tv")) is d  # recorded once
    assert len(ag.declarations) == 1 and len(ag.trace.model_calls()) == n
    assert a_of(ag.assessments, "R2").endpoints[1].state == "established"
    # the guidance no longer asks for the TV's identity; the replacement comes from the templates (no model call)
    assert ag.requests[-1].gap_code != "DEVICE_UNCONFIRMED" and ag.requests[-1].planner == "deterministic_fallback"


# ==================================================================== 4. two similar TVs; swapped devices
def test_declaration_is_refused_for_ambiguous_or_differently_matched_devices():
    two_tvs = tv_panel(4, devices=[device("D1", "tv", certainty="uncertain"), device("D2", "tv", certainty="uncertain")])
    swapped = tv_panel(4, devices=[device("D1", "router", certainty="clear")])
    for photo, why in ((two_tvs, "more than one device"), (swapped, "no device")):
        ag = replay_agent(ASSISTED)
        feed(ag, router_lan(1), ps5_rear(2), tv_overview(3), photo)
        with pytest.raises(ValueError, match=why):
            asyncio.run(ag.declare("device_identity", seq=4, device_id="tv"))
        # and the policy ignores such a declaration even if one were injected
        a = a_of(assess_all(ASSISTED, [router_lan(1), ps5_rear(2), tv_overview(3), photo],
                            [decl("device_identity", seq=4, device_id="tv")]), "R2")
        assert a.endpoints[1].state == "unknown" and a.status == "INSUFFICIENT_EVIDENCE"


def test_strict_spec_ignores_and_refuses_device_declarations():
    a = a_of(assess_all(HOME, full_set(), [decl("device_identity", seq=4, device_id="tv")]), "R2")
    assert a.endpoints[1].state == "unknown"
    ag = replay_agent(HOME)
    feed(ag, *full_set())
    with pytest.raises(ValueError, match="does not permit"):
        asyncio.run(ag.declare("device_identity", seq=4, device_id="tv"))


def test_declared_photo_never_creates_a_violation_on_its_own():
    spec = InspectionSpec.model_validate({**json.loads(EXACT.model_dump_json()),
                                          "allow_device_identity_declarations": True})
    sw = rec(1, extraction(devices=[device("D1", "switch", certainty="uncertain")],
                           ports=[cport("P1", "D1", "3", "ethernet", occ="empty", color=None)]))
    a = assess_requirement(spec, spec.requirements[0], [sw], True, [decl("device_identity", seq=1, device_id="switch")])
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[1].state == "unknown"
    assert a.endpoints[1].conflicts and a.endpoints[1].conflicts[0].device_basis == "operator_declared"


# ============================================== 5-9. cable identity: unproven, traced, declared, refused, contradicted
def test_two_confirmed_ethernet_endpoints_without_continuity_stay_insufficient():
    a = a_of(assess_all(HOME, [router_lan(1), ps5_rear(2)]), "R1")
    assert [ep.state for ep in a.endpoints] == ["established", "established"]
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown" and a.assurance is None
    g = next(g for g in a.gaps if g.code == "CABLE_CONTINUITY")
    assert g.context["declaration_permitted"] is False


def test_directly_traced_ethernet_cable_is_verified_from_photos():
    trace = rec(3, extraction(devices=[device("D1", "router"), device("D2", "ps5")],
                              ports=[cport("P1", "D1", "LAN 2", "ethernet", color="blue"),
                                     cport("P2", "D2", None, "ethernet", color="blue", legible="no_label",
                                           box=(600, 400, 660, 480))],
                              cables=[ccable("C1", "blue", ["P1", "P2"], "ethernet")]), {"P1": ETH, "P2": ETH})
    a = a_of(assess_all(HOME, [trace]), "R1")
    assert a.status == "VERIFIED" and a.identity_state == "established" and not a.operator_declarations
    assert a.assurance == "spec_assumption"  # the PS5 LAN port is identified by socket shape (spec assumption)


def test_operator_declared_continuity_with_permission_is_verified_and_marked():
    a = a_of(assess_all(ASSISTED, [router_lan(1), ps5_rear(2)], [decl("cable_identity", requirement_id="R1")]), "R1")
    assert a.status == "VERIFIED" and a.identity_state == "declared_by_operator"
    assert a.assurance == "operator_assisted" and not a.identity_evidence
    assert "not traced in any photo" in a.explanation


def test_operator_declared_continuity_without_permission_is_ignored_and_refused():
    a = a_of(assess_all(HOME, [router_lan(1), ps5_rear(2)], [decl("cable_identity", requirement_id="R1")]), "R1")
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    ag = replay_agent(HOME)
    feed(ag, router_lan(1), ps5_rear(2))
    with pytest.raises(ValueError, match="does not permit"):
        asyncio.run(ag.declare("cable_identity", requirement_id="R1"))


def test_cable_declaration_needs_both_endpoints_and_observed_connector_families():
    ag = replay_agent(ASSISTED)
    feed(ag, router_lan(1))
    with pytest.raises(ValueError, match="both ends"):
        asyncio.run(ag.declare("cable_identity", requirement_id="R1"))
    unclear = rec(2, extraction(devices=[device("D1", "ps5")],
                                ports=[cport("P1", "D1", "LAN", "unclear", color="blue")]), {"P1": ETH})
    a = a_of(assess_all(ASSISTED, [router_lan(1), unclear], [decl("cable_identity", requirement_id="R1")]), "R1")
    assert a.status == "INSUFFICIENT_EVIDENCE"  # PS5 port supported by its label, but its family was never reported
    assert next(g for g in a.gaps if g.code == "CABLE_CONTINUITY").context["declaration_permitted"] is False


def test_cable_declaration_contradicted_by_a_visible_trace_needs_review():
    # Photo 3 traces the PS5's cable (fully, grounded at both ports) to the router's WAN socket.
    wan = rec(3, extraction(devices=[device("D1", "router"), device("D2", "ps5")],
                            ports=[cport("P1", "D1", "WAN", "ethernet", color="blue"),
                                   cport("P2", "D2", None, "ethernet", color="blue", legible="no_label",
                                         box=(600, 400, 660, 480))],
                            cables=[ccable("C1", "blue", ["P1", "P2"], "ethernet")]), {"P1": ETH, "P2": ETH})
    obs = [router_lan(1), ps5_rear(2), wan]
    a = a_of(assess_all(ASSISTED, obs, [decl("cable_identity", requirement_id="R1")]), "R1")
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    assert any(g.code == "CONTRADICTION" and "declaration" in g.missing_fact for g in a.gaps)
    assert a.contradictions and not a.operator_declarations
    ag = replay_agent(ASSISTED)
    feed(ag, *obs)
    asyncio.run(ag.declare("cable_identity", requirement_id="R1"))
    assert any(r["requirement_id"] == "R1" for r in ag.review_items())


# =========================================================================== 10. wrong-port violation preserved
def test_wrong_port_violation_is_visual_and_not_erased_by_a_later_ambiguous_photo():
    empty = rec(1, extraction(devices=[device("D1", "router")],
                              ports=[cport("P1", "D1", None, "ethernet", color="blue", legible="no_label"),
                                     cport("P2", "D1", "LAN 1", "ethernet", occ="empty", color=None)]))
    ambiguous = rec(2, extraction(devices=[device("D1", "router"), device("D2", "router")],
                                  ports=[cport("P1", "D1", "LAN 1", "ethernet", color="blue")]), {"P1": "blue ethernet cable"})
    for obs in ([empty], [empty, ambiguous]):
        a = assess_requirement(EXACT, EXACT.requirements[0], obs)
        assert a.status == "VIOLATED" and a.assurance == "visual"
        assert a.endpoints[0].state == "violated"


# ===================================================== single-socket (PS5) cross-photo contradiction (Report B)
def test_report_b_ps5_lan_socket_occupied_in_photo_4_and_empty_in_5_is_a_contradiction():
    a = a_of(assess_all(HOME, [live_b(4), live_b(5)]), "R1")
    ps5 = a.endpoints[1]
    assert ps5.state == "contradicted" and a.status == "INSUFFICIENT_EVIDENCE"
    assert any("only ethernet socket" in x.claim for x in ps5.conflicts)
    # Without the spec's single-socket assertion, shape-identified sockets are not cross-matched (unchanged rule).
    d = json.loads(HOME.model_dump_json())
    d["requirements"][0]["endpoints"][1]["selector"]["only_socket"] = False
    legacy = InspectionSpec.model_validate(d)
    assert a_of(assess_all(legacy, [live_b(4), live_b(5)]), "R1").endpoints[1].state == "established"


def test_single_socket_seen_empty_is_never_a_violation_by_itself():
    a = a_of(assess_all(HOME, [ps5_rear(1, lan="empty")]), "R1")
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[1].state == "unknown"
    assert "only one ethernet socket" in a.endpoints[1].gap.missing_fact


# ============================== 11-13. guidance: view fulfilled without evidence; retry ceiling; photo limit
def test_report_b_replay_guidance_moves_on_after_one_failed_grounding_view():
    ag = replay_agent(HOME)
    steps = feed(ag, *[live_b(n) for n in range(1, 9)])
    # photo 5 answered nv for INSERTION_UNCLEAR; photo 6 the one GROUNDING_MISSING retry; then the TV is requested
    assert steps[4].next_view.gap_code == "GROUNDING_MISSING"
    assert "R2:GROUNDING_MISSING:0" in ag.exhausted and "camera angle is unlikely to help" in ag.exhausted[
        "R2:GROUNDING_MISSING:0"]
    assert steps[5].next_view.gap_key == "R2:PORTS_NOT_VISIBLE:1"
    # photo 8: the requested TV panel WAS captured, yet no evidence was accepted (identity not confirmed)
    assert steps[7].view_check.status == "captured" and steps[7].view_check.identity_confirmed is False
    assert not any(x.seq == 8 for a in steps[7].assessments for ep in a.endpoints for x in ep.support)
    assert steps[7].next_view.gap_code == "DEVICE_UNCONFIRMED"
    # 12 photos are now allowed for this two-connection spec: no photo-limit stop at 8
    assert ag.max_observations == 12 and steps[7].stop_reason is None
    assert overall_assessment(ag.assessments).status == "INSUFFICIENT_EVIDENCE"


def test_photo_limit_still_stops_the_inspection():
    d = {**json.loads(HOME.model_dump_json()), "max_photos": 2}
    ag = replay_agent(InspectionSpec.model_validate(d))
    steps = feed(ag, live_b(1), live_b(2))
    assert steps[-1].stop_reason == "observation_budget_exhausted" and steps[-1].next_view is None


# ================================== 14-16. call budget config, restart persistence, report provenance (HTTP)
TV_PANEL_OBS = extraction(devices=[device("D1", "tv", certainty="uncertain")],
                          ports=[cport("P1", "D1", "HDMI 1", "hdmi", color="black")])


def test_declarations_over_http_persist_across_restart_cost_nothing_and_appear_in_the_report(tmp_path):
    fm = FakeMeta()
    fm.queue_chat(OBS, TV_PANEL_OBS)
    fm.queue_chat(PLAN, plan("Show the TV's logo and its HDMI panel together.", action="step_back_wide_view"))

    async def go():
        async with server(tmp_path, fm, inspection_call_limit=60) as (c, store, _a):
            strict = await create(c, "ps5_home_setup")
            iid = await create(c, "ps5_home_setup_assisted")
            r = await cap(c, iid, "tv.jpg")
            assert r.status_code == 200, r.text
            assert r.json()["usage"]["model_call_limit"] == 60 and r.json()["usage"]["max_photos"] == 12
            sent = len(fm.requests)
            bad = await c.post(f"/api/inspections/{iid}/events", json={"type": "device_identity", "seq": 1,
                                                                       "device_id": "tv"})
            assert bad.status_code == 422  # not confirmed
            refused = await c.post(f"/api/inspections/{strict}/events",
                                   json={"type": "cable_identity", "requirement_id": "R1", "confirm": True})
            assert refused.status_code == 422 and refused.json()["error"] == "declaration_refused"
            ok = await c.post(f"/api/inspections/{iid}/events",
                              json={"type": "device_identity", "seq": 1, "device_id": "tv", "confirm": True})
            assert ok.status_code == 200, ok.text
            assert [d["statement"] for d in ok.json()["declarations"]] == ["Photo 1 shows the Samsung Television."]
            assert len(fm.requests) == sent  # a declaration never calls a model
        async with server(tmp_path, fm) as (c, store, _a):  # restart, with the default per-inspection limit
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert len(st["declarations"]) == 1 and st["usage"]["model_call_limit"] == 60  # kept from creation
            assert (await c.get(f"/api/inspections/{strict}")).json()["usage"]["model_call_limit"] == 60
            new = await create(c, "ps5_home_setup")
            assert (await c.get(f"/api/inspections/{new}")).json()["usage"]["model_call_limit"] == 40
            rep = (await c.get(f"/api/inspections/{iid}/report")).json()
            assert rep["operator_declarations"][0]["kind"] == "device_identity"
            assert rep["models_called"] and all(m["source"] == "mock" for m in rep["models_called"])
            assert "synthetic" in rep["provenance_note"] and rep["photo_budget"] == {"photos_used": 1,
                                                                                    "max_photos": 12}
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert "Statements by the person inspecting" in md and "Photo 1 shows the Samsung Television." in md
            assert "Models called:" in md
            # append-only: the stored declaration cannot be dropped by a later snapshot
            b = store.load_restore_bundle(iid)
            assert b.state.declarations[0].kind == "device_identity"

    asyncio.run(go())


def test_report_states_assurance_for_an_operator_assisted_verdict():
    ag = replay_agent(ASSISTED)
    feed(ag, router_lan(1), ps5_rear(2))
    asyncio.run(ag.declare("cable_identity", requirement_id="R1"))
    r1 = a_of(ag.assessments, "R1")
    assert r1.status == "VERIFIED" and r1.assurance == "operator_assisted"
    md = render_markdown(ag, {}, ag.trace.summary())
    assert "statements by the person inspecting" in md and "Operator declaration relied on" in md
    assert "(statement by the person inspecting; not traced in any photo)" in md
    rep = build_report(ag, "insp_test", {})
    assert rep["requirements"][0]["assurance"] == "operator_assisted"


# ================================================= 17-18. compatibility of stored state and legacy specs
def test_snapshots_from_before_m37_load_without_declarations():
    ag = replay_agent(EXACT)
    raw = json.loads(ag.snapshot().model_dump_json())
    raw.pop("declarations")
    assert AgentState.model_validate(raw).declarations == []
    assert not EXACT.allow_device_identity_declarations
    assert all(r.cable_identity == "require_trace" for r in EXACT.requirements)


def test_flexible_home_spec_still_verifies_from_traced_photos_without_any_declaration():
    hdmi_trace = rec(5, extraction(devices=[device("D1", "ps5"), device("D2", "tv")],
                                   ports=[cport("P1", "D1", "HDMI", "hdmi", color="black"),
                                          cport("P2", "D2", "HDMI 2", "hdmi", color="black", box=(600, 400, 660, 480))],
                                   cables=[ccable("C1", "black", ["P1", "P2"], "hdmi")]), {"P1": HDMI, "P2": HDMI})
    eth_trace = rec(6, extraction(devices=[device("D1", "router"), device("D2", "ps5")],
                                  ports=[cport("P1", "D1", "LAN 3", "ethernet", color="blue"),
                                         cport("P2", "D2", None, "ethernet", color="blue", legible="no_label",
                                               box=(600, 400, 660, 480))],
                                  cables=[ccable("C1", "blue", ["P1", "P2"], "ethernet")]), {"P1": ETH, "P2": ETH})
    for spec in (HOME, ASSISTED):
        out = assess_all(spec, [hdmi_trace, eth_trace])
        assert [a.status for a in out] == ["VERIFIED", "VERIFIED"]
        assert all(a.identity_state == "established" and not a.operator_declarations for a in out)
        assert overall_assessment(out).status == "VERIFIED"
