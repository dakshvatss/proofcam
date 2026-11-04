# Progress log

## 2026-11-04 — M3.9: assisted template accepts a router OR a Jio set-top box (no paid calls; not committed)
- An **intentional spec change**, requested by the user for this installation. The equipment is a dark navy Jio
  set-top box with one RJ45 socket and a white Ethernet cable to the PS5. This is not a claim that a set-top box is
  technically equivalent to a router.
- In `ps5_home_setup_assisted.json` (now `_v2`), device `router` / "Wi-Fi Router" becomes `source` / "Ethernet source
  device". Its description lists the accepted categories and tells Muse to state the category and never call a
  set-top box a router.
- The R1 source endpoint accepts any RJ45 socket identified by its observed shape. A legibly labelled `WAN` or
  `Internet` socket never qualifies. There are no LAN 1–4 labels, port count or colour requirements.
- The PS5 description lists two USB-A, RJ45, HDMI OUT and AC IN. The TV accepts any HDMI input, numbering optional.
- The report lists, per photo, which spec device each seen device was matched to and Muse's own description, so the
  actual category is shown.
- The previous router-based assisted spec is kept as `backend/tests/fixtures/assisted_router_spec.json`, so the
  M3.7/M3.8 assisted-rule tests still run against it. The strict template and all other templates are unchanged.
- Tests: backend 493 passed (`test_m39_source_device.py` 8). Frontend 54 passed; build OK.

## 2026-11-04 — M3.8: operator-assisted Home template usability (no paid calls; not committed)

**Root causes of the repetition** (Report B record):
- Muse's planner was free to answer an open fact with small re-framings ("shift a few inches left", "step back 6–8
  inches"), and the same gap could be requested twice.
- A plug Muse saw clearly but SAM missed could never be completed, so the only move left was another photo of the
  same plug.

**Changes (only where the spec sets `assisted`, i.e. `ps5_home_setup_assisted.json`):**
- `AssistedMode` holds the explicit flags for this template.
- **Colour:** ignored; the spec may not even name a colour. Connector family is still enforced.
- **One targeted request per open fact**, then the guidance moves on with a clear note.
- **Micro-adjustment guard:** planner instructions that only re-frame the same view are replaced by the fixed
  template for the missing fact. The planner also gets assisted rules: seek new facts, several at once.
- **New statement `endpoint_insertion`:** "the plug Muse saw is seated". It is allowed only for:
  - a clear insertion,
  - at a port identified by label or socket shape,
  - where Muse explicitly reported the requirement's connector family,
  - with no contrary photo (an empty or other-plug observation refuses it).

  The item is marked `insertion_basis: operator_confirmed`, and the verdict is operator-assisted.
- **Labels:** "Verified — operator-assisted" / "Verified — visual evidence" in the app and report
  (`OverallAssessment.assurance`). The report tags every supporting item with its provenance (Muse observation, SAM
  corroboration, socket assumption, operator statement).

**Strict and exact templates are unchanged:**
- they have no `assisted` block;
- a test compares Report B's verdicts under both Home templates;
- strict reports keep the plain `[VERIFIED]`.

**Tests:**
- Backend: **485 passed** (`test_m38_assisted.py` 20).
- Mutation-checked: 6 of 6 new rules, when broken, fail a test.
- Frontend: **54 passed**; `tsc` clean; oxlint the same 3 warnings; build OK.

## 2026-11-04 — M3.7: evidence levels, SAM recall fallback, operator statements, limits (no paid calls; not committed)

**Diagnosed from the recorded live observations** in `var/live-m33.db` (read-only; see D39):
- **Report B** (insp_c3ff…, Home Entertainment, 8 photos, 39/40 calls, INSUFFICIENT_EVIDENCE):
  - SAM `hdmi cable` segmented **nothing in 12 of 12** recorded photos, including clear PS5 HDMI close-ups. Muse saw
    the plug clearly in photos 5–7. Three photos went to re-framing the same plug. The cause is the concept's recall,
    not camera angle, thresholds or geometry.
  - Photo 4 (492×440 upload) reports a blue plug in the PS5 LAN socket. Photos 5–7 (iPhone photos) report the same
    socket **clearly empty**. The policy still said "confirmed (photo 4)", because shape-identified sockets were never
    cross-matched. This was a latent false-confirmation risk.
  - Photo 8 showed the TV's HDMI panel. Muse marked the TV `uncertain` (no logo in frame), and the earlier overview
    was rightly not reused.
- **Report A** (insp_f1bb…, router→switch, VIOLATED): sound.
  - Photo 3 read `LAN 1` as legible, clear and empty on an exact endpoint. The router was identified clearly, and SAM
    corroborated it (IoU 0.95).
  - The photo-2 refund and nv1 re-issue were correct.
  - Only presentation was wrong: the report card led with the switch's "not identified" gap instead of the violating
    evidence.

**Changes (verdict states unchanged; policy only gets stricter, except where a spec explicitly permits a statement):**
- `only_socket` selector flag. A spec-declared single socket is cross-matched across photos, so a plug in one photo and
  the socket empty in another is a CONTRADICTION. It never creates a violation on its own. Set for the PS5 LAN and
  HDMI OUT sockets.
- Muse-only plugs are kept as `candidates` on the endpoint ("seen by Muse only · SAM did not corroborate"). They never
  count as support.
- SAM generic `cable` fallback: at most one extra call, within the per-photo SAM cap. It fires only when the
  requirement's own concept returned no object at all. It uses a tighter region and an exclusivity check. Relying on
  it is disclosed as an assumption. **Not yet observed live.**
- Cable concepts that no occupied port could use are no longer sent, which saves one call on most single-family
  photos.
- `GROUNDING_MISSING` gets one targeted retry, then the guidance moves on with an honest reason.
- Operator statements (`OperatorDeclaration`), only where the spec permits them:
  - **Device identity:** for a device Muse claimed uncertainly in one photo. Never for an ambiguous or
    differently-matched device. It supports evidence only and never creates a violation.
  - **Cable identity:** between two supported endpoints whose connector family Muse reported. It is refused against
    a contrary trace, which becomes a CONTRADICTION.
  - Both are free (no model calls) and append-only. They are persisted and survive a restart.
- `assurance` (`visual` / `spec_assumption` / `operator_assisted`) and `operator_declarations` on every
  VERIFIED/VIOLATED requirement.
- Limits:
  - `MAX_PHOTOS_LIMIT` is now 16, and the Home spec allows 12 photos (was 8).
  - The per-inspection call limit is configurable (`PROOFCAM_INSPECTION_CALL_LIMIT`, `start-live.ps1
    -InspectionCallLimit`, default 40). It is fixed per inspection at creation.
  - The app warns near either limit, and turns the camera off below 2 calls left.
- Report: the assurance line, statements with time and configuration, Muse-only candidates, the models actually
  called, the photo budget, and a provenance note (synthetic vs physical is **not** recorded).
