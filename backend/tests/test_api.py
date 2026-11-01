"""M1 Stage 3: HTTP API over the service. httpx.AsyncClient + ASGITransport (app lifespan run explicitly);
temporary SQLite databases; mocked Meta responses only (FakeMeta)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from fakes import FakeMeta, plan, settings
from proofcam.api import create_app
from proofcam.images import normalize_image_bytes
from proofcam.service import ServiceConfig
from proofcam.store import Store
from test_agent import FRONT, OBS, PLAN, REAR_BOTH, SPEC, base_fake
from test_service import Gate, photo, two_photo_fake

FORBIDDEN = (b"test-key", b"Bearer", b"bearer", b"authorization", b"Authorization", b"data:image/", b"Traceback")


@contextlib.asynccontextmanager
async def api(tmp_path: Path, transport: httpx.AsyncBaseTransport | FakeMeta, budget: dict | None = None,
              bodies: list[bytes] | None = None, **cfg):
    if isinstance(transport, FakeMeta):
        transport = httpx.MockTransport(transport.handler)
    store = Store(tmp_path / "var" / "proofcam.db")
    cfg.setdefault("model_source", "mock")
    app = create_app(settings(**(budget or {})), store, transport, config=ServiceConfig(**cfg))

    async def keep(r: httpx.Response) -> None:
        await r.aread()
        if bodies is not None:
            bodies.append(r.content + b"\n" + str(r.headers).encode())

    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                         base_url="http://proofcam.test", event_hooks={"response": [keep]}) as c:
                yield c, store
    finally:
        store.close()


def upload(name: str, data: bytes | None = None, **form):
    return {"files": {"file": (name, photo(name) if data is None else data, "image/jpeg")}, "data": form}


async def new_inspection(c: httpx.AsyncClient, **body) -> str:
    r = await c.post("/api/inspections", json=body or {"spec_id": "router_switch"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run(coro):
    return asyncio.run(coro)


def err(r: httpx.Response) -> tuple[int, str]:
    body = r.json()
    assert set(body) == {"error", "message"}, body
    return r.status_code, body["error"]


# ============================================================================ inspections

def test_create_get_and_not_found(tmp_path):
    async def go():
        async with api(tmp_path, base_fake()) as (c, _):
            r = await c.post("/api/inspections", json={"spec_id": "router_switch"})
            assert r.status_code == 201
            st = r.json()
            assert st["status"] == "open" and st["spec"]["id"] == SPEC.id and st["usage"]["model_calls"] == 0
            r = await c.get(f"/api/inspections/{st['id']}")
            assert r.status_code == 200 and r.json() == st
            assert err(await c.get("/api/inspections/insp_nope")) == (404, "not_found")
            assert err(await c.get("/api/no/such/route")) == (404, "not_found")
            r = await c.post("/api/inspections", json={"spec": SPEC.model_dump()})
            assert r.status_code == 201 and r.json()["spec_id"] is None
    run(go())


@pytest.mark.parametrize("body,expected", [
    ({"spec_id": "../secrets"}, (422, "invalid_request")),
    ({"spec_id": "..\\..\\x"}, (422, "invalid_request")),
    ({"spec_id": "/etc/passwd"}, (422, "invalid_request")),
    ({"spec_id": "router_switch.json"}, (422, "invalid_request")),
    ({"spec_id": "%2e%2e%2fx"}, (422, "invalid_request")),
    ({"spec_id": "reference"}, (404, "spec_not_found")),  # a directory, not an allow-listed spec file
    ({"spec_id": "does_not_exist"}, (404, "spec_not_found")),
    ({}, (422, "invalid_request")),
    ({"spec_id": "router_switch", "spec": SPEC.model_dump()}, (422, "invalid_request")),
    ({"spec": {"id": "x", "title": "t", "devices": [], "requirements": [], "extra": 1}}, (422, "invalid_request")),
    ({"spec": {"id": "x", "title": "t", "devices": [], "requirements": [
        {"id": "r", "text": "t", "cable_color": "blue",
         "endpoints": [{"device_id": "ghost", "port_label": "1"}, {"device_id": "ghost", "port_label": "2"}]}]}},
     (422, "invalid_request")),
])
def test_invalid_creation_requests(tmp_path, body, expected):
    async def go():
        async with api(tmp_path, base_fake()) as (c, store):
            assert err(await c.post("/api/inspections", json=body)) == expected
            assert store._conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0] == 0
    run(go())


# ============================================================================ captures, report, images, restart

def test_full_flow_survives_restart(tmp_path):
    async def go():
        fm = two_photo_fake()
        async with api(tmp_path, fm) as (c, _):
            iid = await new_inspection(c)
            r = await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"),
                             headers={"Idempotency-Key": "k1"})
            assert r.status_code == 200, r.text
            s1 = r.json()
            assert s1["seq"] == 1 and s1["next_view"]["id"] == "nv1" and s1["status"] == "open"
        async with api(tmp_path, fm) as (c, store):  # server restart
            r = await c.post(f"/api/inspections/{iid}/captures", **upload("rear.jpg", responding_to="nv1"))
            assert r.status_code == 200, r.text
            assert r.json()["assessments"][0]["status"] == "VERIFIED" and r.json()["status"] == "stopped"
            stored_overlay = store.load_overlay(iid, r.json()["image_id"])
        async with api(tmp_path, fm) as (c, store):  # restart again; read everything back
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["stop_reason"] == "all_requirements_resolved" and len(st["photos"]) == 2
            assert st["usage"]["model_calls"] == len(fm.requests) and st["policy_drift"] == []

            rep = await c.get(f"/api/inspections/{iid}/report")
            assert rep.status_code == 200 and rep.headers["content-type"].startswith("application/json")
            report = rep.json()
            assert report["requirements"][0]["status"] == "VERIFIED" and report["stop_reason"] == st["stop_reason"]
            assert set(report["overlays"]) == {p["image_id"] for p in st["photos"]}
            assert report["persistent_usage"]["model_calls"] == len(fm.requests)
            md = await c.get(f"/api/inspections/{iid}/report", params={"format": "md"})
            assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
            assert "[VERIFIED]" in md.text and "visually observable conditions only" in md.text
            assert err(await c.get(f"/api/inspections/{iid}/report", params={"format": "pdf"})) == \
                   (422, "invalid_request")

            for p, name in zip(st["photos"], ("front.jpg", "rear.jpg")):
                img = await c.get(p["photo_url"])
                assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
                assert img.content == normalize_image_bytes(photo(name), name).jpeg_bytes
                assert "img_" + hashlib.sha256(img.content).hexdigest()[:12] == p["image_id"]
                ov = await c.get(p["overlay_url"])
                assert ov.status_code == 200 and Image.open(io.BytesIO(ov.content)).size == (400, 300)
            assert (await c.get(st["photos"][1]["overlay_url"])).content == stored_overlay
            assert err(await c.get(f"/api/inspections/{iid}/photos/img_000000000000")) == (404, "photo_not_found")
            # encoded slashes do not even match the photo route: the router answers 404 before the store is touched
            assert err(await c.get(f"/api/inspections/{iid}/photos/..%2F..%2Fx")) == (404, "not_found")
            assert err(await c.get(f"/api/inspections/{iid}/photos/img_..")) == (404, "photo_not_found")
            assert err(await c.get(f"/api/inspections/insp_nope/photos/{st['photos'][0]['image_id']}")) == \
                   (404, "not_found")
    run(go())


def test_upload_errors(tmp_path):
    async def go():
        async with api(tmp_path, base_fake()) as (c, store):
            iid = await new_inspection(c)
            url = f"/api/inspections/{iid}/captures"
            assert err(await c.post(url, **upload("e.jpg", b""))) == (422, "empty_upload")
            assert err(await c.post(url, **upload("t.jpg", b"plain text, not a photo"))) == \
                   (422, "image_not_decodable")
            assert err(await c.post(url, **upload("c.jpg", photo("c.jpg")[:300]))) == (422, "image_not_decodable")
            assert err(await c.post(url, data={"source_name": "x"})) == (422, "invalid_request")  # no file part
            big = b"\xff\xd8" + b"\0" * (15 * 1024 * 1024)
            assert err(await c.post(url, **upload("big.jpg", big))) == (413, "upload_too_large")
            assert err(await c.post(url, **upload("a.jpg"), headers={"Idempotency-Key": "has spaces"})) == \
                   (422, "invalid_idempotency_key")
            assert err(await c.post("/api/inspections/insp_nope/captures", **upload("a.jpg"))) == (404, "not_found")
            assert store.list_model_calls(iid) == []
    run(go())


def test_concurrent_capture_gets_409_busy(tmp_path):
    async def go():
        gate = Gate(two_photo_fake())
        async with api(tmp_path, gate.transport()) as (c, _):
            iid = await new_inspection(c)
            url = f"/api/inspections/{iid}/captures"
            first = asyncio.create_task(c.post(url, **upload("front.jpg")))
            await gate.entered.wait()
            assert err(await asyncio.wait_for(c.post(url, **upload("other.jpg")), 5)) == (409, "inspection_busy")
            assert (await c.get(f"/api/inspections/{iid}")).json()["busy"] is True
            gate.release.set()
            r = await first
            assert r.status_code == 200 and r.json()["seq"] == 1
            assert (await c.get(f"/api/inspections/{iid}")).json()["busy"] is False
    run(go())


def test_stale_guidance_and_stopped_inspection_are_409(tmp_path):
    async def go():
        async with api(tmp_path, two_photo_fake()) as (c, _):
            iid = await new_inspection(c)
            url = f"/api/inspections/{iid}/captures"
            assert err(await c.post(url, **upload("front.jpg", responding_to="nv1"))) == (409, "stale_guidance")
            assert (await c.post(url, **upload("front.jpg"))).json()["next_view"]["id"] == "nv1"
            assert err(await c.post(url, **upload("rear.jpg", responding_to="nv7"))) == (409, "stale_guidance")
            r = await c.post(url, **upload("rear.jpg", responding_to="nv1"))
            assert r.status_code == 200 and r.json()["status"] == "stopped"
            assert err(await c.post(url, **upload("late.jpg"))) == (409, "inspection_stopped")
    run(go())


def test_idempotency_over_http(tmp_path):
    async def go():
        fm = two_photo_fake()
        async with api(tmp_path, fm) as (c, _):
            iid = await new_inspection(c)
            url = f"/api/inspections/{iid}/captures"
            r1 = await c.post(url, **upload("front.jpg"), headers={"Idempotency-Key": "abc"})
            n = len(fm.requests)
            r2 = await c.post(url, **upload("front.jpg"), headers={"Idempotency-Key": "abc"})
            assert r2.status_code == 200 and r2.json()["replayed"] is True and len(fm.requests) == n
            assert {**r2.json(), "replayed": False} == r1.json()
            assert err(await c.post(url, **upload("rear.jpg"), headers={"Idempotency-Key": "abc"})) == \
                   (409, "idempotency_conflict")
            r3 = await c.post(url, **upload("front.jpg"), headers={"Idempotency-Key": "new"})
            assert r3.json()["duplicate_of"] == 1 and len(fm.requests) == n
    run(go())


def test_installation_change_event(tmp_path):
    async def go():
        async with api(tmp_path, two_photo_fake()) as (c, _):
            iid = await new_inspection(c)
            await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"))
            ev = f"/api/inspections/{iid}/events"
            assert err(await c.post(ev, json={"type": "reboot", "reason": "x"})) == (422, "invalid_request")
            assert err(await c.post(ev, json={"type": "installation_changed", "reason": ""})) == \
                   (422, "invalid_request")
            r = await c.post(ev, json={"type": "installation_changed", "reason": "cable moved"})
            assert r.status_code == 200 and r.json()["epoch"] == 1 and r.json()["photos"][0]["superseded"]
            assert err(await c.post("/api/inspections/insp_nope/events",
                                    json={"type": "installation_changed", "reason": "x"})) == (404, "not_found")
        fm = base_fake()
        fm.queue_chat(OBS, FRONT)
        fm.queue_chat(PLAN, plan())
        async with api(tmp_path / "b", fm, budget={"max_observations": 1}) as (c, _):
            iid = await new_inspection(c)
            await c.post(f"/api/inspections/{iid}/captures", **upload("a.jpg"))
            assert err(await c.post(f"/api/inspections/{iid}/events",
                                    json={"type": "installation_changed", "reason": "x"})) == (409, "cannot_reopen")
    run(go())


def test_health(tmp_path):
    async def go():
        async with api(tmp_path, base_fake()) as (c, _):
            r = await c.get("/api/health")
            assert r.status_code == 200
            assert r.json() | {"engine_version": "x"} == {"status": "ok", "schema_version": 1,
                                                          "integrity_problems": [], "engine_version": "x",
                                                          "model_source": "mock"}
    run(go())


def test_unexpected_error_is_a_generic_500_and_unlocks(tmp_path):
    async def go():
        fm = base_fake()
        fm.queue_chat(OBS, RuntimeError("internal detail that must not leak"))
        async with api(tmp_path, fm) as (c, _):
            iid = await new_inspection(c)
            r = await c.post(f"/api/inspections/{iid}/captures", **upload("a.jpg"))
            assert err(r) == (500, "internal_error") and "internal detail" not in r.text
            assert (await c.get(f"/api/inspections/{iid}")).json()["busy"] is False
    run(go())


def test_no_secrets_in_any_response(tmp_path):
    async def go():
        bodies: list[bytes] = []
        fm = two_photo_fake()
        async with api(tmp_path, fm, bodies=bodies) as (c, _):
            iid = await new_inspection(c)
            await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"))
            await c.post(f"/api/inspections/{iid}/captures", **upload("rear.jpg"))
            for path in ("", "/report", "/report?format=md"):
                assert (await c.get(f"/api/inspections/{iid}{path}")).status_code == 200
            await c.get("/api/health")
            await c.post(f"/api/inspections/{iid}/captures", **upload("x.jpg", b"junk"))
        assert any(r.headers.get("authorization") == "Bearer test-key" for r in fm.requests)  # key was used...
        text = [b for b in bodies if not b.startswith(b"\xff\xd8")]
        assert len(text) >= 7
        for b in text:  # ...but never appears in any API response
            for f in FORBIDDEN:
                assert f not in b, f
    run(go())
