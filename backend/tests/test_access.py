"""M3.2 access boundary and spending cap. Mocked Meta responses only (FakeMeta); temporary SQLite; no network.

- Access code -> HttpOnly session cookie; every non-open route (incl. photos/overlays) needs it.
- Without an access code, local_only refuses anything not coming straight from this machine (Tailscale Serve,
  reverse proxies, LAN clients, non-local Host).
- Global model-call cap across all inspections: refuses a capture before anything is sent, and is a hard backstop
  inside the per-call reservation.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import httpx
import pytest

from fakes import FakeMeta, plan, settings
from proofcam import api as api_module
from proofcam.api import SESSION_COOKIE, create_app, global_call_limit_from_env, session_token
from proofcam.service import ServiceConfig
from proofcam.store import Store
from test_agent import FRONT, OBS, PLAN, REAR_BOTH, base_fake
from test_api import err, upload

CODE = "correct-horse-battery-staple"


@contextlib.asynccontextmanager
async def app_client(tmp_path: Path, fm: FakeMeta | None = None, *, base_url: str = "http://127.0.0.1:8000",
                     client_addr: tuple[str, int] = ("127.0.0.1", 50000), **kw):
    fm = fm or base_fake()
    store = Store(tmp_path / "var" / "proofcam.db")
    cfg = kw.pop("config", ServiceConfig(model_source="mock"))
    app = create_app(settings(), store, httpx.MockTransport(fm.handler), config=cfg, **kw)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, client=client_addr, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as c:
                yield c, store
    finally:
        store.close()


def run(coro):
    return asyncio.run(coro)


async def create(c: httpx.AsyncClient) -> str:
    r = await c.post("/api/inspections", json={"spec_id": "my_setup"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ============================================================================ access code

def test_access_code_gates_every_data_route_and_issues_an_httponly_cookie(tmp_path):
    async def go():
        async with app_client(tmp_path, access_code=CODE) as (c, _):
            assert (await c.get("/api/health")).status_code == 200
            st = (await c.get("/api/access")).json()
            assert st == {"auth_required": True, "authenticated": False, "model_source": "mock",
                          "global_model_calls": None, "global_call_limit": None, "global_remaining": None}
            assert err(await c.post("/api/inspections", json={"spec_id": "my_setup"})) == (401, "unauthorized")
            assert err(await c.get("/api/inspections/insp_x")) == (401, "unauthorized")
            assert err(await c.get("/api/inspections/insp_x/photos/img_000000000000")) == (401, "unauthorized")
            assert err(await c.get("/docs")) == (401, "unauthorized")

            assert err(await c.post("/api/session", json={"access_code": "wrong-code-123"})) == \
                   (401, "invalid_access_code")
            r = await c.post("/api/session", json={"access_code": CODE})
            assert r.status_code == 200 and r.json()["authenticated"] is True
            cookie = r.headers["set-cookie"]
            assert f"{SESSION_COOKIE}={session_token(CODE)}" in cookie
            assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
            assert CODE not in cookie and CODE not in r.text  # the code itself never goes back to the browser

            iid = await create(c)
            assert (await c.get(f"/api/inspections/{iid}")).status_code == 200
            assert (await c.get("/api/access")).json()["authenticated"] is True

            assert (await c.delete("/api/session")).status_code == 204
            assert err(await c.get(f"/api/inspections/{iid}")) == (401, "unauthorized")
    run(go())


def test_forged_or_stale_cookie_is_refused(tmp_path):
    async def go():
        async with app_client(tmp_path, access_code=CODE) as (c, _):
            c.cookies.set(SESSION_COOKIE, session_token("some-other-code-xyz"))
            assert err(await c.post("/api/inspections", json={"spec_id": "my_setup"})) == (401, "unauthorized")
    run(go())


def test_wrong_codes_are_throttled(tmp_path):
    async def go():
        async with app_client(tmp_path, access_code=CODE) as (c, _):
            for _ in range(10):
                assert err(await c.post("/api/session", json={"access_code": "nope-nope-nope"}))[0] == 401
            assert err(await c.post("/api/session", json={"access_code": CODE})) == (429, "too_many_attempts")
    run(go())


def test_short_access_codes_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_app(settings(), Store(tmp_path / "a.db"), access_code="short")


def test_capture_and_photo_work_with_a_session(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())

    async def go():
        async with app_client(tmp_path, fm, access_code=CODE) as (c, _):
            await c.post("/api/session", json={"access_code": CODE})
            iid = await create(c)
            r = await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"),
                             headers={"Idempotency-Key": "k1"})
            assert r.status_code == 200
            assert (await c.get(f"/api/inspections/{iid}/photos/{r.json()['image_id']}")).status_code == 200
    run(go())


# ============================================================================ local-only without an access code

@pytest.mark.parametrize("base_url,client_addr,headers", [
    ("http://mylaptop.tail1234.ts.net", ("127.0.0.1", 5), {}),                   # Tailscale Serve hostname
    ("http://127.0.0.1:8000", ("127.0.0.1", 5), {"Tailscale-User-Login": "me@example.com"}),
    ("http://127.0.0.1:8000", ("127.0.0.1", 5), {"X-Forwarded-For": "100.101.102.103"}),
    ("http://127.0.0.1:8000", ("127.0.0.1", 5), {"Forwarded": "for=192.168.1.20"}),
    ("http://127.0.0.1:8000", ("192.168.1.20", 5), {}),                          # LAN client
    ("http://192.168.1.10:8000", ("127.0.0.1", 5), {}),                          # LAN address as Host
])
def test_without_a_code_remote_requests_are_refused(tmp_path, base_url, client_addr, headers):
    async def go():
        async with app_client(tmp_path, base_url=base_url, client_addr=client_addr, local_only=True) as (c, _):
            for method, path in (("GET", "/api/health"), ("POST", "/api/inspections")):
                r = await c.request(method, path, headers=headers, json={"spec_id": "my_setup"})
                assert err(r) == (403, "remote_access_requires_auth")
    run(go())


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8000", "http://localhost:5173", "http://[::1]:8000"])
def test_without_a_code_this_computer_is_served(tmp_path, base_url):
    async def go():
        async with app_client(tmp_path, base_url=base_url, local_only=True) as (c, _):
            assert (await c.get("/api/health")).status_code == 200
            await create(c)
            assert (await c.get("/api/access")).json()["auth_required"] is False
    run(go())


def test_with_a_code_remote_requests_work_after_login(tmp_path):
    async def go():
        async with app_client(tmp_path, base_url="https://mylaptop.tail1234.ts.net", local_only=True,
                              access_code=CODE) as (c, _):
            h = {"Tailscale-User-Login": "me@example.com"}
            assert err(await c.post("/api/inspections", json={"spec_id": "my_setup"}, headers=h))[0] == 401
            r = await c.post("/api/session", json={"access_code": CODE}, headers=h)
            assert "Secure" in r.headers["set-cookie"]  # https request -> Secure cookie
            r = await c.post("/api/inspections", json={"spec_id": "my_setup"}, headers=h)
            assert r.status_code == 201
    run(go())


def test_app_from_env_reads_code_and_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "dummy-key-not-real-0000")
    monkeypatch.setenv("PROOFCAM_DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("PROOFCAM_ACCESS_CODE", CODE)
    monkeypatch.setenv("PROOFCAM_GLOBAL_CALL_LIMIT", "12")
    app = api_module.app_from_env()

    async def go():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as c:
                assert err(await c.post("/api/inspections", json={"spec_id": "my_setup"}))[0] == 401
                st = (await c.post("/api/session", json={"access_code": CODE})).json()
                assert st["global_call_limit"] == 12 and st["model_source"] == "live"
    run(go())


def test_global_call_limit_from_env(monkeypatch):
    monkeypatch.delenv("PROOFCAM_GLOBAL_CALL_LIMIT", raising=False)
    assert global_call_limit_from_env() == 50
    monkeypatch.setenv("PROOFCAM_GLOBAL_CALL_LIMIT", "none")
    assert global_call_limit_from_env() is None
    monkeypatch.setenv("PROOFCAM_GLOBAL_CALL_LIMIT", "7")
    assert global_call_limit_from_env() == 7


# ============================================================================ spending cap

def test_spend_cap_refuses_a_capture_before_any_model_call_and_leaves_the_inspection_open(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())

    async def go():
        cfg = ServiceConfig(model_source="mock", global_call_limit=7, capture_call_reserve=8)
        async with app_client(tmp_path, fm, config=cfg) as (c, store):
            iid = await create(c)
            r = await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"),
                             headers={"Idempotency-Key": "k1"})
            assert err(r) == (429, "spend_cap_reached")
            assert fm.requests == []
            st = (await c.get(f"/api/inspections/{iid}")).json()
            assert st["status"] == "open" and st["busy"] is False and st["photos"] == []
            assert (await c.get("/api/access")).json()["global_remaining"] == 7
    run(go())


def test_spend_cap_counts_every_inspection_and_is_a_hard_backstop(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan(), plan())

    async def go():
        # Pre-check disabled (reserve 0) to exercise the in-transaction backstop.
        # 5 = the overview's 4 calls (M3.7: no cable concept is sent for a photo without occupied ports) + one Muse
        # call for the second inspection, so its SAM calls are refused.
        cfg = ServiceConfig(model_source="mock", global_call_limit=5, capture_call_reserve=0)
        async with app_client(tmp_path, fm, config=cfg) as (c, store):
            a = await create(c)
            r = await c.post(f"/api/inspections/{a}/captures", **upload("front.jpg"), headers={"Idempotency-Key": "a1"})
            assert r.status_code == 200
            used = store.total_model_calls()
            assert used == len(fm.requests) == 4
            b = await create(c)
            r = await c.post(f"/api/inspections/{b}/captures", **upload("rear.jpg"), headers={"Idempotency-Key": "b1"})
            assert r.status_code == 200
            # never more HTTP requests than the cap, across both inspections
            assert len(fm.requests) == store.total_model_calls() == 5
            # SAM was refused, so the plug cannot be grounded: the cap never turns into a false verification.
            assert r.json()["assessments"][0]["status"] == "INSUFFICIENT_EVIDENCE"
            calls = (await c.get(f"/api/inspections/{b}")).json()["usage"]
            assert calls["model_calls"] == store.total_model_calls() - (await c.get(f"/api/inspections/{a}")).json()["usage"]["model_calls"]
    run(go())


def test_m33_live_cap_admits_an_overview_and_a_close_up(tmp_path):
    """M3.3 initial live session: cap 20, default reserve 8. The planned two-photo test must fit, and a further
    photo is admitted only while >= 8 calls remain."""
    fm = base_fake()
    fm.queue_chat(OBS, FRONT, REAR_BOTH)
    fm.queue_chat(PLAN, plan(), plan())

    async def go():
        cfg = ServiceConfig(model_source="mock", global_call_limit=20)
        assert cfg.capture_call_reserve == 8
        async with app_client(tmp_path, fm, config=cfg) as (c, store):
            iid = await create(c)
            for i, name in enumerate(("front.jpg", "rear.jpg")):
                r = await c.post(f"/api/inspections/{iid}/captures", **upload(name),
                                 headers={"Idempotency-Key": f"m33-{i}"})
                assert r.status_code == 200, r.text
            used = store.total_model_calls()
            assert used == len(fm.requests) <= 20
            st = (await c.get("/api/access")).json()
            assert (st["global_call_limit"], st["global_remaining"]) == (20, 20 - used)
            r = await c.post(f"/api/inspections/{iid}/captures", **upload("third.jpg"),
                             headers={"Idempotency-Key": "m33-2"})
            if used + 8 > 20:
                assert err(r) == (429, "spend_cap_reached") and len(fm.requests) == used
            assert store.total_model_calls() <= 20
    run(go())


def test_idempotent_replay_is_served_even_when_the_cap_is_reached(tmp_path):
    fm = base_fake()
    fm.queue_chat(OBS, FRONT)
    fm.queue_chat(PLAN, plan())

    async def go():
        cfg = ServiceConfig(model_source="mock", global_call_limit=4, capture_call_reserve=0)
        async with app_client(tmp_path, fm, config=cfg) as (c, store):
            iid = await create(c)
            r1 = await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"),
                              headers={"Idempotency-Key": "k1"})
            n = len(fm.requests)
            r2 = await c.post(f"/api/inspections/{iid}/captures", **upload("front.jpg"),
                              headers={"Idempotency-Key": "k1"})
            assert r2.status_code == 200 and r2.json()["replayed"] is True and len(fm.requests) == n
            assert {**r2.json(), "replayed": False} == r1.json()
    run(go())
