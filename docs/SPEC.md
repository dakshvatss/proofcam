# ProofCam — product specification

## Product
A mobile-first, camera-first web app. The user points a phone camera at a physical installation; ProofCam
observes it, identifies relevant components, evaluates written requirements, determines what evidence is
missing, and tells the user exactly which view to show next. The camera stays open throughout. Inference
runs on selectively captured frames (user-triggered first, stable-frame detection later), asynchronously,
via Meta Model API.

ProofCam verifies **visually observable conditions only**. It does not certify electrical safety, hidden
connectivity, operational performance, or regulatory compliance.

## Scope of the MVP
- Requirement type: **connection** — "cable of colour C connects device A port X to device B port Y".
  The spec format has a `kind` discriminator so more visible-condition types can be added later.
- Physical environment: router/switch (or labelled mock devices), distinguishable coloured cables,
  correct, incorrect, hidden and ambiguous arrangements, multiple angles.

## Requirement states
`VERIFIED` · `VIOLATED` · `INSUFFICIENT_EVIDENCE`, set only by the deterministic policy.

## Evidence model (per inspection)
Inspection ID · spec/requirements · source images with capture sequence and image IDs · per-image model
claims · SAM grounding and its link to claims · supporting / conflicting evidence per endpoint ·
requirement states · next-view requests · gaps abandoned and why · agent steps · model invocation trace
(latency, status, usage, cost) · final report.

Each next-view request carries: requirement, missing fact (gap code + text), target region, camera action,
instruction, rationale, success criteria, planner source (Muse / deterministic fallback), base image.

## Acceptance criteria — Milestone 0 (feasibility)
Given a saved photo of a setup with incomplete evidence, ProofCam:
1. recognises the relevant visible equipment (Muse, live);
2. identifies a specific unresolved requirement and the missing fact;
3. requests a useful, specific next camera view;
4. grounds at least one relevant object with real SAM 3.1 output, drawn as an aligned overlay;
5. incorporates a second real photo;
6. updates findings with source-image provenance;
7. never falsely verifies something it cannot establish.

## Acceptance criteria — later milestones (summary)
- **M1** FastAPI endpoints (create inspection, submit capture, get state/report), SQLite persistence.
- **M2** Loop refinements: contradiction resolution with explicit re-inspection, better gap planning, traces.
- **M3** React app: live preview (MediaDevices), capture, guidance banner, overlays on captured frames,
  evidence history, report, upload fallback. Dark charcoal + teal, mobile-first.
- **M4** Labelled physical scenarios, dev/held-out split; passive single-photo baseline vs active agent:
  accuracy, violation detection, false-verification rate, appropriate abstention, view relevance,
  completion, latency, calls, cost. No fabricated results.
- **M5** Deployment with server-side key, public repo, README, 3-minute demo.
