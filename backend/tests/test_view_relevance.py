"""View relevance (A) vs evidence acceptance (B) vs requirement verification (C).

Regression for the live Home Entertainment inspection of 2026-11-04: the router's rear panel was photographed as
requested (LAN 1-4 legible and empty, a blue plug in a separate unlabelled RJ45 socket), yet the app said the photo
"did not show what request nv1 asked for". Root cause: the request matcher required a CERTAIN device identification,
which is an evidence-acceptance rule, not a view-relevance rule; and the policy then kept reporting "ports have not
been visible", so the planner asked for the same view again.

Photos 1 and 3 of that inspection are replayed from the recorded live Muse/SAM output
(fixtures/live_home_router_rear.json, copied verbatim; the photographs are not included). Everything else is
hand-built mocked model claims. No network, no paid calls.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from fakes import FakeMeta, device, extraction, make_image, plan, settings
from proofcam.agent import InspectionAgent
from proofcam.evidence import ObservationRecord
from proofcam.policy import assess_requirement
from proofcam.prompts import PLAN_SYSTEM
from proofcam.spec import InspectionSpec
from proofcam.trace import Trace
from test_flexible_requirements import ETH, eth_photo, variant
from test_multi_requirement import cport, rec
from test_persistence import replay_factory

ROOT = Path(__file__).resolve().parents[2]
HOME = InspectionSpec.load(ROOT / "data" / "specs" / "ps5_home_setup.json")
EXACT = InspectionSpec.load(ROOT / "data" / "specs" / "router_switch.json")
LIVE = json.loads((Path(__file__).parent / "fixtures" / "live_home_router_rear.json").read_text(encoding="utf-8"))
ROUTER_BOX = (0, 192, 1000, 815)


def live(n: int, **device_changes) -> ObservationRecord:
    """Recorded live observation of photo n; device_changes edits the router claim (to build controlled variants)."""
    d = copy.deepcopy(LIVE[f"photo_{n}"])
    for dev in d["extraction"]["devices"]:
        if dev["spec_device_id"] == "router" or dev["ref"] == "D1":
            dev.update(device_changes)
    if device_changes:
        d["image_id"] = d["image_id"] + "_variant"
    return ObservationRecord.model_validate(d)


def agent(spec: InspectionSpec = HOME, client=None, **budget) -> InspectionAgent:
    s = settings(**budget)
    return InspectionAgent(spec, client or replay_factory(s, Trace()), s, plan_with_muse=client is not None)


def feed(ag: InspectionAgent, *records: ObservationRecord, image=None):
    return [asyncio.run(ag.observe_recorded(r, image=image)) for r in records]


def accepted_from(step) -> int:
    """Policy-accepted evidence items from this photo (support or cable identity), as the app counts them."""
    return sum(len([x for x in a.identity_evidence if x.seq == step.seq])
               + sum(len([x for x in ep.support if x.seq == step.seq]) for ep in a.endpoints)
               for a in step.assessments)


def r1(step):
    return next(a for a in step.assessments if a.requirement_id == "R1")


def router_rear(*ports, certainty="clear") -> dict:
    return extraction(devices=[device("D1", "router", box=ROUTER_BOX, certainty=certainty)], ports=list(ports))


def lan(ref, n, occ="empty", color=None, x=322):
    return cport(ref, "D1", str(n), "ethernet", group="LAN", occ=occ, color=color, box=(x, 561, x + 100, 715))


LAN_EMPTY = [lan(f"P{n + 2}", n, x=322 + 105 * (n - 1)) for n in range(1, 5)]


def start_at_router(ag: InspectionAgent):
    """Live photo 1 (front overview of router, console and TV): the first request is the router's ports."""
    (s1,) = feed(ag, live(1))
    assert s1.view_check is None and s1.next_view.gap_key == "R1:PORTS_NOT_VISIBLE:0"
    return s1


# ============================================================ the live failure, replayed from the recorded output

