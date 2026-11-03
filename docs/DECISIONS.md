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

## D22 — Service and HTTP API (2026-11-02)
`InspectionService` rebuilds the agent from SQLite for every operation (no cache); reads use a MetaClient whose
transport refuses all requests, so reading an inspection can never call a model. Capture order: validate +
normalize (no lease) → `begin_capture` (idempotency + lease) → load bundle under the lease → stopped / stale-guidance
checks → restore → `observe` → overlays → response → `commit_step`; any exception → `fail_submission`. The step runs in
a service-owned task awaited through `asyncio.shield` (client disconnect does not abort a paid step); on shutdown
in-flight steps are cancelled and record their failure. Routes: `POST /api/inspections` (allow-listed `spec_id` =
stem of a `data/specs/*.json`, or inline spec), `GET /api/inspections/{id}`, `POST .../captures` (multipart `file`,
`source_name`, `responding_to`; `Idempotency-Key` header, else a server key), `POST .../events`
(`installation_changed`), `GET .../report?format=json|md`, `GET .../photos/{image_id}`, `GET .../overlays/{image_id}`,
`GET /api/health`. Errors are `{"error","message"}`: 404 not_found/spec_not_found/photo_not_found/overlay_not_found;
409 inspection_busy/inspection_stopped/stale_guidance/idempotency_conflict/cannot_reopen/lease_lost/conflict;
413 upload_too_large (15 MB); 422 invalid_request/empty_upload/image_not_decodable/image_too_large/
invalid_idempotency_key/invalid_spec_id; 500 internal_error (no internals) / storage_corrupt. State and report expose
`policy_drift` and `engine_changed`; stored verdicts are never recomputed in place.

## D23 — Persistent accounting hook, heartbeats, recovery (2026-11-02)
`MetaClient(accounting=...)` calls `before_request` before EVERY HTTP attempt (so retries are counted separately in
persistent mode, while the in-memory counter still counts logical calls) and `after_request` with the attempt's
known outcome; `StoreAccounting` maps these to `reserve_model_call` / `settle_model_call` and turns a store budget
refusal into `BudgetExhausted` (the request is never sent; the agent handles it like the in-memory budget). Store
errors such as `LeaseLost` are not `MetaAPIError`s, so they abort the step instead of becoming a fallback plan. A
heartbeat task renews the lease every 10 s; leases with a heartbeat older than 60 s are recovered at startup and
lazily when a request finds the inspection busy — an actively renewed lease is never taken. A step that lost its
lease is never committed (`lease_lost`). Deployment assumption for M1: one uvicorn worker; multi-process
correctness relies on the store's conditional leases and version checks, not on in-process state.

## D24 — Deployment constraints found in M1.4 (2026-11-02; to resolve before M5)
Synchronous `POST /captures` duration: observed live 25–48 s per photo (6–29 s with `reasoning_effort=low`); the
theoretical worst case with current timeouts (Muse 120 s and SAM 90 s, one retry on timeout, extraction + repair +
planning) is ~19 min. Common proxy defaults (e.g. 60 s) can cut the connection; the step still completes and the
client recovers by retrying the same Idempotency-Key (stored response) or reading `GET /api/inspections/{id}`.
Before deployment: raise the proxy timeout (≥ 300 s) and cap per-request model time, or switch to 202 + polling
(service already runs the step independently of the connection). The API has no authentication: any client that
reaches it can spend the model budget, so it must not be exposed publicly without an access control in M5. A
reverse proxy must also enforce the 15 MB body limit (the app rejects larger uploads only after receiving them).

## D25 — Three-way colour comparison (M2.1, 2026-11-02)
Defect (M2.0 probe): any single recognised colour word different from the requirement was a violation, so "dark
gray" for a black cable, "off-white" for beige, and a clear RJ45 plug described as "translucent white" with the
blue cable visibly attached all produced VIOLATED. Rule now (`policy.compare_color`, `plug_colour_status`): MATCH
(exactly one recognised base colour equal to the requirement) is the only colour that supports; CLEAR MISMATCH
(exactly one recognised colour, not a near neighbour, not described as see-through) is the only colour that may
violate; everything else is UNCERTAIN and does neither (gap INSERTION_UNCLEAR, `colour_ambiguous`). Near pairs are a
fixed table (white/beige/gray, black/gray, blue/purple, red/pink/orange/brown, orange/yellow, yellow/beige/green,
pink/purple); unknown words (teal, cyan, charcoal) stay unmapped and therefore uncertain. A colourless or
see-through plug takes the colour of a cable Muse links to that port only if the port is SAM-grounded, even in the
no-grounding ablation. A plug colour that clearly differs while a linked cable is (or may be) the required colour is
an in-photo disagreement: uncertain. The unique-cable wrong-port violation requires the plug's OWN colour. Trade-off:
a genuinely wrong near-colour cable (gray where black is required) is reported as unclear, not VIOLATED.

