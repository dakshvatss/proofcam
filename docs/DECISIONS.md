# Technical decisions

## D1 — Chat Completions for Muse, Responses (streaming) for SAM (2026-10-30)
Chat Completions has documented examples for both image input and `response_format` json_schema with
`muse-spark-1.3`. SAM is documented only on `/v1/responses`. We call both with `httpx` directly (async)
rather than the OpenAI SDK, for full control of SSE parsing, retries, timing and trace capture.

## D2 — One normalized image per capture (2026-10-30)
EXIF-transposed, RGB, long side ≤ 1600 px, JPEG q90; `image_id = sha256(bytes)[:12]`. The *same bytes*
go to Muse and SAM, so Muse's 0–1000 grid and SAM's pixel boxes share one basis, and overlays are drawn
on exactly what the models saw.

## D3 — Model output is claims; verdicts are deterministic (2026-10-30)
Muse returns per-image perception claims (devices, ports, cables, legibility, visibility) and never a
verdict. `policy.py` turns claims into endpoint states and requirement statuses with explicit rules.
Weak claims (`uncertain`, `partial`, `partially_legible`, unknown colour) can never support a positive.

## D4 — Perception prompt is not primed with the expected answer (2026-10-30)
The observation prompt lists devices and ports of interest but **not** the required cable colour or the
requirement assertion, to reduce confirmation bias. The planner does see the requirement.

## D5 — SAM corroboration required for endpoint support (default on) (2026-10-30)
An endpoint is supported only if a SAM mask of the required cable concept reaches the Muse-reported port
region (expanded 50%, ≥30 px and ≥5% of region). This makes unsupported positives harder. Violations
(e.g. port clearly empty) do not require SAM, because absence cannot be segmented. `--no-grounding-requirement`
exists for ablation only. **Risk:** SAM may miss small plugs → more INSUFFICIENT_EVIDENCE; to be measured live.

## D6 — Cable identity is never inferred from appearance across images (2026-10-30)
VERIFIED requires either one image in which the same cable is `fully_traced` between both supported ports,
or a spec-author assertion `cable_identity: "unique_in_installation"`, which is reported as an assumption.
The same assertion also enables "required cable is in the wrong port" violations.

## D7 — Contradictions block verdicts (2026-10-30)
Support + violation for the same endpoint → `contradicted` → INSUFFICIENT_EVIDENCE and a CONTRADICTION gap
(highest planning priority). We do not yet model "user fixed the installation between captures"; that
needs an explicit re-inspection action in the app (Milestone 2/3).

## D8 — Gap-driven next-view planning with deterministic fallback (2026-10-30)
Policy emits typed gaps (DEVICE_NOT_SEEN, PORTS_NOT_VISIBLE, LABEL_ILLEGIBLE, PORT_NOT_FOUND,
INSERTION_UNCLEAR, GROUNDING_MISSING, CABLE_CONTINUITY, CONTRADICTION). The agent picks the most
fundamental open gap; Muse plans a concrete camera instruction from the latest photo. If Muse fails, a
deterministic template still names the device/port. Each gap has ≤ 2 targeted attempts; the planner can
declare a gap not visually resolvable. Hard caps on observations and model calls (enforced in the client).

## D9 — Milestone 0 persistence = run directory, not SQLite (2026-10-30)
`runs/<id>/` holds normalized images, overlays, `trace.jsonl`, `report.json`, `report.md`. SQLite arrives
with the FastAPI backend in Milestone 1. `runs/` is git-ignored (private photos).

## D10 — Async core (2026-10-30)
The agent and client are async so FastAPI can call them directly and SAM concepts run concurrently.