def test_live_rear_panel_is_the_requested_view_even_with_zero_accepted_evidence():
    ag = agent()
    s1 = start_at_router(ag)
    (s3,) = feed(ag, live(3))
    c = s3.view_check
    # A. view relevance: captured, and it counts as a genuine attempt
    assert c.request_id == s1.next_view.id and c.status == "captured" and c.counted_as_attempt
    assert c.shown == ["the Wi-Fi Router", "the Wi-Fi Router's connection ports"] and c.missing == []
    assert c.identity_confirmed is False and c.unconfirmed_devices == ["Wi-Fi Router"]
    # B. evidence acceptance: none (the router was only identified with uncertainty in this photo)
    assert accepted_from(s3) == 0
    # C. verification: unchanged, honest
    assert all(a.status == "INSUFFICIENT_EVIDENCE" for a in s3.assessments)
    text = " ".join(s3.notes)
    assert "did not show" not in text and "no attempt was counted" not in text
    assert "showed the view requested in nv1" in text and "not identified with certainty" in text


def test_live_rear_panel_turns_the_gap_into_an_identity_gap_not_the_same_request_again():
    ag = agent()
    start_at_router(ag)
    (s3,) = feed(ag, live(3))
    g = r1(s3).endpoints[0].gap
    # (the recorded photo 3 is this replay's photo 2: the off-target photo 2 is not replayed)
    assert g.code == "DEVICE_UNCONFIRMED" and g.context["unconfirmed_port_photos"] == [2]
    assert "Ports were photographed (photo 2)" in g.missing_fact
    assert "have not been visible" not in g.missing_fact  # the false statement that caused the repeat request
    nv = s3.next_view
    assert nv.gap_code == "DEVICE_UNCONFIRMED" and nv.id != "nv1"
    assert "identifying features" in nv.instruction and "connection ports" in nv.instruction


def test_live_rear_panel_with_a_confirmed_router_asks_about_the_occupied_port():
    ag = agent()
    start_at_router(ag)
    (s3,) = feed(ag, live(3, identification_certainty="clear"))
    assert s3.view_check.status == "captured" and s3.view_check.identity_confirmed is True
    a = r1(s3)
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "unknown"
    g = a.endpoints[0].gap
    # The blue plug is in a socket with no readable label: its identity is the open question; LAN 1-4 are empty.
    assert g.code == "LABEL_ILLEGIBLE" and g.context["label_hidden_by_plug"]
    assert g.context["permitted_ports_seen_empty"] == ["LAN 1", "LAN 2", "LAN 3", "LAN 4"]
    assert "does not show where the cable is" in g.missing_fact
    nv = s3.next_view
    assert nv.gap_code == "LABEL_ILLEGIBLE" and "close-up of that occupied port" in nv.instruction
    # never presumes the socket's role, never asks to move the cable
    for t in (nv.instruction, nv.rationale, g.missing_fact):
        assert "WAN" not in t and "must be" not in t and "unplug" not in t.lower()


# ============================================================ the 12 requested scenarios

def test_1_rear_view_with_an_allowed_lan_connection():
    ag = agent()
    start_at_router(ag)
    o = rec(2, router_rear(*LAN_EMPTY[:1], lan("P9", 2, occ="cable_inserted", color="blue", x=430), *LAN_EMPTY[2:]),
            {"P9": ETH})
    (s,) = feed(ag, o)
    assert s.view_check.status == "captured" and accepted_from(s) == 1
    a = r1(s)
    assert a.endpoints[0].state == "established" and a.endpoints[0].support[0].port_basis == "direct_label"
    assert a.status == "INSUFFICIENT_EVIDENCE"  # the console end and the cable trace are still unproven


@pytest.mark.parametrize("label", ["WAN", "Internet"])
def test_2_rear_view_with_a_plug_in_a_port_that_is_not_permitted(label):
    ag = agent()
    start_at_router(ag)
    wrong = cport("P1", "D1", label, "ethernet", color="blue", box=(199, 565, 335, 728))
    (s,) = feed(ag, rec(2, router_rear(wrong, *LAN_EMPTY), {"P1": ETH}))
    assert s.view_check.status == "captured" and accepted_from(s) == 0
    a = r1(s)
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "unknown"
    g = a.endpoints[0].gap
    assert g.code == "PORT_NOT_FOUND" and g.context["plugs_in_ports_not_permitted"] == [f"photo 2: '{label}'"]
    assert "does not satisfy this requirement" in g.missing_fact
    assert "another permitted port may hold it" in g.missing_fact  # four empty LAN ports prove nothing off-frame


def test_2b_wrong_port_is_violated_only_under_the_existing_unique_cable_criterion():
    spec = variant(HOME, "R1", cable_color="blue", cable_identity="unique_in_installation")
    wrong = cport("P1", "D1", "WAN", "ethernet", color="blue")
    a = assess_requirement(spec, spec.requirements[0], [rec(1, router_rear(wrong, *LAN_EMPTY))])
    assert a.status == "VIOLATED" and a.endpoints[0].state == "violated"


