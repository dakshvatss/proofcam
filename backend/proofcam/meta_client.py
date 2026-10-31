"""Meta Model API integration (the only runtime AI dependency).

Verified request formats: see docs/META_API_FACTS.md.
  * Muse Spark: POST /v1/chat/completions, image as {"type":"image_url","image_url":{"url":data-url}},
    structured output via response_format={"type":"json_schema","json_schema":{name,schema}}.
  * SAM 3.1:    POST /v1/responses, stream=true, input_text (concept) + input_image (data URL);
    output_text is SAM special-token grammar, decoded with the official meta_sam_parser.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from meta_sam_parser import (
    ImageSegmentationResult,
    ResponsesStreamError,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    image_segmentation_format,
    parse_responses_stream,
)

from .config import Settings
from .images import NormalizedImage
from .trace import Trace

RETRYABLE_STATUS = {429, 500, 502, 503}


class MetaAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


class BudgetExhausted(MetaAPIError):
    pass


@dataclass(frozen=True)
class SamObject:
    object_id: str
    box: tuple[float, float, float, float]  # half-open pixel bounds on the normalized image
    confidence: float | None
    mask: SegmentationMaskRecord


@dataclass(frozen=True)
class SamSegmentation:
    image_id: str
    concept: str
    width: int
    height: int
    objects: list[SamObject]
    raw_output: str
    diagnostics: list[str]


def _error_from_response(status: int, body: str, retry_after: str | None) -> MetaAPIError:
    code = message = None
    try:
        err = json.loads(body).get("error", {})
        code, message = err.get("code"), err.get("message")
    except (ValueError, AttributeError):
        pass
    e = MetaAPIError(f"HTTP {status}: {message or body[:300]}", status=status, code=code,
                     retryable=status in RETRYABLE_STATUS)
    e.retry_after = retry_after  # type: ignore[attr-defined]
    return e


def _redact_request(payload: dict[str, Any], image: NormalizedImage | None) -> dict[str, Any]:
    """Trace-safe copy of a request: data URLs replaced by image ids."""
    def walk(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str) and x.startswith("data:image/"):
            return f"<{image.image_id if image else 'image'} {len(x)} chars>"
        return x
    return walk(payload)


class MetaClient:
    def __init__(self, settings: Settings, trace: Trace,
                 transport: httpx.AsyncBaseTransport | None = None, source: str = "live",
                 call_limit: int | None = None) -> None:
        self.s = settings
        self.call_limit = call_limit if call_limit is not None else settings.budget.max_model_calls
        self.calls_started = 0
        self.trace = trace
        self.source = source
        self._http = httpx.AsyncClient(
            base_url=settings.api_base,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _reserve_call(self, name: str) -> None:
        if self.calls_started >= self.call_limit:
            raise BudgetExhausted(f"model call budget ({self.call_limit}) exhausted before {name}")
        self.calls_started += 1

    async def _with_retries(self, fn, *, name: str):
        self._reserve_call(name)
        attempt = 0
        while True:
            attempt += 1
            try:
                return await fn(), attempt
            except (httpx.TimeoutException, httpx.TransportError) as e:
                err = MetaAPIError(f"{type(e).__name__}: {e}", retryable=True)
                # 504 / read timeouts are not worth more than one retry (docs: do not simply retry).
                if attempt > min(1, self.s.max_retries):
                    raise err from e
                wait = 1.0
            except MetaAPIError as e:
                if not e.retryable or attempt > self.s.max_retries:
                    e.attempts = attempt  # type: ignore[attr-defined]
                    raise
                ra = getattr(e, "retry_after", None)
                try:
                    wait = float(ra) if ra else 2.0 ** attempt
                except ValueError:
                    wait = 2.0 ** attempt
                wait = min(wait, self.s.max_retry_wait_s) + random.uniform(0, 0.5)
            self.trace.add("error", f"{name}.retry", detail={"attempt": attempt, "wait_s": wait})
            await asyncio.sleep(wait)

    # ---------------------------------------------------------------- Muse Spark
    async def chat_structured(self, *, messages: list[dict[str, Any]], schema_name: str,
                              schema: dict[str, Any], image: NormalizedImage | None,
                              purpose: str) -> tuple[str, dict[str, Any]]:
        payload = {
            "model": self.s.muse_model,
            "messages": messages,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema_name, "schema": schema}},
        }
        if self.s.muse_reasoning_effort:
            payload["reasoning_effort"] = self.s.muse_reasoning_effort

        async def call():
            r = await self._http.post("/chat/completions", json=payload, timeout=self.s.muse_timeout_s)
            if r.status_code != 200:
                raise _error_from_response(r.status_code, r.text, r.headers.get("retry-after"))
            return r.json()

        t0 = time.perf_counter()
        try:
            body, attempts = await self._with_retries(call, name=purpose)
        except MetaAPIError as e:
            if isinstance(e, BudgetExhausted):
                raise
            self.trace.add("model_call", purpose, source=self.source, model=self.s.muse_model,
                           image_id=image.image_id if image else None, status="error",
                           latency_ms=(time.perf_counter() - t0) * 1000, http_status=e.status,
                           attempts=getattr(e, "attempts", None),
                           request=_redact_request(payload, image), error=str(e))
            raise
        latency = (time.perf_counter() - t0) * 1000
        try:
            choice = body["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise MetaAPIError(f"unexpected chat completion shape: {str(body)[:300]}") from e
        usage = body.get("usage") or {}
        self.trace.add("model_call", purpose, source=self.source, model=self.s.muse_model,
                       image_id=image.image_id if image else None, latency_ms=latency,
                       http_status=200, attempts=attempts, usage=usage,
                       request=_redact_request(payload, image), response_text=content,
                       detail={"finish_reason": choice.get("finish_reason")})
        return content, usage

    # ---------------------------------------------------------------- SAM 3.1
    async def sam_segment(self, image: NormalizedImage, concept: str) -> SamSegmentation:
        payload = {
            "model": self.s.sam_model,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": concept},
                {"type": "input_image", "image_url": image.data_url()},
            ]}],
            "stream": True,
            "metadata": {"include_confidence": "true"},
        }

        async def call() -> list[dict[str, Any]]:
            events: list[dict[str, Any]] = []
            async with self._http.stream("POST", "/responses", json=payload,
                                         headers={"Accept": "text/event-stream"},
                                         timeout=self.s.sam_timeout_s) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", "replace")
                    raise _error_from_response(r.status_code, body, r.headers.get("retry-after"))
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    ev = json.loads(data)
                    events.append(ev)
                    if ev.get("type") == "error":
                        err = ev.get("error") or ev
                        code = err.get("code")
                        raise MetaAPIError(f"stream error: {err.get('message')}", code=code,
                                           retryable=code in {"server_shutting_down", "service_overloaded",
                                                              "backend_unavailable"})
            return events

        t0 = time.perf_counter()
        try:
            events, attempts = await self._with_retries(call, name=f"sam:{concept}")
            seg = await _parse_sam_events(events, image, concept)
        except (MetaAPIError, ResponsesStreamError) as e:
            if isinstance(e, BudgetExhausted):
                raise
            self.trace.add("model_call", f"sam_segment:{concept}", source=self.source,
                           model=self.s.sam_model, image_id=image.image_id, status="error",
                           latency_ms=(time.perf_counter() - t0) * 1000,
                           http_status=getattr(e, "status", None),
                           request=_redact_request(payload, image), error=str(e))
            if isinstance(e, ResponsesStreamError):
                raise MetaAPIError(f"SAM stream could not be parsed: {e}") from e
            raise
        usage = next((ev.get("response", {}).get("usage") for ev in reversed(events)
                      if ev.get("type") == "response.completed"), None)
        self.trace.add("model_call", f"sam_segment:{concept}", source=self.source,
                       model=self.s.sam_model, image_id=image.image_id,
                       latency_ms=(time.perf_counter() - t0) * 1000, http_status=200,
                       attempts=attempts, usage=usage, request=_redact_request(payload, image),
                       response_text=seg.raw_output,
                       detail={"objects": len(seg.objects), "diagnostics": seg.diagnostics})
        return seg


async def _aiter(items: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    for x in items:
        yield x


async def _parse_sam_events(events: list[dict[str, Any]], image: NormalizedImage,
                            concept: str) -> SamSegmentation:
    types = {e.get("type") for e in events}
    if "response.completed" not in types:
        raise MetaAPIError("SAM stream ended without response.completed", retryable=True)
    has_text = bool(types & {"response.output_text.delta", "response.output_text.done",
                             "response.content_part.done"})
    if not has_text:
        # Documented: zero matches -> response.completed with an empty output_text lane.
        return SamSegmentation(image.image_id, concept, image.width, image.height, [], "", [])
    result: ImageSegmentationResult = await parse_responses_stream(
        _aiter(events), image_segmentation_format()).final_result()
    return sam_result_to_segmentation(result, image, concept)


def sam_result_to_segmentation(result: ImageSegmentationResult, image: NormalizedImage,
                               concept: str) -> SamSegmentation:
    boxes = {r.object_id: r for r in result.records if isinstance(r, SegmentationBoxRecord)}
    objects = []
    for r in result.records:
        if isinstance(r, SegmentationMaskRecord):
            b = boxes.get(r.object_id)
            box = (b.left, b.top, b.right, b.bottom) if b else (
                r.bounds.left, r.bounds.top, r.bounds.right, r.bounds.bottom)
            objects.append(SamObject(r.object_id, box, r.confidence, r))
    diags = [f"{d.severity}:{d.code}:{d.message}" for d in result.diagnostics]
    # Every record repeats the source size it was computed in. If that is not the image we
    # sent, the coordinates are in an unknown basis and must not be used.
    sizes = {(int(w), int(h)) for w, h in _WH.findall(result.raw_output)}
    if sizes and sizes != {(image.width, image.height)}:
        diags.append(f"error:size_mismatch:SAM reported {sorted(sizes)}, sent {image.width}x{image.height}")
        objects = []
    return SamSegmentation(image.image_id, concept, image.width, image.height, objects,
                           result.raw_output, diags)


_WH = re.compile(r"<\|box;[^|]*?\bw=(\d+);h=(\d+)")
