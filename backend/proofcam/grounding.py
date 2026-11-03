"""SAM 3.1 visual grounding and its link to Muse claims.

SAM locates instances of a concept. It does NOT establish connection semantics. We use it only
to check that a Muse claim ("a blue plug is in this port", "the router is here") coincides with
a real segmented region on the same image.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass, field

import numpy as np

from .evidence import GroundingLink, SamGrounding, SamObjectSummary
from .geometry import box_area, box_iou, expand_box, mask_pixels_in_box, mask_to_image
from .images import NormalizedImage
from .meta_client import MetaAPIError, MetaClient, SamSegmentation
from .observation import ObservationExtraction

DEVICE_IOU_MIN = 0.5
# Device corroboration by containment (report-level only; no verdict uses device links). SAM segments whole objects
# (a router with its antennas) while Muse boxes the body, so box IoU fails on correct masks. Alternative route: the
# Muse body box lies almost entirely inside ONE SAM object's box, that object's mask actually covers most of the
# Muse box, and the object is not scene-sized. Set on 2026-11-03 after measuring recorded live runs (see D31).
DEVICE_CONTAIN_MIN = 0.9   # share of the Muse box area inside the SAM object's box
DEVICE_COVER_MIN = 0.6     # share of the Muse box area covered by that object's mask pixels
DEVICE_MAX_AREA_RATIO = 5.0  # SAM box area at most 5x the Muse box area (antennas, stands), never a whole desk
PORT_EXPAND = 0.5          # grow the Muse port box by 50% each side before testing overlap
PORT_MIN_PX = 30
PORT_MIN_FRAC = 0.05


@dataclass
class GroundingRun:
    groundings: list[SamGrounding] = field(default_factory=list)
    masks: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)  # (concept, obj) -> HxW


async def run_sam(client: MetaClient, image: NormalizedImage, concepts: list[str]) -> GroundingRun:
    async def one(concept: str) -> SamSegmentation | MetaAPIError:
        try:
            return await client.sam_segment(image, concept)
        except MetaAPIError as e:
            return e

    run = GroundingRun()
    results = await asyncio.gather(*(one(c) for c in concepts))
    for concept, res in zip(concepts, results):
        if isinstance(res, MetaAPIError):
            run.groundings.append(SamGrounding(concept=concept, status="error", error=str(res)))
            continue
        summaries = []
        for o in res.objects:
            m = mask_to_image(o.mask, image.width, image.height)
            run.masks[(concept, o.object_id)] = m
            summaries.append(SamObjectSummary(object_id=o.object_id, box_px=o.box,
                                              confidence=o.confidence, mask_area_px=int(m.sum())))
        run.groundings.append(SamGrounding(concept=concept, status="ok", objects=summaries,
                                           diagnostics=res.diagnostics))
    return run


@dataclass(frozen=True)
class DeviceDecision:
    corroborated: bool
    basis: str                 # "iou" | "containment" | "none"
    object_id: str | None
    iou: float                 # box IoU of the chosen SAM object with the Muse box
    containment: float         # share of the Muse box inside the chosen SAM object's box
    coverage: float            # share of the Muse box covered by the chosen SAM mask
    mask_inside: float         # share of the chosen SAM mask lying inside the Muse box (diagnostic)
    area_ratio: float          # SAM box area / Muse box area

    def note(self, concept: str) -> str:
        if self.object_id is None:
            return f"SAM found no '{concept}'"
        verdict = {"iou": "corroborated by box IoU", "containment": "corroborated by containment",
                   "none": "not corroborated"}[self.basis]
        return (f"best SAM '{concept}' object {self.object_id}: box IoU {self.iou:.2f}, Muse box {self.containment:.0%} "
                f"inside its box, mask covers {self.coverage:.0%} of the Muse box, {self.mask_inside:.0%} of the mask "
                f"inside it, area ratio {self.area_ratio:.2f} -> {verdict}")


def _box_inside(inner, outer) -> float:
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return ix * iy / max(1.0, box_area(inner))


def device_corroboration(muse_box, objects) -> DeviceDecision:
    """Does one SAM object coincide with the device Muse boxed? objects: [(object_id, sam_box_px, full-image mask)].

    Route 1 (unchanged): box IoU >= DEVICE_IOU_MIN. Route 2: containment (see the constants). Each object is judged
    on its own, so a different object of the same concept (SAM 'router' also returns the switch) never counts for
    this device. Report-level only: device corroboration is not evidence of any connection and no verdict uses it.
    """
    scored = []
    for oid, sb, m in objects:
        inside = mask_pixels_in_box(m, muse_box)
        mb_area = max(1.0, box_area(muse_box))
        scored.append(DeviceDecision(False, "none", oid, box_iou(muse_box, sb), _box_inside(muse_box, sb),
                                     inside / mb_area, inside / max(1, int(m.sum())), box_area(sb) / mb_area))
    if not scored:
        return DeviceDecision(False, "none", None, 0.0, 0.0, 0.0, 0.0, 0.0)
    best_iou = max(scored, key=lambda d: d.iou)
    if best_iou.iou >= DEVICE_IOU_MIN:
        return dataclasses.replace(best_iou, corroborated=True, basis="iou")
    contained = [d for d in scored if d.containment >= DEVICE_CONTAIN_MIN and d.coverage >= DEVICE_COVER_MIN
                 and d.area_ratio <= DEVICE_MAX_AREA_RATIO]
    if contained:
        return dataclasses.replace(max(contained, key=lambda d: d.coverage), corroborated=True, basis="containment")
    return best_iou


def link_devices(ext: ObservationExtraction, run: GroundingRun, device_concepts: dict[str, str],
                 width: int, height: int) -> dict[str, GroundingLink]:
    links: dict[str, GroundingLink] = {}
    for d in ext.devices:
        if not d.spec_device_id or d.spec_device_id not in device_concepts:
            continue
        concept = device_concepts[d.spec_device_id]
        g = next((x for x in run.groundings if x.concept == concept), None)
        if g is None or g.status != "ok":
            links[d.ref] = GroundingLink(concept=concept, sam_object_id=None, corroborated=False,
                                         note="SAM not run or failed for this concept")
            continue
        if d.box is None:
            links[d.ref] = GroundingLink(concept=concept, sam_object_id=None, corroborated=False,
                                         note="Muse gave no box for this device")
            continue
        mb = d.box.to_pixels(width, height)
        objs = [(o.object_id, o.box_px, run.masks[(concept, o.object_id)]) for o in g.objects
                if (concept, o.object_id) in run.masks]
        dec = device_corroboration(mb, objs)
        links[d.ref] = GroundingLink(
            concept=concept, sam_object_id=dec.object_id, iou=round(dec.iou, 3),
            corroborated=dec.corroborated, note=dec.note(concept))
    return links


def link_ports(ext: ObservationExtraction, run: GroundingRun, cable_concepts: list[str],
               width: int, height: int) -> dict[str, GroundingLink]:
    """For every occupied port with a box, test whether a SAM cable mask reaches into it."""
    links: dict[str, GroundingLink] = {}
    for p in ext.ports:
        if p.occupancy != "cable_inserted":
            continue
        for concept in cable_concepts:
            key = f"{p.ref}|{concept}"
            g = next((x for x in run.groundings if x.concept == concept), None)
            if g is None or g.status != "ok":
                links[key] = GroundingLink(concept=concept, sam_object_id=None, corroborated=False,
                                           note="SAM not run or failed for this concept")
                continue
            if p.box is None:
                links[key] = GroundingLink(concept=concept, sam_object_id=None, corroborated=False,
                                           note="Muse gave no box for this port")
                continue
            region = expand_box(p.box.to_pixels(width, height), PORT_EXPAND, width, height)
            area = max(1.0, (region[2] - region[0]) * (region[3] - region[1]))
            best_id, best_px = None, 0
            for o in g.objects:
                px = mask_pixels_in_box(run.masks[(concept, o.object_id)], region)
                if px > best_px:
                    best_id, best_px = o.object_id, px
            ok = best_px >= max(PORT_MIN_PX, PORT_MIN_FRAC * area)
            links[key] = GroundingLink(
                concept=concept, sam_object_id=best_id, overlap_px=best_px, corroborated=ok,
                note=(f"SAM '{concept}' mask covers {best_px}px of the port region"
                      if best_id else f"no SAM '{concept}' mask reaches the port region"))
    return links