- New spec `ps5_home_setup_assisted.json` permits both statements. The strict `ps5_home_setup.json` does not; its
  verification rules are unchanged apart from `only_socket`.

**Replay of Report B (offline, 0 calls), current engine:**
- R1 is CONTRADICTION (PS5 LAN: photo 4 vs 5–7), so review is required.
- R2 PS5 HDMI is GROUNDING_MISSING (candidates 5–7, "SAM segmented no 'hdmi cable'"), exhausted after photo 6.
- Photo 6's guidance moves to the TV.
- Photo 8 is `captured` but gives `DEVICE_UNCONFIRMED`. It is declarable only under the assisted spec.

**Tests:**
- Backend: **465 passed**, 1 deselected (live). `test_m37_evidence.py` has 26 tests, including a Report B replay from
  `tests/fixtures/live_home_report_b.json`.
- Mutation-checked: each of 9 safety rules, when broken, fails a test.
- Frontend: **50 passed** (`m37.test.tsx` 7); `tsc` clean; oxlint the same 3 known warnings; build OK.

## 2026-11-04 — M3.6: view relevance vs evidence vs verdict (live-run fix; no paid calls; not committed)

**Live failure:**
- In inspection insp_f702… (live Muse Spark 1.3 + SAM 3.1), photo 3 showed the router rear as requested.
- The app called it off-target and accepted 0 evidence items.
- Diagnosed from the recorded observations in `var/live-m33.db` (see D38):
  - **Muse:** read the ports and labels correctly, but marked the router `uncertain`. The spec description did not
    match this router.
  - **Guidance matching:** required a certain identification. This was the bug.
  - **Policy:** kept a false "ports not visible" gap, so the planner repeated the request.