def test_3_uncertain_port_identity_never_verifies_and_never_violates():
    o = rec(1, router_rear(cport("P1", "D1", None, "ethernet", color="blue", legible="no_label"), *LAN_EMPTY),
            {"P1": ETH})
    obs = [o, rec(2, eth_photo(router_port=cport("P1", "D1", None, "ethernet", color="grey", legible="illegible")),
                  {"P1": ETH, "P2": ETH})]
    for k in (1, 2):
        a = assess_requirement(HOME, HOME.requirements[0], obs[:k])
        assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "unknown"
        assert a.endpoints[0].gap.code == "LABEL_ILLEGIBLE"


def test_4_rear_view_with_lan_ports_but_no_cables():
    ag = agent()
    start_at_router(ag)
    (s,) = feed(ag, rec(2, router_rear(*LAN_EMPTY)))
    assert s.view_check.status == "captured" and s.view_check.counted_as_attempt and accepted_from(s) == 0
    a = r1(s)
    assert a.status == "INSUFFICIENT_EVIDENCE"  # empty permitted ports are not a violation
    assert a.endpoints[0].gap.code == "PORT_NOT_FOUND"
    assert "4 empty" in a.endpoints[0].gap.missing_fact


def test_5_router_top_view_without_rear_ports_is_partial():
    ag = agent()
    start_at_router(ag)
    (s,) = feed(ag, rec(2, extraction(devices=[device("D1", "router", side="top", ports=False)])))
    c = s.view_check
    assert c.status == "partial" and c.shown == ["the Wi-Fi Router"] and c.missing == ["the Wi-Fi Router's connection ports"]
    # Unchanged accounting rule: the right device from the wrong side is a genuine attempt at a PORTS_NOT_VISIBLE gap.
    assert c.counted_as_attempt
    assert "partly showed the view requested in nv1" in " ".join(s.notes)


def test_5b_top_view_muse_could_not_attribute_is_not_captured_and_refunded():
    """Live photo 2 of the same inspection: a top view Muse did not attribute to any listed device."""
    ag = agent()
    s1 = start_at_router(ag)
    top = extraction(devices=[device("D1", None, side="top", ports=False, certainty="uncertain")], subject=False)
    (s,) = feed(ag, rec(2, top))
    assert s.view_check.status == "not_captured" and not s.view_check.counted_as_attempt
    assert s.next_view.id == s1.next_view.id and ag.gap_attempts["R1:PORTS_NOT_VISIBLE:0"] == 1
    assert "no attempt was counted" in " ".join(s.notes)


def test_6_unrelated_photo_is_not_captured_and_the_guidance_stays():
    ag = agent()
    s1 = start_at_router(ag)
    (s,) = feed(ag, rec(2, extraction(subject=False, summary="a kitchen table")))
    assert s.view_check.status == "not_captured" and s.view_check.shown == []
    assert s.next_view.id == s1.next_view.id and accepted_from(s) == 0
    assert all(a.status == "INSUFFICIENT_EVIDENCE" for a in s.assessments)


def test_7_relevant_photo_with_zero_accepted_evidence():
    ag = agent()
    start_at_router(ag)
    (s,) = feed(ag, live(3))
    assert s.view_check.status == "captured" and accepted_from(s) == 0
    assert all(not ep.support for a in s.assessments for ep in a.endpoints)


def test_8_partial_fulfilment_of_a_multi_part_request():
    ag = agent()
    start_at_router(ag)
    (s2,) = feed(ag, live(3, identification_certainty="clear"))
    assert s2.next_view.gap_code == "LABEL_ILLEGIBLE"  # parts: router, its ports, the port holding the plug
    (s3,) = feed(ag, rec(3, router_rear(*LAN_EMPTY)))  # LAN 1-4 framed, the occupied socket left out
    c = s3.view_check
    assert c.status == "partial" and c.counted_as_attempt
    assert c.shown == ["the Wi-Fi Router", "the Wi-Fi Router's connection ports"]
    assert c.missing == ["the Wi-Fi Router port holding the ethernet plug"]