## D26 — Conflicting cable traces are contradictions (M2.1, 2026-11-02)
Defect (M2.0 probe P2): photo A traced the LAN 1 cable to switch port 3, photo B traced the same LAN 1 cable to
port 4; the result was VERIFIED with no contradiction. Rule now (`identity_evidence` returns conflicting traces): a
cable meeting every condition of an identity proof (fully traced, MATCH colour, plugs inserted with MATCH colour,
SAM-grounded) running from a port identified as one spec endpoint to a port on the other spec device whose own label
is legibly a different port is conflicting evidence (the conflicting side needs a direct label; inference never
creates negative evidence). Under the static-installation assumption one plug has one cable, so with a proof present
(or, with `unique_in_installation`, with both endpoints supported) it is a visible contradiction: `contradictions`
entry "cable identity: ...", CONTRADICTION gap (endpoint_index None), identity not established, no VERIFIED. Without
an opposing proof it is reported as "conflicting trace (not counted as evidence)"; it does not create a new violation
rule. Only current-epoch photos count (D15). Cable appearance across photos is still never used to join cables.

## D27 — Ambiguous device identity; cross-photo recognition disclosed (M2.1, 2026-11-02)
Defect (M2.0 probe P3): two devices in one photo both claimed as `router` still produced VERIFIED. Rule now
(`ambiguous_device_ids`): if more than one device in a photo (any certainty) claims the same spec id, that photo is
not used for that spec device at all (no support, no violation, no trace end); other devices in the photo are
unaffected; the explanation names the unused photos and DEVICE_NOT_SEEN carries `ambiguous_photos`. Recognition of
a device in different photos by matching the spec description is not independent proof of one physical unit; this
is stated in every report (`device_identity_note`, Markdown header) rather than solved (it would need unique marks).

Compatibility of D25–D27: no change to evidence/gap models, SQLite schema or API contracts (one additive report key).
Stored verdicts are never recomputed: inspections recorded by the M1 policy whose verdict the new policy would not
reproduce show `policy_drift` and `engine_changed`, with the stored verdict unchanged (tested).

