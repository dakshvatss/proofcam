# ProofCam — project context for Claude Code

ProofCam is a real-time, camera-guided AI agent that verifies physical equipment installations
(Meta Global AI Developer Hackathon 2026, Indie Developer track, theme "Push the Frontier";
deadline **2026-11-04 21:00 ET**). The product decision is final.

**Core idea:** active visual evidence acquisition under uncertainty. The agent decides what it needs to
see next: OBSERVE → GROUND → ASSESS → IDENTIFY UNCERTAINTY → SELECT NEXT VIEW → REOBSERVE → VERIFY,
bounded by budgets.

## Non-negotiable rules
- Runtime AI = **Meta Model API only** (Muse Spark 1.3, SAM 3.1). Never Anthropic models at runtime.
- Requirement states: `VERIFIED`, `VIOLATED`, `INSUFFICIENT_EVIDENCE`. **Only the deterministic policy
  (`backend/proofcam/policy.py`) sets them.** Model JSON is a claim, never proof.
- Never invent masks, boxes, confidences, observations, test assets, or benchmark results.
- SAM segmentation ≠ connection semantics. A cable near a port ≠ connected. Similar cables in different
  images ≠ same cable. Missing observation ≠ verification. Contradictions stay visible.
- Overlays are drawn on the captured (normalized) image, not on the live preview, unless alignment is proven.
- Keep live API results, mocks, replays and synthetic assets clearly labelled (`TraceEvent.source`).
- Never expose `MODEL_API_KEY` to the browser; never commit secrets, private photos, or databases.
- Verify Meta API behaviour against docs (raw markdown: `https://dev.meta.ai/docs/<page>.md`, index at
  `https://dev.meta.ai/llms.txt`) and record it in `docs/META_API_FACTS.md`. Do not assume features.

## Architecture (backend/proofcam)
`config` settings/budgets · `images` normalization (one image basis for Muse+SAM) · `meta_client` HTTP,
retries, SSE, official `meta_sam_parser` · `observation` model-output schemas · `wire_schema` →
response_format · `muse` extraction + next-view planning · `grounding`/`geometry` SAM ↔ Muse linking ·
`evidence` ledger types · `policy` deterministic verdicts + gap selection · `agent` bounded loop ·
`trace` audit · `report`/`overlay` outputs · `cli`.

## Working conventions
- Python 3.12 venv at `backend/.venv` (`backend/.venv/Scripts/python.exe` on Windows).
- Tests: `cd backend && .venv/Scripts/python.exe -m pytest -q` (mocks). Live: `-m live` (costs money).
- Stack: React/TS/Vite/Tailwind/shadcn/Lucide frontend (Milestone 3); FastAPI/Pydantic/SQLite backend.
- Milestones: 0 feasibility → 1 core backend → 2 active agent → 3 live camera app → 4 evaluation →
  5 deploy/submission. Stop for review at milestone boundaries.
- Update `docs/PROGRESS.md` (log), `docs/DECISIONS.md` (choices), `docs/META_API_FACTS.md` (API facts).
  Keep this file short and stable.
