"""Local development server for the M3 frontend with MOCKED Meta models. No network, no API key, no cost.

The real FastAPI app, service, store and deterministic policy run unchanged; only the Meta transport is replaced by
the test double from tests/fakes.py, which answers with a scripted scenario (canned Muse JSON, SAM masks scaled to
the uploaded photo). Every model call is traced with source="mock" and /api/health reports model_source "mock".
Nothing here is real inference: verdicts depend on the script, not on what the photo shows.

    cd backend
    .venv/Scripts/python.exe experiments/dev_mock_server.py                     # scenario "verify", port 8000
    .venv/Scripts/python.exe experiments/dev_mock_server.py --scenario review
    .venv/Scripts/python.exe experiments/dev_mock_server.py --export-fixtures ../frontend/src/test/fixtures

Scenarios (each photo consumes the next scripted observation; the script repeats):
  verify   photo 1: both devices from the front (ports not visible) -> guidance; photo 2: rear view -> VERIFIED
  review   photo 1: cable traced to switch port 4; photo 2: traced to port 3 -> contradiction -> review stop;
           after "installation changed", photo 3: rear view -> VERIFIED
  violated photo 1: router LAN 1 clearly empty -> VIOLATED
  hidden   every photo: blue plug in a router port whose label is hidden -> LABEL_ILLEGIBLE guidance (repeats)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import sys
from pathlib import Path

import httpx
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / "tests")]

from fakes import FakeMeta, H, W, cable, device, extraction, plan, port, sam_record  # noqa: E402
from proofcam.api import create_app  # noqa: E402
from proofcam.config import REPO_ROOT, Budget, Settings  # noqa: E402
from proofcam.service import ServiceConfig  # noqa: E402
from proofcam.store import Store  # noqa: E402

OBS, PLAN = "ObservationExtraction", "NextViewPlan"
R_BOX, S_BOX = (50, 100, 450, 600), (550, 100, 950, 600)
FRONT = extraction(devices=[device("D1", "router", side="front", ports=False, box=R_BOX),
                            device("D2", "switch", side="front", ports=False, box=S_BOX)],
                   summary="[MOCK] router and switch seen from the front")


def rear(switch_label: str) -> dict:
    return extraction(devices=[device("D1", "router", box=R_BOX), device("D2", "switch", box=S_BOX)],
                      ports=[port("P1", "D1", "1", group="LAN", box=(200, 400, 260, 480)),
                             port("P2", "D2", switch_label, box=(600, 400, 660, 480))],
                      cables=[cable("C1", "blue", ["P1", "P2"], path="fully_traced")],
                      summary=f"[MOCK] rear view, blue cable traced to switch port {switch_label}")


EMPTY_LAN1 = extraction(devices=[device("D1", "router", box=R_BOX)],
                        ports=[port("P1", "D1", "1", group="LAN", occ="empty", color=None)],
                        summary="[MOCK] router rear, LAN 1 empty")
HIDDEN = extraction(devices=[device("D1", "router", box=R_BOX)],
                    ports=[port("P1", "D1", None, legible="illegible", box=(200, 400, 260, 480))],
                    summary="[MOCK] router rear, label under the plug unreadable")

SCENARIOS = {"verify": [FRONT, rear("3")], "review": [rear("4"), rear("3"), rear("3")],
             "violated": [EMPTY_LAN1], "hidden": [HIDDEN]}
PLAN_MOCK = plan(instruction="[MOCK] Walk around to the back of the router and switch and frame both port rows "
                             "so the printed labels can be read.", action="move_to_rear")
# SAM boxes defined on a 400x300 image (as in the tests), scaled to the uploaded photo's normalized size.
SAM_BOXES = {"blue ethernet cable": (80, 120, 270, 150), "router": (20, 30, 180, 180)}


class ScriptedMeta(FakeMeta):
    def __init__(self, script: list[dict]) -> None:
        super().__init__()
        self.script = script

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.chat[OBS]:
            self.queue_chat(OBS, *self.script)
        if not self.chat[PLAN]:
            self.queue_chat(PLAN, PLAN_MOCK)
        if request.url.path.endswith("/responses"):
            body = json.loads(request.content)
            content = body["input"][0]["content"]
            data_url = next(c["image_url"] for c in content if c.get("type") == "input_image")
            w, h = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).size
            self.sam = {}
            for concept, (x1, y1, x2, y2) in SAM_BOXES.items():
                sx, sy = w / W, h / H
                self.sam[concept] = sam_record(0, (int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)), w=w, h=h)
        return super().handler(request)


def build_app(scenario: str, db: Path, access_code: str | None = None):
    settings = Settings(api_key="mock-no-real-key", api_base="https://mock.invalid/v1", max_retries=0,
                        budget=Budget())
    fm = ScriptedMeta(SCENARIOS[scenario])
    store = Store(db)
    # Same access boundary as the real server: without an access code, only this computer is served.
    app = create_app(settings, store, httpx.MockTransport(fm.handler),
                     config=ServiceConfig(model_source="mock"), owns_store=True, access_code=access_code,
                     local_only=True)
    return app


def synthetic_photo(name: str, size=(800, 600)) -> bytes:
    """A flat-colour synthetic JPEG (not a photograph)."""
    import hashlib
    buf = io.BytesIO()
    Image.new("RGB", size, tuple(hashlib.sha256(name.encode()).digest()[:3])).save(buf, "JPEG")
    return buf.getvalue()


async def export_fixtures(out: Path, tmp: Path) -> None:
    """Record real API responses (mocked models) for the frontend tests."""
    out.mkdir(parents=True, exist_ok=True)
    saved: dict[str, object] = {}

    async def session(scenario: str, db: Path):
        app = build_app(scenario, db)
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
        return app, ctx, client

    async def capture(c, iid, name, key, responding_to=None):
        data = {"responding_to": responding_to} if responding_to else {}
        r = await c.post(f"/api/inspections/{iid}/captures", files={"file": (name, synthetic_photo(name), "image/jpeg")},
                         data=data, headers={"Idempotency-Key": key})
        assert r.status_code == 200, r.text
        return r.json()

    # verify scenario
    _app, ctx, c = await session("verify", tmp / "verify.db")
    st = (await c.post("/api/inspections", json={"spec_id": "my_setup"})).json()
    saved["created"] = st
    iid = st["id"]
    s1 = await capture(c, iid, "front.jpg", "fixture-key-1")
    saved["step1_guidance"] = s1
    saved["state_after_step1"] = (await c.get(f"/api/inspections/{iid}")).json()
    s2 = await capture(c, iid, "rear.jpg", "fixture-key-2", s1["next_view"]["id"])
    saved["step2_verified"] = s2
    saved["state_verified"] = (await c.get(f"/api/inspections/{iid}")).json()
    saved["report_md"] = (await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})).text
    await c.aclose()
    await ctx.__aexit__(None, None, None)

    # review scenario
    _app, ctx, c = await session("review", tmp / "review.db")
    iid = (await c.post("/api/inspections", json={"spec_id": "my_setup"})).json()["id"]
    r1 = await capture(c, iid, "to_port_4.jpg", "fixture-key-r1")
    r2 = await capture(c, iid, "to_port_3.jpg", "fixture-key-r2", r1["next_view"]["id"] if r1["next_view"] else None)
    saved["step_review"] = r2
    saved["state_review"] = (await c.get(f"/api/inspections/{iid}")).json()
    r = await c.post(f"/api/inspections/{iid}/events",
                     json={"type": "installation_changed", "reason": "moved the cable to port 3"})
    saved["state_after_change"] = r.json()
    await c.aclose()
    await ctx.__aexit__(None, None, None)

    for name, value in saved.items():
        if isinstance(value, str):
            (out / f"{name}.md").write_text(value, encoding="utf-8")
        else:
            (out / f"{name}.json").write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(saved)} fixtures to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="verify")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", type=Path, default=REPO_ROOT / "var" / "dev-mock.db",
                    help="SQLite file (git-ignored var/ by default); separate from the real var/proofcam.db")
    ap.add_argument("--export-fixtures", type=Path, help="write frontend test fixtures to this directory and exit")
    ap.add_argument("--access-code", default=os.environ.get("PROOFCAM_ACCESS_CODE") or None,
                    help="require this access code (>= 12 chars; default: PROOFCAM_ACCESS_CODE). Needed for phone access")
    args = ap.parse_args()
    if args.export_fixtures:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(export_fixtures(args.export_fixtures.resolve(), Path(tmp)))
        return
    import uvicorn
    args.db.parent.mkdir(parents=True, exist_ok=True)
    print(f"[MOCK MODELS] scenario={args.scenario} db={args.db} -> http://127.0.0.1:{args.port}  (no Meta calls)")
    print("access code: " + ("required" if args.access_code else "none -> this computer only"))
    uvicorn.run(build_app(args.scenario, args.db, args.access_code), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
