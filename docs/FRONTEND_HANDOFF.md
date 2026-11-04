# Frontend handoff — ProofCam HTTP API (as of M3.2, 2026-11-03)

For the Milestone 3 camera app. Describes the API **as it exists** (`backend/proofcam/api.py`, `api_models.py`,
`evidence.py`); nothing here is planned behaviour. The interactive schema is at `http://localhost:8000/docs`.

Start: `cd backend; .venv\Scripts\python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --port 8000`

## Ground rules for the app
- **The browser never sees `MODEL_API_KEY`.** It talks only to this API.
- **No CORS middleware exists.** Serve the app from the same origin, or use a Vite dev proxy (`/api` →
  `http://localhost:8000`). Do not add `allow_origins=["*"]`.
- **Access boundary (M3.2, D35).** If the server has `PROOFCAM_ACCESS_CODE`, every route except `/api/health`,
  `/api/access`, `/api/session` needs the session cookie from `POST /api/session` (else 401 `unauthorized`). Without a
  code, `app_from_env` (and the mock dev server) only serve requests made directly on that computer (403
  `remote_access_requires_auth`). A server-wide model-call cap (`PROOFCAM_GLOBAL_CALL_LIMIT`, default 50) refuses new
  captures with 429 `spend_cap_reached`. This is a private-testing boundary, not a public deployment (M5).
- **Verdicts come only from the server.** Show `assessments[].status` exactly; never derive or upgrade a status in
  the UI. Model claims (`explanation`, `claim` strings) are evidence descriptions, not verdicts.
- **Overlays are drawn on the captured photo** (`overlay_url`), never on the live preview.
- Show the `disclaimer` string on the report screen.

## Errors (all routes)
`{"error": "<code>", "message": "<human text>"}`.

| Status | Codes |
|---|---|
| 404 | `not_found`, `spec_not_found`, `photo_not_found`, `overlay_not_found` |
| 401 | `unauthorized` (no/invalid session), `invalid_access_code` |
| 403 | `remote_access_requires_auth` (no access code configured; request not from this computer) |
| 429 | `spend_cap_reached` (server-wide model-call cap; nothing sent), `too_many_attempts` (10 wrong codes/min) |
| 409 | `inspection_busy`, `inspection_stopped`, `stale_guidance`, `idempotency_conflict`, `cannot_reopen`, `lease_lost`, `conflict` |
| 413 | `upload_too_large` (> 15 MB) |
| 422 | `invalid_request`, `empty_upload`, `image_not_decodable`, `image_too_large`, `invalid_idempotency_key`, `invalid_spec_id` |
| 500 | `internal_error` (no internals), `storage_corrupt`, `spec_invalid` |

## Routes

### `GET /api/health` → `Health`
`{status: "ok"|"degraded", schema_version, integrity_problems: [], engine_version, model_source}`.

### `GET /api/access` → `AccessStatus` (open)
`{auth_required, authenticated, model_source ("live"|"mock"), global_model_calls, global_call_limit,
global_remaining}` — the spend fields are null unless authenticated. The app calls it at start-up.

### `POST /api/session` → `AccessStatus` (open) · `DELETE /api/session` → 204
Body `{"access_code": "..."}`. Sets cookie `proofcam_access` (HttpOnly, SameSite=Strict, Secure on HTTPS, 30 days;
value is an HMAC, not the code). Wrong code → 401 `invalid_access_code`; 10 wrong codes in a minute → 429. Cookies are
per origin, and an iOS Home Screen app has its own cookie jar (enter the code again there).

### `POST /api/inspections` → 201 `InspectionState`
Body: exactly one of `{"spec_id": "my_setup"}` (stem of a file in `data/specs/`: `my_setup`, `router_switch`) or
`{"spec": {...inline InspectionSpec...}}`. Free (no model calls).

### `GET /api/specs` → `SpecSummary[]` (M3.4; extended M3.5)
`[{spec_id, title, devices: [name], max_photos, requirements: [{id, text, connector, cable_color (null = any),
endpoints: [{device, port, flexible}]}]}]`. Free. Lists only specs that load, so drafts holding `TODO` placeholders
never appear. Spec endpoints may carry a `selector` (flexible: any permitted port; see D37); `port_label` is then a
display name such as "any LAN port". `InspectionState.created_at` (Unix seconds) is new in M3.5.

