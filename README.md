# ProofCam

**A camera-guided AI agent that verifies physical equipment installations — and decides what it needs to see next.**

Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer track, theme "Push the Frontier").
Deadline: **2026-11-04, 21:00 ET**. Runtime AI is exclusively the Meta Model API: **Muse Spark 1.3** (reads photos,
plans camera moves) and **SAM 3.1** (outlines objects). Claude Code is used only to *write* the code.

> **Snapshot (2026-11-03):** Milestones 0, 1 and 2 are complete. The backend engine, the deterministic policy, the
> FastAPI + SQLite service (live smoke-tested through the API) and the M2 agent refinements all pass offline
> acceptance (**351 tests passed**, 1 live test deselected). M3.1: a first working camera web app ([frontend/](frontend/README.md)); evaluation
> (M4) and deployment/submission (M5) are pending. No live guidance validation has been run since the M2 changes.

Contents: [1. Plain-English overview](#1-plain-english-overview) · [2. Where we stand](#2-where-we-stand) ·
[3. Git state](#3-git-state) · [4. Repository map](#4-repository-map) ·
[5. How a photo flows through the code](#5-how-one-photo-flows-through-the-code) ·
[6. Key concepts](#6-key-concepts) · [7. Setup and run](#7-setup-and-run) · [8. Results and costs](#8-where-results-live-and-what-it-costs) ·
[9. What's next](#9-whats-next) · [10. Glossary](#10-glossary)

---

## 1. Plain-English overview

### The problem
Someone installs equipment — say a router and a network switch — and a cable has to go from *this* port to
*that* port. Checking by hand is tedious, and a single photo often can't show enough: the port might be on the
back, the label too small to read, the cable hidden behind something.

### What ProofCam does
You point your phone at the setup and give it a written rule, for example:

> "The blue Ethernet cable must connect Router LAN 1 to Switch Port 3."

ProofCam looks, works out **what it still can't see**, and tells you where to point the camera next
("I can see both devices but not the router's ports — move to the back of the router"). You take another photo; it
updates what it knows; it asks again if needed. You can photograph the parts **in any order** — ProofCam remembers
what each photo proved and combines them; it never makes you follow a fixed photo sequence. This repeats within
fixed limits. In the end each rule gets one of three answers:

| Answer | Meaning |
|---|---|
| `VERIFIED` | The photos clearly show the rule is met |
| `VIOLATED` | The photos clearly show it is not met (empty port, wrong-coloured plug…) |
| `INSUFFICIENT_EVIDENCE` | The photos don't settle it, so ProofCam refuses to guess |

If photos contradict each other, ProofCam does not ask for more photos (another photo of an unchanged installation
cannot remove a contradiction); it asks for the installation to be reviewed, and continues only if a physical change
is declared.

### What each model is used for

| Model | Job | What it is *not* allowed to do |
|---|---|---|
| **Muse Spark 1.3** (vision + reasoning) | (1) Read each photo and report *claims*: which devices, which ports, what labels, what plugs, where cables go, with rough boxes. (2) Turn the biggest missing fact into a plain instruction for the user ("move closer to the label"). | Decide any verdict. Its output is a claim, never proof. |
| **SAM 3.1** (segmentation) | Outline objects ("blue ethernet cable", "router") as pixel masks, so a claim like "the blue cable is in this port" can be checked against something physically traced in the image. | Decide connectivity. A cable *near* a port is not a cable *plugged in*. |
| **Plain Python rulebook** ([policy.py](backend/proofcam/policy.py)) | The *only* thing that sets `VERIFIED` / `VIOLATED` / `INSUFFICIENT_EVIDENCE`, using strict rules and the evidence from all photos. | — |

### What the finished product should look like
A **mobile-first web app** (dark charcoal + teal) that keeps the phone camera open the whole time:
1. Pick or load an inspection (the devices and the rules to check).
2. Point the camera; tap to capture. A frame is sent to the server (the API key never reaches the browser).
3. A guidance banner says what to show next; the captured photo appears with coloured overlays (SAM masks, Muse boxes).
4. An evidence history shows every photo, what each one proved, what contradicts, and what's still missing.
5. A final report lists each rule's verdict with the exact photo behind it, plus an honest audit trail of every model call.

Plus: an evaluation on real physical scenarios comparing "one photo, no guidance" against the active ProofCam loop,
a public deployment, and a 3-minute demo video. Today the engine behind steps 2–5 exists as an HTTP API and a CLI;
the camera app is Milestone 3 (API contract: [docs/FRONTEND_HANDOFF.md](docs/FRONTEND_HANDOFF.md)).

### Ground rules the design never breaks
- Models report; the policy decides. Missing evidence is never a pass.
- Two similar cables in two different photos are **not** assumed to be the same cable.
- Contradictions between photos stay visible and block a verdict.
- No invented masks, boxes, confidences or results. Live results, mocks and replays are always labelled.
- Overlays are drawn on the *captured* image, never on the live preview.

ProofCam verifies visually observable conditions only. It does not certify electrical safety, hidden
connectivity, operational performance, or regulatory compliance.

---

## 2. Where we stand

| Milestone | What | Status |
|---|---|---|
| 0 | Feasibility: live Muse + SAM, the loop, the policy | **Complete.** Single-photo pipeline proven live; order-independent multi-photo accumulation proven offline; one live multi-photo run (third photo synthetic) |
| 1 | Core backend: FastAPI endpoints, SQLite persistence, reliability | **Complete.** Offline acceptance over HTTP with restarts; **live API smoke test passed** (2026-11-02, 4 calls, ≈ $0.035) |
| 2 | Active-agent refinements | **Complete (offline acceptance, 2026-11-03).** M2.1 verdict correctness · M2.2 guidance + contradiction review · M2.3 device grounding geometry · M2.4 offline acceptance + close-out ([docs/M2_ACCEPTANCE.md](docs/M2_ACCEPTANCE.md)) |
| 3 | Live camera web app (React/TS/Vite/Tailwind/shadcn) | **M3.1 + M3.2 done (2026-11-03, not committed):** mobile-first app in [frontend/](frontend/README.md); access code, spending cap, PWA, iPhone setup prepared ([docs/IPHONE_SETUP.md](docs/IPHONE_SETUP.md)) — **not yet tested on an iPhone** |
| 4 | Evaluation on real scenarios + passive baseline | Pending |
| 5 | Deploy, final README, 3-minute demo, submission | Pending |

**Tests:** `pytest -q` → **351 passed**, 1 live test deselected (mocked Meta API, replays, temporary SQLite).

**Proven live:** Muse returns valid structured observations; SAM masks line up with the photo; the single-photo
pipeline runs end to end and abstained correctly on all five reference images; on the user's own setup, m1 and m5
were correctly `VIOLATED` (switch port 3 clearly empty); one capture through the real HTTP API (M1 smoke test) ran
4 calls, committed, survived a restart and replayed idempotently. A live multi-photo run reached `VERIFIED` only with
an **AI-generated** third photo — not a validation on a real installation.

**Proven offline only:** order independence of multi-photo evidence; every M2 rule (colour ambiguity, conflicting
traces, device ambiguity, contradiction review, off-target photo accounting, the unread-label guard, containment for
antenna masks); restart/idempotency/accounting guarantees with the M2 changes in place.

**Known limitations** (detail in [docs/M2_ACCEPTANCE.md](docs/M2_ACCEPTANCE.md) and [docs/DECISIONS.md](docs/DECISIONS.md)):
1. **No live guidance validation since M2.** The new planner wording and the unread-label guard are tested with mocks
   only. The guard is deterministic, so user-facing guidance cannot present an unread label as printed text; how often
   Muse itself tries to is unmeasured.
2. **Adjacent same-colour cables are ambiguous.** SAM port grounding shows a cable of the right colour *near* a port; it
   cannot tell neighbouring ports apart (D32). Port identity rests on Muse's label/occupancy claims.
3. **Cross-photo physical identity is not independently proven.** A device is recognised per photo from the spec
   description; reports say so. Cable identity across photos is joined only through port identity under the
   static-installation assumption.
4. **Not a public deployment:** M3.2 added a private-testing boundary (access code, local-only without a code,
   server-wide call cap; D35), but captures are still synchronous (25–48 s live; worst case ≈ 19 min, D24) and nothing
   has been reviewed for internet exposure.
5. **Historical policy drift:** inspections stored by an earlier engine show `engine_changed` / `policy_drift`; their
   stored verdicts are never rewritten.
6. On the user's real setup the inserted plug hides both target labels, so the strict `label_only` rule cannot verify
   it from real photos (correctly `INSUFFICIENT_EVIDENCE`).
7. SAM `network switch` returns 0 objects on the user's switch (report-only; no verdict uses device links).

---

## 3. Git state

Remote: `https://github.com/dakshvatss/proofcam.git`. Current branch **`m2-active-agent`** (local only, no upstream),
7 commits ahead of `main`: `m1.3` … `m2.3` (`6755b4f`). Remote branches: `main`, `m0-feasibility`, `m1-core-backend`.
The M2.4 close-out (documentation only) is uncommitted at the time of writing.

**Deliberately never committed** (git-ignored; this machine only): `.env` (real `MODEL_API_KEY`), `data/images/*`
(private photos), `runs/` (real-run outputs incl. photos), `var/` and `*.db*` (SQLite with photo BLOBs),
`backend/.venv/`. A test (`test_no_secrets_databases_or_private_images_are_tracked`) checks this.

---

## 4. Repository map

```
proofcam/
├── README.md · GUIDE.md · CLAUDE.md · .env.example · .gitignore · .gitattributes
├── docs/
│   ├── SPEC.md                 product requirements + acceptance criteria per milestone
│   ├── META_API_FACTS.md       what the Meta API does; each fact tagged DOC / SRC / LIVE / UNVERIFIED
│   ├── DECISIONS.md            design decisions D1–D33 and their reasons
│   ├── PROGRESS.md             dated log: work done, test results, live findings
│   ├── M2_ACCEPTANCE.md        Milestone 2 offline acceptance report
│   └── FRONTEND_HANDOFF.md     HTTP API contract for the M3 camera app
├── data/
│   ├── images/ (git-ignored)   private photos: 01–05 reference, m1–m7 own setup
│   └── specs/                  router_switch.json, my_setup.json, reference/ (s01–s05)
├── backend/
│   ├── pyproject.toml          deps, pytest config (live tests excluded by default)
│   ├── proofcam/               the engine + service + API (table below)
│   ├── tests/                  mocked unit/acceptance tests, offline replays, opt-in live test
│   └── experiments/            real-API scripts and offline measurement scripts
├── runs/ (git-ignored)         outputs of real runs
└── var/  (git-ignored)         default SQLite database
```

### `backend/proofcam/`

| File | What it is |
|---|---|
| [config.py](backend/proofcam/config.py) | Settings from `.env`; `Budget` (6 photos, 40 model calls, 2 attempts per gap, 4 SAM calls per photo); `database_path()` |
| [images.py](backend/proofcam/images.py) | Photo → EXIF rotation → RGB → long side ≤ 1600 px → JPEG; id = SHA-256 prefix. One image basis for both models |
| [meta_client.py](backend/proofcam/meta_client.py) | **The only code that talks to Meta.** Muse via Chat Completions + JSON schema; SAM via streaming Responses; retries, hard call cap, accounting hook, redacted trace |
| [observation.py](backend/proofcam/observation.py) · [wire_schema.py](backend/proofcam/wire_schema.py) | Strict model-output schemas and their wire JSON schema |
| [prompts.py](backend/proofcam/prompts.py) · [muse.py](backend/proofcam/muse.py) | Prompts; observation extraction, next-view planning, deterministic fallback templates, unread-label guard |
| [spec.py](backend/proofcam/spec.py) | Inspection specs; label normalization; `port_rows`, `port_identity` |
| [geometry.py](backend/proofcam/geometry.py) · [grounding.py](backend/proofcam/grounding.py) | Mask placement, IoU; SAM runs; device links (IoU or containment), port links (presence near a port) |
| [evidence.py](backend/proofcam/evidence.py) | Observations, links, evidence items, gaps, assessments, next-view requests |
| [policy.py](backend/proofcam/policy.py) | **The rulebook — the only place verdicts are set** |
| [agent.py](backend/proofcam/agent.py) | The bounded loop; snapshot/restore; installation changes; review items |
| [store.py](backend/proofcam/store.py) | SQLite persistence: leases, idempotency, model-call reservations, append-only evidence |
| [service.py](backend/proofcam/service.py) · [api.py](backend/proofcam/api.py) · [api_models.py](backend/proofcam/api_models.py) | `InspectionService` and the FastAPI app (routes in [docs/FRONTEND_HANDOFF.md](docs/FRONTEND_HANDOFF.md)) |
| [trace.py](backend/proofcam/trace.py) · [overlay.py](backend/proofcam/overlay.py) · [report.py](backend/proofcam/report.py) · [cli.py](backend/proofcam/cli.py) | Audit trace; overlays; JSON/Markdown reports; command line |

### `backend/tests/` — 351 pass, 1 live test excluded by default

| File | Covers |
|---|---|
| [fakes.py](backend/tests/fakes.py) | The mock Meta API (canned Muse JSON, real-format SAM streams), tagged `source="mock"` |
| `test_policy`, `test_evidence_fusion`, `test_sequences` | Verdict rules, false-positive traps, multi-photo fusion, replay of recorded live m1–m7 output |
| `test_verdict_correctness` (M2.1) | Colour ambiguity, conflicting traces, ambiguous devices, policy-drift flagging |
| `test_guidance` (M2.2) | Unread-label guard, off-target photo accounting, contradiction review stop |
| `test_grounding_geometry` (M2.3) | Containment for antenna masks, its guards, documented port-grounding limit |
| `test_agent`, `test_persistence`, `test_store`, `test_service`, `test_api`, `test_acceptance` | Loop, restart equivalence, SQLite, service, HTTP, end-to-end reliability |
| `test_schemas_geometry`, `test_meta_client` | Model-output validation, mask geometry, request formats, retries, budget |
| `test_live` | Real API (opt-in, `-m live`); asserts safety properties only |

### `backend/experiments/`

| File | Does |
|---|---|
| `probe_api.py` | 4 quick real calls (≈ $0.01) |
| `run_scenarios.py` | Each reference photo as its own live inspection |
| `run_sequences.py` | Multi-photo order experiment (offline replay by default; `--mode live` costs money) |
| `api_smoke.py` | One live capture through the HTTP API with a hard call cap (M1 smoke test) |
| `grounding_offline.py` | Re-decodes recorded SAM output to measure grounding rules (no API calls) |

---

## 5. How one photo flows through the code

```
POST /api/inspections/{id}/captures  (or cli.py)
 → images.normalize → store.begin_capture (idempotency + lease) → agent.restore from SQLite → agent.observe():
   1 OBSERVE  muse.extract_observations()   Muse reports claims (strict JSON; one repair retry)
   2 GROUND   grounding.run_sam()           SAM masks; link to Muse devices/ports
   3 ASSESS   policy.assess_requirement()   VERIFIED / VIOLATED / INSUFFICIENT + typed gaps
   4 STOP?    all settled / photo or call budget used / gaps exhausted / only contradictions left
   5 PLAN     contradictions → review item (no camera request); otherwise policy.select_gap() →
              muse.plan_next_view() (unread-label guard; fallback template if Muse fails)
 → overlays rendered → store.commit_step (one transaction)
```
The next photo (any order) re-runs the assessment over **all** photos of the current configuration, so the verdict
depends only on the evidence collected, not on its order. Earlier photos are never discarded. Identical repeat photos
are ignored. After a declared installation change, earlier photos stay in the report but stop counting.

---

## 6. Key concepts

- **Claims vs verdicts.** Weak wording (`uncertain`, `partial`, `partially_legible`, unknown or ambiguous colour) can never count toward `VERIFIED`.
- **An endpoint is supported** only when, in one photo: device identified `clear` (and no other device in that photo
  claims the same spec id); port identified (own label `legible` and matching — or, only if the spec opts in,
  inferred from legible neighbours + declared layout); a cable `cable_inserted` with `clear` visibility; colour
  *matches*; and SAM's mask of the required cable reaches that port.
- **A violation** is a clear view of the directly labelled port that is empty, or holds a plug of a *clearly*
  different colour (near colours are uncertain, never violations). Violations don't need SAM.
- **Cable identity:** one photo with the cable `fully_traced` between the two identified ports, or the spec author's
  explicit `unique_in_installation` assertion (reported as an assumption). Conflicting traces are contradictions.
- **Contradictions** block a verdict and produce a `review_required` item, not a camera request.
- **Static verification:** all photos are assumed to show one unchanged installation; a physical change must be
  declared (`installation_changed`); undeclared mixes surface as contradictions or violations.
- **Gaps:** `CONTRADICTION` › `DEVICE_NOT_SEEN` › `PORTS_NOT_VISIBLE` › `LABEL_ILLEGIBLE` › `PORT_NOT_FOUND` ›
  `INSERTION_UNCLEAR` › `GROUNDING_MISSING` › `CABLE_CONTINUITY`, devices in the latest photo first. Each gap gets at
  most two *on-target* attempts.
- **Coordinates** always refer to the normalized image. Muse boxes use a 0–1000 grid; SAM boxes are pixels.

More detail: [GUIDE.md](GUIDE.md).

---

## 7. Setup and run

Windows / PowerShell shown; Python 3.12. From `backend/`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install pydantic httpx pillow python-dotenv meta-sam-parser numpy pytest fastapi uvicorn python-multipart
copy ..\.env.example ..\.env        # then put your key in MODEL_API_KEY

# Tests (mocked, free)
.venv\Scripts\python.exe -m pytest -q
# Live tests (costs money)
$env:PROOFCAM_LIVE_IMAGES = "a.png;b.png"; .venv\Scripts\python.exe -m pytest -q -m live

# Multi-photo order experiment — offline replay, free
.venv\Scripts\python.exe experiments\run_sequences.py

# A real multi-photo inspection from the CLI (costs money)
.venv\Scripts\python.exe -m proofcam.cli --spec ..\data\specs\my_setup.json --image ..\data\images\m2_router_rear_close.png --interactive

# Faster Muse (same verdicts on the reference set)
$env:PROOFCAM_MUSE_REASONING_EFFORT = "low"
```

**Web app (M3.1).** See [frontend/README.md](frontend/README.md): backend (mock models via
`experiments\dev_mock_server.py`, or real) on port 8000 + `npm run dev` in `frontend/`, then open http://127.0.0.1:5173.

**HTTP API.** One worker only. The key stays server-side (`.env`); the database defaults to `var/proofcam.db`
(override with `PROOFCAM_DB_PATH`). Creating and reading inspections is free; **every photo uploaded to `/captures`
makes live, paid Meta API calls.** Without `PROOFCAM_ACCESS_CODE` it answers only this computer; with it, other
devices need the code. `PROOFCAM_GLOBAL_CALL_LIMIT` (default 50) caps paid calls. Phone testing: [docs/IPHONE_SETUP.md](docs/IPHONE_SETUP.md).

```powershell
.venv\Scripts\python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --port 8000
# http://localhost:8000/docs lists the routes; contract in docs/FRONTEND_HANDOFF.md
```

---

## 8. Where results live and what it costs

Each CLI run writes `runs/<id>/`: `report.md` (start here), `report.json`, `trace.jsonl`, `overlays/*.jpg`,
`images/*.jpg`. The API stores the same in SQLite and serves it via `/report`, `/photos`, `/overlays`.

| Item | Price |
|---|---|
| Muse Spark 1.3 | $1.25 / 1M input tokens ($0.15 cached), $4.25 / 1M output (hidden reasoning counts) |
| SAM 3.1 | $2.50 per 1,000 images (≈ $0.0025 per call) |

One photo through the full pipeline ≈ $0.01–0.03 (M1 smoke capture: 4 calls, $0.0348). Total live spend recorded in
PROGRESS so far ≈ $0.57.

---

## 9. What's next

1. **iPhone test** (needs approval: Tailscale install/sign-in, see [docs/IPHONE_SETUP.md](docs/IPHONE_SETUP.md)), then a
   capped live-model test from the phone (separate approval).
2. **Before any public deployment (M5):** authentication, a spending cap across inspections, and request-timeout
   handling (D24).
3. **With approval, when time allows:** a capped live check of the M2 guidance wording; the SAM port/plug concept
   measurement (PROGRESS 2026-11-03).
4. **M4** evaluation and **M5** deployment, demo, submission before 2026-11-04 21:00 ET.

Stop for review at each milestone boundary.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| Claim | Something a model says it sees; never a verdict |
| Grounding | Checking a Muse claim against a real SAM mask in the same photo |
| Endpoint | One end of a required connection (device + port label) |
| Gap | A specific missing fact that blocks a verdict, with a type code |
| Next view | The camera instruction ProofCam gives to close a gap |
| Review item | A requirement blocked by a contradiction; needs a person to check the installation |
| Spec | The JSON file describing devices and requirements |
| Normalized image | The resized, rotated JPEG sent to both models; all coordinates refer to it |
| Epoch | Photos taken between two declared installation changes; only the current one counts |
| Trace | Per-call audit log |
| Replay | Feeding recorded model output back through the agent with no API calls (`source="replay"`) |