## D28 — Expected labels are not observed text; guidance guard (M2.2, 2026-11-02)
Defect (live M1 smoke test): Muse's guidance said "the printed 'LAN 1' text beside its boot", text no photo had
shown (the plug hides it on the user's setup). Now: the agent computes the gap's spec labels never legibly read on an
unambiguously identified device in the current configuration and passes them to the planner as
`labels_never_read_in_any_photo`; the planner prompt says the gap's port_label is expected, not seen, and the
hidden-label rule no longer presumes a label exists (prompt change; live validation pending, M2.4). A deterministic
guard (`muse.presumes_unread_label`) flags such a label presented as visible text (followed by text/label/marking/
sticker, or preceded by printed/reads/says/showing...; bare-number labels only when quoted); naming the target
("the port labelled LAN 1", "the port expected to be LAN 1") is allowed. A flagged instruction is replaced by the
neutral deterministic plan (planner `deterministic_fallback`, `planner_error` says why, trace `unread_label_guard`);
flagged success_criteria/target_region/rationale are rewritten neutrally; plans judged not visually resolvable are
left alone. All fallback templates were reworded to be neutral (tested against the guard). No extra model call.

## D29 — Attempts count only on-target photos (M2.2, 2026-11-02)
Defect (M2.0 probe P4): two unrelated photos exhausted the router's gap. An attempt is still counted when a request is
issued (unchanged stored semantics); if the photo answering it does not address it (unusable or no subject; the
target device not identified clearly and unambiguously, any certainty for DEVICE_NOT_SEEN; for port-level gaps the
device without any reported port; CABLE_CONTINUITY needs both devices) the attempt is refunded. If the same gap is
selected again, the same request (same id) is re-issued with no planner call. Guidance context ("device in latest
view") now skips photos that identify no spec device, so an irrelevant photo does not redirect guidance. Bounded by
the photo and model-call budgets (an off-target photo still costs its own observe call). Deterministic; no new stored
state. "Addresses" uses Muse's validated per-photo claims, not SAM device masks (the switch concept found 0 objects).

## D30 — Contradictions call for installation review, not photos; stop `contradiction_requires_review` (M2.2)
Defect (M2.0 probe P5): a contradiction was answered with "close view" requests although, with append-only evidence,
no further photo of the unchanged installation can remove it. Now an INSUFFICIENT requirement with a CONTRADICTION
gap is blocked: it gets no camera request; `agent.review_items()` describes it (conflicting photos, contradiction
text, action `review_installation`, message pointing to `installation_changed`); other requirements continue. When
nothing else can be pursued the agent stops with the new reason `contradiction_requires_review` (additive Literal
value; stored states, AgentState JSON and the store accept it). Like other non-budget stops it is reopened by a
declared installation change, which supersedes (never deletes) earlier photos; epochs are never reset
automatically. The endpoint-contradiction gap text no longer promises that "a clear, close view is needed" (text
only; stored assessments of contradicted inspections will show `policy_drift`, verdict unchanged).
API (additive): `review_required: list[ReviewItem]` on inspection state and step responses (derived at read time;
default [] so stored pre-M2.2 responses replay unchanged); report JSON `review_required`; Markdown "Review required"
section. A photo-budget stop still takes precedence over a review stop on the last allowed photo. Clients that switch
on `stop_reason` must treat the new value as a stopped inspection.

## D31 — Device corroboration by IoU or containment (M2.3, 2026-11-03; report-level only)
Problem: SAM segments the whole router (body + antennas) while Muse boxes the body, so box IoU < 0.5 on correct masks.
Measured offline on recorded live runs (`experiments/grounding_offline.py`: the recorded raw SAM output re-decoded with
the production parser, no API calls): of 17 device groundings with SAM objects, 12 passed IoU (not each checked by eye;
the m4/m7 overlays viewed show correct masks); 4 failed IoU although the mask was visually the right device with antennas (m7-synthetic 0.41, s01
0.32 and 0.32, m4 0.23); 1 (s05 run 2, IoU 0.44) could not be judged (image 282 px wide). Rule now
(`grounding.device_corroboration`): IoU >= 0.5 as before, OR containment, judged per SAM object: Muse box >= 90%
inside that object's box, the object's mask covers >= 60% of the Muse box, SAM box area <= 5x the Muse box. On the
recorded data this turns the 4 confirmed false negatives into corroborations (worst values 0.948 / 0.746 / 4.02),
leaves the unjudgeable case uncorroborated (containment 0.828) and changes none of the 12 IoU passes. The thresholds
were set AFTER seeing these 17 cases (no held-out set exists), with margin to the worst value, plus guards tested on
synthetic negatives: scene-sized, displaced, outline-only and partially contained masks, and a different object of the
same concept (SAM 'router' also returned the NETGEAR switch in m4 and m7; per-object judging never lets it vouch for
the router). The link note now records IoU, containment, coverage, mask-inside share and area ratio. GroundingLink's
fields are unchanged (stored records are compared byte-for-byte). No verdict, gap or guidance uses device links.

## D32 — Port grounding unchanged; it is presence near a port, not port identity (M2.3, 2026-11-03)
Measured on the same recorded runs: of 14 occupied ports whose cable grounding passed, 10 had at least one EMPTY
neighbouring port whose expanded region the same mask also passes; in s04 the empty neighbour received more overlap
(1140 px) than the occupied port (970 px), and the switch port 3 support of the only live VERIFIED run had a neighbour
at 60% of its overlap. Because Muse port boxes are displaced (~half to one port), a stricter own-vs-neighbour rule
would drop correct support, so the rule (50% expansion, >= 30 px and >= 5%) stays. SAM port grounding therefore only
corroborates "a cable of this colour reaches near this port"; port identity and insertion rest on Muse's per-port
label/occupancy claims and the M2.1 rules (a legibly empty port stays a violation whatever SAM shows). Residual risk:
two same-colour cables in adjacent ports cannot be told apart by SAM. A SAM port/plug concept might localise ports;
untested — proposed as a capped paid experiment (PROGRESS 2026-11-03), not assumed.
