# Progress log

## 2026-10-30 — Milestone 0: technical feasibility (implementation complete, live validation BLOCKED)

### Environment
Windows 11, Python 3.12.10 venv (`backend/.venv`; system default 3.15 not used for wheel compatibility).
Node not installed (not needed until Milestone 3). `pip install -e` failed (build-deps fetch); tests use
`pythonpath` in `pyproject.toml` instead. **No `MODEL_API_KEY` present. No physical photos present.**

### Done
- Verified Meta API docs (raw `.md` pages) → `docs/META_API_FACTS.md`; inspected `meta-sam-parser` 0.1.0 source
  for the undocumented Python entry point (`parse_responses_stream(...).final_result()`) and record semantics.
- Backend package `backend/proofcam/`: client (retries, Retry-After, SSE, hard call budget, redacted trace),
  image normalization, strict Pydantic model-output schemas + wire-schema generator, Muse observation
  extraction with one validation-repair retry, SAM grounding + Muse↔SAM linking, deterministic policy,
  gap selection, Muse next-view planner with deterministic fallback, bounded agent loop, overlays,
  JSON/Markdown reports, CLI (`python -m proofcam.cli`), live API probe (`experiments/probe_api.py`).
- Example spec `data/specs/router_switch.json` (device descriptions are placeholders to edit).

### Tests (all mocked — no real inference)
`pytest -q` → **52 passed** (2026-10-30). Coverage of the Phase C list:
structured-output validation (6 malformed cases, wire schema flat/locked) · missing evidence · correctly
visible → VERIFIED · empty port / wrong colour / wrong port (spec-unique only) → VIOLATED · contradictory
observations → INSUFFICIENT + CONTRADICTION gap · unrelated follow-up photo contributes nothing, SAM skipped ·
unjustified positives (illegible label, partial visibility, uncertain identity, no SAM corroboration, similar
cables across images, partially visible cable) → never VERIFIED · SAM inclusive→half-open boxes, mask placement,
sparse ids, zero matches, size mismatch · API failures (429 retry, 400 no retry, bounded 503, timeout, stream
error event, truncated stream, 401 on observe, planner 500 → fallback, SAM 400 → no grounded verdict) ·
bounded loop (gap attempts, observation budget, hard model-call budget, planner "not resolvable").
`pytest -m live` → 1 skipped (no key). Synthetic overlay alignment check: mask pixels exactly match the drawn
region (12,000/12,000).

### NOT done / blocked
- **No live Muse or SAM call has been executed.** All Milestone 0 success criteria that require real inference
  (recognition, useful next-view, real SAM grounding, second-photo update) are unverified.
- Unverified API assumptions: schema acceptance (`anyOf` nullables, inlined refs), Chat Completions reasoning
  parameter, real latency, SAM behaviour on thin cables/plugs.

### Next actions
1. User supplies `MODEL_API_KEY` in `.env` and a photo set (see README / chat instructions).
2. Run `experiments/probe_api.py` (format check), then the CLI on the photo set; record LIVE facts.
3. Tune prompts / grounding thresholds only against development photos; keep held-out photos untouched.
4. GO/NO-GO review before Milestone 1.

### Known issues
- Overlay text labels can overlap when Muse device and port boxes share a corner (cosmetic).
- Contradictions caused by the user physically fixing the setup mid-inspection are treated as contradictions
  (by design for now; see D7).
