"""M2.3 grounding geometry: device corroboration by IoU or containment; port grounding limits.

All masks here are synthetic and deterministic. Masks sent "over the wire" are encoded with meta_sam_parser's own
encoder and decoded by the production parser, so coordinates go through the real conversion path. Device links are
report-level only; the last tests check that no verdict depends on them.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest
from meta_sam_parser._mask_codec import _encode_raster  # test-only: produce valid one_bit payloads

from fakes import W, H, cable, device, extraction, make_image, plan, port, sam_record, settings
from proofcam.agent import InspectionAgent
from proofcam.evidence import GroundingLink
from proofcam.grounding import (DEVICE_CONTAIN_MIN, DEVICE_COVER_MIN, DEVICE_MAX_AREA_RATIO, GroundingRun,
                                device_corroboration, link_ports)
from proofcam.observation import ObservationExtraction
from proofcam.overlay import render_overlay_jpeg
from proofcam.policy import assess_requirement
from test_acceptance import cap, check_invariants, create, server
from test_agent import OBS, PLAN, REAR_BOTH, SPEC, base_fake, observe
from test_policy import both_ends_one_image

# Router on a 400x300 image: body (Muse box) plus two thin antennas rising above it (only SAM includes those).
BODY = (100, 180, 300, 270)               # half-open pixel box
BODY_1000 = (250, 600, 750, 900)          # the same box on Muse's 0-1000 grid (x*0.4, y*0.3)
ANTENNAS = [(110, 20, 120, 180), (280, 20, 290, 180)]


def mask(*boxes) -> np.ndarray:
    m = np.zeros((H, W), dtype=bool)
    for x0, y0, x1, y1 in boxes:
        m[y0:y1, x0:x1] = True
    return m


def bbox(m: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(m)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def obj(oid: str, m: np.ndarray):
    return (oid, bbox(m), m)


ROUTER_WITH_ANTENNAS = mask(BODY, *ANTENNAS)


def sam_line(oid: int, m: np.ndarray, conf: float = 0.9) -> str:
    """SAM wire record for an arbitrary mask (inclusive box, box-local raster)."""
    x0, y0, x1, y1 = bbox(m)
    local = m[y0:y1, x0:x1].astype(int)
    payload = _encode_raster(local.flatten().tolist(), x1 - x0, y1 - y0)
    return (f"{oid}<|box;x1={x0};y1={y0};x2={x1 - 1};y2={y1 - 1};w={W};h={H};c={conf}|>"
            f"<|mask;x=0;y=0;c={conf};data={y1 - y0},{x1 - x0},{payload}|>")


# ============================================================================ device_corroboration (pure)

def test_router_with_antennas_is_corroborated_by_containment_not_iou():
    d = device_corroboration(BODY, [obj("0", ROUTER_WITH_ANTENNAS)])
    assert d.iou < 0.5  # the old IoU-only rule failed this correct mask
    assert d.corroborated and d.basis == "containment" and d.object_id == "0"
    assert d.containment == 1.0 and d.coverage == 1.0 and 1.0 < d.area_ratio <= DEVICE_MAX_AREA_RATIO


def test_accurate_mask_keeps_the_iou_route():
    d = device_corroboration(BODY, [obj("0", mask(BODY))])
    assert d.corroborated and d.basis == "iou" and d.iou == 1.0


def test_oversized_mask_does_not_corroborate():
    d = device_corroboration(BODY, [obj("0", mask((0, 0, W, H)))])  # e.g. the whole desk
    assert d.containment == 1.0 and d.coverage == 1.0 and d.area_ratio > DEVICE_MAX_AREA_RATIO
    assert not d.corroborated and d.basis == "none"


def test_displaced_mask_does_not_corroborate():
    shifted = mask((240, 180, 400, 270))  # body-sized region 140 px to the right
    d = device_corroboration(BODY, [obj("0", shifted)])
    assert d.containment < DEVICE_CONTAIN_MIN and not d.corroborated


def test_sparse_mask_inside_a_large_box_is_a_near_miss():
    # The SAM box contains the Muse box, but the mask itself is only an outline: it does not cover the body.
    outline = mask((100, 20, 300, 26), (100, 264, 300, 270), (100, 20, 106, 270), (294, 20, 300, 270))
    d = device_corroboration(BODY, [obj("0", outline)])
    assert d.containment == 1.0 and d.coverage < DEVICE_COVER_MIN and not d.corroborated


def test_partially_contained_box_is_a_near_miss():
    # Mask/box cut off at x=270: 85% of the Muse box inside, short of DEVICE_CONTAIN_MIN.
    clipped = mask((100, 20, 270, 270))
    d = device_corroboration(BODY, [obj("0", clipped)])
    assert 0.8 < d.containment < DEVICE_CONTAIN_MIN and not d.corroborated


def test_each_object_is_judged_alone_a_different_object_never_counts():
    # SAM 'router' also returned the switch (seen live in m4/m7). It must not vouch for the router.
    switch_obj = obj("0", mask((320, 200, 400, 280)))
    d = device_corroboration(BODY, [switch_obj, obj("1", ROUTER_WITH_ANTENNAS)])
    assert d.corroborated and d.object_id == "1" and d.basis == "containment"
    assert not device_corroboration(BODY, [switch_obj]).corroborated


def test_higher_iou_wrong_object_does_not_hide_the_contained_one():
    # A displaced object overlaps the body more by IoU (0.43) than the true antenna-shaped mask (0.25), yet fails
    # containment; the true object must still be found by judging every object on its own.
    displaced = obj("0", mask((180, 180, 380, 270)))
    true_router = obj("1", ROUTER_WITH_ANTENNAS)
    assert device_corroboration(BODY, [displaced]).iou > device_corroboration(BODY, [true_router]).iou
    d = device_corroboration(BODY, [displaced, true_router])
    assert d.corroborated and d.object_id == "1" and d.basis == "containment"


def test_no_objects_is_not_corroborated():
    d = device_corroboration(BODY, [])
    assert not d.corroborated and d.object_id is None and d.note("router") == "SAM found no 'router'"


def test_note_keeps_every_diagnostic_value():
    note = device_corroboration(BODY, [obj("0", ROUTER_WITH_ANTENNAS)]).note("router")
    for part in ("box IoU", "inside its box", "mask covers", "of the mask inside", "area ratio",
                 "corroborated by containment"):
        assert part in note


# ============================================================================ through the real parser and agent

def _agent_with_router_sam(line: str, devices) -> InspectionAgent:
    fm = base_fake()
    fm.sam["router"] = line
    fm.queue_chat(OBS, extraction(devices=devices))
    fm.queue_chat(PLAN, plan())
    ag = InspectionAgent(SPEC, fm.client(settings()), settings())
    asyncio.run(ag.observe(make_image("router.jpg")))
    return ag


def test_link_devices_end_to_end_with_antenna_mask():
    ag = _agent_with_router_sam("<0f>" + sam_line(0, ROUTER_WITH_ANTENNAS),
                                [device("D1", "router", side="rear", ports=False, box=BODY_1000)])
    o = ag.observations[0]
    g = next(x for x in o.sam if x.concept == "router")
    assert g.objects[0].box_px == (100, 20, 300, 270)  # inclusive wire box -> half-open pixels
    assert g.objects[0].mask_area_px == int(ROUTER_WITH_ANTENNAS.sum())
    link = o.device_links["D1"]
    assert link.corroborated and link.sam_object_id == "0" and link.iou < 0.5
    assert "corroborated by containment" in link.note


def test_link_devices_end_to_end_two_objects_picks_the_router():
    line = "<0f>" + sam_line(0, mask((320, 200, 400, 280))) + "," + sam_line(1, ROUTER_WITH_ANTENNAS)
    ag = _agent_with_router_sam(line, [device("D1", "router", side="rear", ports=False, box=BODY_1000)])
    link = ag.observations[0].device_links["D1"]
    assert link.corroborated and link.sam_object_id == "1"


def test_no_sam_result_for_the_switch_leaves_its_link_uncorroborated_and_the_verdict_intact():
    fm = base_fake()  # no 'network switch' entry: SAM returns zero objects, as in all 7 own photos
    fm.queue_chat(OBS, REAR_BOTH)
    ag = InspectionAgent(SPEC, fm.client(settings()), settings())
    s = asyncio.run(ag.observe(make_image("rear.jpg")))
    assert s.assessments[0].status == "VERIFIED"
    link = ag.observations[0].device_links["D2"]
    assert not link.corroborated and link.note == "SAM found no 'network switch'"


def test_grounding_link_schema_unchanged_for_stored_records():
    # Stored ObservationRecords are compared byte-for-byte on commit (append-only check): no new fields.
    assert set(GroundingLink.model_fields) == {"concept", "sam_object_id", "iou", "overlap_px", "corroborated",
                                               "note"}


def test_overlay_renders_the_antenna_mask_deterministically():
    ag = _agent_with_router_sam("<0f>" + sam_line(0, ROUTER_WITH_ANTENNAS),
                                [device("D1", "router", side="rear", ports=False, box=BODY_1000)])
    o, img = ag.observations[0], ag.images[ag.observations[0].image_id]
    a = render_overlay_jpeg(img, o, ag.grounding_runs[o.seq])
    assert a == render_overlay_jpeg(img, o, ag.grounding_runs[o.seq]) and a[:2] == b"\xff\xd8"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(a)).size == (W, H)


# ============================================================================ port grounding limits (unchanged rule)

def _port_ext(boxes, occupied):
    return ObservationExtraction.model_validate(extraction(
        devices=[device("D1", "router")],
        ports=[port(f"P{i + 1}", "D1", str(i + 1), box=b, occ="cable_inserted" if i in occupied else "empty",
                    color="blue" if i in occupied else None) for i, b in enumerate(boxes)]))


def test_cable_mask_at_one_port_also_reaches_the_expanded_region_of_its_neighbour():
    """Documented limitation (measured on recorded live photos: 10 of 14 grounded ports): with the 50% expansion,
    one cable mask also 'reaches' an adjacent port region, so SAM port grounding is presence near the port, not
    proof of insertion into that specific port. Port identity and insertion rest on Muse's own per-port claims."""
    boxes = [(200, 400, 240, 480), (250, 400, 290, 480)]  # adjacent ports, pitch 50 on the 0-1000 grid
    cable_mask = mask((100, 120, 116, 145))               # pixels of a plug in port 2 only (x 100..116)
    run = GroundingRun(masks={("blue ethernet cable", "0"): cable_mask})
    from proofcam.evidence import SamGrounding, SamObjectSummary
    run.groundings.append(SamGrounding(concept="blue ethernet cable", status="ok", objects=[
        SamObjectSummary(object_id="0", box_px=(100, 120, 116, 145), confidence=0.9, mask_area_px=400)]))
    links = link_ports(_port_ext(boxes, occupied={0, 1}), run, ["blue ethernet cable"], W, H)
    assert links["P2|blue ethernet cable"].corroborated
    assert links["P1|blue ethernet cable"].corroborated  # the neighbour passes too: no port-level discrimination