**Fix:**
- `ViewCheck` (captured / partial / not_captured) in the step response and history.
- New gap `DEVICE_UNCONFIRMED`.
- Clearer facts for permitted ports seen empty and for plugs in non-permitted ports.
- Flexible-endpoint contradictions on the same labelled port.
- Planner rules against cable-moving instructions and unsupported claims.
- Accurate wording on the last-photo card ("Requested view captured", "Connection still needs evidence", "Port
  identity could not be established").
- The router description now holds only the facts the user gave.

**Verification is unchanged:**
- The policy still accepts only clearly identified devices.
- Wrong-port VIOLATED is only possible under the existing criteria.

**Replay of the recorded live inspection (offline, 0 model calls):**
- Photo 2, a top view Muse attributed to no device: `not_captured`, refunded, nv1 kept.
- Photo 3: `captured`, identity not confirmed, 0 evidence, gap `R1:DEVICE_UNCONFIRMED:0`.
- Next request: a raised, angled view tying the router's identifying features to its ports.

**Tests:**
- `test_view_relevance.py` (20): the 12 requested scenarios, plus live photos 1 and 3 replayed from
  `tests/fixtures/live_home_router_rear.json` (recorded output, copied verbatim; no photographs).
- An updated policy test, now split in two.
- An HTTP `view_check` check.
- `viewcheck.test.tsx` (4).
- Mutation-checked: each of these fails a test:
  - requiring a certain identity in the matcher again;
  - dropping the identity gap;
  - dropping the flexible contradiction;
  - letting the policy accept uncertain devices;
  - letting excluded labels such as WAN count as permitted.

**Results:**
- Backend: 439 passed, 1 deselected.
- Frontend: 43 passed; `tsc` clean; oxlint the same 3 known warnings; build OK.

## 2026-11-04 — M3.5: final release candidate (no paid calls; not committed)

Release candidate for the demo. Nothing below has been run on the real hardware with live models.

**Backend**
- Flexible requirements (D37): port selectors (allowed labels, label groups, exclusions, spec-asserted socket
  shape), any-colour cables, and a per-spec `max_photos` (≤ 10).
- SAM concepts are prioritised when the per-photo cap binds.
- `GET /api/specs` adds endpoints, `cable_color` and `max_photos`; `InspectionState` adds `created_at`.
- `data/specs/ps5_home_setup.json` is active ("Home Entertainment Installation"; any LAN port → PS5 LAN, Ethernet;
  PS5 HDMI OUT → any TV HDMI input, HDMI; any colour; trace required; 8 photos).
- Exact specs are unchanged (`my_setup.json` untouched).
- New tests: `test_flexible_requirements.py` (23, mutation-checked: shape-without-observation, empty-permitted-port
  violation, loose group prefix, ignored exclusions and untraced any-colour cables each fail a test).

**Frontend:** light-first redesign.
- Design tokens; Inter (OFL, self-hosted); new brand mark, favicon and PWA icons.
- Landing with templates, inline setup and a connection diagram.
- Camera workspace; honest analysing state; last-photo result from the real step response.
- Progress per connection (Pending / Verified / Violated / Needs evidence); audit timeline from persisted
  history; supervisor report summary with photo-backed claims, Download and JSON.
- Two-column desktop layout; LIVE / MOCK / REPLAY labels.
- Visual QA: headless Edge with mobile emulation, 375 / 390 / 430 px and 1440 px, on synthetic images through the
  real API with mocked models. A diagram overflow at 390 px was found and fixed.

**Results**
- Backend: 418 passed, 1 deselected.
- Frontend: 39 passed; `tsc` clean; oxlint the same 3 reviewed warnings; build OK, with no chunk warning (report
  lazy-loaded).
- The API key value appears in no file outside `.env`.

Runbook and recording checklist: `docs/DEMO_RUNBOOK.md`.

## 2026-11-04 — M3.4 spec finalisation: blocked on three facts (no paid calls; not committed)

No router or TV photographs were found in the session or the repository (`data/images` holds only the
2026-10-31 router/switch reference set). Filled in the draft `data/specs/drafts/ps5_home_setup.json` with what is
established:
- router and TV descriptions as stated by the user;
- original PS5 rear ports as named by Sony ("LAN port", "HDMI OUT port"; spec labels `LAN` / `HDMI OUT`).

Whether that text is printed on the PS5 case is not confirmed; if it is not, those endpoints stay
INSUFFICIENT_EVIDENCE by design. Still `TODO`, so the spec stays non-loadable and is not offered by `/api/specs`:
- the router LAN port label;
- the TV HDMI input label;
- the Ethernet cable colour;
- the HDMI cable colour.

`my_setup.json` is untouched. Tests: backend spec/policy/API 61 passed; frontend 35 passed; build OK.

## 2026-11-04 — M3.4: three devices, two connections in one inspection (mocks only; no paid calls; not committed)

Generalised engine (D36): requirement `connector`; observed `connector_type` per port and cable; connector-family
rules in the policy; `policy.overall_assessment` exposed as `overall` in state, step responses and reports (plus a
Markdown "Overall installation verdict" section for multi-requirement specs); `GET /api/specs`; `TODO` guard on
specs. Draft `data/specs/drafts/ps5_home_setup.json` (Home Entertainment Installation; every hardware fact is
`TODO`, not loadable). Frontend: spec chooser on the landing page, overall summary card, connection-labelled
requirement cards, and guidance that names its connection. Tests: `backend/tests/test_multi_requirement.py` (23,
synthetic fixture spec, mocked models; mutation-checked: disabling the family rule, the mixed-device rule or the
overall rule each fails tests) and `frontend/src/multi.test.tsx` (4). Results:
- backend: **395 passed**, 1 deselected;
- frontend: **35 passed**;
- `tsc` clean;
- oxlint: the same 3 reviewed warnings;
- build OK.

Runbook and the hardware facts still needed: `docs/THREE_DEVICE_INSPECTION.md`.

## 2026-11-04 — M3.3 UI/UX redesign (frontend only; no paid calls; not committed)

Visual and UX refinement of every screen. No change to the API client, `useInspection` (capture, retry, idempotency,
`responding_to`, stale guidance), the camera lifecycle, the service worker, or anything in the backend.

- **Design system:** colour, font and radius tokens in `src/index.css` (`@theme`):
  - warm-neutral near-black canvas; one teal accent for actions;
  - verdict colours reserved: green VERIFIED, red VIOLATED, sand INSUFFICIENT_EVIDENCE; violet for mock mode;
  - one global `:focus-visible` ring; reduced-motion override; `phone-landscape` variant.
- **Primitives:** Button (primary, secondary, ghost, danger), Card, CardTitle, Badge, Callout and Logo.
- **Screens:**
  - sticky app bar with a live/mock indicator, which stays the single `role="note"`;
  - access gate, landing ("Visual proof for physical work.") and the disconnected state with Try again;
  - viewfinder frame with corner marks and a thumb-zone control bar (upload, round shutter, switch camera); the staged-photo and analysing states share the same frame;
  - analysing state shows elapsed time only, with no invented progress;
  - status-led verdict panels with an observed/unproven checklist and evidence/explanation disclosures;
  - guidance card, review card, stop card and a bottom-sheet change dialog (Esc closes it);
  - photo viewer and history, and the audit-style report.
- **Checks:** headless Edge with mobile emulation at 375×667, 390×844, 430×932 and 844×390, on synthetic images against the mock server: no horizontal overflow.
- **Tests:** frontend 31/31; `tsc` clean; oxlint shows the same 3 reviewed warnings; build OK; backend 372 passed.

## 2026-11-03 — Milestone 3.3: live-inference readiness (no paid calls; not committed)

The user opened M3.2 on the iPhone 16 over Tailscale Serve (tailnet only; Funnel off; serve → 127.0.0.1:4173).
Change of plan: the user does **not** own the router + switch shown in the AI-generated reference images. The real
equipment is a wall-mounted router with no switch. `my_setup` is therefore used as a deliberately unfulfilled work
order: expected INSUFFICIENT_EVIDENCE, or VIOLATED only for a clearly empty or wrong-colour, legibly labelled LAN 1
on a router matching the spec description. VERIFIED is impossible by construction.

Audit: model IDs, SAM ID and base URL in `.env` equal the documented values; key present (not printed);
`PROOFCAM_ACCESS_CODE` is not in `.env` (the phone session used a terminal variable). No backend or frontend
process was running; ports 8000/4173 were free. Added `scripts/start-live.ps1`: 127.0.0.1 only, refuses a busy port
and a missing or short code, separate DB `var/live-m33.db`, global cap 20, reasoning `low`, restores the
environment on exit. Zero-call probe on port 8010 with a scratch DB: `model_source=live`, 401 without a session
(also with a Tailscale header), cap 20/20 after login, 0 model calls. New test
`test_m33_live_cap_admits_an_overview_and_a_close_up`. Backend **372 passed**, 1 deselected. Frontend unchanged
(`dist` current). Runbook, expected verdicts, stop conditions, second-spec requirements and demo checklist:
`docs/LIVE_TEST_M33.md`. Awaiting approval for the first paid capture (≈ 8–12 calls, ≈ $0.06–0.12, hard
ceiling 20 calls).

## 2026-11-03 — Milestone 3.2: iPhone readiness, access boundary, spending cap (no paid calls; not committed)

**Not yet tested on an iPhone.** Tailscale is not installed; installing it, signing in, installing the iOS app and
enabling MagicDNS + HTTPS certificates need the user's approval (docs/IPHONE_SETUP.md step 0). Researched the
Tailscale docs (Serve, HTTPS certificates); `winget show Tailscale.Tailscale` → 1.104.5 (not installed).

Backend (D35): access code → HttpOnly session cookie (`POST/DELETE /api/session`, open `GET /api/access`), middleware
on every non-open route, wrong-code throttle; `local_only` guard without a code (403 for non-loopback client, non-local
Host, proxy/Tailscale headers); server-wide model-call cap (`PROOFCAM_GLOBAL_CALL_LIMIT`, default 50) with a pre-check
(429 `spend_cap_reached`, nothing sent, inspection untouched) and an in-transaction backstop in
`Store.reserve_model_call`; `app_from_env` reads both; mock server gets `--access-code` and the same guard. Bug found
and fixed: a call refused at its first reservation was counted as started (stored counter over-count).
No policy/grounding/agent change; engine version unchanged.

Frontend: access-code screen (code never stored; 401 anywhere → back to it); Live (amber, calls left) vs Mock
(purple) banner; stale guidance after an installation change hidden + "new configuration" prompt, next photo sent
without `responding_to`; per-verdict evidence list (support / conflicts / not counted, SAM notes, jump to photo);
Markdown report rendered (react-markdown + remark-gfm, no raw HTML); camera: rear preferred (4:3), stops on
background/interruption with a resume prompt, iOS-specific permission help; uploads re-encoded client-side to JPEG
≤ 2400 px (HEIC from the iPhone library, EXIF/GPS stripped; falls back to the original if undecodable);
`spend_cap_reached` keeps the photo for a later manual retry; safe areas (`viewport-fit=cover`, insets), `dvh`, sticky
thumb-reachable capture bar; PWA: manifest, icons (192/512/maskable/apple-touch 180), service worker for the app
shell only (never `/api`), registered in production builds; Vite `allowedHosts: ['.ts.net']`, preview proxy.

Tests: backend `pytest -q` → **371 passed** (351 + 20 in `tests/test_access.py`), 1 deselected. Frontend `npm test`
→ **31 passed** (17 + 14 in `src/phone.test.tsx`: access code flow, session expiry, live/mock labels, stale guidance
helper + no `responding_to`, evidence + jump to photo, rendered report, spend cap, rear camera + interruption,
background release, HEIC re-encode, decode fallback, review regression). Two existing frontend test fakes updated for
the new calls (`/api/access` at start-up; `getVideoTracks`). `tsc -b` clean, `vite build` OK, oxlint 3 reviewed warnings.

Local end-to-end (production build via `vite preview` → mock server with an access code, port 8010): PWA assets served;
`*.ts.net` Host accepted; 401 before login; wrong code 401; login cookie HttpOnly/SameSite=Strict (HMAC, not the code);
create + capture with a Tailscale identity header after login; photo 401 without cookie. Note: a mock server on port
8000 and a Vite dev server on 5173 started by the user at 19:49–19:50 were running (old code); left untouched.

## 2026-11-03 — Milestone 3.1: mobile-first camera web app (no paid calls; not committed)

Branch `m3-camera-frontend` (from `6755b4f`; carries the uncommitted M2.4 docs). Node.js v26.13.0 / npm 11.20.0
installed with winget (none was present). New `frontend/`: React 19, TypeScript 7, Vite 8, Tailwind 4, lucide-react,
hand-written shadcn-style primitives; Vitest 5 + Testing Library. New `backend/experiments/dev_mock_server.py`: the
real FastAPI app/service/store/policy with the tests' FakeMeta transport (scripted scenarios, SAM masks scaled to the
uploaded photo, every call `source="mock"`, health `model_source: "mock"`); also exports frontend fixtures recorded
from the real API. No change to backend runtime code, policy, thresholds or tests.

