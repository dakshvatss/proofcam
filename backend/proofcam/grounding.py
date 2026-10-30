"""SAM 3.1 visual grounding and its link to Muse claims.

SAM locates instances of a concept. It does NOT establish connection semantics. We use it only
to check that a Muse claim ("a blue plug is in this port", "the router is here") coincides with
a real segmented region on the same image.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import numpy as np

from .evidence import GroundingLink, SamGrounding, SamObjectSummary
from .geometry import box_iou, expand_box, mask_pixels_in_box, mask_to_image
from .images import NormalizedImage
from .meta_client import MetaAPIError, MetaClient, SamSegmentation
from .observation import ObservationExtraction

DEVICE_IOU_MIN = 0.5
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
        best = max(g.objects, key=lambda o: box_iou(mb, o.box_px), default=None)
        iou = box_iou(mb, best.box_px) if best else 0.0
        links[d.ref] = GroundingLink(
            concept=concept, sam_object_id=best.object_id if best else None, iou=round(iou, 3),
            corroborated=iou >= DEVICE_IOU_MIN,
            note=f"best SAM '{concept}' box IoU {iou:.2f}" if best else f"SAM found no '{concept}'")
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
