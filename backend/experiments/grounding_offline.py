"""Offline grounding-geometry measurement on RECORDED live runs (no API calls, no network).

    python experiments/grounding_offline.py [--runs ../runs]

For every recorded run directory (report.json + trace.jsonl + images/), it re-decodes the SAM output that was
recorded live (trace `response_text`, the raw SAM token stream incl. masks) with the production parser, and
compares it with the Muse boxes recorded in the same run:

  devices: box IoU (current rule), mask coverage of the Muse box, share of the mask inside the Muse box, SAM/Muse box
           area ratio, and the current vs the proposed (containment) corroboration decision;
  ports:   for every occupied port, which ports of the same device the same cable mask would corroborate under the
           current expanded-region rule (is port grounding specific to one port?).

Inputs are model outputs recorded on 2026-10-31/11-02; nothing is re-run. Results -> runs/grounding-offline-<ts>/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofcam.config import REPO_ROOT  # noqa: E402
from proofcam.evidence import ObservationRecord  # noqa: E402
from proofcam.geometry import box_area, box_iou, expand_box, mask_pixels_in_box, mask_to_image  # noqa: E402
from proofcam.grounding import PORT_EXPAND, PORT_MIN_FRAC, PORT_MIN_PX, device_corroboration  # noqa: E402
from proofcam.images import NormalizedImage  # noqa: E402
from proofcam.meta_client import _parse_sam_events  # noqa: E402


def sam_events(raw: str) -> list[dict]:
    lane = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
    evs: list[dict] = [{"type": "response.created", "response": {"id": "r"}}]
    if raw:
        evs += [{"type": "response.output_text.delta", "delta": raw, **lane},
                {"type": "response.output_text.done", "text": raw, **lane}]
    return evs + [{"type": "response.completed", "response": {"id": "r", "usage": None}}]


def _contained(inner, outer) -> float:
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return ix * iy / max(1.0, box_area(inner))


def run_dirs(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.rglob("report.json")
                  if (p.parent / "trace.jsonl").exists() and (p.parent / "images").is_dir())


async def measure(root: Path) -> dict:
    devices, ports = [], []
    for d in run_dirs(root):
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        concepts = {dv["id"]: dv["sam_concept"] for dv in report["spec"]["devices"]}
        cable_concepts = sorted({r.get("sam_concept") or f"{r['cable_color']} {r.get('cable_type', 'ethernet cable')}"
                                 for r in report["spec"]["requirements"]})
        sam: dict[tuple[str, str], str] = {}
        for line in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e["kind"] == "model_call" and e["name"].startswith("sam_segment:") and e["status"] == "ok":
                sam[(e["image_id"], e["name"].split(":", 1)[1])] = e.get("response_text") or ""
        if not sam:  # offline replays: no SAM output was recorded in this run
            continue
        for od in report["observations"]:
            o = ObservationRecord.model_validate(od)
            img_path = d / "images" / f"{o.seq:02d}_{o.image_id}.jpg"
            if o.extraction is None or not img_path.exists():
                continue
            img = NormalizedImage.from_stored(o.image_id, o.source_name, o.width, o.height, img_path.read_bytes(),
                                              (o.width, o.height))
            masks: dict[str, list] = {}
            for (iid, concept), raw in sam.items():
                if iid != o.image_id:
                    continue
                seg = await _parse_sam_events(sam_events(raw), img, concept)
                masks[concept] = [(ob, mask_to_image(ob.mask, img.width, img.height)) for ob in seg.objects]
            run = f"{d.relative_to(root).as_posix()}#{o.seq}"
            for dev in o.extraction.devices:
                if not dev.spec_device_id or dev.box is None or dev.spec_device_id not in concepts:
                    continue
                concept = concepts[dev.spec_device_id]
                if concept not in masks:
                    devices.append({"run": run, "image": o.source_name, "device": dev.spec_device_id,
                                    "concept": concept, "sam_objects": None})
                    continue
                mb = dev.box.to_pixels(img.width, img.height)
                objs = masks[concept]
                row = {"run": run, "image": o.source_name, "device": dev.spec_device_id, "concept": concept,
                       "sam_objects": len(objs), "muse_box": mb}
                if objs:
                    best = max(objs, key=lambda x: box_iou(mb, x[0].box))
                    m = best[1]
                    inside = mask_pixels_in_box(m, mb)
                    row.update(containment=round(_contained(mb, best[0].box), 3),
                               iou=round(box_iou(mb, best[0].box), 3),
                               coverage=round(inside / max(1.0, box_area(mb)), 3),
                               mask_inside=round(inside / max(1, int(m.sum())), 3),
                               area_ratio=round(box_area(best[0].box) / max(1.0, box_area(mb)), 2),
                               recorded_corroborated=o.device_links.get(dev.ref).corroborated
                               if dev.ref in o.device_links else None)
                    dec = device_corroboration(mb, [(x[0].object_id, x[0].box, x[1]) for x in objs])
                    row.update(proposed_corroborated=dec.corroborated, proposed_basis=dec.basis,
                               proposed_object=dec.object_id, best_iou_object=best[0].object_id)
                devices.append(row)
            for p in o.extraction.ports:
                if p.occupancy != "cable_inserted" or p.box is None:
                    continue
                for concept in cable_concepts:
                    objs = masks.get(concept) or []
                    same_dev = [q for q in o.extraction.ports if q.device_ref == p.device_ref and q.box is not None]
                    hits, overlap = {}, {}
                    for q in same_dev:
                        region = expand_box(q.box.to_pixels(img.width, img.height), PORT_EXPAND, img.width, img.height)
                        area = max(1.0, box_area(region))
                        best = max((mask_pixels_in_box(m, region) for _, m in objs), default=0)
                        hits[q.ref] = best >= max(PORT_MIN_PX, PORT_MIN_FRAC * area)
                        overlap[q.ref] = best
                    ports.append({"run": run, "image": o.source_name, "port": p.ref, "label": p.label_read,
                                  "concept": concept, "cable_masks": len(objs),
                                  "corroborated": hits.get(p.ref, False), "overlap_px": overlap,
                                  "occupancy": {q.ref: q.occupancy for q in same_dev},
                                  "also_corroborated": sorted(k for k, v in hits.items() if v and k != p.ref),
                                  "also_corroborated_empty": sorted(
                                      q.ref for q in same_dev if q.ref != p.ref and hits.get(q.ref)
                                      and q.occupancy == "empty")})
    return {"devices": devices, "ports": ports}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=str(REPO_ROOT / "runs"))
    args = ap.parse_args()
    root = Path(args.runs)
    res = asyncio.run(measure(root))
    out = root / f"grounding-offline-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir()
    (out / "measurements.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{'run':52} {'image':28} {'dev':7} {'n':>2} {'IoU':>5} {'cov':>5} {'in':>5} {'area':>5} rec  new")
    for r in res["devices"]:
        if r.get("sam_objects") is None:
            print(f"{r['run'][:52]:52} {r['image'][:28]:28} {r['device']:7}  - (SAM not run for '{r['concept']}')")
            continue
        if not r["sam_objects"]:
            print(f"{r['run'][:52]:52} {r['image'][:28]:28} {r['device']:7}  0 (SAM found no '{r['concept']}')")
            continue
        print(f"{r['run'][:52]:52} {r['image'][:28]:28} {r['device']:7} {r['sam_objects']:>2} {r['iou']:>5} "
              f"{r['coverage']:>5} {r['mask_inside']:>5} {r['area_ratio']:>5} {str(r['recorded_corroborated'])[0]}    "
              f"{str(r['proposed_corroborated'])[0]} {r['proposed_basis']}")
    print("\nports (occupied): own-port corroborated / other ports of the device the same mask also corroborates")
    for r in res["ports"]:
        print(f"{r['run'][:52]:52} {r['image'][:28]:28} {r['port']:4} label={str(r['label']):8} "
              f"masks={r['cable_masks']} own={str(r['corroborated'])[0]} also={r['also_corroborated']} "
              f"(empty: {r['also_corroborated_empty']})")
    print(f"\n-> {out / 'measurements.json'}")


if __name__ == "__main__":
    main()
