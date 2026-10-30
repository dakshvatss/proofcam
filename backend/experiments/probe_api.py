"""Live Meta Model API probe: verifies our request formats against the real service.

    python experiments/probe_api.py [--image path/to/photo.jpg] [--concept router]

Makes 4 real calls (~$0.01): text ping, structured output (text), structured output + image, SAM 3.1.
Without --image it uses a SYNTHETIC generated image, which only tests wire formats, never model quality.
Results are printed and saved to runs/probe-<timestamp>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from proofcam.config import REPO_ROOT, Settings  # noqa: E402
from proofcam.images import load_image, normalize_image_bytes  # noqa: E402
from proofcam.meta_client import MetaAPIError, MetaClient  # noqa: E402
from proofcam.trace import Trace  # noqa: E402

TINY = {"type": "object", "properties": {"answer": {"type": "string"}, "count": {"type": "integer"},
                                          "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                                          "kind": {"type": "string", "enum": ["a", "b"]}},
        "required": ["answer", "count", "maybe", "kind"], "additionalProperties": False}


def synthetic():
    img = Image.new("RGB", (640, 480), (235, 235, 235))
    d = ImageDraw.Draw(img)
    d.rectangle([80, 160, 360, 300], fill=(30, 30, 30))       # "device"
    d.rectangle([380, 220, 600, 240], fill=(30, 90, 220))     # "blue cable"
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return normalize_image_bytes(buf.getvalue(), "SYNTHETIC_probe.jpg")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--concept", default="blue cable")
    a = ap.parse_args()
    s = Settings.from_env()
    trace = Trace()
    c = MetaClient(s, trace)
    img = load_image(a.image) if a.image else synthetic()
    out: dict = {"image": img.source_name, "synthetic": not a.image, "size": [img.width, img.height], "steps": {}}

    async def step(name, coro):
        t0 = time.perf_counter()
        try:
            r = await coro
            out["steps"][name] = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "result": r}
        except MetaAPIError as e:
            out["steps"][name] = {"ok": False, "ms": round((time.perf_counter() - t0) * 1000),
                                  "status": e.status, "code": e.code, "error": str(e)}
        print(f"[{name}] {json.dumps(out['steps'][name], default=str)[:800]}")

    async def ping():
        r = await c._http.post("/chat/completions", timeout=60, json={
            "model": s.muse_model, "messages": [{"role": "user", "content": "Reply with the single word: ready"}]})
        if r.status_code != 200:
            raise MetaAPIError(f"HTTP {r.status_code}: {r.text[:300]}", status=r.status_code)
        j = r.json()
        return {"content": j["choices"][0]["message"]["content"], "usage": j.get("usage")}

    await step("chat_ping", ping())
    await step("structured_text", c.chat_structured(
        messages=[{"role": "user", "content": "Answer 'hello', count 3, maybe null, kind a."}],
        schema_name="Tiny", schema=TINY, image=None, purpose="probe_structured_text"))
    await step("structured_image", c.chat_structured(
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Describe the main object in 'answer', count distinct objects, "
                                     "maybe=null, kind=a."},
            {"type": "image_url", "image_url": {"url": img.data_url()}}]}],
        schema_name="Tiny", schema=TINY, image=img, purpose="probe_structured_image"))

    async def sam():
        seg = await c.sam_segment(img, a.concept)
        return {"objects": [{"id": o.object_id, "box": o.box, "conf": o.confidence} for o in seg.objects],
                "diagnostics": seg.diagnostics, "raw_prefix": seg.raw_output[:200]}

    await step("sam", sam())
    await c.aclose()
    out["trace_summary"] = trace.summary()
    p = REPO_ROOT / "runs" / f"probe-{time.strftime('%Y%m%d-%H%M%S')}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({**out, "trace": [e.model_dump() for e in trace.events]}, indent=2, default=str))
    print(f"\nSaved {p}")


if __name__ == "__main__":
    asyncio.run(main())
