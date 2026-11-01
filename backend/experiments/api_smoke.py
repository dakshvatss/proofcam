"""Controlled LIVE smoke test of the M1 HTTP API (FastAPI -> service -> SQLite -> agent -> real Meta API).

    python experiments/api_smoke.py [--image ../data/images/m2_router_rear_close.png] [--max-calls 8]

ONE inspection (spec my_setup), ONE photo. Model calls are hard-capped by the persistent budget: the store refuses
to reserve, and the client never sends, any request beyond --max-calls (default 8; expected ~5, ~$0.04).
Uses the in-process ASGI app with the real network for model calls, a fresh database under runs/api-smoke-<ts>/
(git-ignored; it contains the photo), then "restarts" (new app + Store on the same file) and reads everything back.
Prints a summary and PASS/FAIL per criterion; never prints the API key.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from proofcam.api import create_app  # noqa: E402
from proofcam.config import REPO_ROOT, Budget, Settings  # noqa: E402
from proofcam.service import ServiceConfig  # noqa: E402
from proofcam.store import Store  # noqa: E402


async def _client(settings: Settings, db: Path):
    store = Store(db)
    app = create_app(settings, store, None, config=ServiceConfig(model_source="live"))
    return app, store


async def main(args: argparse.Namespace) -> int:
    base = Settings.from_env()
    settings = dataclasses.replace(base, budget=Budget(max_model_calls=args.max_calls))
    key = base.api_key
    image = Path(args.image)
    out = REPO_ROOT / "runs" / f"api-smoke-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    db = out / "proofcam.db"
    bodies: list[bytes] = []
    checks: dict[str, bool] = {}

    async def keep(r: httpx.Response) -> None:
        await r.aread()
        bodies.append(r.content)

    # ---- server 1: create + one live capture
    app, store = await _client(settings, db)
    t0 = time.perf_counter()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://smoke", timeout=600, event_hooks={"response": [keep]}) as c:
            r = await c.post("/api/inspections", json={"spec_id": "my_setup"})
            iid = r.json()["id"]
            r = await c.post(f"/api/inspections/{iid}/captures", headers={"Idempotency-Key": "smoke-1"},
                             files={"file": (image.name, image.read_bytes(), "image/png")})
            capture_status, step = r.status_code, r.json()
    elapsed = time.perf_counter() - t0
    calls = store.list_model_calls(iid)
    rec = store.get_inspection(iid)
    store.close()

    # ---- server 2 ("restart"): read everything back, no model calls possible on these routes
    app, store = await _client(settings, db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://smoke", timeout=60, event_hooks={"response": [keep]}) as c:
            state = (await c.get(f"/api/inspections/{iid}")).json()
            report = await c.get(f"/api/inspections/{iid}/report")
            md = await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})
            photo = state["photos"][0] if state.get("photos") else None
            ph = await c.get(photo["photo_url"]) if photo else None
            ov = await c.get(photo["overlay_url"]) if photo and photo["overlay_url"] else None
            replay = await c.post(f"/api/inspections/{iid}/captures", headers={"Idempotency-Key": "smoke-1"},
                                  files={"file": (image.name, image.read_bytes(), "image/png")})
    trace = store.load_restore_bundle(iid).trace_events
    calls_after = store.list_model_calls(iid)
    store.close()

    (out / "report.json").write_text(report.text, encoding="utf-8")
    (out / "report.md").write_text(md.text, encoding="utf-8")
    if ov is not None and ov.status_code == 200:
        (out / "overlay.jpg").write_bytes(ov.content)

    model_events = [e for e in trace if e.kind == "model_call"]
    db_bytes = b"".join(p.read_bytes() for p in out.glob("proofcam.db*"))
    leaked = any(key.encode() in b for b in bodies) or key.encode() in db_bytes

    a = step.get("assessments", [{}])[0] if capture_status == 200 else {}
    checks["capture HTTP 200"] = capture_status == 200
    checks["trace source = live"] = bool(model_events) and {e.source for e in model_events} == {"live"}
    checks["reservations == HTTP attempts recorded"] = (
        rec.model_calls_reserved == len(calls)
        and sum((e.attempts or 1) for e in model_events) <= len(calls))
    checks[f"within cap ({args.max_calls})"] = len(calls) <= args.max_calls
    checks["all reservations settled"] = all(x.status in ("ok", "error") for x in calls)
    checks["verdict is not VERIFIED"] = a.get("status") != "VERIFIED"
    checks["state/report/md after restart"] = (state.get("id") == iid and report.status_code == 200
                                               and md.status_code == 200)
    checks["photo + overlay retrievable"] = (ph is not None and ph.status_code == 200 and ov is not None
                                             and ov.status_code == 200)
    checks["idempotent replay: no new calls"] = (replay.status_code == 200 and replay.json().get("replayed") is True
                                                 and len(calls_after) == len(calls))
    checks["key absent from DB and responses"] = not leaked

    summary = {
        "inspection_id": iid, "image": image.name, "elapsed_s": round(elapsed, 1), "capture_status": capture_status,
        "verdict": a.get("status"), "explanation": a.get("explanation"),
        "endpoints": [(e["device_id"], e["port_label"], e["state"]) for e in a.get("endpoints", [])],
        "gaps": [g["code"] for g in a.get("gaps", [])], "notes": step.get("notes"),
        "next_view": (step.get("next_view") or {}).get("instruction"),
        "next_view_planner": (step.get("next_view") or {}).get("planner"),
        "usage": step.get("usage"),
        "calls": [{"n": x.ordinal, "name": x.name, "status": x.status} for x in calls],
        "trace_latency_ms": {e.name: round(e.latency_ms or 0) for e in model_events},
        "checks": checks, "error": None if capture_status == 200 else step,
    }
    (out / "smoke_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nOutput: {out}")
    print("RESULT:", "PASS" if all(checks.values()) else "FAIL")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", default=str(REPO_ROOT / "data" / "images" / "m2_router_rear_close.png"))
    ap.add_argument("--max-calls", type=int, default=8)
    sys.exit(asyncio.run(main(ap.parse_args())))
