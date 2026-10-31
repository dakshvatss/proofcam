"""LIVE reference-image scenarios. Each image is an INDEPENDENT inspection (own spec, fresh agent).

    python experiments/run_scenarios.py [--only s04]

These reference photos come from different setups; nothing here combines them, and a single photo
can never verify a two-ended connection. Output: runs/scenarios-<ts>/<scenario>/ + summary.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofcam.agent import InspectionAgent  # noqa: E402
from proofcam.config import REPO_ROOT, Settings  # noqa: E402
from proofcam.images import load_image  # noqa: E402
from proofcam.meta_client import MetaClient  # noqa: E402
from proofcam.report import write_report  # noqa: E402
from proofcam.spec import InspectionSpec  # noqa: E402
from proofcam.trace import Trace  # noqa: E402

SCENARIOS = [
    ("s01", "01_white_rear.png", "s01_white_rear.json"),
    ("s02", "02_white_front.png", "s02_white_front.json"),
    ("s03", "03_asus_front.png", "s03_asus_front.json"),
    ("s04", "04_blue_cable.png", "s04_blue_cable.json"),
    ("s05", "05_laptop_router.png", "s05_laptop_router.json"),
]


async def run_one(settings: Settings, sid: str, image: str, spec_file: str, out: Path) -> dict:
    spec = InspectionSpec.load(REPO_ROOT / "data" / "specs" / "reference" / spec_file)
    trace = Trace()
    client = MetaClient(settings, trace)
    agent = InspectionAgent(spec, client, settings)
    img = load_image(REPO_ROOT / "data" / "images" / image, settings.image_max_side)
    t0 = time.perf_counter()
    error = None
    step = None
    try:
        step = await agent.observe(img)
    except Exception as e:  # report, never hide
        error = f"{type(e).__name__}: {e}"
    wall = (time.perf_counter() - t0) * 1000
    await client.aclose()
    if agent.observations:
        write_report(agent, out / sid)
    o = agent.observations[0] if agent.observations else None
    return {
        "scenario": sid, "image": image, "image_id": img.image_id, "size": [img.width, img.height],
        "wall_ms": round(wall), "error": error,
        "extraction": o.extraction.model_dump() if o and o.extraction else None,
        "extraction_error": o.extraction_error if o else None,
        "sam": [g.model_dump() for g in o.sam] if o else [],
        "device_links": {k: v.model_dump() for k, v in o.device_links.items()} if o else {},
        "port_links": {k: v.model_dump() for k, v in o.port_links.items()} if o else {},
        "verdicts": [{"id": a.requirement_id, "status": a.status, "explanation": a.explanation,
                      "endpoints": [(ep.device_id, ep.port_label, ep.state) for ep in a.endpoints],
                      "gaps": [g.code for g in a.gaps]} for a in agent.assessments],
        "next_view": step.next_view.model_dump() if step and step.next_view else None,
        "stop_reason": agent.stop_reason, "notes": step.notes if step else [],
        "calls": [{"name": e.name, "model": e.model, "ms": round(e.latency_ms or 0), "status": e.status,
                   "http": e.http_status, "attempts": e.attempts, "usage": e.usage, "error": e.error}
                  for e in trace.model_calls()],
        "usage": trace.summary(),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    a = ap.parse_args()
    settings = Settings.from_env()
    out = REPO_ROOT / "runs" / f"scenarios-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    results = []
    for sid, image, spec in SCENARIOS:
        if a.only and sid != a.only:
            continue
        print(f"--- {sid} {image}", flush=True)
        r = await run_one(settings, sid, image, spec, out)
        results.append(r)
        print(json.dumps({k: r[k] for k in ("wall_ms", "error", "verdicts", "stop_reason")}, default=str)[:600])
        if r["next_view"]:
            print("  NEXT VIEW:", r["next_view"]["instruction"])
    (out / "summary.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main())