### `GET /api/inspections/{id}` → `InspectionState`
Free; it can never call a model. Use it to resume after reload, poll while `busy`, or recover after a dropped
capture request.

### `POST /api/inspections/{id}/captures` → `StepResponse` (**paid: live Muse + SAM calls**)
`multipart/form-data`:
- `file` (required): the photo. Any Pillow-decodable image (JPEG/PNG/WebP). HEIC is not supported → encode the
  camera frame to JPEG in the browser (canvas `toBlob('image/jpeg', 0.9)`). The server normalizes it (EXIF
  rotation, long side ≤ 1600 px); all coordinates and overlays refer to that normalized image.
- `source_name` (optional, ≤ 200 chars): a display name; reduced to a base name.
- `responding_to` (optional, ≤ 64): the `next_view.id` the user is answering. If given and not the current
  request → 409 `stale_guidance`. Omit it for a free (unguided) capture.
- Header `Idempotency-Key` (recommended; 1–200 visible ASCII chars): one new UUID **per photo**, reused only to
  retry that same photo.

**Synchronous and slow:** 25–48 s live at default reasoning (6–29 s with `PROOFCAM_MUSE_REASONING_EFFORT=low`);
theoretical worst case ≈ 19 min. Set a long client timeout and show progress. The step keeps running if the client
disconnects.

### `POST /api/inspections/{id}/events` → `InspectionState`
Body: `{"type": "installation_changed", "reason": "<1–500 chars>"}`. Declares a physical change: earlier photos
become `superseded` (kept, no longer counted), gap attempts reset, a non-budget stop is reopened. Free.
409 `cannot_reopen` if stopped by a budget; 409 `inspection_busy` during a capture.

### `GET /api/inspections/{id}/report?format=json|md`
JSON report (adds `policy_drift`, `persistent_usage`, `engine_version {recorded, current}`, `version`,
`review_required`) or Markdown (`text/markdown`).

### `GET /api/inspections/{id}/photos/{image_id}` · `GET /api/inspections/{id}/overlays/{image_id}`
`image/jpeg`. The normalized photo the models saw; the overlay (SAM masks filled, Muse boxes dashed) rendered on it.
Use `photos[].photo_url` / `photos[].overlay_url`; `overlay_url` is `null` when no overlay exists (e.g. extraction
failed) → 404 `overlay_not_found` if requested anyway.

## Response shapes (key fields)

`overall` (M3.4; on `InspectionState`, `StepResponse` and the JSON report): `{status, explanation,
requirement_statuses {id: status}, review_required [id]}` or `null` before any photo. The policy derives it from
the requirement verdicts: VERIFIED only if all are VERIFIED, VIOLATED if any is VIOLATED, otherwise
INSUFFICIENT_EVIDENCE. Show it as is; never compute your own. Spec requirements carry `connector` (`ethernet`,
`hdmi`, ...).

`StepResponse`: `inspection_id, seq, image_id, duplicate_of (int|null), notes[str], status ("open"|"stopped"),
stop_reason, assessments[RequirementAssessment], next_view (NextViewRequest|null), review_required[ReviewItem],
version, usage, replayed (bool)`.

`InspectionState`: `id, spec_id, title, status, stop_reason, epoch, version, engine_version, engine_changed,
policy_drift[str], busy, spec, photos[PhotoInfo], assessments, next_view, review_required, exhausted_gaps{key: reason},
history[dict], usage, disclaimer`.

`PhotoInfo`: `seq, image_id, source_name, width, height, epoch, superseded, usable, responding_to, photo_url,
overlay_url`.

`RequirementAssessment`: `requirement_id, status ("VERIFIED"|"VIOLATED"|"INSUFFICIENT_EVIDENCE"), explanation,
endpoints[EndpointAssessment], identity_state ("established"|"assumed_by_spec"|"unknown"|"not_evaluated"),
identity_evidence[EvidenceItem], gaps[Gap], contradictions[str], assumptions[str]`.

