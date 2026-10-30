"""Structured-output validation and SAM coordinate transforms (no network)."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest
from pydantic import ValidationError

from fakes import CABLE_AT_PORT, H, W, extraction, make_image, port, device, sam_events, sam_record
from proofcam.geometry import box_iou, mask_pixels_in_box, mask_to_image
from proofcam.meta_client import _parse_sam_events
from proofcam.observation import Box1000, NextViewPlan, ObservationExtraction
from proofcam.wire_schema import wire_schema


def test_valid_extraction_parses():
    e = ObservationExtraction.model_validate(extraction(devices=[device("D1", "router")],
                                                        ports=[port("P1", "D1", "LAN 1")]))
    assert e.ports[0].label_read == "LAN 1"


@pytest.mark.parametrize("mutate", [
    lambda d: d["ports"][0].update(device_ref="D404"),            # dangling ref
    lambda d: d["ports"][0]["box"].update(x2=1200),                 # off-grid
    lambda d: d["ports"][0]["box"].update(x2=10),                   # degenerate (x2 < x1)
    lambda d: d["ports"][0].update(occupancy="probably"),           # not in enum
    lambda d: d.update(extra_field=1),                              # additionalProperties
    lambda d: d.pop("cables"),                                      # required
])
def test_malformed_extraction_rejected(mutate):
    d = extraction(devices=[device("D1", "router")], ports=[port("P1", "D1", "LAN 1")])
    mutate(d)
    with pytest.raises(ValidationError):
        ObservationExtraction.model_validate(d)


def test_wire_schema_is_flat_and_locked():
    s = wire_schema(ObservationExtraction)
    text = json.dumps(s)
    assert "$ref" not in text and "$defs" not in text

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "object" and "properties" in n:
                assert n["additionalProperties"] is False
                assert set(n["required"]) == set(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(s)


def test_generic_next_view_rejected():
    with pytest.raises(ValidationError):
        NextViewPlan(instruction="Take a photo", camera_action="move_closer", target_region="x",
                     rationale="", success_criteria="", visually_resolvable=True, unresolvable_reason=None)


def test_box1000_to_pixels():
    assert Box1000(x1=0, y1=0, x2=1000, y2=1000).to_pixels(W, H) == (0, 0, W, H)
    assert Box1000(x1=250, y1=500, x2=500, y2=1000).to_pixels(W, H) == (100, 150, 200, 300)


def _parse(line: str):
    return asyncio.run(_parse_sam_events(sam_events(line), make_image(), "c"))


def test_sam_inclusive_box_becomes_half_open_and_mask_lands_in_place():
    x1, y1, x2, y2 = CABLE_AT_PORT
    seg = _parse("<0f>" + sam_record(7, CABLE_AT_PORT, conf=0.75))
    assert len(seg.objects) == 1
    o = seg.objects[0]
    assert o.object_id == "7" and o.confidence == 0.75
    assert o.box == (x1, y1, x2 + 1, y2 + 1)
    m = mask_to_image(o.mask, W, H)
    assert m.shape == (H, W)
    assert m.sum() == (x2 - x1 + 1) * (y2 - y1 + 1)
    ys, xs = np.nonzero(m)
    assert (xs.min(), ys.min(), xs.max(), ys.max()) == (x1, y1, x2, y2)
    assert mask_pixels_in_box(m, (0, 0, x1, H)) == 0   # nothing left of the box


def test_sam_multiple_records_and_sparse_ids():
    seg = _parse("<0f>" + sam_record(0, (0, 0, 9, 9)) + "," + sam_record(2, (50, 50, 59, 69)))
    assert [o.object_id for o in seg.objects] == ["0", "2"]


def test_sam_zero_matches_is_empty_not_error():
    seg = _parse("")
    assert seg.objects == [] and seg.raw_output == ""


def test_sam_size_mismatch_discards_geometry():
    seg = _parse("<0f>" + sam_record(0, (0, 0, 9, 9), w=800, h=600))
    assert seg.objects == [] and any("size_mismatch" in d for d in seg.diagnostics)


def test_box_iou():
    assert box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert box_iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
