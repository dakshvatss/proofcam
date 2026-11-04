"""Inspection report: JSON (machine) + Markdown (human), with source-image provenance."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .agent import InspectionAgent
from .overlay import render_overlay
from .policy import overall_assessment

DISCLAIMER = ("ProofCam verifies visually observable conditions only. It does not certify electrical safety, "
              "hidden connectivity, operational performance, or regulatory compliance.")
DEVICE_IDENTITY_NOTE = ("Devices are recognised in each photo by matching them to the spec description; this is not "
                        "independent proof that photos of a device show the same physical unit. A photo in which more "
                        "than one device matches the same spec device is not used for it.")


def write_report(agent: InspectionAgent, run_dir: Path, stored_overlays: dict[str, bytes] | None = None) -> dict:
    """Write images, overlays, trace and report files to run_dir.

    stored_overlays (image_id -> JPEG) are overlays rendered when the photo was processed; they are used
    as-is. A photo whose SAM masks were not restored (agent.masks_unavailable) is never re-rendered, because
    an overlay without its masks would misrepresent what SAM found.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "images").mkdir(exist_ok=True)
    (run_dir / "overlays").mkdir(exist_ok=True)
    stored_overlays = stored_overlays or {}
    overlays = {}
    for o in agent.observations:
        img = agent.images.get(o.image_id)
        if img is None:  # offline replay without the original photo
            continue
        (run_dir / "images" / f"{o.seq:02d}_{o.image_id}.jpg").write_bytes(img.jpeg_bytes)
        if o.extraction is None:
            continue
        p = run_dir / "overlays" / f"{o.seq:02d}_{o.image_id}.jpg"
        if o.image_id in stored_overlays:
            p.write_bytes(stored_overlays[o.image_id])
        elif o.seq in agent.masks_unavailable:
            continue
        else:
            render_overlay(img, o, agent.grounding_runs.get(o.seq), p)
        overlays[o.image_id] = p.relative_to(run_dir).as_posix()
    agent.trace.write_jsonl(run_dir / "trace.jsonl")
    report = build_report(agent, run_dir.name, overlays)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_markdown(agent, overlays, report["usage"]), encoding="utf-8")
    return report