def test_9_incorrect_device_identity():
    ag = agent()
    s1 = start_at_router(ag)
    ps5_rear = extraction(devices=[device("D1", "ps5")], ports=[cport("P1", "D1", None, "ethernet", legible="no_label")])
    (s,) = feed(ag, rec(2, ps5_rear))
    assert s.view_check.status == "not_captured" and s.view_check.missing[0] == "the Wi-Fi Router"
    assert ag.gap_attempts.get(s1.next_view.gap_key) == 0  # refunded; guidance moves to the console in view
    # Two devices both claimed as the router: which one is the specified router is unknown -> not shown.
    ag2 = agent()
    start_at_router(ag2)
    both = extraction(devices=[device("D1", "router"), device("D2", "router", box=(500, 100, 900, 600))])
    (s,) = feed(ag2, rec(2, both))
    assert s.view_check.status == "not_captured" and s.view_check.identity_confirmed is None


def test_10_contradictory_observations_of_the_same_labelled_permitted_port():
    plugged = rec(1, router_rear(lan("P1", 2, occ="cable_inserted", color="blue")), {"P1": ETH})
    empty = rec(2, router_rear(lan("P1", 2)))
    a = assess_requirement(HOME, HOME.requirements[0], [plugged, empty])
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "contradicted"
    assert a.endpoints[0].gap.code == "CONTRADICTION" and a.contradictions
    assert "photo 1 reported a plug in this same labelled port" in a.endpoints[0].conflicts[0].claim
    # Different permitted ports are not the same port: no contradiction, the plugged one supports.
    other = rec(2, router_rear(lan("P1", 3)))
    assert assess_requirement(HOME, HOME.requirements[0], [plugged, other]).endpoints[0].state == "established"


def test_11_exact_router_to_switch_spec_keeps_its_rules():
    ag = agent(EXACT)
    (s1,) = feed(ag, rec(1, extraction(devices=[device("D1", "router", side="front", ports=False)])))
    assert s1.next_view.gap_key == "R1:PORTS_NOT_VISIBLE:0"
    unsure = extraction(devices=[device("D1", "router", certainty="uncertain")],
                        ports=[cport("P1", "D1", "1", "ethernet", group="LAN")])
    (s2,) = feed(ag, rec(2, unsure, {"P1": "blue ethernet cable"}))
    assert s2.view_check.status == "captured" and s2.view_check.identity_confirmed is False
    assert accepted_from(s2) == 0 and s2.assessments[0].endpoints[0].gap.code == "DEVICE_UNCONFIRMED"
    # Exact endpoint, confirmed router, LAN 1 clearly empty: still a violation, as before.
    empty = extraction(devices=[device("D1", "router")], ports=[cport("P1", "D1", "1", "ethernet", group="LAN",
                                                                      occ="empty", color=None)])
    a = assess_requirement(EXACT, EXACT.requirements[0], [rec(3, empty)])
    assert a.status == "VIOLATED"


def test_12_flexible_router_to_ps5_still_verifies_on_complete_evidence():
    ag = agent()
    start_at_router(ag)
    (s,) = feed(ag, rec(2, eth_photo(), {"P1": ETH, "P2": ETH}))
    assert s.view_check.status == "captured" and r1(s).status == "VERIFIED"


# ============================================================ planner and API plumbing

def test_planner_receives_the_identity_gap_and_is_told_not_to_reuse_the_port_view():
    fm = FakeMeta()
    fm.queue_chat("NextViewPlan", plan("Raise the phone above the router so its logo and rear sockets are both seen."),
                  plan())
    s = settings()
    ag = agent(client=fm.client(s))
    img = make_image("x.jpg")
    feed(ag, live(1), image=img)
    feed(ag, live(3), image=make_image("y.jpg", color=(9, 9, 9)))
    body = [json.loads(json.loads(r.content)["messages"][1]["content"][0]["text"]) for r in fm.requests
            if r.url.path.endswith("/chat/completions")][-1]
    assert body["gap"]["code"] == "DEVICE_UNCONFIRMED"
    assert body["gap"]["context"]["unconfirmed_port_photos"] == [2]
    assert "Do not ask for the same port view again" in PLAN_SYSTEM
    assert "Never ask the person to plug, unplug, move, swap or" in PLAN_SYSTEM
    assert '"must be" somewhere else' in PLAN_SYSTEM


def test_view_check_survives_history_and_is_none_without_a_pending_request():
    ag = agent()
    start_at_router(ag)
    feed(ag, live(3))
    h = ag.snapshot().history
    assert "view_check" not in h[0] and h[1]["view_check"]["status"] == "captured"
    assert any(e.name == "view_check" for e in ag.trace.events)
