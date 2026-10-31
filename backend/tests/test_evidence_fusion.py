"""Evidence fusion across photos, cable identity, and conservative port identification (no network).

All observations here are hand-built model claims (synthetic), not real inference.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from fakes import cable, device, extraction, port
from proofcam.evidence import GroundingLink, ObservationRecord
from proofcam.observation import ObservationExtraction
from proofcam.policy import assess_requirement, infer_port_identity, select_gap
from proofcam.spec import InspectionSpec

SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "specs" / "router_switch.json"
CONCEPT = "blue ethernet cable"
ROUTER_ROW = ["LAN 1", "LAN 2", "LAN 3", "LAN 4"]
SWITCH_ROW = ["1", "2", "3", "4", "5"]


def make_spec(port_identity="label_only", rows=True) -> InspectionSpec:
    d = json.loads(InspectionSpec.load(SPEC_PATH).model_dump_json())
    if rows:
        d["devices"][0]["port_rows"] = [ROUTER_ROW]
        d["devices"][1]["port_rows"] = [SWITCH_ROW]
    d["requirements"][0]["port_identity"] = port_identity
    return InspectionSpec.model_validate(d)


def rec(seq, ext: dict, grounded=()) -> ObservationRecord:
    links = {f"{p}|{CONCEPT}": GroundingLink(concept=CONCEPT, sam_object_id="0", overlap_px=500, corroborated=True,
                                             note="test") for p in grounded}
    return ObservationRecord(seq=seq, image_id=f"img_{seq}", source_name=f"{seq}.jpg", width=400, height=300,
                             extraction=ObservationExtraction.model_validate(ext), port_links=links)


def row(dev, labels, target_idx, y=(500, 560), x0=200, pitch=60, w=50, **target_kw):
    """Ports left-to-right; labels[i] None = unreadable. The target gets a blue plug by default."""
    out = []
    for i, lab in enumerate(labels):
        box = (x0 + i * pitch, y[0], x0 + i * pitch + w, y[1])
        if i == target_idx:
            kw = {"legible": "illegible" if lab is None else "legible", "color": "blue", **target_kw}
            out.append(port(f"P{i + 1}", dev, lab, box=box, **kw))
        else:
            out.append(port(f"P{i + 1}", dev, lab, occ="empty", color=None,
                            legible="legible" if lab else "illegible", box=box))
    return out


def reassess(spec, *recs, grounding=True):
    return assess_requirement(spec, spec.requirements[0], list(recs), grounding)


# --------------------------------------------------------------------------- separable cable identity

def router_closeup(seq):
    return rec(seq, extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "1", group="LAN")]),
               grounded=["P1"])


def switch_closeup(seq):
    return rec(seq, extraction(devices=[device("D1", "switch")], ports=[port("P1", "D1", "3")]), grounded=["P1"])


def wide_trace(seq, switch_label="3", path="fully_traced", grounded=("P1", "P2")):
    # Labels legible but insertion only 'partial': this photo alone cannot support either endpoint.
    return rec(seq, extraction(
        devices=[device("D1", "router"), device("D2", "switch")],
        ports=[port("P1", "D1", "1", group="LAN", vis="partial"), port("P2", "D2", switch_label, vis="partial")],
        cables=[cable("C1", "blue", ["P1", "P2"], path=path)]), grounded=grounded)


def test_complementary_endpoints_plus_separate_trace_verify_in_every_order():
    spec = make_spec()
    photos = [router_closeup(1), switch_closeup(2), wide_trace(3)]
    finals = []
    for perm in itertools.permutations(photos):
        recs = [p.model_copy(update={"seq": i + 1}) for i, p in enumerate(perm)]
        a = reassess(spec, *recs)
        assert a.status == "VERIFIED", a.explanation
        by_img = {r.image_id: r.seq for r in recs}
        finals.append((a.status, a.identity_state,
                       [sorted(s.image_id for s in ep.support) for ep in a.endpoints],
                       sorted(x.image_id for x in a.identity_evidence)))
        assert "photo" in a.explanation and by_img
    assert all(f == finals[0] for f in finals)
    # Provenance: router from the router close-up, switch from the switch close-up, identity from the wide shot.
    assert finals[0][2] == [["img_1"], ["img_2"]] and finals[0][3] == ["img_3"]


def test_endpoints_without_any_trace_are_not_verified():
    a = reassess(make_spec(), router_closeup(1), switch_closeup(2))
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.identity_state == "unknown"
    assert [g.code for g in a.gaps] == ["CABLE_CONTINUITY"]


@pytest.mark.parametrize("trace", [
    wide_trace(3, switch_label="4"),             # trace ends at a different switch port
    wide_trace(3, path="partially_visible"),     # not continuous
    wide_trace(3, grounded=("P1",)),             # switch end not SAM-grounded in the trace photo
])
def test_trace_must_connect_the_identified_ports(trace):
    a = reassess(make_spec(), router_closeup(1), switch_closeup(2), trace)
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert a.identity_state == "unknown"


def test_trace_alone_never_verifies():
    a = reassess(make_spec(), wide_trace(1))
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert a.identity_state == "established"  # identity is a separate fact, visible early
    assert all(ep.state == "unknown" for ep in a.endpoints)
    assert "CABLE_CONTINUITY" not in {g.code for g in a.gaps}  # never re-request a proven trace


def test_trace_with_unidentified_ports_is_reported_as_near_miss():
    t = rec(3, extraction(
        devices=[device("D1", "router"), device("D2", "switch")],
        ports=[port("P1", "D1", None, legible="illegible"), port("P2", "D2", None, legible="illegible")],
        cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")]), grounded=["P1", "P2"])
    a = reassess(make_spec(), router_closeup(1), switch_closeup(2), t)
    assert a.status == "INSUFFICIENT_EVIDENCE"
    g = next(g for g in a.gaps if g.code == "CABLE_CONTINUITY")
    assert g.context["near_misses"] and "could not be identified" in g.missing_fact


# --------------------------------------------------------------------------- plug colour via cable

def test_clear_plug_supported_by_linked_cable_colour():
    o = rec(1, extraction(devices=[device("D1", "router")],
                          ports=[port("P1", "D1", "1", group="LAN", color="transparent")],
                          cables=[cable("C1", "blue", ["P1"])]), grounded=["P1"])
    ep = reassess(make_spec(), o).endpoints[0]
    assert ep.state == "established" and "visibly belongs" in ep.support[0].claim


def test_clear_plug_on_other_colour_cable_is_neither_support_nor_violation():
    o = rec(1, extraction(devices=[device("D1", "router")],
                          ports=[port("P1", "D1", "1", group="LAN", color="transparent")],
                          cables=[cable("C1", "black", ["P1"])]), grounded=["P1"])
    a = reassess(make_spec(), o)
    assert a.endpoints[0].state == "unknown" and a.status == "INSUFFICIENT_EVIDENCE"


# --------------------------------------------------------------------------- layout inference (rule)

def ext_of(ports, dev="router"):
    return ObservationExtraction.model_validate(extraction(devices=[device("D1", dev)], ports=ports))


def infer(ports, target="P1", dev_idx=0, port_label=None, rows=True):
    spec = make_spec(rows=rows)
    e = spec.requirements[0].endpoints[dev_idx]
    if port_label:
        e = e.model_copy(update={"port_label": port_label})
    ext = ext_of(ports, "router" if dev_idx == 0 else "switch")
    p = next(q for q in ext.ports if q.ref == target)
    return infer_port_identity(ext, "D1", p, e, spec.device(e.device_id))


def test_inference_row_end_two_anchors():
    note = infer(row("D1", [None, "LAN 2", "LAN 3", "LAN 4"], 0))
    assert note and "'LAN 2' (P2)" in note and "'LAN 3' (P3)" in note


def test_inference_interior_both_neighbours():
    assert infer(row("D1", ["1", "2", None, "4", "5"], 2), target="P3", dev_idx=1)


@pytest.mark.parametrize("labels,target,dev_idx,why", [
    ([None, "LAN 2", None, "LAN 4"], 0, 0, "row end needs two consecutive inward anchors"),
    (["1", None, None, "4", "5"], 2, 1, "interior port needs BOTH neighbours legible"),
    (["1", "4", None, "2", "5"], 2, 1, "neighbours out of declared order"),
    (["3", "2", None, "4", "5"], 2, 1, "another port is legibly labelled as the target"),
    ([None, "LAN 3", "LAN 4", "LAN 2"], 0, 0, "legible label at the wrong offset"),
])
def test_inference_refuses(labels, target, dev_idx, why):
    assert infer(row("D1", labels, target), target=f"P{target + 1}", dev_idx=dev_idx) is None, why


def test_inference_refuses_partially_legible_anchors():
    ports = row("D1", [None, "LAN 2", "LAN 3", "LAN 4"], 0)
    for p in ports[1:]:
        p["label_legibility"] = "partially_legible"
    assert infer(ports) is None


def test_inference_refuses_irregular_spacing_from_a_missed_port():
    ports = row("D1", ["1", "2", None, "4", "5"], 2)
    for p in ports[3:]:  # a gap the width of one port to the right of the target
        p["box"]["x1"] += 60
        p["box"]["x2"] += 60
    assert infer(ports, target="P3", dev_idx=1) is None


def test_inference_refuses_unboxed_port_and_missing_layout():
    ports = row("D1", [None, "LAN 2", "LAN 3", "LAN 4"], 0)
    assert infer(ports, rows=False) is None
    ports[3]["box"] = None
    assert infer(ports) is None


def test_inference_refuses_port_whose_own_label_is_legible():
    assert infer(row("D1", ["USB", "LAN 2", "LAN 3", "LAN 4"], 0)) is None


# --------------------------------------------------------------------------- layout inference (policy use)

def router_hidden_label(seq, **target_kw):
    return rec(seq, extraction(devices=[device("D1", "router")],
                               ports=row("D1", [None, "LAN 2", "LAN 3", "LAN 4"], 0, **target_kw)),
               grounded=["P1"])


def switch_hidden_label(seq):
    return rec(seq, extraction(devices=[device("D1", "switch")], ports=row("D1", ["1", "2", None, "4", "5"], 2)),
               grounded=["P3"])


def test_inference_not_permitted_is_recorded_but_never_support():
    a = reassess(make_spec("label_only"), router_hidden_label(1))
    ep = a.endpoints[0]
    assert ep.state == "unknown" and not ep.support
    assert ep.inferred_only and ep.inferred_only[0].port_basis == "layout_inference"
    assert ep.gap.code == "LABEL_ILLEGIBLE" and ep.gap.context["label_hidden_by_plug"]
    assert ep.gap.context["layout_inference_available"]


def test_inference_permitted_supports_and_is_disclosed():
    a = reassess(make_spec("label_or_layout"), router_hidden_label(1))
    ep = a.endpoints[0]
    assert ep.state == "established" and ep.support[0].port_basis == "layout_inference"
    assert any("layout inference" in x for x in a.assumptions)


def test_inferred_identity_never_establishes_a_violation():
    a = reassess(make_spec("label_or_layout"), router_hidden_label(1, occ="empty", color=None))
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "unknown"
    a = reassess(make_spec("label_or_layout"), router_hidden_label(1, color="red"))
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.endpoints[0].state == "unknown"


def test_inferred_support_against_direct_empty_label_is_a_contradiction():
    empty = rec(2, extraction(devices=[device("D1", "router")],
                              ports=[port("P1", "D1", "1", group="LAN", occ="empty", color=None)]))
    a = reassess(make_spec("label_or_layout"), router_hidden_label(1), empty)
    assert a.endpoints[0].state == "contradicted" and a.status == "INSUFFICIENT_EVIDENCE"
    assert a.gaps[0].code == "CONTRADICTION" and a.contradictions


def test_inferred_support_still_requires_sam_grounding():
    o = router_hidden_label(1).model_copy(update={"port_links": {}})
    a = reassess(make_spec("label_or_layout"), o)
    assert a.endpoints[0].state == "unknown" and a.endpoints[0].gap.code == "GROUNDING_MISSING"


def test_verified_with_inferred_ports_needs_a_trace_and_discloses_it():
    spec = make_spec("label_or_layout")
    wide = rec(3, extraction(
        devices=[device("D1", "router"), device("D2", "switch")],
        ports=row("D1", [None, "LAN 2", "LAN 3", "LAN 4"], 0, vis="partial")
        + [port("S3", "D2", "3", vis="partial", box=(700, 500, 750, 560))],
        cables=[cable("C1", "blue", ["P1", "S3"], path="fully_traced")]), grounded=["P1", "S3"])
    assert reassess(spec, router_hidden_label(1), switch_hidden_label(2)).status == "INSUFFICIENT_EVIDENCE"
    a = reassess(spec, router_hidden_label(1), switch_hidden_label(2), wide)
    assert a.status == "VERIFIED", a.explanation
    assert a.identity_evidence[0].port_basis == "layout_inference"
    assert len(a.assumptions) >= 3  # two inferred endpoints + inferred trace port
    # The same photos under the strict default never verify.
    assert reassess(make_spec("label_only"), router_hidden_label(1), switch_hidden_label(2),
                    wide).status == "INSUFFICIENT_EVIDENCE"


# --------------------------------------------------------------------------- guidance

def test_select_gap_prefers_device_in_view_but_contradiction_first():
    spec = make_spec()
    # Router seen (ports not visible), switch never seen.
    o = rec(1, extraction(devices=[device("D1", "router", side="front", ports=False)]))
    a = reassess(spec, o)
    assert select_gap([a], set()).code == "DEVICE_NOT_SEEN"  # old behaviour without view context
    assert select_gap([a], set(), {"router"}).code == "PORTS_NOT_VISIBLE"
    assert select_gap([a], set(), {"router"}).context["device_id"] == "router"
