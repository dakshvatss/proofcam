"""Audit trace of every model/tool invocation and agent decision."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

TraceKind = Literal["model_call", "agent_step", "policy", "plan", "stop", "error"]


class TraceEvent(BaseModel):
    seq: int
    ts: float
    kind: TraceKind
    name: str
    # Provenance of model output: "live" = real Meta API response in this run,
    # "mock" = test double. Replays (later milestones) will use "replay".
    source: Literal["live", "mock", "replay", "local"] = "local"
    model: str | None = None
    image_id: str | None = None
    latency_ms: float | None = None
    status: Literal["ok", "error"] = "ok"
    http_status: int | None = None
    attempts: int | None = None
    usage: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    response_text: str | None = None
    error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class Trace:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    @classmethod
    def from_events(cls, events: list[TraceEvent] | list[dict[str, Any]]) -> Trace:
        """Rebuild a persisted trace. Events must be the complete, contiguous sequence 0..n-1 so that
        new events continue the numbering; anything else means the stored trace is incomplete."""
        t = cls()
        t.events = [e.model_copy(deep=True) if isinstance(e, TraceEvent) else TraceEvent.model_validate(e)
                    for e in events]
        seqs = [e.seq for e in t.events]
        if seqs != list(range(len(seqs))):
            raise ValueError(f"trace events are not a contiguous 0..n-1 sequence (got {seqs[:10]}...)")
        return t

    def add(self, kind: TraceKind, name: str, **kw: Any) -> TraceEvent:
        ev = TraceEvent(seq=len(self.events), ts=time.time(), kind=kind, name=name, **kw)
        self.events.append(ev)
        return ev

    def model_calls(self) -> list[TraceEvent]:
        return [e for e in self.events if e.kind == "model_call"]

    def write_jsonl(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as f:
            for e in self.events:
                f.write(e.model_dump_json() + "\n")

    def summary(self) -> dict[str, Any]:
        calls = self.model_calls()
        by_model: dict[str, dict[str, Any]] = {}
        for c in calls:
            m = by_model.setdefault(c.model or "?", {"calls": 0, "errors": 0, "latency_ms": 0.0,
                                                    "input_tokens": 0, "output_tokens": 0})
            m["calls"] += 1
            m["errors"] += c.status == "error"
            m["latency_ms"] += c.latency_ms or 0.0
            u = c.usage or {}
            m["input_tokens"] += int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
            m["output_tokens"] += int(u.get("completion_tokens") or u.get("output_tokens") or 0)
        return {"model_calls": len(calls), "by_model": by_model,
                "estimated_cost_usd": estimate_cost(by_model)}


# Standard-mode list prices from https://dev.meta.ai/docs/pricing-rate-limits (fetched 2026-10-30).
_PRICES = {
    "muse-spark-1.3": {"in": 1.25 / 1e6, "out": 4.25 / 1e6},
    "sam-3.1": {"per_call": 2.50 / 1000},  # per image segmented
}


def estimate_cost(by_model: dict[str, dict[str, Any]]) -> float:
    total = 0.0
    for model, m in by_model.items():
        p = _PRICES.get(model)
        if not p:
            continue
        if "per_call" in p:
            total += p["per_call"] * (m["calls"] - m["errors"])
        else:
            total += m["input_tokens"] * p["in"] + m["output_tokens"] * p["out"]
    return round(total, 6)
