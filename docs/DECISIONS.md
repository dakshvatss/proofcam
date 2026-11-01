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

## D11 — Reasoning effort is configurable, default unchanged (2026-10-31)
Live runs: `reasoning_effort=low` cut per-photo wall time ~2× (25–48 s → 6–29 s) with identical verdicts on the
five reference images. Added `PROOFCAM_MUSE_REASONING_EFFORT` (unset = API default). Choosing a default for the
live camera app needs same-device multi-view data and repeated runs; decide in Milestone 1.

## D12 — Reference images are independent scenarios (2026-10-31)
The five reference photos come from different setups. Each runs with its own spec and a fresh agent
(`experiments/run_scenarios.py`, `data/specs/reference/`). They validate API integration and single-photo
perception/abstention only; they cannot demonstrate multi-view inspection.

## D13 — Port identity: direct label by default; neighbour-layout inference only by explicit opt-in (2026-10-31)
On the user's setup the plug hides the target label whenever the cable is inserted (router LAN 1, switch 3), so
the label-only rule can never establish either endpoint. Rule (`policy.infer_port_identity`), all in ONE image:
the device declares `port_rows` containing the target once; every reported port of the device has a box; no port
is legibly labelled as the target; every legible label of that row sits at exactly the predicted offset (ordered
by box centre, same row = ≥50% vertical overlap); two legible anchors (both neighbours, or the next two inward
ports for a row end); neighbour spacing regular (ratio ≤ 1.5) so a port Muse missed breaks the chain instead of
shifting it. Muse is never asked to guess a hidden label. Inferred identity: counts toward support/identity only
when the requirement sets `port_identity: "label_or_layout"`, is disclosed as an assumption, still needs clear
insertion, colour and SAM grounding, and **never establishes a violation** (a mis-inference must not condemn a
correct installation). Inferred support against a direct-label violation is a contradiction. Known residual risk:
the rule trusts Muse's left-to-right order and box geometry (port boxes were ~1 port off in s01, though relative
order held in m2/m3); mirrored/rotated photos fail the order check rather than mis-identify. Default stays
`label_only`, including for `my_setup.json`.

## D14 — Cable identity is a separate single-image fact, joined to endpoints by port identity (2026-10-31)
Previously identity required the trace image to also fully support both endpoints. Now any one image showing a
required-colour cable `fully_traced` between ports identified as the two spec ports (plugs inserted, SAM-grounded)
establishes identity, and endpoint support may come from other photos. Joining is through *port* identity under
the static-installation assumption (a port holds one plug), never through cable appearance across images.

## D15 — Static verification by default; installation changes must be declared (2026-10-31)
All photos of an inspection are assumed to show one unchanged installation; a clear violation is terminal. A
correction workflow (technician fixes the cable mid-inspection) is supported only through an explicit
`mark_installation_changed(reason)` event: observations carry an `epoch`, only the current epoch is assessed,
earlier photos stay in the report marked superseded, gap attempts reset, budget stops are never reopened. Mixing
configurations without declaring a change surfaces as a contradiction or a violation, never as verification.
Deferred (Milestone 2/3): an "installation guidance" mode where violations are non-terminal coaching steps, and
automatic change detection.

## D16 — Perceive once, replay in any order (2026-10-31)
Perception of a photo (Muse extraction + SAM links) does not depend on inspection state, so experiments perceive
each photo once and replay the same observation into every order (`observe_recorded`, trace `source="replay"`).
Final-assessment differences can then only come from the agent/policy, not from Muse run-to-run variance.
Guidance planning may still be live (Muse) or deterministic (offline).

## D17 — M1 persistence: SQLite, rebuild the agent per request, snapshot + append-only evidence (2026-11-02)
No in-memory agent cache: every request rebuilds `InspectionAgent` from SQLite (`AgentState` snapshot + stored
trace events + stored normalized photos), so "after a restart" is the normal code path. Observations, requests,
history and trace events are append-only; a step commits in one transaction. Rebuilding by replaying
`observe_recorded` was rejected: it re-plans and would not reproduce request ids or gap attempts. Restore checks
budget, call limit, a fresh client (calls counter restored, never added to), trace length and sequence integrity.
Normalized photos and rendered overlays are stored as SQLite BLOBs (overlays rendered when the photo is processed,
because SAM masks are not persisted); originals are never stored. `policy_drift()` flags, never replaces, a stored
verdict that the current policy would not produce. Muse reasoning-effort configuration unchanged (D11).

## D18 — One capture at a time per inspection; synchronous POST /captures (2026-11-02)
A second capture while one is processing gets HTTP 409 (guidance is sequential). M1 uses a synchronous request;
the service keeps the step in a task independent of the HTTP connection so a 202 + polling flow can be added
without changing the engine. The agent itself refuses overlapping steps and snapshots taken mid-step.

## D19 — Idempotency and interrupted submissions (2026-11-02)
Retrying an `Idempotency-Key` returns the stored response; reusing a key with different image content is rejected.
An interrupted submission must not double-count model calls nor leave the inspection locked (design for Stage 2:
the call counter is persisted with each attempt, the lease is cleared and the submission marked interrupted on
recovery).

## D20 — SQLite schema, migrations and transactions (2026-11-02)
Stdlib `sqlite3` (no ORM), one connection per `Store` serialized by a lock, WAL, `foreign_keys=ON`,
`busy_timeout` 5 s. Schema version in `PRAGMA user_version`; each migration runs in one transaction with its
version bump (DDL is transactional in SQLite), a newer on-disk version is refused. Each fact is stored once:
inspection control state (gap attempts, exhausted gaps, current assessments, stop reason, budget) in
`inspections.control_json`; observations, requests, history (+ assessment snapshot per step) and trace in
append-only tables; normalized photos and overlays as BLOBs, restored with `NormalizedImage.from_stored`. Every
observation must reference a stored photo (FK), so replay-only agents without photos are not storable by design.
`commit_step` is one `BEGIN IMMEDIATE` transaction guarded by lease token + expected version; stored rows must be an
unchanged prefix of the new state (append-only check), so a stale or rewritten state cannot drop or alter evidence.
Trace/response/failure content carrying `data:image/` or bearer tokens is refused. `engine_version` = package
version + hash of the verdict/guidance modules, kept per inspection for policy-drift audit.

## D21 — Leases, idempotency and model-call accounting (supersedes the worst-case charge idea) (2026-11-02)
Lease = conditional `UPDATE ... WHERE lease_token IS NULL` with a random token and a heartbeat; never stolen on
acquire. `recover_interrupted(stale_before)` clears leases with an older heartbeat, marks their `processing`
submissions `interrupted` (failure audit kept) and their unsettled calls `outcome_unknown`; idempotent; re-checks
staleness inside the write transaction. `begin_capture` checks the idempotency key and takes the lease atomically:
same key + same image → stored response if done, busy if processing, new attempt if failed/interrupted; same key +
different image → `IdempotencyConflict`. Model calls: `reserve_model_call` (under the lease, before the request is
sent) increments the authoritative counter and inserts a `reserved` row in one transaction and refuses beyond the
budget; `settle_model_call` records ok/error without touching the counter; recovery and failure only relabel
unsettled rows `outcome_unknown` (billing unknown, counted once, never invented as completed). `commit_step` sets the
counter to max(stored, agent count), never a sum; `load_restore_bundle` gives the restored client the authoritative
counter. Stage 3 hook required: `MetaClient._reserve_call` must call `Store.reserve_model_call` (abort the call if it
raises) and the service settles each reservation from the matching `model_call` trace event; without the hook, calls
of an attempt that never commits are not counted.
