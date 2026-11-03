"""M2.1 verdict correctness: colour ambiguity, conflicting cable traces, ambiguous device identity.

Every case starting "probe" reproduces a defect confirmed in the M2.0 audit (offline, synthetic claims) that the
M1 policy got wrong. All model output here is hand-built (synthetic) or mocked; no real inference.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fakes import cable, device, extraction, plan, port, settings
from proofcam.agent import InspectionAgent
from proofcam.meta_client import MetaClient
from proofcam.policy import assess_requirement, compare_color, select_gap
from proofcam.spec import InspectionSpec
from proofcam.trace import Trace
from test_acceptance import cap, check_invariants, create, server
from test_agent import OBS, PLAN, base_fake
from test_persistence import replay_factory, restart
from test_policy import both_ends_one_image, rec

SPEC = InspectionSpec.load(Path(__file__).resolve().parents[2] / "data" / "specs" / "router_switch.json")


def spec_with(**req) -> InspectionSpec:
    d = json.loads(SPEC.model_dump_json())
    d["requirements"][0].update(req)
    return InspectionSpec.model_validate(d)


def assess(spec: InspectionSpec, *recs, grounding: bool = True):
    return assess_requirement(spec, spec.requirements[0], list(recs), grounding)


def router_port(color, cables=(), grounded=("P1",), label="LAN 1", occ="cable_inserted", seq=1, **kw):
    return rec(seq, extraction(devices=[device("D1", "router")],
                               ports=[port("P1", "D1", label, occ=occ, color=color, **kw)], cables=list(cables)),
               grounded_ports=list(grounded))


def trace_photo(seq, router_label="1", switch_label="3", grounded=("P1", "P2"), path="fully_traced",
                color="blue", plug="blue", router_legible="legible", switch_legible="legible"):
    return rec(seq, extraction(
        devices=[device("D1", "router"), device("D2", "switch")],
        ports=[port("P1", "D1", router_label, group="LAN", color=plug, legible=router_legible),
               port("P2", "D2", switch_label, color=plug, legible=switch_legible)],
        cables=[cable("C1", color, ["P1", "P2"], path=path)]), grounded_ports=list(grounded))


# ============================================================================ 1. colour: three-way comparison

@pytest.mark.parametrize("text,want,expected", [
    ("blue", "blue", "match"), ("navy blue", "blue", "match"), ("Light Blue", "blue", "match"),
    ("transparent blue", "blue", "match"),
    ("yellow", "blue", "mismatch"), ("red", "blue", "mismatch"), ("white", "blue", "mismatch"),
    ("black", "blue", "mismatch"), ("orange", "black", "mismatch"),
    ("dark gray", "black", "uncertain"), ("charcoal", "black", "uncertain"), ("off-white", "beige", "uncertain"),
    ("cream", "white", "uncertain"), ("purple", "blue", "uncertain"), ("teal", "blue", "uncertain"),
    ("cyan", "blue", "uncertain"), ("translucent white", "blue", "uncertain"), ("clear", "blue", "uncertain"),
    ("blue/white", "blue", "uncertain"), (None, "blue", "uncertain"), ("", "blue", "uncertain"),
    ("blue", None, "uncertain"),
])
def test_compare_color(text, want, expected):
    assert compare_color(text, want) == expected


def test_probe_near_colour_is_not_a_violation():
    blk = spec_with(cable_color="black")
    a = assess(blk, router_port("dark gray"))
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "unknown"
    g = a.endpoints[0].gap
    assert g.code == "INSERTION_UNCLEAR" and g.context["colour_ambiguous"] and "dark gray" in g.context["observed"][0]


def test_probe_off_white_plug_does_not_violate_a_beige_requirement():
    beige = spec_with(cable_color="beige")
    assert assess(beige, router_port("off-white")).status == "INSUFFICIENT_EVIDENCE"


def test_probe_translucent_plug_takes_the_grounded_cable_colour():
    a = assess(SPEC, router_port("translucent white", cables=[cable("C1", "blue", ["P1"])]))
    ep = a.endpoints[0]
    assert a.status == "INSUFFICIENT_EVIDENCE"  # the switch is not in this photo
    assert ep.state == "established" and "visibly belongs" in ep.support[0].claim


def test_cable_colour_association_must_be_sam_grounded_even_in_ablation():
    o = router_port("translucent white", cables=[cable("C1", "blue", ["P1"])], grounded=())
    for grounding in (True, False):
        ep = assess(SPEC, o, grounding=grounding).endpoints[0]
        assert ep.state == "unknown" and ep.gap.code == "GROUNDING_MISSING", grounding
    # a plug whose OWN colour matches keeps the old ablation behaviour
    assert assess(SPEC, router_port("blue", grounded=()), grounding=False).endpoints[0].state == "established"


def test_plug_colour_disagreeing_with_its_own_cable_is_uncertain_not_a_violation():
    a = assess(SPEC, router_port("white", cables=[cable("C1", "blue", ["P1"])]))
    ep = a.endpoints[0]
    assert a.status == "INSUFFICIENT_EVIDENCE" and ep.state == "unknown" and not ep.conflicts
    assert "disagrees with the cable" in ep.gap.context["observed"][0]


@pytest.mark.parametrize("plug,cables", [
    ("yellow", []),
    ("yellow", [cable("C1", "yellow", ["P1"])]),
    ("white", [cable("C1", "black", ["P1"])]),
])
def test_clearly_different_colour_still_violates(plug, cables):
    a = assess(SPEC, router_port(plug, cables=cables))
    assert a.status == "VIOLATED" and "not blue" in a.explanation


def test_empty_target_port_still_violates():
    assert assess(SPEC, router_port(None, occ="empty")).status == "VIOLATED"


def test_unique_spec_wrong_port_rule_needs_the_plugs_own_colour():
    uniq = spec_with(cable_identity="unique_in_installation")
    own = rec(1, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 2", color="blue")]))
    assert assess(uniq, own).status == "VIOLATED"  # unchanged M1 behaviour
    borrowed = rec(1, extraction(devices=[device("D1", "router")],
                                 ports=[port("P1", "D1", "LAN 2", color="transparent")],
                                 cables=[cable("C1", "blue", ["P1"])]))
    assert assess(uniq, borrowed).status == "INSUFFICIENT_EVIDENCE"  # colour borrowed from a cable: no violation


def test_correct_installations_still_verify():
    assert assess(SPEC, both_ends_one_image(grounded_ports=["P1", "P2"])).status == "VERIFIED"
    clear_plugs = trace_photo(1, plug="transparent")
    a = assess(SPEC, clear_plugs)
    assert a.status == "VERIFIED" and a.identity_state == "established"


def test_traced_cable_with_ambiguous_plug_colour_is_not_identity():
    a = assess(SPEC, trace_photo(1, plug="purple"))
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"


# ============================================================================ 2. conflicting cable traces

def test_probe_conflicting_trace_is_a_visible_contradiction_not_verified():
    good, other = trace_photo(1), trace_photo(2, switch_label="4")
    for order in ([good, other], [other, good]):
        a = assess(SPEC, *order)
        assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
        assert len(a.contradictions) == 1 and a.contradictions[0].startswith("cable identity")
        assert "img_1" in a.contradictions[0] and "img_2" in a.contradictions[0]
        g = next(g for g in a.gaps if g.code == "CONTRADICTION")
        assert g.endpoint_index is None and g.context["images"] == ["img_1", "img_2"]
        assert select_gap([a], set()).code == "CONTRADICTION"


def test_conflict_detected_from_either_endpoint():
    a = assess(SPEC, trace_photo(1), trace_photo(2, router_label="2"))  # switch 3's cable traced to router LAN 2
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.contradictions


@pytest.mark.parametrize("why,kw", [
    ("other port not SAM-grounded", {"grounded": ("P1",)}),
    ("trace not continuous", {"path": "partially_visible"}),
    ("other label not legible", {"switch_legible": "illegible"}),
    # a black plug in LAN 1 would be a direct endpoint conflict; a see-through plug on a black cable is not
    ("different cable colour", {"color": "black", "plug": "transparent"}),
    ("ambiguous cable colour", {"color": "purple", "plug": "purple"}),
])
def test_unqualified_traces_do_not_create_conflicts(why, kw):
    a = assess(SPEC, trace_photo(1), trace_photo(2, switch_label="4", **kw))
    assert a.status == "VERIFIED" and not a.contradictions, why


def test_similar_cable_between_other_ports_is_not_joined():
    # A blue cable LAN 2 -> switch 4 in another photo says nothing about the cable in LAN 1.
    a = assess(SPEC, trace_photo(1), trace_photo(2, router_label="2", switch_label="4"))
    assert a.status == "VERIFIED" and not a.contradictions


def test_conflicting_trace_without_a_positive_trace_is_reported_not_counted():
    router_close = router_port("blue", seq=1)
    switch_close = rec(2, extraction(devices=[device("D1", "switch")], ports=[port("P1", "D1", "3")]),
                       grounded_ports=["P1"])
    a = assess(SPEC, router_close, switch_close, trace_photo(3, switch_label="4"))
    assert [ep.state for ep in a.endpoints] == ["established", "established"]
    assert a.status == "INSUFFICIENT_EVIDENCE" and not a.contradictions
    g = next(g for g in a.gaps if g.code == "CABLE_CONTINUITY")
    assert any("conflicting trace" in n for n in g.context["near_misses"])


def test_unique_spec_with_conflicting_trace_is_never_verified():
    uniq = spec_with(cable_identity="unique_in_installation")
    a = assess(uniq, both_ends_one_image(grounded_ports=["P1", "P2"]), trace_photo(2, switch_label="4"))
    assert a.status != "VERIFIED"


def test_conflicting_photo_from_a_superseded_configuration_no_longer_counts():
    agent = InspectionAgent(SPEC, replay_factory(settings(), Trace()), settings(), plan_with_muse=False)
    asyncio.run(agent.observe_recorded(trace_photo(0, switch_label="4")))
    assert agent.assessments[0].status == "INSUFFICIENT_EVIDENCE"
    agent.mark_installation_changed("moved the cable to switch port 3")
    step = asyncio.run(agent.observe_recorded(trace_photo(0).model_copy(update={"image_id": "img_b"})))
    assert step.assessments[0].status == "VERIFIED" and not step.assessments[0].contradictions


def test_contradiction_survives_snapshot_and_restore():
    agent = InspectionAgent(SPEC, replay_factory(settings(), Trace()), settings(), plan_with_muse=False)
    asyncio.run(agent.observe_recorded(trace_photo(0)))
    assert agent.done  # VERIFIED from the first photo
    agent = InspectionAgent(SPEC, replay_factory(settings(), Trace()), settings(), plan_with_muse=False)
    asyncio.run(agent.observe_recorded(trace_photo(0, switch_label="4")))
    asyncio.run(agent.observe_recorded(trace_photo(0).model_copy(update={"image_id": "img_b"})))
    before = agent.assessments[0]
    assert before.contradictions and before.status == "INSUFFICIENT_EVIDENCE"
    back = restart(agent, replay_factory)
    assert back.assessments == agent.assessments and back.policy_drift() == []


# ============================================================================ 3. ambiguous device identity

def twin_router_photo(seq=1, target_occ="cable_inserted", second_certainty="clear"):
    return rec(seq, extraction(
        devices=[device("D1", "router"), device("D3", "router", certainty=second_certainty), device("D2", "switch")],
        ports=[port("P1", "D3", "1", group="LAN", occ=target_occ, color="blue" if target_occ != "empty" else None),
               port("P2", "D2", "3")],
        cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")] if target_occ != "empty" else []),
        grounded_ports=["P1", "P2"])


@pytest.mark.parametrize("second", ["clear", "uncertain"])
def test_probe_two_devices_claiming_one_spec_id_are_not_used(second):
    a = assess(SPEC, twin_router_photo(second_certainty=second))
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    ep = a.endpoints[0]
    assert ep.state == "unknown" and ep.gap.code == "DEVICE_NOT_SEEN"
    assert ep.gap.context["ambiguous_photos"] == [1] and "ambiguous" in ep.gap.missing_fact
    assert a.endpoints[1].state == "established"  # the switch in the same photo is unaffected


def test_ambiguous_photo_cannot_establish_a_violation():
    a = assess(SPEC, twin_router_photo(target_occ="empty"))
    assert a.status == "INSUFFICIENT_EVIDENCE"


def test_unambiguous_photo_still_verifies_and_the_ignored_photo_is_named():
    a = assess(SPEC, twin_router_photo(seq=1), both_ends_one_image(seq=2, grounded_ports=["P1", "P2"]))
    assert a.status == "VERIFIED"
    assert "Photo 1 not used for the Router" in a.explanation
    assert {s.seq for s in a.endpoints[0].support} == {2}  # router: only the unambiguous photo
    assert {s.seq for s in a.endpoints[1].support} == {1, 2}  # switch: unambiguous in both photos


def test_single_device_behaviour_unchanged():
    a = assess(SPEC, both_ends_one_image(grounded_ports=["P1", "P2"]))
    assert a.status == "VERIFIED" and "not used" not in a.explanation


# ============================================================================ 4. service, API, report, drift

R, S = (50, 100, 450, 600), (550, 100, 950, 600)
REAR = dict(devices=[device("D1", "router", box=R), device("D2", "switch", box=S)])


def rear(switch_label: str) -> dict:
    return extraction(**REAR, ports=[port("P1", "D1", "1", group="LAN", box=(200, 400, 260, 480)),
                                     port("P2", "D2", switch_label, box=(600, 400, 660, 480))],
                      cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")])


def test_conflicting_traces_over_http_report_and_restart(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, rear("4"), rear("3"))
    fm.queue_chat(PLAN, plan(), plan())

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            r1 = await cap(c, iid, "to_port_4.jpg")
            assert r1.json()["assessments"][0]["status"] == "INSUFFICIENT_EVIDENCE"
            r2 = await cap(c, iid, "to_port_3.jpg")
            a = r2.json()["assessments"][0]
            assert a["status"] == "INSUFFICIENT_EVIDENCE" and a["contradictions"]
            # M2.2: no camera request for a contradiction; the inspection stops for review
            assert r2.json()["next_view"] is None and r2.json()["stop_reason"] == "contradiction_requires_review"
        async with server(tmp_path, fm) as (c, store, _a):
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["assessments"][0]["contradictions"] and st["policy_drift"] == []
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert "Unresolved contradiction: cable identity" in md
            assert "not independent proof" in md  # cross-photo device identity is disclosed
            report = (await c.get(f"/api/inspections/{iid}/report")).json()
            assert "matching them to the spec description" in report["device_identity_note"]
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())


def test_old_verdicts_are_flagged_not_rewritten(tmp_path):
    """A clear plug Muse called 'translucent white' with the blue cable attached: M1 stored VIOLATED (probe P1b).
    The M2.1 policy no longer reproduces that verdict; the stored one is shown unchanged and flagged."""
    fm = base_fake()
    fm.queue_chat(OBS, extraction(devices=[device("D1", "router", box=R)],
                                  ports=[port("P1", "D1", "1", group="LAN", color="translucent white",
                                              box=(200, 400, 260, 480))],
                                  cables=[cable("C1", "blue", ["P1"])]))
    fm.queue_chat(PLAN, plan())

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            r = await cap(c, iid, "clear_plug.jpg")
            assert r.json()["assessments"][0]["status"] == "INSUFFICIENT_EVIDENCE"  # M2.1 policy
            assert r.json()["assessments"][0]["endpoints"][0]["state"] == "established"
            # Rewrite the stored record as the M1 engine produced it.
            ctl = json.loads(store._conn.execute("SELECT control_json FROM inspections WHERE id = ?",
                                                 (iid,)).fetchone()[0])
            ctl["assessments"][0]["status"] = "VIOLATED"
            store._conn.execute("UPDATE inspections SET control_json = ?, engine_version = ? WHERE id = ?",
                                (json.dumps(ctl), "0.0.1+m1engine", iid))
        async with server(tmp_path, fm) as (c, store, _a):
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["assessments"][0]["status"] == "VIOLATED"  # stored verdict shown as stored
            assert st["policy_drift"] == [SPEC.requirements[0].id] and st["engine_changed"] is True
            report = (await c.get(f"/api/inspections/{iid}/report")).json()
            assert report["requirements"][0]["status"] == "VIOLATED" and report["policy_drift"]
            assert report["engine_version"]["recorded"] == "0.0.1+m1engine"

    asyncio.run(go())