Implemented (D34): landing → create `my_setup` inspection; camera (MediaDevices, rear preferred, switch if several
cameras, opt-in, stopped after capture/when hidden/unmount, permission and insecure-context messages) + upload
fallback; confirm step before the paid analysis; capture with one Idempotency-Key per photo and `responding_to`;
processing state with elapsed time; verdict per requirement exactly as returned, missing evidence, assumptions;
guidance (instruction, camera action, success criteria); photo viewer with stored overlay toggle; history thumbnails
(superseded/unusable badges); review card for `review_required` / `contradiction_requires_review`; installation change
with explicit confirmation + reason; stop reasons; saved Markdown report + JSON link; resume after refresh (localStorage
+ `?inspection=`), including waiting for a capture still processing; engine-drift banner; mock-models banner.
Retry protocol: no HTTP response or 409 `inspection_busy` / 500 → poll saved state until not busy; if a step was
committed meanwhile, resend the same key (stored response, no new calls), else ask the user (retry same key / discard);
`stale_guidance` / `inspection_stopped` → discard photo, refresh state; double clicks guarded synchronously.

Tests: frontend `npm test` → **17 passed** (create, double-click create, resume, resume while busy, 404 resume,
upload→guidance→overlay→VERIFIED with `responding_to` and distinct keys, double-click analyse = 1 request, stale
guidance, dropped connection → state read → same-key replay, failure without commit → manual retry same key then new
key for a new photo, busy → poll → replay, review card without camera guidance + confirmed change, cancel sends
nothing, report, camera permission denied, stream stopped after capture, insecure context). `tsc -b` clean;
`vite build` OK; oxlint 2 warnings (reviewed, intentional). Backend `pytest -q` → **351 passed**, 1 deselected.

Local validation through the Vite proxy: real backend (`app_from_env` with a dummy key and an unroutable Meta URL,
scratch DB) — health, create `my_setup`, get, Markdown report, 404 shape, 0 model calls; mock server — capture →
INSUFFICIENT + `nv1`, same-key replay `replayed: true`, 409 `stale_guidance`, second capture → VERIFIED, overlay JPEG
served and visually aligned (1280×960). Not done: viewing the UI in a real browser (no browser automation here),
real phone, any live Meta call.

Findings (not changed): after `installation_changed`, `next_view` still returns the last request of the previous
configuration (backend returns `requests[-1]`); the dev proxy is HTTP only, so phone cameras need HTTPS (M3.2).

## 2026-11-03 — Milestone 2.4: offline acceptance and Milestone 2 close-out (no paid calls; not committed)

Documentation only; no code, policy, threshold or test change. HEAD `6755b4f` (m2.3), branch `m2-active-agent`.

Tests: `pytest -q` → **351 passed**, 1 live deselected (random seed, 162 s); `PYTHONHASHSEED=0 pytest -q -rA` →
351 passed (59 s). Identical to the M2.3 baseline. M2.1–M2.3 checked together against 10 criteria via existing
tests (colour ambiguity, conflicting traces, device ambiguity, contradiction review, off-target accounting, unread-label
guard on mocked guidance, antenna containment, documented port-grounding limit, restart/idempotency/accounting,
historical drift flagged not rewritten): **all PASS** — `docs/M2_ACCEPTANCE.md`.

New: `docs/M2_ACCEPTANCE.md` (acceptance report + unresolved risks R1–R8), `docs/FRONTEND_HANDOFF.md` (exact API
contract for M3: routes, shapes, stop reasons, `review_required`, photos/overlays, safe retries). Updated: README
(status, git state, repository map, next steps), GUIDE (status, maps, run commands, next steps), DECISIONS D33,
META_API_FACTS (open questions, recorded live facts from M1/M2.3). Finding while writing the handoff (not changed):
the API has no CORS configuration, so the app must be same-origin or use a dev proxy.

**Milestone 2: complete (offline).** Not done, by decision (D33): live validation of the M2 guidance wording, the SAM
port/plug concept measurement, authentication / global spending cap / timeout handling (needed before M5).
Live spend to date unchanged: ≈ $0.57 (no calls since the 2026-11-02 smoke test).

## 2026-11-03 — Milestone 2.3: grounding geometry (offline; no paid calls; not committed)

Implemented: device corroboration by IoU **or containment** (D31) in `grounding.py`; report-level only. Port grounding
rule unchanged after measurement (D32). New: `experiments/grounding_offline.py` (re-decodes SAM output recorded in
`runs/` with the production parser; writes `runs/grounding-offline-<ts>/measurements.json`; no API calls).

**Offline measurements on previously recorded live output** (2026-10-31 scenarios s01/s02/s04/s05 twice, own photos
m1-m7, the synthetic-image run; visual ground truth from the recorded overlays):
- Devices: 17 groundings with SAM objects. IoU rule: 12 corroborated (not each checked by eye), 4 false negatives
  (visually correct router masks incl. antennas), 1 unjudgeable. Containment rule: the 4 false negatives corroborated,
  the unjudgeable one not, the 12 unchanged. SAM `network switch`: 0 objects in all 8 switch groundings (as recorded before).
- New observation: SAM `router` also segmented the NETGEAR switch in m4 and m7 (second object). Muse's switch box
  matched that object well. Hypothesis only: a different switch concept might work; untested.
- Ports: 14 occupied ports grounded; in 10 the same mask also passes an empty neighbour's region; in s04 the empty
  neighbour got more overlap than the occupied port. Port grounding cannot discriminate adjacent ports.

