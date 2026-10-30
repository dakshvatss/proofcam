"""Inspection report: JSON (machine) + Markdown (human), with source-image provenance."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .agent import InspectionAgent
from .overlay import render_overlay

DISCLAIMER = ("ProofCam verifies visually observable conditions only. It does not certify electrical safety, "
              "hidden connectivity, operational performance, or regulatory compliance.")


def write_report(agent: InspectionAgent, run_dir: Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "images").mkdir(exist_ok=True)
    (run_dir / "overlays").mkdir(exist_ok=True)
    overlays = {}
    for o in agent.observations:
        img = agent.images[o.image_id]
        (run_dir / "images" / f"{o.seq:02d}_{o.image_id}.jpg").write_bytes(img.jpeg_bytes)
        if o.extraction is not None:
            p = render_overlay(img, o, agent.grounding_runs.get(o.seq),
                               run_dir / "overlays" / f"{o.seq:02d}_{o.image_id}.jpg")
            overlays[o.image_id] = str(p.relative_to(run_dir))
    agent.trace.write_jsonl(run_dir / "trace.jsonl")
    report = {
        "inspection_id": run_dir.name,
        "spec": agent.spec.model_dump(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "require_grounding": agent.require_grounding,
        "stop_reason": agent.stop_reason,
        "requirements": [a.model_dump() for a in agent.assessments],
        "observations": [o.model_dump() for o in agent.observations],
        "next_view_requests": [r.model_dump() for r in agent.requests],
        "exhausted_gaps": agent.exhausted,
        "overlays": overlays,
        "usage": agent.trace.summary(),
        "disclaimer": DISCLAIMER,
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_markdown(agent, overlays, report["usage"]), encoding="utf-8")
    return report


_ICON = {"VERIFIED": "[VERIFIED]", "VIOLATED": "[VIOLATED]", "INSUFFICIENT_EVIDENCE": "[INSUFFICIENT EVIDENCE]"}


def render_markdown(agent: InspectionAgent, overlays: dict, usage: dict) -> str:
    L = [f"# ProofCam inspection: {agent.spec.title}", "", f"_{DISCLAIMER}_", "",
         f"Stop reason: `{agent.stop_reason}` · observations: {len(agent.observations)} · "
         f"model calls: {usage['model_calls']} · est. cost ${usage['estimated_cost_usd']:.4f}", "",
         "## Requirements", ""]
    for a in agent.assessments:
        req = agent.spec.requirement(a.requirement_id)
        L += [f"### {_ICON[a.status]} {req.id}: {req.text}", "", a.explanation, ""]
        for ep in a.endpoints:
            L.append(f"- Endpoint {ep.index + 1} `{ep.device_id} {ep.port_label}`: **{ep.state}**")
            for s in ep.support:
                g = f" — grounding: {s.grounding.note}" if s.grounding else ""
                L.append(f"  - supports [{s.image_id}]: {s.claim}{g}")
            for c in ep.conflicts:
                L.append(f"  - conflicts [{c.image_id}]: {c.claim}")
            if ep.gap:
                L.append(f"  - missing: {ep.gap.missing_fact}")
        L.append(f"- Cable identity: **{a.identity_state}**")
        for x in a.identity_evidence:
            L.append(f"  - [{x.image_id}] {x.claim}")
        for x in a.assumptions:
            L.append(f"- Assumption: {x}")
        for x in a.contradictions:
            L.append(f"- Unresolved contradiction: {x}")
        L.append("")
    L += ["## Investigation", ""]
    for o in agent.observations:
        L.append(f"### Photo {o.seq} — `{o.image_id}` ({o.source_name}, {o.width}x{o.height})"
                 + (f" responding to `{o.responding_to}`" if o.responding_to else ""))
        if o.extraction is None:
            L += [f"Extraction failed: {o.extraction_error}", ""]
            continue
        e = o.extraction
        L.append(f"Scene: {e.scene_summary}")
        if not e.shows_inspection_subject:
            L.append("**Photo does not show the specified equipment — no evidence taken.**")
        if o.image_id in overlays:
            L.append(f"![overlay]({overlays[o.image_id]})")
        for g in o.sam:
            L.append(f"- SAM `{g.concept}`: {g.status}, {len(g.objects)} object(s)"
                     + (f" — {g.error}" if g.error else ""))
        for ref, link in o.device_links.items():
            L.append(f"- Device {ref} grounding: {link.note} (corroborated={link.corroborated})")
        L.append("")
        req = next((r for r in agent.requests if r.based_on_image_id == o.image_id), None)
        if req:
            L += [f"**Next view `{req.id}`** ({req.planner}, gap `{req.gap_code}`): {req.instruction}",
                  f"- missing fact: {req.missing_fact}", f"- target: {req.target_region} · action: `{req.camera_action}`",
                  f"- why: {req.rationale}", f"- resolves if: {req.success_criteria}", ""]
    if agent.exhausted:
        L += ["## Gaps abandoned", ""] + [f"- `{k}`: {v}" for k, v in agent.exhausted.items()] + [""]
    L += ["## Model usage", "", "```json", json.dumps(usage, indent=2), "```"]
    return "\n".join(L)
