"""ProofCam HTTP API (Milestone 1). Thin layer over InspectionService; all errors are {"error", "message"}.

Run locally (one worker; see service.py for the deployment assumption):
    cd backend
    .venv/Scripts/python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

import httpx
from fastapi import FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api_models import CreateInspectionRequest, EventRequest, Health, InspectionState, StepResponse
from .config import Settings, database_path
from .service import InspectionService, ServiceConfig, ServiceError
from .store import Store

log = logging.getLogger("proofcam.api")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def create_app(settings: Settings, store: Store, transport: httpx.AsyncBaseTransport | None = None, *,
               config: ServiceConfig | None = None, owns_store: bool = False) -> FastAPI:
    """`transport` replaces the network for model calls (tests inject a mock); the API key in `settings` never
    leaves the server process."""
    service = InspectionService(settings, store, transport, config)
    cfg = service.config

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.recover_stale()
        yield
        await service.shutdown()
        if owns_store:
            store.close()

    app = FastAPI(title="ProofCam API", version=__version__, lifespan=lifespan)
    app.state.service = service

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
        return await service.declare_installation_changed(inspection_id, body.reason)

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


def app_from_env() -> FastAPI:
    """uvicorn factory: key from .env / environment (server-side only), database at PROOFCAM_DB_PATH."""
    return create_app(Settings.from_env(), Store(database_path()), owns_store=True)