Tests: `pytest -q` → **351 passed**, 1 live deselected (331 + 20 in `tests/test_grounding_geometry.py`), identical under
`PYTHONHASHSEED` random/0/621; no existing test changed. Mutation check: 5 containment guards each fail a test (one
initially survived; a test with a higher-IoU displaced decoy was added). Verdicts are provably independent of device
links (tested); M2.1/M2.2 suites unchanged and passing.

**Proposed paid experiment (NOT run; needs approval):** SAM only, on normalized images already recorded in
`runs/scenarios-m-20261031-154423` (the real m1-m7, not the synthetic revision now in `data/images/m7`), reusing the
recorded Muse output (0 Muse calls). Calls: m2 {ethernet port, ethernet plug}; m3, m4, m7 {ethernet port, ethernet
plug, ethernet switch}; m5 {ethernet port, ethernet plug}; m1 {ethernet plug, ethernet switch} = **15 SAM calls,
hard cap 16 (retries included), est. $0.04** (SAM $2.50/1000). Measure: port instances vs visible ports per row;
plug instances and whether each lands in the correct port column (ground truth from the photos: router leftmost port,
switch port 3; m5 port 4); a snapped Muse port box vs the known plug position; switch-concept IoU/containment vs Muse's
switch box. Success: port instances match the visible row in >= 3 of 4 positive photos with centres within half a
pitch; the plug concept finds the blue plug at the correct port in every positive photo. False-positive check: any plug
instance at a known-empty port (all of m1's switch ports; m5 switch port 3) or a port instance where there is none
fails the concept. Only a concept meeting all criteria would be proposed, in a later stage, for port-level grounding.

## 2026-11-02 — Milestone 2.2: next-view guidance and contradiction handling (offline; not committed)

D28 unread-label guard (prompt rule + deterministic check + neutral templates), D29 on-target attempt accounting with
request re-issue, D30 contradictions -> installation review and stop `contradiction_requires_review`. Files:
`agent.py`, `muse.py`, `prompts.py` (planner prompt only), `policy.py` (contradiction gap wording only), `service.py`,
`api_models.py` (additive `review_required`), `report.py`, GUIDE. No schema or endpoint change; no verdict rule change.

Tests: `pytest -q` → **331 passed**, 1 live deselected (297 + 34 in `tests/test_guidance.py`), identical under
`PYTHONHASHSEED` random/0/621. Three existing tests changed expectation by design (they asserted the removed
behaviour): a contradiction no longer yields a CONTRADICTION camera request (test_sequences, test_verdict_correctness),
and an unusable follow-up photo no longer triggers a planner call (test_persistence; its restored-image check now
calls the planning step directly). Mutation check: 9 new guards each fail a test. All other M2.1 tests unchanged.

The live smoke-test instruction ("...with the printed 'LAN 1' text beside its boot...") is now replaced by: "A plug is
in a Router port whose printed label could not be read, so it is not yet known whether this is LAN 1. Photograph that
port row closely from a low, angled position so that any label beside or under the plug can be read, and keep the
neighbouring ports' labels in the same frame." Whether Muse itself now avoids the presumption is unverified (M2.4).

## 2026-11-02 — Milestone 2.1: verdict correctness (offline; no paid calls; not committed)

Fixed the three classes of unsafe verdict confirmed in the M2.0 audit, in `policy.py` only (+ one report note):
three-way colour comparison (D25), conflicting cable traces as contradictions (D26), ambiguous device identity and
disclosure of cross-photo recognition (D27). All four M2.0 probes now give INSUFFICIENT_EVIDENCE (dark gray vs black,
translucent white + blue cable no longer VIOLATED; conflicting trace and duplicate router no longer VERIFIED); the
legitimate single-photo and complementary-photo VERIFIED cases are unchanged.

Tests: `pytest -q` → **297 passed**, 1 live deselected (244 + 53 in `tests/test_verdict_correctness.py`), identical
under `PYTHONHASHSEED` random/0/621; no existing test changed expectation. Covered: colour table (22 cases), near
colours, see-through plugs (grounded vs not, incl. ablation), in-photo plug/cable disagreement, clear mismatches and
empty ports still VIOLATED, unique-cable rule, conflicting traces in both orders and from either endpoint, five
non-qualifying traces that must not conflict, similar cables not joined, conflict without a proof reported only,
superseded epoch, snapshot/restore, duplicate devices (clear/uncertain), ambiguous photo cannot violate, HTTP +
restart + Markdown report showing the contradiction, and an M1-stored verdict flagged by `policy_drift` /
`engine_changed` without being rewritten. Mutation check: 8 new guards each fail a test.

Not yet done (M2.2): a contradiction still produces a "close view" request (now also for trace conflicts), although
no photo can resolve it.

## 2026-11-02 — First LIVE call through the M1 API (approved smoke test): PASS

`backend/experiments/api_smoke.py` (new): one inspection (`my_setup`), one real photo (`m2_router_rear_close.png`),
in-process ASGI app with the real network, hard cap 8 calls via the persistent budget, fresh DB in
`runs/api-smoke-20261102-022148/` (git-ignored), then a restart and full read-back. Trace `source="live"`.

Result: HTTP 200 in 33.9 s; **4 calls** (Muse observe 11.0 s, SAM `blue ethernet cable` 3.5 s, SAM `router` 8.1 s,
Muse plan 9.5 s), all reserved before sending and settled `ok`, 0 errors/retries; est. **$0.0348**. Verdict
**INSUFFICIENT_EVIDENCE** (router LAN 1 label hidden by the plug — `label_only` refuses the layout inference;
switch not seen), consistent with the 2026-10-31 live run of m2. Next view (Muse): get low and to the left of the
router rear to read the LAN 1 label. All 10 criteria passed: state/report/MD/photo/overlay after restart; idempotent
replay with no new calls; key absent from DB files and all responses. Overlay checked visually: SAM router mask and
cable box aligned with the photo; Muse port boxes slightly right-shifted (known M0 finding).
Observation (not changed): the planner's instruction refers to "the printed 'LAN 1' text beside its boot", a label
that has never been observed (the spec records it as hidden); guidance wording can presume unobserved facts.

## 2026-11-02 — Milestone 1, Stage 4: end-to-end reliability and offline acceptance (no paid calls, not committed)

Added `backend/tests/test_acceptance.py` (29 tests, FakeMeta/MockTransport + temp SQLite only). Fix: corrupt stored
state on the capture and event paths now returns 500 `storage_corrupt` (was generic `internal_error`); no other code
change. `pytest -q` → **244 passed**, 1 live deselected, identical under `PYTHONHASHSEED` random/0/621.

Demonstrated over HTTP with a fresh server + reopened SQLite before every photo: VERIFIED, VIOLATED and
INSUFFICIENT_EVIDENCE (bounded stop) give exactly the direct M0 engine's assessments, history, request ids, gap
attempts, exhausted gaps, trace (minus timings), images and calls; reports (JSON/MD) and stored photo/overlay bytes
match. All 6 photo orders of the complementary set verify with identical provenance. VIOLATED stop → 409 on capture
→ installation change → VERIFIED, earlier photo superseded, identical to M0. Budget never resets across restarts.
Reliability: reservation written before every HTTP attempt incl. 503 and timeout retries (checked inside the
transport); Muse 400 / malformed output / SAM 500 never yield a verdict; long call keeps its lease past the staleness
threshold, other inspections proceed in parallel; server shutdown mid-step → outcome_unknown, retry counted once;
**real `kill` of a child process mid-call** → lease recovered at next startup, submission interrupted, retry
completes, call counted once; commit failure rolls back; rogue version bump → 409 conflict, nothing saved; corrupt
state → 500 storage_corrupt, contained to that inspection; idempotency across restarts and inspections; no
cross-inspection leakage. Security: no DB/WAL/.env/private images/runs tracked and all git-ignored; the configured
key is in no tracked file (checked without printing it); hostile filenames reduced to base names; real
`uvicorn ... --factory --workers 1` started with a dummy key: health/create/get OK, key absent from logs. CLI and API
produce identical reports and traces for the same photos. Invariants (contiguous reservations = HTTP requests sent,
no unsettled reservation without a lease, contiguous sequences, image hashes, integrity, no VERIFIED without
grounded support) checked after every scenario. Mutation check: 4 more guards each fail an acceptance test.

Open (see D24): synchronous capture duration vs proxy timeouts; no API authentication (a public deployment would
let anyone spend the model budget); no live call through the API yet.

## 2026-11-02 — Milestone 1, Stage 3: service + FastAPI (mocked only; no paid calls; nothing committed)

New: `proofcam/service.py` (`InspectionService`), `proofcam/api.py` (`create_app(settings, store, transport=None)`,
`app_from_env` uvicorn factory), `proofcam/api_models.py`. Changed: `meta_client.py` (optional `CallAccounting`
hook called around EVERY HTTP attempt incl. retries; `image_id` passed to `_with_retries`; no hook = M0 behaviour),
`pyproject.toml` (fastapi, uvicorn, python-multipart). Policy, evidence, prompts, muse, grounding, CLI untouched.
Routes, accounting, heartbeat and recovery: D22–D23. Local startup: README §7.

Tests: `pytest -q` → **215 passed**, 1 live deselected (177 + 17 `test_service.py` + 21 `test_api.py`), identical
under `PYTHONHASHSEED` random/0/621. Covered: restart between photos equals an uninterrupted M0 agent (state, trace
minus timings, photos byte-identical, usage); reserve-before-send checked from inside the transport; retries
counted per attempt (503 settled `error`); store budget refuses before sending and survives restart; shutdown
mid-request → `outcome_unknown`, lease released, retry counts once; a frozen process's lease recovered by a second
process whose late result is refused (`lease_lost`); heartbeat keeps a lease past the staleness threshold and lazy
recovery does not steal it; caller disconnect does not abort the step; failure mid-commit leaves no partial step;
idempotent replay/conflict/duplicate; upload validation (empty, non-image, truncated, >15 MB); 409 busy/stopped/
stale guidance/cannot reopen; report JSON+MD and photo/overlay bytes after restart; policy drift flagged, not
replaced; generic 500 without internals; no key/Bearer/data URL in any response. Mutation check: 11 Stage 3 guards
each fail a test. Smoke run of the real `uvicorn proofcam.api:app_from_env` (scratch DB): health, create, get,
traversal 422 — no captures, so no model calls.

Not yet demonstrated: any live Meta call through the API (needs approval); heartbeat behaviour under a real
120 s Muse call; behaviour under multiple uvicorn workers (unsupported in M1); real process kill (simulated by a
frozen heartbeat + second Store on the same file).

## 2026-11-02 — Milestone 1, Stage 2: SQLite store (no API calls, no HTTP/service yet, nothing committed)

`backend/proofcam/store.py` (stdlib sqlite3; WAL, foreign keys, `PRAGMA user_version` migrations, explicit
`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`). Tables: `inspections`, `photos` (normalized JPEG + overlay BLOBs),
`observations`, `next_view_requests`, `steps`, `trace_events`, `submissions`, `model_calls`. AgentState is rebuilt
from the tables (`load_restore_bundle`), not stored twice. `config.database_path()` (`PROOFCAM_DB_PATH`, default
`var/proofcam.db`); `.gitignore` now also covers `var/` and `*.db-wal`/`-shm`/`-journal`. See D20–D21.

Tests: `pytest -q` → **177 passed**, 1 live deselected (133 + 44 in `tests/test_store.py`; temp databases, FakeMeta
only), identical under `PYTHONHASHSEED` random/0/621. Reopening the database between every photo reproduces the
uninterrupted run (state, trace minus timings, counters, request ids, photos byte-identical, overlays, per-step
assessments); bounded stop, budget stop and installation-change epochs survive reopening. Mutation check: 13
store guards (version check, append-only, rollback, idempotency image check, conditional lease, recovery staleness,
recovery call relabelling, max-not-sum counter, authoritative counter on restore, store budget check, unsafe
content) each make a test fail.

Not verifiable until Stage 3: the `MetaClient._reserve_call` → `Store.reserve_model_call` hook (exercised here only
by a test subclass), settlement of call outcomes in the live service, lease heartbeats during long Muse calls, the
startup recovery call, and HTTP 409 mapping of `InspectionBusy`.

## 2026-11-02 — Milestone 1, Stage 1: resumable agent state (no API calls, nothing committed)

Architecture approved (D17–D19). Stage 1 adds, with no change to `policy.py`/`evidence.py`:
`AgentState` + `InspectionAgent.snapshot()`/`restore()` (all counters, request ids, gap attempts, exhausted gaps,
stop reason, epoch, history, model-call counter; checks budget, fresh client, trace length, seq 1..n, image ids);
`InspectionAgent.policy_drift()` (pure re-assessment check); a one-step-at-a-time guard on `observe`,
`observe_recorded`, `mark_installation_changed`; `Trace.from_events`; `NormalizedImage.from_stored` (no re-encode,
bytes must hash to `image_id`); `overlay.render_overlay_jpeg`; `report.build_report` (side-effect free) and
`write_report(..., stored_overlays=)`, which never redraws a restored photo's overlay without its SAM masks.

Tests: `pytest -q` → **133 passed**, 1 live deselected (98 + 35 in `tests/test_persistence.py`, all mocked/replay).
Restart between every photo reproduces the uninterrupted run exactly (state, request ids, trace minus timings,
call counter) in 3 live-path orders, the bounded no-progress loop, the call-budget stop and the m2/m3/m7 replay.
Mutation check: removing any one restore step (calls counter, gap attempts, exhausted, requests, stop reason,
epoch, images, fresh-client check, busy flag, trace copy) fails at least one test.

Found and fixed a pre-existing flaky M0 test helper: `test_agent.observe()` coloured images with `hash(name) % 255`
(per-process randomized), so ~1 run in 255 two names produced identical photos → duplicate → 2 M0 tests failed
(reproduced with `PYTHONHASHSEED=621`). Now a sha256-derived colour; suite passes under seeds 0/1/621/12345/random.

## 2026-10-31 — Live multi-photo test with a SYNTHETIC (AI-generated) image: first live VERIFIED

**What this is:** a real Meta API run (trace `source="live"`, 12 calls, all `ok`) in which the third photo was an
**AI-generated revision of M7** (file `data/images/m7_router_rear_far.png`, image id `img_559976dd5064`; the original
real M7 was `img_4d3f6768c11c`). It tests the live pipeline and the policy on synthetic image evidence. It is
**NOT validation on a real installation**, and the VERIFIED must not be reported as one.

**Run:** `runs/20261031-180239-0c97ea/` (spec `data/specs/my_setup.json`, requirement `port_identity` =
`label_only`, SAM grounding required). All figures below were checked against that run's `report.json`/`trace.jsonl`.

| | |
|---|---|
| Photos, in order | 1 `m2_router_rear_close.png` → 2 `m3_switch_ports_close.png` → 3 revised `m7_router_rear_far.png` |
| After photo 1 / 2 | INSUFFICIENT_EVIDENCE both times (both endpoints `unknown`); Muse next-views `nv1`, `nv2` (gap `LABEL_ILLEGIBLE`) |
| After photo 3 | **VERIFIED**; stop reason `all_requirements_resolved` |
| Router LAN 1 | established from **photo 3**: P1 label `LAN 1` read as `legible` (`direct_label`), blue plug, clear, SAM cable mask 3609 px at the port |
| Switch Port 3 | established from **photo 3**: P9 label `3` `legible` (`direct_label`), blue plug, clear, SAM 3140 px |
| Cable continuity | established from **photo 3**: blue cable C1 `fully_traced` P1 ↔ P9, both ports SAM-grounded |
| Assumptions | none (no layout inference used) |
| Calls / cost | 12 calls (Muse 5: 3 observe + 2 plan; SAM 7), 0 errors; est. **$0.0941** (Muse ≈ 56.6 s total, SAM ≈ 25.4 s) |

How the verdict was reached: in photos 1 and 2 the plug hides the target labels. Layout inference identified
`LAN 1` (photo 1) and `3` (photo 2) but is **not permitted** under `label_only`, so those items are listed as "not
counted" and nothing was established. Photo 3 (synthetic) shows every port label `legible` (LAN 1–4, USB, 1–5), so
each endpoint and the cable trace were established directly in one image.

**How this differs from the earlier offline replay (section below):** the replay used the *real* M7, whose labels
were only `partially_legible`, and correctly stayed INSUFFICIENT_EVIDENCE in every order (cable identity not
established). That replay made no API calls. This run used a different, synthetic third image and live Muse/SAM, so
the two results are not comparable evidence of the same thing: the difference between them is the image, not the
policy. It does show that the policy reaches VERIFIED from live model output when the image legibly supports it.

**What this does and does not show.**
- Shows: live Muse + SAM + policy + live next-view planning run end to end; the policy verifies when one photo
  legibly shows both ports and a grounded, fully traced cable; no assumption or inference was needed.
- Does not show: behaviour on real photos (the real M7 cannot verify); that Muse reads real labels this well; order
  independence on live data (only one order, M2→M3→M7, was run live); stability across repeated runs.
- Note: Muse could in principle read an AI-generated image's text more cleanly than a real photo's; do not infer
  real-world accuracy from it.

Other observations from the run: SAM `network switch` again returned 0 objects (switch device grounding not
corroborated, and router device IoU was 0.41, below 0.5); neither is required for the verdict. Local file note: the
offline fixture and replay tests refer to the original M7 (`img_4d3f6768c11c`); with the revised file now at
`data/images/m7_router_rear_far.png`, `run_sequences.py` replay will not attach that photo (image-id mismatch;
verdicts unaffected, overlays/images omitted).

**Milestone 0 multi-photo status:** still not marked complete. A live order-varied experiment on real photos
(`run_sequences.py --mode live`) has not been run.

## 2026-10-31 — Order-independent evidence accumulation (offline only; live experiment NOT yet run)

**No paid API calls were made in this session.** Everything below is mocked or an offline replay of observations
recorded in the earlier live run `runs/scenarios-m-20261031-154423`.

### The m1–m7 live run (recorded here for the first time)
`runs/scenarios-m-20261031-154423` (script not in the repo): each own-setup photo was run as an INDEPENDENT
single-photo inspection with `data/specs/my_setup.json`. 30 live calls, ≈ $0.24, 16–37 s per photo. 0 API errors.

| Photo | What Muse/SAM reported | Verdict |
|---|---|---|
| m1 front | Switch ports `1`–`5` legible, all empty; router front only | VIOLATED (switch 3 clearly empty) — a different physical configuration (cable not yet in) |
| m2 router rear close | Leftmost Ethernet port: blue plug, `no_label` (label under the plug); `LAN 2/3/4` legible + empty; SAM cable grounded (22,151 px) | INSUFFICIENT (gap was PORT_NOT_FOUND) |
| m3 switch close | Middle port: blue plug, label `illegible` (under the plug); `1,2,4,5` legible; grounded | INSUFFICIENT |
| m4 wide | Switch 3rd port blue (label illegible); router end hidden under the router | INSUFFICIENT |
| m5 wrong port | Blue plug in switch 4th port; port `3` legible + empty | VIOLATED (switch 3 empty) |
| m6 occluded | Hand inserting the cable; labels 1–3 hidden | INSUFFICIENT |
| m7 rear far | Blue cable C1 `fully_traced` router P1 ↔ switch P9, both grounded; but every label only `partially_legible`/`illegible` | INSUFFICIENT |

Live findings: (a) the target labels are **physically hidden by the inserted plug** on both devices whenever the
cable is in place, so the strict rule can never establish either endpoint for this setup; (b) SAM `network
switch` returned **0 objects in all 7 photos** (`router` worked), so switch device grounding never corroborates
(device grounding is not required for verdicts, but the concept needs changing, e.g. "ethernet switch" / "black
box" — untested); (c) Muse also lists the DC jack / power button as ports.

### What already worked (verified by reading the code)
One `InspectionAgent` keeps every `ObservationRecord`; each `observe()` re-assesses ALL observations, so endpoint
support from different photos was already combined; gaps, attempt limits and budgets were bounded.

### What was missing → changes
1. **Cable identity was tied to endpoint support in the same image.** `require_trace` only accepted a fully traced
   cable in an image where both endpoints were also fully *supported*; identity was not even evaluated until both
   endpoints were established. Now (`policy.identity_evidence`) identity is a separate single-image fact: a cable of
   the required colour fully traced between a port identified as endpoint 1 and one identified as endpoint 2, each
   with a plug inserted and SAM-grounded. Insertion clarity may come from close-ups. Near misses (traced cable,
   ports not identifiable in that photo) are reported but never count.
2. **Port identity from neighbours** (`policy.infer_port_identity`, opt-in): see DECISIONS D13. Default
   `port_identity="label_only"` keeps the old behaviour. `my_setup.json` now declares `port_rows` for both devices
   (layout facts; the router's leftmost port being `LAN 1` is the user's own label — it is never printed visibly),
   but its requirement stays `label_only`.
3. **Clear plugs:** a colourless/unknown plug is supported if a cable of the required colour visibly belongs to
   that port in the same image (support only; never a violation).
4. **Hidden-label gap:** a matching plug in a port with an unreadable label now yields `LABEL_ILLEGIBLE` with
   `label_hidden_by_plug` (was `PORT_NOT_FOUND`) and a specific angle instruction.
5. **Guidance:** contradictions first, then gaps on a device visible in the latest photo, then gap type
   (fixes the s02 finding). The Muse planner now receives the established evidence and the earlier instructions
   for the same gap ("do not repeat"); the fallback template says the previous view failed. Fallback text no longer
   pastes the whole device description.
6. **Duplicates:** an identical image (same `image_id`) is not sent to the models and adds no evidence.
7. **Installation changes:** `InspectionAgent.mark_installation_changed(reason)` (CLI interactive: `!changed`).
   Static verification stays the default and violations stay terminal; after an explicit change, earlier photos
   are kept but stop counting (an `epoch` per observation). Budget stops cannot be reopened. See D15.
8. **Replay:** `InspectionAgent.observe_recorded()` integrates a recorded observation without perception calls
   (trace `source="replay"`); `plan_with_muse=False` uses deterministic plans (zero API calls).
9. **Report:** photo order, a per-photo verdict timeline, what each photo contributes, port-identity basis
   (`direct_label` / `layout_inference`), evidence not counted, near misses, installation changes, stop reason.

### Tests
`pytest -q` → **98 passed**, 1 live test deselected (was 52). New: `tests/test_evidence_fusion.py` (27, synthetic:
separable identity in all 6 orders → VERIFIED; trace to the wrong port / partial / ungrounded → not; trace alone
never verifies; 7 inference refusal cases; inference never a violation; inferred vs direct-empty → contradiction;
inferred support still needs SAM; clear-plug colour), `tests/test_sequences.py` (15, replay of the recorded
m1/m2/m3/m5/m7 observations from `tests/fixtures/my_setup_live_observations.json` — Muse/SAM text output only, no
photos), 4 more in `test_agent.py` (live code path with mocks: three complementary photos in three orders →
VERIFIED with correct provenance; planner receives evidence state and earlier failed requests). Mutation check:
disabling each of five policy guards (pitch ratio, anchor count, inference opt-in, near-miss, unboxed port) makes a test fail.

### Order-independence results (offline replay, `runs/sequences-replay-20261031-172829`)
`experiments/run_sequences.py` (replay mode), M2/M3/M7 in orders A m2→m3→m7, B m3→m7→m2, C m7→m2→m3 (tests: all 6):

| Variant | Final in every order | Endpoints | Identity |
|---|---|---|---|
| `label_only` (spec as authored) | INSUFFICIENT_EVIDENCE, identical | both `unknown`: LABEL_ILLEGIBLE (label hidden by plug) | unknown |
| `label_or_layout` | INSUFFICIENT_EVIDENCE, identical | router LAN 1 established from **m2**, switch 3 from **m3** (both by layout inference, disclosed) | unknown: m7 traces the cable but its labels are only partially legible, so its ports are not identified (near miss) |

Intermediate guidance differs by order, as expected (e.g. after m2 the strict variant asks for an angle on the
router label; the layout variant, router done, asks for the switch). Negatives (separate): m1 → VIOLATED and
stops; m5 → VIOLATED and stops; m3 then m1 without declaring a change → `label_only`: VIOLATED (m3 contributes
nothing); `label_or_layout`: CONTRADICTION (no verdict); m1 → declared change → m2,m3,m7 → m1 superseded, same
final as the positive set.

### Status
Order-independent accumulation is demonstrated **offline only**. Multi-photo behaviour for Milestone 0 is NOT
marked complete: the live experiment (`run_sequences.py --mode live`, ≈ $0.3–0.5) has not been run (needs
approval), and no live VERIFIED exists. With the current photos even the layout variant cannot verify; a wide
photo where both port rows' labels are legible (or a close-up that shows the cable leaving one port toward the
other device) is needed.

## 2026-10-31 — Own-setup inspection spec (`data/specs/my_setup.json`)

No live API calls; no inspection run. Spec authored from the user's photos `data/images/m1–m7` (gitignored, not
committed). Requirement R1 (blue Ethernet cable, Router LAN 1 → Switch Port 3, `require_trace`) is user-defined.

