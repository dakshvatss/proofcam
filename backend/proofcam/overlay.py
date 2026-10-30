"""Render evidence overlays on the normalized captured image (never on a live preview).

Filled translucent regions + solid boxes  = real SAM 3.1 masks/boxes.
Thin dashed-style outlines                = Muse Spark grounding boxes (model claims, not masks).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .evidence import ObservationRecord
from .grounding import GroundingRun
from .images import NormalizedImage

_PALETTE = [(20, 184, 166), (244, 114, 182), (250, 204, 21), (96, 165, 250), (251, 146, 60)]
_MUSE = (255, 255, 255)


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _dashed_rect(draw: ImageDraw.ImageDraw, box, color, width=2, dash=10):
    x0, y0, x1, y1 = box
    for (a, b) in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
        length = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        steps = max(1, int(length // dash))
        for i in range(0, steps, 2):
            t0, t1 = i / steps, min(1, (i + 1) / steps)
            draw.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                       (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=color, width=width)


def render_overlay(image: NormalizedImage, rec: ObservationRecord, run: GroundingRun | None, path: Path) -> Path:
    base = image.pil().convert("RGBA")
    w, h = base.size
    font = _font(max(12, w // 80))
    layer = np.zeros((h, w, 4), dtype=np.uint8)
    concepts = [g.concept for g in rec.sam]
    if run is not None:
        for (concept, _oid), mask in run.masks.items():
            r, g, b = _PALETTE[concepts.index(concept) % len(_PALETTE)]
            layer[mask] = (r, g, b, 110)
    img = Image.alpha_composite(base, Image.fromarray(layer, "RGBA"))
    draw = ImageDraw.Draw(img)
    for gi, g in enumerate(rec.sam):
        color = _PALETTE[gi % len(_PALETTE)]
        for o in g.objects:
            x0, y0, x1, y1 = o.box_px
            draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=color, width=3)
            conf = f" {o.confidence:.2f}" if o.confidence is not None else ""
            draw.text((x0 + 3, max(0, y0 - font.size - 4)), f"SAM {g.concept}#{o.object_id}{conf}",
                      fill=color, font=font)
    if rec.extraction is not None:
        for d in rec.extraction.devices:
            if d.box:
                bx = d.box.to_pixels(w, h)
                _dashed_rect(draw, bx, _MUSE)
                draw.text((bx[0] + 3, bx[3] + 2), f"Muse {d.ref}:{d.spec_device_id or '?'}", fill=_MUSE, font=font)
        for p in rec.extraction.ports:
            if p.box:
                bx = p.box.to_pixels(w, h)
                _dashed_rect(draw, bx, (255, 230, 120), width=2, dash=6)
                draw.text((bx[0], bx[3] + 1), f"{p.ref}:{p.label_read or '?'}", fill=(255, 230, 120), font=font)
    legend = "Filled/solid = SAM 3.1 mask+box | dashed = Muse Spark box (claim) | " + image.image_id
    draw.rectangle([0, h - font.size - 8, w, h], fill=(17, 17, 17, 220))
    draw.text((6, h - font.size - 6), legend, fill=(230, 230, 230), font=font)
    img.convert("RGB").save(path, quality=90)
    return path