def test_policy_does_not_let_a_neighbouring_mask_turn_an_empty_port_into_support():
    # Muse reads LAN 1 legibly as empty while a grounded blue cable sits in the next port: still a violation.
    o = both_ends_one_image(grounded_ports=["P1", "P2"])
    ext = o.extraction.model_copy(deep=True)
    ext.ports[0] = ext.ports[0].model_copy(update={"occupancy": "empty", "plug_color": None})
    a = assess_requirement(SPEC, SPEC.requirements[0], [o.model_copy(update={"extraction": ext})])
    assert a.status == "VIOLATED"


# ============================================================================ verdicts do not depend on device links

@pytest.mark.parametrize("corroborated", [True, False])
def test_device_links_never_change_a_verdict(corroborated):
    base = both_ends_one_image(grounded_ports=["P1", "P2"])
    links = {r: GroundingLink(concept="x", sam_object_id=None, corroborated=corroborated, note="t")
             for r in ("D1", "D2")}
    a = assess_requirement(SPEC, SPEC.requirements[0], [base.model_copy(update={"device_links": links})])
    assert a == assess_requirement(SPEC, SPEC.requirements[0], [base])
    assert a.status == "VERIFIED"


def test_antenna_mask_over_http_report_and_unchanged_verdict(tmp_path):
    fm = base_fake()
    fm.sam["router"] = "<0f>" + sam_line(0, ROUTER_WITH_ANTENNAS)
    rear_router = extraction(devices=[device("D1", "router", box=BODY_1000), device("D2", "switch")],
                             ports=[port("P1", "D1", "1", group="LAN"), port("P2", "D2", "3")],
                             cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")])
    fm.queue_chat(OBS, rear_router)

    async def go():
        async with server(tmp_path, fm) as (c, store, _a):
            iid = await create(c)
            r = await cap(c, iid, "rear.jpg")
            assert r.json()["assessments"][0]["status"] == "VERIFIED"  # verdict from port evidence, as before
            md = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
            assert "corroborated by containment" in md
            check_invariants(store, iid, sent=len(fm.requests))

    asyncio.run(go())
