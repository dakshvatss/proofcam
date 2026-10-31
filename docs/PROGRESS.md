# Progress log

## 2026-10-31 — Milestone 0: live Meta API validation

### Environment
Key loaded from root `.env` (value never printed). Python 3.12.10 venv, all deps present. Unit tests: 52 passed
before and after changes. Images: five PNGs in `data/images/` (395×236 to 1112×810); all decode. 02 and 05 look
rendered/stock; 01 and 02 are **different** white routers — never paired.

### Live calls (all `source="live"`)
Probe (`experiments/probe_api.py` on 04): text ping 2.0 s, structured text 4.8 s, structured+image 9.4 s, SAM 3.2 s — all OK.
Scenarios (`experiments/run_scenarios.py`, each image an independent inspection with its own spec in
`data/specs/reference/`): run twice — API-default reasoning and `reasoning_effort=low`. 0 API errors, 0 retries,
0 schema-validation failures. Total ≈ 40 calls, ≈ $0.20.

| Scenario | Expected (annotated by viewing the image) | Actual Muse/SAM output | Verdict / next view |
|---|---|---|---|
| s01 white rear | Router rear, 1 blue + 4 orange ports, all empty, no readable labels | Router identified (clear, rear); 6–7 ports all `empty`/`clear`; labels `illegible`/`no_label` (correct); also counted power jack/buttons as ports. SAM router mask exact (incl. antennas); SAM blue cable: 0 matches (correct) | INSUFFICIENT. Gaps LABEL_ILLEGIBLE/PORT_NOT_FOUND + switch DEVICE_NOT_SEEN. Next view: step back to find the switch |
| s02 white front | Front only, ports not visible → should ask for rear | `visible_side=front`, `ports_visible=false` (correct). SAM router IoU 0.95 | INSUFFICIENT with PORTS_NOT_VISIBLE gap found — **but planner targeted the higher-priority switch DEVICE_NOT_SEEN gap**, not "go to the rear" |
| s03 ASUS front (spec names only a white router) | Must not be matched to the white router | `spec_device_id=null`, `shows_inspection_subject=false` both runs (correct, not merged). SAM skipped | INSUFFICIENT; deterministic fallback guidance (planner not called on a no-subject photo, by design) |
| s04 blue cable | ETHERNET port with blue cable, clear plug; DSL, USB empty | Ports DSL/USB/ETHERNET read; `partially_legible` (plug partly covers label); ETHERNET `cable_inserted`, **plug colour `transparent`** (correct: clear RJ45); cable C1 blue linked to P3. SAM cable conf 0.89, 970 px overlap with port region; modem IoU 0.88 | INSUFFICIENT (label partially legible; computer not seen). Next view: follow the blue cable to the right to the computer — specific |
| s05 laptop+router | Beige cable from yellow port to laptop; labels too small | Router + laptop identified; port with beige/off-white plug; labels illegible / partially legible. Run 2 claimed the cable `fully_traced` into a laptop port. SAM: cable 0.67, laptop 0.94, router 0.68 masks aligned | INSUFFICIENT both runs. Next view: move close to router rear to read port numbers / to laptop port at table level |

No VERIFIED or VIOLATED verdict was produced, and none was justified by any single reference photo.

### Findings
1. **Plug vs cable colour (policy gap):** policy matches colour only on `plug_color`; clear plugs (04) report
   `transparent`, so a correct blue cable could never be supported. Fix candidate: accept colour from a cable
   record linked to the port via `connected_port_refs`.
2. **Gap priority (02):** DEVICE_NOT_SEEN on the absent device outranks PORTS_NOT_VISIBLE on the device in view, so
   the "go to the rear" request was not issued. Fix candidate: prefer gaps on devices already in frame.
3. **Muse port boxes are imprecise** (offset ~1 port in 01); device boxes are good. Port grounding should come from
   SAM (e.g. a port concept) with Muse claims snapped to SAM instances.
4. **Device IoU check is wrong for antenna routers** (SAM includes antennas, Muse doesn't): use containment.
5. **Run-to-run variance** in Muse claims (colour words, `fully_traced`, legibility). Policy stayed conservative.
6. **Latency:** default reasoning 25–48 s/photo; `low` 6–29 s with the same verdicts. Added opt-in
   `PROOFCAM_MUSE_REASONING_EFFORT` (default unset = API default). Decision deferred to Milestone 1.
7. All-ports-clearly-empty (01) cannot yet yield VIOLATED because labels are unreadable; kept conservative.
8. Colour vocabulary lacks beige/off-white; spec colour "beige" currently can neither match nor conflict.

### Unproven
Same-device multi-view inspection; a live VERIFIED or VIOLATED verdict; next-view → follow-up photo actually
resolving a gap; stability across repeated runs; latency on phone-camera-sized images.

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