Transcribed (m1–m4 only): router = black TP-Link (logo on top), glossy top, two black external antennas, front LED
row; rear: DC jack, `WPS/Reset`, four silver-framed RJ45 ports, blue `USB`, `Power` button. Printed `LAN 2`/`LAN 3`/
`LAN 4` are legible (m2); **the leftmost port's printed label is hidden by the plug in m2 (and m7) — UNKNOWN**, so
`LAN 1` is the user's label and no aliases were added. Switch = black NETGEAR (wordmark on top), `Power` LED, five
ports printed `1`–`5` (port `3` legible in m1, covered by the plug in m3). Model numbers: not visible on either
device — omitted. Cable: blue jacket; transparent plug head with blue boot (m2, m3). Other cables: black power cords
only; no second Ethernet cable visible in m1–m4. Note: the fourth file is named `m4_wide_run.jpg.png`.

Local validation: spec parses (`LAN 1`→`LAN1`, `3`→`3`); all seven photos load via `images.load_image()` at
1448×1086 (unchanged). Privacy check (all seven viewed): no legible Wi-Fi password, serial number, MAC address or
other private text; m6 shows the user's hand. Unit tests: 52 passed, 1 deselected.

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
8. **False-violation risk from colour wording.** `beige/cream/tan/khaki/ivory → beige` was added to the colour
   table this session (active during both runs; the edit was interrupted, so confirm it should stay; no test yet).
   s05 run 2 called the same cable "off-white" → base `white` ≠ spec `beige`. Had the port label been legible, the
   policy would have reported a clear wrong-colour VIOLATION for a correct cable. Fix candidate: treat adjacent
   colours (white/beige/gray) as "uncertain", not as conflict.

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
