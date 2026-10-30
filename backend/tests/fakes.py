"""Test doubles. NOTHING here is real Meta inference; all traces from these are source='mock'.

The SAM fake emits the documented wire grammar with masks encoded by meta_sam_parser's own
encoder, so the real parser and our geometry code are exercised end to end.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict, deque
from typing import Any

import httpx
from meta_sam_parser._mask_codec import _encode_raster  # test-only: produce valid one_bit payloads
from PIL import Image

from proofcam.config import Budget, Settings
from proofcam.images import NormalizedImage, normalize_image_bytes
from proofcam.meta_client import MetaClient
from proofcam.trace import Trace

W, H = 400, 300


def make_image(name: str = "a.jpg", color=(40, 40, 40), size=(W, H)) -> NormalizedImage:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return normalize_image_bytes(buf.getvalue(), name)


def settings(**budget) -> Settings:
    return Settings(api_key="test-key", api_base="https://api.test/v1", max_retries=2,
                    max_retry_wait_s=0.01, budget=Budget(**budget))


def sam_record(obj_id: int, box_incl: tuple[int, int, int, int], w: int = W, h: int = H,
               conf: float | None = 0.9, fill: bool = True) -> str:
    x1, y1, x2, y2 = box_incl
    mw, mh = x2 - x1 + 1, y2 - y1 + 1
    raster = [1 if fill else 0] * (mw * mh)
    payload = _encode_raster(raster, mw, mh)
    c = f";c={conf}" if conf is not None else ""
    return (f"{obj_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h}{c}|>"
            f"<|mask;x=0;y=0{c};data={mh},{mw},{payload}|>")


def sse(events: list[dict[str, Any]]) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


def sam_events(line: str) -> list[dict[str, Any]]:
    lane = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
    evs: list[dict[str, Any]] = [{"type": "response.created", "response": {"id": "r1"}}]
    if line:
        evs += [{"type": "response.output_text.delta", "delta": line, **lane},
                {"type": "response.output_text.done", "text": line, **lane}]
    evs.append({"type": "response.completed", "response": {"id": "r1", "usage": None}})
    return evs


class FakeMeta:
    """Routes requests to queued canned responses.

    chat[schema_name]  : deque of dict (JSON body to return as content) | httpx.Response | Exception
    sam[concept]       : SAM output line (str) | httpx.Response   (missing concept -> zero matches)
    """

    def __init__(self) -> None:
        self.chat: dict[str, deque] = defaultdict(deque)
        self.sam: dict[str, Any] = {}
        self.requests: list[httpx.Request] = []

    def queue_chat(self, schema: str, *items: Any) -> None:
        self.chat[schema].extend(items)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/chat/completions"):
            name = body["response_format"]["json_schema"]["name"]
            if not self.chat[name]:
                raise AssertionError(f"unexpected chat call for {name}")
            item = self.chat[name].popleft()
            if isinstance(item, Exception):
                raise item
            if isinstance(item, httpx.Response):
                return item
            content = item if isinstance(item, str) else json.dumps(item)
            return httpx.Response(200, json={
                "object": "chat.completion",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 1500, "completion_tokens": 300, "total_tokens": 1800}})
        if request.url.path.endswith("/responses"):
            concept = body["input"][0]["content"][0]["text"]
            item = self.sam.get(concept, "")
            if isinstance(item, httpx.Response):
                return item
            line = item if not item or item.startswith("<0f>") else "<0f>" + item
            return httpx.Response(200, content=sse(sam_events(line)),
                                  headers={"content-type": "text/event-stream"})
        raise AssertionError(f"unexpected path {request.url.path}")

    def client(self, s: Settings | None = None, trace: Trace | None = None) -> MetaClient:
        s = s or settings()
        return MetaClient(s, trace or Trace(), transport=httpx.MockTransport(self.handler), source="mock")


# ---------- canned Muse observation payloads (box coords on the 0-1000 grid) ----------

def device(ref, spec_id, side="rear", ports=True, box=(100, 100, 600, 700), certainty="clear"):
    return {"ref": ref, "spec_device_id": spec_id, "identification_basis": "label on case",
            "identification_certainty": certainty, "visible_side": side, "ports_visible": ports,
            "box": dict(zip(("x1", "y1", "x2", "y2"), box)) if box else None}


def port(ref, dev, label, occ="cable_inserted", color="blue", vis="clear", legible="legible",
         group=None, box=(200, 400, 260, 480)):
    return {"ref": ref, "device_ref": dev, "label_read": label, "label_group": group,
            "label_legibility": legible, "occupancy": occ, "plug_color": color,
            "insertion_visibility": vis, "box": dict(zip(("x1", "y1", "x2", "y2"), box)) if box else None}


def cable(ref, color, ports, path="partially_visible"):
    return {"ref": ref, "color": color, "path_visibility": path, "connected_port_refs": ports}


def extraction(devices=(), ports=(), cables=(), subject=True, usable=True, summary="test scene"):
    return {"image_usable": usable, "image_issues": [], "shows_inspection_subject": subject,
            "scene_summary": summary, "devices": list(devices), "ports": list(ports),
            "cables": list(cables), "unreadable_details": []}


def plan(instruction="Walk around to the back of the router and frame its port row.",
         action="move_to_rear", resolvable=True, reason=None):
    return {"instruction": instruction, "camera_action": action, "target_region": "router rear ports",
            "rationale": "ports not visible", "success_criteria": "LAN 1 label and plug readable",
            "visually_resolvable": resolvable, "unresolvable_reason": reason}


# Port box (200,400)-(260,480) on the 0-1000 grid of a 400x300 image = pixels (80,120)-(104,144).
CABLE_AT_PORT = (85, 125, 140, 160)   # inclusive SAM box overlapping that port region
CABLE_ELSEWHERE = (300, 10, 390, 40)  # far from it