def build_report(agent: InspectionAgent, inspection_id: str, overlays: dict[str, str]) -> dict:
    """Report as a JSON-able dict, with no side effects. overlays: image_id -> overlay reference (path/URL)."""
    return {
        "inspection_id": inspection_id,
        "spec": agent.spec.model_dump(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "require_grounding": agent.require_grounding,
        "stop_reason": agent.stop_reason,
        "epoch": agent.epoch,
        "photo_order": [{"seq": o.seq, "image_id": o.image_id, "source_name": o.source_name, "epoch": o.epoch}
                        for o in agent.observations],
        "history": agent.history,
        "requirements": [a.model_dump() for a in agent.assessments],
        "overall": (o.model_dump() if (o := overall_assessment(agent.assessments)) else None),
        "observations": [o.model_dump() for o in agent.observations],
        "next_view_requests": [r.model_dump() for r in agent.requests],
        "review_required": agent.review_items(),
        "exhausted_gaps": agent.exhausted,
        "overlays": overlays,
        "usage": agent.trace.summary(),
        "disclaimer": DISCLAIMER,
        "device_identity_note": DEVICE_IDENTITY_NOTE,
    }


_ICON = {"VERIFIED": "[VERIFIED]", "VIOLATED": "[VIOLATED]", "INSUFFICIENT_EVIDENCE": "[INSUFFICIENT EVIDENCE]"}


def _ep_line(agent: InspectionAgent, ep) -> list[str]:
    L = [f"- Endpoint {ep.index + 1} `{agent.spec.device(ep.device_id).name} {ep.port_label}`: **{ep.state}**"]
    for s in ep.support:
        g = f" — grounding: {s.grounding.note}" if s.grounding else ""
        L.append(f"  - supports [photo {s.seq} · {s.image_id} · {s.port_basis}]: {s.claim}{g}")
    for c in ep.conflicts:
        L.append(f"  - conflicts [photo {c.seq} · {c.image_id}]: {c.claim}")
    for x in ep.inferred_only:
        L.append(f"  - not counted [photo {x.seq} · {x.image_id} · {x.port_basis or 'unidentified'}]: {x.claim}")
    if ep.gap:
        L.append(f"  - missing ({ep.gap.code}): {ep.gap.missing_fact}")
    return L


def _contributions(agent: InspectionAgent, seq: int) -> list[str]:
    """Evidence items in the CURRENT assessment that come from this photo."""
    L = []
    for a in agent.assessments:
        for ep in a.endpoints:
            name = f"{agent.spec.device(ep.device_id).name} {ep.port_label}"
            L += [f"- supports {name} ({x.port_basis})" for x in ep.support if x.seq == seq]
            L += [f"- conflicts with {name}: {x.claim}" for x in ep.conflicts if x.seq == seq]
            L += [f"- plug at {name} seen but not counted ({x.port_basis or 'port not identified'})"
                  for x in ep.inferred_only if x.seq == seq]
        L += [f"- cable identity: {x.claim}" for x in a.identity_evidence if x.seq == seq]
    return L


def render_markdown(agent: InspectionAgent, overlays: dict, usage: dict) -> str:
    L = [f"# ProofCam inspection: {agent.spec.title}", "", f"_{DISCLAIMER}_", "", f"_{DEVICE_IDENTITY_NOTE}_", "",
         f"Stop reason: `{agent.stop_reason or 'open — no more photos supplied'}` · photos: {len(agent.observations)} · "
         f"model calls: {usage['model_calls']} · est. cost ${usage['estimated_cost_usd']:.4f}", "",
         "Mode: static verification — all photos of one configuration are assumed to show the same unchanged "
         "installation; photo order does not change the assessment.", ""]
    if agent.epoch:
        L += [f"**The installation was declared changed {agent.epoch} time(s); only photos of configuration "
              f"{agent.epoch} count below.**", ""]
    review = agent.review_items()
    if review:
        L += ["## Review required", ""] + [f"- **{r['requirement_id']}**: {r['message']}" for r in review] + [""]
    overall = overall_assessment(agent.assessments)
    if overall and len(agent.assessments) > 1:
        L += ["## Overall installation verdict", "",
              f"**{_ICON[overall.status]}** {overall.explanation}", "",
              "_Derived from the requirement verdicts below: VERIFIED only if every requirement is VERIFIED, "
              "VIOLATED if any is VIOLATED, otherwise INSUFFICIENT EVIDENCE._", ""]
    L += ["## Final verdict", ""]
    for a in agent.assessments:
        req = agent.spec.requirement(a.requirement_id)
        L += [f"### {_ICON[a.status]} {req.id}: {req.text}", "", a.explanation, ""]
        for ep in a.endpoints:
            L += _ep_line(agent, ep)
        L.append(f"- Cable identity: **{a.identity_state}**")
        for x in a.identity_evidence:
            L.append(f"  - [photo {x.seq} · {x.image_id}] {x.claim}")
        for x in a.assumptions:
            L.append(f"- Assumption: {x}")
        for x in a.contradictions:
            L.append(f"- Unresolved contradiction: {x}")
        for g in a.gaps:
            L.append(f"- Open gap `{g.key}`: {g.missing_fact}")
        L.append("")

    L += ["## Timeline (verdict after each photo)", "",
          "| # | photo | config | verdict(s) | endpoints | identity | next view / event |",
          "|---|---|---|---|---|---|---|"]
    for h in agent.history:
        if h["event"] == "installation_changed":
            L.append(f"| — | — | {h['epoch']} | — | — | — | installation changed: {h['reason']} "
                     f"(photos {h['superseded_photos']} no longer count) |")
            continue
        reqs = h["requirements"]
        eps = "; ".join(f"{e['device_id']} {e['port_label']}={e['state']}" for r in reqs for e in r["endpoints"])
        ev = h["next_view"] or (f"STOP: {h['stop_reason']}" if h["stop_reason"] else "")
        if h.get("duplicate_of"):
            ev = f"duplicate of photo {h['duplicate_of']} (ignored); " + ev
        L.append(f"| {h['seq']} | {h['source_name']} | {h['epoch']} | "
                 + ", ".join(r["status"] for r in reqs) + f" | {eps} | "
                 + ", ".join(r["identity_state"] for r in reqs) + f" | {ev} |")
    L.append("")

    L += ["## Investigation (photos in the order received)", ""]
    for o in agent.observations:
        L.append(f"### Photo {o.seq} — `{o.image_id}` ({o.source_name}, {o.width}x{o.height})"
                 + (f" responding to `{o.responding_to}`" if o.responding_to else "")
                 + (" — SUPERSEDED (earlier configuration)" if o.epoch != agent.epoch else ""))
        if o.extraction is None:
            L += [f"Extraction failed: {o.extraction_error}", ""]
            continue
        e = o.extraction
        L.append(f"Scene: {e.scene_summary}")
        if not e.shows_inspection_subject:
            L.append("**Photo does not show the specified equipment — no evidence taken.**")
        if o.image_id in overlays:
            L.append(f"![overlay]({overlays[o.image_id]})")
        if e.ports:
            L.append("Muse port claims: " + "; ".join(
                f"{p.ref} '{(p.label_group + ' ') if p.label_group else ''}{p.label_read or '?'}' "
                f"[{p.label_legibility}] {p.occupancy} plug={p.plug_color or '-'} ({p.insertion_visibility})"
                for p in e.ports))
        for c in e.cables:
            L.append(f"- cable {c.ref}: {c.color}, {c.path_visibility}, ports {c.connected_port_refs}")
        for g in o.sam:
            L.append(f"- SAM `{g.concept}`: {g.status}, {len(g.objects)} object(s)"
                     + (f" — {g.error}" if g.error else ""))
        for ref, link in o.device_links.items():
            L.append(f"- Device {ref} grounding: {link.note} (corroborated={link.corroborated})")
        for key, link in o.port_links.items():
            L.append(f"- Port {key} grounding: {link.note} (corroborated={link.corroborated})")
        if o.epoch == agent.epoch:
            L += ["", "Contributes to the final assessment:"] + (_contributions(agent, o.seq) or ["- nothing"])
        L.append("")
        req = next((r for r in agent.requests if (r.after_image_id or r.based_on_image_id) == o.image_id), None)
        if req:
            L += [f"**Next view `{req.id}`** ({req.planner}, gap `{req.gap_code}`): {req.instruction}",
                  f"- missing fact: {req.missing_fact}",
                  f"- target: {req.target_region} · action: `{req.camera_action}`",
                  f"- why: {req.rationale}", f"- resolves if: {req.success_criteria}", ""]
    if agent.exhausted:
        L += ["## Gaps abandoned", ""] + [f"- `{k}`: {v}" for k, v in agent.exhausted.items()] + [""]
    L += ["## Model usage", "", "```json", json.dumps(usage, indent=2), "```"]
    return "\n".join(L)
