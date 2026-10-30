"""HTTP-layer tests against a mock transport (NOT real inference)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from fakes import FakeMeta, make_image, sam_record, settings
from proofcam.meta_client import BudgetExhausted, MetaAPIError
from proofcam.trace import Trace

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
          "additionalProperties": False}


def chat(client, image=None):
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"},
                                         {"type": "image_url", "image_url": {"url": image.data_url()}}]}]
    return asyncio.run(client.chat_structured(messages=msgs, schema_name="T", schema=SCHEMA, image=image,
                                              purpose="test"))


def test_chat_request_format_and_redacted_trace():
    fm = FakeMeta()
    fm.queue_chat("T", {"a": "x"})
    img = make_image()
    c = fm.client()
    content, usage = chat(c, img)
    assert json.loads(content) == {"a": "x"} and usage["prompt_tokens"] == 1500
    req = fm.requests[0]
    assert req.url.path == "/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer test-key"
    body = json.loads(req.content)
    assert body["model"] == "muse-spark-1.3"
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "T", "schema": SCHEMA}}
    part = body["messages"][0]["content"][1]
    assert part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    ev = c.trace.model_calls()[0]
    assert ev.source == "mock" and ev.status == "ok" and ev.image_id == img.image_id
    assert "base64" not in json.dumps(ev.request)   # image bytes never land in the trace


def test_rate_limit_retried_with_retry_after():
    fm = FakeMeta()
    fm.queue_chat("T", httpx.Response(429, headers={"retry-after": "0"},
                                      json={"error": {"code": "rate_limit_exceeded", "message": "slow"}}),
                  {"a": "ok"})
    c = fm.client()
    chat(c, make_image())
    assert c.trace.model_calls()[0].attempts == 2
    assert any(e.name.endswith(".retry") for e in c.trace.events)


def test_bad_request_not_retried():
    fm = FakeMeta()
    fm.queue_chat("T", httpx.Response(400, json={"error": {"code": "invalid", "message": "bad schema"}}))
    c = fm.client()
    with pytest.raises(MetaAPIError) as ei:
        chat(c, make_image())
    assert ei.value.status == 400 and "bad schema" in str(ei.value)
    assert len(fm.requests) == 1
    assert c.trace.model_calls()[0].status == "error"


def test_persistent_503_is_bounded():
    fm = FakeMeta()
    fm.queue_chat("T", *[httpx.Response(503, json={"error": {"message": "overloaded"}})] * 5)
    with pytest.raises(MetaAPIError):
        chat(fm.client(), make_image())
    assert len(fm.requests) == 3   # 1 + max_retries(2)


def test_timeout_retried_once_then_raises():
    fm = FakeMeta()
    fm.queue_chat("T", httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), {"a": "never"})
    with pytest.raises(MetaAPIError):
        chat(fm.client(), make_image())
    assert len(fm.requests) == 2


def test_call_budget_is_hard():
    fm = FakeMeta()
    fm.queue_chat("T", {"a": "1"}, {"a": "2"})
    c = fm.client(settings(max_model_calls=1))
    chat(c, make_image())
    with pytest.raises(BudgetExhausted):
        chat(c, make_image())
    assert len(fm.requests) == 1


def test_sam_request_format_and_parse():
    fm = FakeMeta()
    fm.sam["router"] = sam_record(0, (10, 20, 59, 79))
    img = make_image()
    c = fm.client()
    seg = asyncio.run(c.sam_segment(img, "router"))
    body = json.loads(fm.requests[0].content)
    assert fm.requests[0].url.path == "/v1/responses"
    assert body["model"] == "sam-3.1" and body["stream"] is True
    assert body["metadata"] == {"include_confidence": "true"}
    parts = body["input"][0]["content"]
    assert parts[0] == {"type": "input_text", "text": "router"}
    assert parts[1]["type"] == "input_image" and parts[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert len(seg.objects) == 1 and seg.objects[0].box == (10, 20, 60, 80)


def test_sam_stream_error_event_raises():
    from fakes import sse
    fm = FakeMeta()
    fm.sam["router"] = httpx.Response(200, content=sse([
        {"type": "response.created"}, {"type": "error", "error": {"code": "invalid_prompt", "message": "nope"}}]))
    with pytest.raises(MetaAPIError, match="nope"):
        asyncio.run(fm.client().sam_segment(make_image(), "router"))


def test_sam_truncated_stream_raises():
    from fakes import sse
    fm = FakeMeta()
    fm.sam["router"] = httpx.Response(200, content=sse([{"type": "response.created"}]))
    with pytest.raises(MetaAPIError, match="without response.completed"):
        asyncio.run(fm.client(settings()).sam_segment(make_image(), "router"))
