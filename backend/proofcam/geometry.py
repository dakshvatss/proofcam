"""Coordinate transforms between SAM output, Muse grounding boxes, and image pixels.

Conventions (all on the normalized image ProofCam sent to the models):
  * Pixel boxes are half-open (left, top, right, bottom). The SAM wire format uses
    inclusive x2/y2; meta_sam_parser already converts them to half-open.
  * A SAM mask raster is H rows x W cols, row-major, covering its record's box bounds.
"""

from __future__ import annotations

import numpy as np
from meta_sam_parser import SegmentationMaskRecord, decode_mask_to_raster
from PIL import Image

Box = tuple[float, float, float, float]


def mask_to_image(record: SegmentationMaskRecord, width: int, height: int) -> np.ndarray:
    """Place a box-local SAM mask into a full-image boolean array (height x width)."""
    m = record.mask
    raster = np.frombuffer(decode_mask_to_raster(m), dtype=np.uint8).reshape(m.height, m.width)
    left, top = int(record.bounds.left), int(record.bounds.top)
    bw = int(record.bounds.right) - left
    bh = int(record.bounds.bottom) - top
    if (bh, bw) != raster.shape:
        # Not observed in the docs' examples, but handled: scale raster to its bounds.
        img = Image.fromarray(raster * 255).resize((bw, bh), Image.Resampling.NEAREST)
        raster = (np.asarray(img) > 127).astype(np.uint8)
    full = np.zeros((height, width), dtype=bool)
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(width, left + bw), min(height, top + bh)
    if x1 > x0 and y1 > y0:
        full[y0:y1, x0:x1] = raster[y0 - top:y1 - top, x0 - left:x1 - left].astype(bool)
    return full


def box_area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def box_iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


def expand_box(b: Box, frac: float, width: int, height: int) -> Box:
    dx, dy = (b[2] - b[0]) * frac, (b[3] - b[1]) * frac
    return (max(0, b[0] - dx), max(0, b[1] - dy), min(width, b[2] + dx), min(height, b[3] + dy))


def mask_pixels_in_box(mask: np.ndarray, b: Box) -> int:
    x0, y0, x1, y1 = (int(round(v)) for v in b)
    return int(mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].sum())
