"""Deterministic policy tests (no network). Observations are hand-built model claims."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakes import cable, device, extraction, port
from proofcam.evidence import GroundingLink, ObservationRecord
from proofcam.observation import ObservationExtraction
from proofcam.policy import assess_requirement, base_color, select_gap
from proofcam.spec import InspectionSpec, normalize_label

SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "specs" / "router_switch.json"
CONCEPT = "blue ethernet cable"


@pytest.fixture
def spec() -> InspectionSpec:
    return InspectionSpec.load(SPEC_PATH)


def unique_spec(spec: InspectionSpec) -> InspectionSpec:
    d = json.loads(spec.model_dump_json())
    d["requirements"][0]["cable_identity"] = "unique_in_installation"
    return InspectionSpec.model_validate(d)


def rec(seq, ext: dict, grounded_ports=(), ungrounded_ports=()) -> ObservationRecord:
    links = {}
    for p in grounded_ports:
        links[f"{p}|{CONCEPT}"] = GroundingLink(concept=CONCEPT, sam_object_id="0", overlap_px=500,
                                                corroborated=True, note="test")
    for p in ungrounded_ports:
        links[f"{p}|{CONCEPT}"] = GroundingLink(concept=CONCEPT, sam_object_id=None, overlap_px=0,
                                                corroborated=False, note="test")
    return ObservationRecord(seq=seq, image_id=f"img_{seq}", source_name=f"{seq}.jpg", width=400, height=300,
                             extraction=ObservationExtraction.model_validate(ext), port_links=links)


def both_ends_one_image(seq=1, path="fully_traced", **kw):
    return rec(seq, extraction(
        devices=[device("D1", "router"), device("D2", "switch")],
        ports=[port("P1", "D1", "1", group="LAN"), port("P2", "D2", "3")],
        cables=[cable("C1", "blue", ["P1", "P2"], path=path)]), **kw)


# --------------------------------------------------------------------------- helpers

def test_label_normalization():
    assert normalize_label("LAN 1") == normalize_label("lan-1") == normalize_label("LAN1")
    assert normalize_label("Port 3") == normalize_label("3") == normalize_label("P3")
    assert normalize_label("LAN1") != normalize_label("1")


def test_base_color():
    assert base_color("light blue") == "blue"
    assert base_color("Navy") == "blue"
    assert base_color("blue/white striped") is None  # ambiguous
    assert base_color("teal") is None                # unknown
    assert base_color(None) is None


# --------------------------------------------------------------------------- verdicts

def test_correctly_visible_requirement_verified(spec):
    a = assess_requirement(spec, spec.requirements[0], [both_ends_one_image(grounded_ports=["P1", "P2"])])
    assert a.status == "VERIFIED"
    assert a.identity_state == "established"
    assert {s.image_id for ep in a.endpoints for s in ep.support} == {"img_1"}


def test_missing_evidence_front_only(spec):
    o = rec(1, extraction(devices=[device("D1", "router", side="front", ports=False),
                                   device("D2", "switch", side="front", ports=False)]))
    a = assess_requirement(spec, spec.requirements[0], [o])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert {g.code for g in a.gaps} == {"PORTS_NOT_VISIBLE"}
    assert a.gaps[0].context["sides_seen"] == ["front"]


def test_no_observations_is_insufficient(spec):
    a = assess_requirement(spec, spec.requirements[0], [])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert {g.code for g in a.gaps} == {"DEVICE_NOT_SEEN"}


def test_target_port_clearly_empty_is_violation(spec):
    o = rec(1, extraction(devices=[device("D1", "router")],
                          ports=[port("P1", "D1", "LAN 1", occ="empty", color=None)]))
    a = assess_requirement(spec, spec.requirements[0], [o])
    assert a.status == "VIOLATED"
    assert "empty" in a.explanation


def test_wrong_colour_in_target_port_is_violation(spec):
    o = rec(1, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 1", color="yellow")]))
    assert assess_requirement(spec, spec.requirements[0], [o]).status == "VIOLATED"


def test_wrong_port_only_violation_when_spec_asserts_uniqueness(spec):
    o = rec(1, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 2")]),
            grounded_ports=["P1"])
    assert assess_requirement(spec, spec.requirements[0], [o]).status == "INSUFFICIENT_EVIDENCE"
    u = unique_spec(spec)
    a = assess_requirement(u, u.requirements[0], [o])
    assert a.status == "VIOLATED" and "wrong port" in a.explanation


def test_contradictory_observations_stay_visible(spec):
    o1 = rec(1, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 1")]),
             grounded_ports=["P1"])
    o2 = rec(2, extraction(devices=[device("D1", "router")],
                           ports=[port("P1", "D1", "LAN 1", occ="empty", color=None)]))
    a = assess_requirement(spec, spec.requirements[0], [o1, o2])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert a.endpoints[0].state == "contradicted"
    assert a.contradictions and "img_1" in a.contradictions[0] and "img_2" in a.contradictions[0]
    assert select_gap([a], set()).code == "CONTRADICTION"


def test_unrelated_followup_contributes_nothing(spec):
    o1 = rec(1, extraction(devices=[device("D1", "router", side="front", ports=False)]))
    o2 = rec(2, extraction(subject=False, devices=[device("D9", "router")],  # even if it claims a router
                           ports=[port("P1", "D9", "LAN 1")]), grounded_ports=["P1"])
    a = assess_requirement(spec, spec.requirements[0], [o1, o2])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert all(not ep.support for ep in a.endpoints)


# --------------------------------------------------------------------------- unjustified positives

def test_illegible_label_never_supports(spec):
    o = rec(1, extraction(devices=[device("D1", "router")],
                          ports=[port("P1", "D1", "LAN 1", legible="partially_legible")]), grounded_ports=["P1"])
    a = assess_requirement(spec, spec.requirements[0], [o])
    assert a.endpoints[0].state == "unknown" and a.endpoints[0].gap.code == "LABEL_ILLEGIBLE"


def test_partial_insertion_visibility_never_supports(spec):
    o = rec(1, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 1", vis="partial")]),
            grounded_ports=["P1"])
    a = assess_requirement(spec, spec.requirements[0], [o])
    assert a.endpoints[0].gap.code == "INSERTION_UNCLEAR"


def test_uncertain_device_identification_never_supports(spec):
    o = rec(1, extraction(devices=[device("D1", "router", certainty="uncertain")],
                          ports=[port("P1", "D1", "LAN 1")]), grounded_ports=["P1"])
    a = assess_requirement(spec, spec.requirements[0], [o])
    assert a.endpoints[0].state == "unknown" and a.endpoints[0].gap.code == "DEVICE_NOT_SEEN"
    assert a.endpoints[0].gap.context["seen_uncertain"] is True


def test_model_claim_without_sam_grounding_is_not_verified(spec):
    a = assess_requirement(spec, spec.requirements[0], [both_ends_one_image(ungrounded_ports=["P1", "P2"])])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert {g.code for g in a.gaps} == {"GROUNDING_MISSING"}
    # ablation switch exists, but is explicit
    b = assess_requirement(spec, spec.requirements[0], [both_ends_one_image(ungrounded_ports=["P1", "P2"])],
                           require_grounding=False)
    assert b.status == "VERIFIED"


def test_similar_cables_in_different_images_are_not_joined(spec):
    o1 = rec(1, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 1")],
                           cables=[cable("C1", "blue", ["P1"])]), grounded_ports=["P1"])
    o2 = rec(2, extraction(devices=[device("D1", "switch")], ports=[port("P1", "D1", "3")],
                           cables=[cable("C1", "blue", ["P1"])]), grounded_ports=["P1"])
    a = assess_requirement(spec, spec.requirements[0], [o1, o2])
    assert [ep.state for ep in a.endpoints] == ["established", "established"]
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    assert [g.code for g in a.gaps] == ["CABLE_CONTINUITY"]
    # Only an explicit, disclosed spec assertion may join them.
    u = unique_spec(spec)
    b = assess_requirement(u, u.requirements[0], [o1, o2])
    assert b.status == "VERIFIED" and b.identity_state == "assumed_by_spec" and b.assumptions


def test_partially_visible_cable_in_one_image_is_not_a_trace(spec):
    a = assess_requirement(spec, spec.requirements[0],
                           [both_ends_one_image(path="partially_visible", grounded_ports=["P1", "P2"])])
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert [g.code for g in a.gaps] == ["CABLE_CONTINUITY"]


def test_select_gap_respects_exhaustion_and_priority(spec):
    o = rec(1, extraction(devices=[device("D1", "router", side="front", ports=False)]))
    a = assess_requirement(spec, spec.requirements[0], [o])
    g = select_gap([a], set())
    assert g.code == "DEVICE_NOT_SEEN" and g.endpoint_index == 1   # switch never seen outranks router ports
    g2 = select_gap([a], {g.key})
    assert g2.code == "PORTS_NOT_VISIBLE"
    assert select_gap([a], {g.key, g2.key}) is None