`EndpointAssessment`: `index, device_id, port_label, state ("established"|"violated"|"contradicted"|"unknown"),
support[EvidenceItem], conflicts[EvidenceItem], inferred_only[EvidenceItem], gap`. `EvidenceItem`: `seq, image_id,
port_ref, device_ref, claim, grounding, port_basis ("direct_label"|"layout_inference"|null)` — `seq` links evidence
to a photo.

`NextViewRequest` (the guidance banner): `id, requirement_id, gap_code, missing_fact, target_region, camera_action,
instruction, rationale, success_criteria, planner ("muse"|"deterministic_fallback"), based_on_image_id,
after_image_id, gap_key, planner_error`. Show `instruction` prominently, `success_criteria` as the check.
`camera_action` ∈ `move_closer, move_to_rear, move_to_front, move_left, move_right, look_down_from_above,
look_up_from_below, step_back_wide_view, remove_obstruction, improve_lighting, hold_steady_refocus` (icon hint).

`ReviewItem`: `requirement_id, photos[int seq], contradictions[str], action: "review_installation", message`.

`Usage`: `model_calls, model_call_limit, remaining, calls_by_status{ok, error, reserved, outcome_unknown},
estimated_cost_usd, cost_basis`.

## Stop reasons (`status == "stopped"`)
| `stop_reason` | Meaning | Can continue? |
|---|---|---|
| `all_requirements_resolved` | Every requirement VERIFIED or VIOLATED | Only via `installation_changed` (e.g. after fixing a VIOLATED cable) |
| `no_visually_resolvable_gaps` | Remaining gaps exhausted (2 on-target attempts) or judged not visually resolvable | Via `installation_changed` |
| `contradiction_requires_review` | Every open requirement is blocked by a contradiction | Via `installation_changed` if something was physically changed; otherwise final |
| `observation_budget_exhausted` | 6 photos used | **No** (409 `cannot_reopen`) |
| `model_call_budget_exhausted` | 40 model calls used | **No** |
Treat any unknown future value as "stopped". A capture on a stopped inspection → 409 `inspection_stopped`.

## `review_required` behaviour
A requirement whose evidence contradicts itself (photos disagree about a port, or trace one cable to different
ports) gets **no camera request** — another photo of an unchanged installation cannot remove the conflict. It appears
in `review_required` with the photos involved and a message. Other requirements may still have a `next_view`, so
the inspection can be `open` with review items. UI: show a review card (not a camera prompt) listing the photos, with
an action "I changed the installation" → `POST /events installation_changed`. `review_required` defaults to `[]`.

## Other notes the UI should surface
- `notes[]` on a step: human-readable messages (photo not usable, off-target photo with the guidance kept, gap given
  up, review needed). Show them under the result.
- `duplicate_of`: the identical photo was already submitted; no model calls were made.
- An **off-target photo** (wrong device, unusable) keeps the same `next_view.id`; no attempt is counted.
- `engine_changed` / `policy_drift`: the inspection was recorded by an older engine; show a banner. Stored verdicts
  are shown unchanged by design.
- `assumptions[]` must be shown next to a VERIFIED verdict (e.g. layout inference, spec-asserted unique cable).

## Safe retry handling
1. Generate one `Idempotency-Key` per photo before uploading; keep it until a 2xx or a non-retryable 4xx.
2. Network error / timeout / 5xx `internal_error`: retry the **same photo with the same key**:
   - finished meanwhile → 200 with the stored response, `replayed: true`, **no new model calls**;
   - still processing → 409 `inspection_busy` → wait (poll `GET /api/inspections/{id}` until `busy == false`), retry;
   - previous attempt failed or was interrupted → it is run again (new calls; earlier calls stay counted).
3. Same key with a different photo → 409 `idempotency_conflict` (bug in the client: new photo needs a new key).
4. 409 `stale_guidance` → re-read state and show the current `next_view`; do not resend blindly.
5. 409 `lease_lost` / `conflict` → nothing was saved; retry the same key.
6. 409 `inspection_stopped` → show the final state; offer `installation_changed` only for non-budget stops.
7. Never send two captures for one inspection concurrently (the second gets 409 `inspection_busy`).
8. Without an `Idempotency-Key` the server generates one, so a retried upload becomes a **new** paid step (or a
   `duplicate_of` no-op if the image bytes normalize identically). Always send a key.
