"""ProofCam HTTP API (Milestone 1). Thin layer over InspectionService; all errors are {"error", "message"}.

Run locally (one worker; see service.py for the deployment assumption):
    cd backend
    .venv/Scripts/python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --port 8000

Access boundary (M3.2). With an access code configured, every route except /api/health, /api/access and
/api/session requires the session cookie obtained by POST /api/session {"access_code": ...} (HttpOnly, SameSite=Strict;
the code itself is never stored in the browser). Without a code, `local_only` (set by app_from_env) refuses any request
that did not come straight from this machine (non-loopback client, non-local Host, or proxy/Tailscale headers), so the
unauthenticated API cannot be reached through a tunnel or the LAN by accident.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api_models import (AccessStatus, CreateInspectionRequest, EventRequest, Health, InspectionState, SessionRequest,
                         SpecSummary, StepResponse)
from .config import Settings, database_path
from .service import InspectionService, ServiceConfig, ServiceError
from .store import Store

log = logging.getLogger("proofcam.api")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


SESSION_COOKIE = "proofcam_access"
MIN_ACCESS_CODE_LEN = 12
_OPEN_PATHS = frozenset({"/api/health", "/api/access", "/api/session"})
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_PROXY_HEADERS = ("tailscale-user-login", "x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip")


def session_token(access_code: str) -> str:
    """Cookie value: an HMAC of a fixed label keyed by the access code (the code itself never leaves the server)."""
    return hmac.new(access_code.encode(), b"proofcam-session-v1", hashlib.sha256).hexdigest()


def is_remote_request(request: Request) -> bool:
    """True unless the request came straight from this machine to a local hostname, with no proxy headers."""
    client = request.client.host if request.client else ""
    if client not in _LOOPBACK:
        return True
    if any(h in request.headers for h in _PROXY_HEADERS):
        return True
    host = request.headers.get("host", "")
    host = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.rsplit(":", 1)[0]
    return host.lower() not in _LOOPBACK


def create_app(settings: Settings, store: Store, transport: httpx.AsyncBaseTransport | None = None, *,
               config: ServiceConfig | None = None, owns_store: bool = False, access_code: str | None = None,
               local_only: bool = False) -> FastAPI:
    """`transport` replaces the network for model calls (tests inject a mock); the API key in `settings` never
    leaves the server process. `access_code`: require a session for every non-open route. `local_only`: without an
    access code, refuse requests that did not come directly from this machine."""
    if access_code is not None and len(access_code) < MIN_ACCESS_CODE_LEN:
        raise ValueError(f"access code must be at least {MIN_ACCESS_CODE_LEN} characters")
    service = InspectionService(settings, store, transport, config)
    cfg = service.config
    token = session_token(access_code) if access_code else None
    failures: deque[float] = deque()  # recent wrong access codes (process-wide throttle)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.recover_stale()
        yield
        await service.shutdown()
        if owns_store:
            store.close()

    app = FastAPI(title="ProofCam API", version=__version__, lifespan=lifespan)
    app.state.service = service

    def authenticated(request: Request) -> bool:
        return token is None or hmac.compare_digest(request.cookies.get(SESSION_COOKIE, ""), token)

    def access_status(request: Request) -> dict[str, Any]:
        ok = authenticated(request)
        spend = service.spend() if ok else {"global_model_calls": None, "global_call_limit": None,
                                            "global_remaining": None}
        return {"auth_required": token is not None, "authenticated": ok, "model_source": cfg.model_source, **spend}

    @app.middleware("http")
    async def access_boundary(request: Request, call_next):
        if token is None and local_only and is_remote_request(request):
            return _error(403, "remote_access_requires_auth",
                          "this server has no access code configured, so it only accepts requests from this computer")
        if token is not None and request.url.path not in _OPEN_PATHS and not authenticated(request):
            return _error(401, "unauthorized", "enter the access code to use this server")
        return await call_next(request)

    @app.get("/api/access", response_model=AccessStatus)
    async def access(request: Request) -> dict[str, Any]:
        return access_status(request)

    @app.post("/api/session", response_model=AccessStatus)
    async def login(body: SessionRequest, request: Request) -> Response:
        if token is None or access_code is None:
            return JSONResponse(access_status(request))
        now = time.monotonic()
        while failures and now - failures[0] > 60:
            failures.popleft()
        if len(failures) >= 10:
            return _error(429, "too_many_attempts", "too many wrong access codes; wait a minute")
        if not hmac.compare_digest(body.access_code.encode(), access_code.encode()):
            failures.append(now)
            return _error(401, "invalid_access_code", "that access code is not correct")
        resp = JSONResponse({"auth_required": True, "authenticated": True, "model_source": cfg.model_source,
                             **service.spend()})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie(SESSION_COOKIE, token, max_age=30 * 24 * 3600, httponly=True, samesite="strict",
                        secure=secure, path="/")
        return resp

    @app.delete("/api/session", status_code=204, response_model=None)
    async def logout() -> Response:
        resp = Response(status_code=204)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        parts = [f"{'.'.join(str(x) for x in e.get('loc', ()))}: {e.get('msg', 'invalid')}" for e in exc.errors()]
        return _error(422, "invalid_request", "; ".join(parts)[:1000] or "invalid request")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)  # server log only
        return _error(500, "internal_error", "unexpected server error")

    @app.get("/api/health", response_model=Health)
    async def health() -> dict[str, Any]:
        return service.health()

    @app.get("/api/specs", response_model=list[SpecSummary])
    async def list_specs() -> list[SpecSummary]:
        return service.list_specs()

    @app.post("/api/inspections", status_code=201, response_model=InspectionState)
    async def create_inspection(body: CreateInspectionRequest) -> InspectionState:
        return await service.create_inspection(spec_id=body.spec_id, spec=body.spec)

    @app.get("/api/inspections/{inspection_id}", response_model=InspectionState)
    async def get_inspection(inspection_id: str) -> InspectionState:
        return await service.get_inspection(inspection_id)

    @app.post("/api/inspections/{inspection_id}/captures", response_model=StepResponse)
    async def capture(inspection_id: str, file: Annotated[UploadFile, File()],
                      source_name: Annotated[str | None, Form(max_length=200)] = None,
                      responding_to: Annotated[str | None, Form(max_length=64)] = None,
                      idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
                      ) -> StepResponse:
        data = await file.read(cfg.max_upload_bytes + 1)  # never more than limit + 1 bytes in memory
        return await service.submit_capture(inspection_id, data, idempotency_key=idempotency_key,
                                            source_name=source_name or file.filename,
                                            responding_to=responding_to)

    @app.post("/api/inspections/{inspection_id}/events", response_model=InspectionState)
    async def event(inspection_id: str, body: EventRequest) -> InspectionState:
        if body.type == "installation_changed":
            return await service.declare_installation_changed(inspection_id, body.reason)  # type: ignore[arg-type]
        return await service.record_declaration(inspection_id, body.type, seq=body.seq, device_id=body.device_id,
                                                 requirement_id=body.requirement_id,
                                                 endpoint_index=body.endpoint_index)

    @app.get("/api/inspections/{inspection_id}/report", response_model=None)
    async def report(inspection_id: str,
                     format: Annotated[Literal["json", "md"], Query()] = "json") -> Response:
        result = await service.get_report(inspection_id, format)
        if format == "md":
            return PlainTextResponse(result, media_type="text/markdown; charset=utf-8")  # type: ignore[arg-type]
        return JSONResponse(result)

    @app.get("/api/inspections/{inspection_id}/photos/{image_id}", response_model=None)
    async def photo(inspection_id: str, image_id: str) -> Response:
        return Response(service.get_photo(inspection_id, image_id), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/inspections/{inspection_id}/overlays/{image_id}", response_model=None)
    async def overlay(inspection_id: str, image_id: str) -> Response:
        return Response(service.get_overlay(inspection_id, image_id), media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-cache"})

    return app


DEFAULT_GLOBAL_CALL_LIMIT = 50


def inspection_call_limit_from_env() -> int | None:
    """PROOFCAM_INSPECTION_CALL_LIMIT: model calls each NEW inspection may use (unset = 40). Existing inspections keep
    the limit they were created with."""
    raw = os.environ.get("PROOFCAM_INSPECTION_CALL_LIMIT", "").strip()
    return int(raw) if raw else None


def global_call_limit_from_env() -> int | None:
    """PROOFCAM_GLOBAL_CALL_LIMIT: integer cap on model calls across all inspections; "none" disables it."""
    raw = os.environ.get("PROOFCAM_GLOBAL_CALL_LIMIT", "").strip().lower()
    if raw == "none":
        return None
    return int(raw) if raw else DEFAULT_GLOBAL_CALL_LIMIT


def app_from_env() -> FastAPI:
    """uvicorn factory: key from .env / environment (server-side only), database at PROOFCAM_DB_PATH, optional
    PROOFCAM_ACCESS_CODE (>= 12 chars; required for any access from another device) and PROOFCAM_GLOBAL_CALL_LIMIT
    (default 50 calls across all inspections). Without an access code only this computer is served."""
    settings = Settings.from_env()  # also loads .env
    code = os.environ.get("PROOFCAM_ACCESS_CODE", "").strip() or None
    limit = global_call_limit_from_env()
    per_inspection = inspection_call_limit_from_env()
    if code is None:
        log.warning("PROOFCAM_ACCESS_CODE not set: serving requests from this computer only")
    log.warning("model-call limits: %s across all inspections, %s per new inspection",
                limit if limit is not None else "no cap", per_inspection or settings.budget.max_model_calls)
    return create_app(settings, Store(database_path()), owns_store=True, access_code=code, local_only=True,
                      config=ServiceConfig(global_call_limit=limit, inspection_call_limit=per_inspection))
