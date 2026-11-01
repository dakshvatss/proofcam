# ProofCam

**A camera-guided AI agent that verifies physical equipment installations — and decides what it needs to see next.**

Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer track, theme "Push the Frontier").
Deadline: **2026-11-04, 21:00 ET**. Runtime AI is exclusively the Meta Model API: **Muse Spark 1.3** (reads photos,
plans camera moves) and **SAM 3.1** (outlines objects). Claude Code is used only to *write* the code.

> **Snapshot (2026-10-31):** Milestone 0 single-photo feasibility is done and live-validated. Order-independent
> multi-photo evidence accumulation is implemented and proven **offline** (replay of recorded live observations +
> synthetic cases); the **live multi-photo experiment has not been run yet**, so Milestone 0 multi-photo behaviour
> is not marked complete. There is **no web app, no API server and no database yet**. No live `VERIFIED` exists.

Contents: [1. Plain-English overview](#1-plain-english-overview) · [2. Where we stand](#2-where-we-stand) ·
[3. Git state](#3-git-state-committed-vs-not) · [4. Repository map](#4-repository-map-every-file) ·
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

The key idea: ordinary tools judge whatever photo they're handed. ProofCam **chooses which photo it needs next**.
Think of an inspector who says "show me the back panel" instead of signing off on a front-only photo.

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

Plus: an evaluation on real physical scenarios (correct, wrong, hidden, ambiguous setups) comparing "one photo,
no guidance" against the active ProofCam loop, a public deployment, and a 3-minute demo video.
Today only the engine behind step 2–5 exists, driven from the command line.

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
| 0 | Feasibility: live Muse + SAM, the loop, the policy | Single-photo pipeline **proven live**. Multi-photo, order-independent accumulation **proven offline only** — live experiment pending approval |
| 1 | Core backend: FastAPI endpoints, SQLite persistence | Not started |
| 2 | Active-agent refinements: gap planning, contradiction handling | Not started |
| 3 | Live camera web app (React/TS/Vite/Tailwind/shadcn) | Not started; no `frontend/` folder, Node not installed |
| 4 | Evaluation on real scenarios + passive baseline | Not started |
| 5 | Deploy, final README, 3-minute demo, submission | Not started |

**Proven live (2026-10-31):** Muse returns valid structured observations; SAM masks line up with the photo; the
whole single-photo pipeline runs end to end; it abstained correctly on all five reference images (no false
verdicts). ~40 real calls, ≈ $0.20. (Unit-test count at that time: 52.)

**Live single photos on the user's own setup (m1–m7, ≈ $0.24):** m1 and m5 correctly `VIOLATED` (switch port 3
clearly empty); m2/m3/m4/m6/m7 `INSUFFICIENT_EVIDENCE`. Key finding: **the inserted plug hides the target port
label** on both devices, so the strict label rule can never establish either end of this setup.

**Proven offline (2026-10-31):** one persistent agent fed the recorded m2/m3/m7 observations in all 6 orders reaches
the identical final assessment; synthetic complementary photos (router close-up + switch close-up + wide cable
shot) reach `VERIFIED` in every order; negatives stay negative. Tests: **98 passed** (mocked/offline).

**Not yet proven:** the live multi-photo run; any live `VERIFIED`; run-to-run stability; latency on phone images.

**Known weaknesses to fix next** (detail in [docs/PROGRESS.md](docs/PROGRESS.md)):
1. *(Fixed)* Clear plugs: a cable of the right colour linked to the port now counts (support only).
2. *(Fixed)* Guidance now prefers the device already in view; the planner is told what is established and what already failed.
3. Close colour words ("beige" vs "off-white") could produce a *false VIOLATED*. A `beige/cream/tan/khaki/ivory → beige`
   mapping was added to the colour table during live testing with no test yet — confirm it should stay.
4. Muse port-level boxes are about one port-width off; device boxes are good. Device matching uses IoU, which is
   wrong for antenna routers (SAM includes antennas) — containment is the likely fix.
5. Latency: 25–48 s per photo at default reasoning, 6–29 s with `PROOFCAM_MUSE_REASONING_EFFORT=low`.
6. No cumulative spend cap across inspections (only a per-inspection call cap).
7. SAM `network switch` found 0 objects in all 7 own-setup photos (`router` works) — switch device grounding never corroborates.
8. Layout inference (identifying a hidden-label port from its neighbours) trusts Muse's port order and boxes; it is
   opt-in, disclosed, and never produces `VIOLATED`. Even with it, m7's labels are too small to prove cable identity.

**Own-setup work:** spec [data/specs/my_setup.json](data/specs/my_setup.json) (now with declared `port_rows`;
requirement still strict `label_only`). The m1–m7 live results are recorded in [docs/PROGRESS.md](docs/PROGRESS.md).

---

## 3. Git state (committed vs not)

Remote: `https://github.com/dakshvatss/proofcam.git`. Current branch: **`m0-feasibility`**, which is fully pushed
(`origin/m0-feasibility` = `93141a7`). `main` still holds only the *Initial commit* — Milestone 0 has **not been
merged into `main`** yet.

**Committed and pushed** (everything listed in [section 4](#4-repository-map-every-file) marked ✅): the backend package,
tests, experiment scripts and specs as of `93141a7`, plus `CLAUDE.md`, `.env.example`. Many of these are now locally modified (✏️, below).

**Uncommitted local changes right now (2026-10-31, evidence-accumulation work):**
- Modified: `README.md`, `GUIDE.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md`, `data/specs/my_setup.json`,
  `backend/proofcam/{agent,cli,evidence,muse,policy,prompts,report,spec}.py`, `backend/tests/test_agent.py`.
- New: `backend/experiments/run_sequences.py`, `backend/tests/test_evidence_fusion.py`,
  `backend/tests/test_sequences.py`, `backend/tests/fixtures/my_setup_live_observations.json`.
- `data/images/README.md` — **deleted locally**, still in the last commit (`git restore data/images/README.md`
  to keep it; its suggested filenames are stale).

**Deliberately never committed** (git-ignored; exist on this machine only):
| Item | Why |
|---|---|
| `.env` | holds the real `MODEL_API_KEY` |
| `data/images/*` — five reference PNGs (`01`–`05`) and seven own-setup PNGs (`m1`–`m7`) | private photos (`m6` shows a hand) |
| `runs/` — 8 run folders + `probe-*.json` | outputs from real runs; contain the photos |
| `backend/.venv/`, `backend/.pytest_cache/` | local environment and caches |

Commit history: `d1024b7` Initial commit → `ab0b654` M0 backend/policy/tests → `4921135` M0 live validation →
`f8610ed` PROGRESS correction → `8ae03f3` GUIDE.md → `93141a7` my_setup spec.

---

## 4. Repository map (every file)

✅ = committed and pushed · 🔒 = local only, git-ignored · ✏️ = changed/uncommitted

```
proofcam/
├── README.md ✏️                 this file: overview, status, navigation
├── GUIDE.md ✏️                   deeper code walkthrough (concepts, gap codes, spec format, outputs)
├── CLAUDE.md ✅                  short, stable rules/context for Claude Code
├── .env.example ✅               template for .env (MODEL_API_KEY + optional overrides)
├── .env 🔒                       real key — never commit, never print
├── .gitignore ✅  .gitattributes ✅
│
├── docs/
│   ├── SPEC.md ✅                product requirements + acceptance criteria per milestone
│   ├── META_API_FACTS.md ✅      what the Meta API does; each fact tagged DOC / SRC / LIVE / UNVERIFIED
│   ├── DECISIONS.md ✏️           design decisions D1–D16 and their reasons
│   └── PROGRESS.md ✏️            dated log: work done, test results, live findings, blockers
│
├── data/
│   ├── images/ 🔒                private photos: 01–05 reference PNGs, m1–m7 own-setup PNGs
│   │   └── README.md ✏️          (deleted locally; still in last commit)
│   └── specs/
│       ├── router_switch.json ✅ example spec: blue cable, Router LAN 1 → Switch port 3 (placeholder device text)
│       ├── my_setup.json ✏️      spec for the user's real TP-Link router + NETGEAR switch (+ port_rows)
│       └── reference/ ✅         one spec per reference photo, used by run_scenarios.py
│           ├── s01_white_rear.json   s02_white_front.json   s03_asus_front.json
│           └── s04_blue_cable.json   s05_laptop_router.json
│
├── backend/
│   ├── pyproject.toml ✅         deps, `proofcam` script, pytest config (live tests skipped by default)
│   ├── .venv/ 🔒                 Python 3.12 virtual env
│   ├── proofcam/                 THE ENGINE (all ✅) — see table below
│   ├── tests/                    mocked unit tests, offline replays, opt-in live tests
│   │   └── fixtures/ ✏️          recorded Muse/SAM text output of the live m1–m7 run (no photos)
│   └── experiments/              real-API scripts + the multi-photo order experiment
│
└── runs/ 🔒                      outputs of real runs (reports, traces, overlays, photos)
```

### `backend/proofcam/` — the engine (✏️ = changed in the uncommitted evidence-accumulation work)

| File | What it is |
|---|---|
| [config.py](backend/proofcam/config.py) | Settings from `.env`; `Budget` limits (6 photos, 40 model calls, 2 attempts per gap, 4 SAM calls per photo) |
| [images.py](backend/proofcam/images.py) | Loads a photo → rotates by EXIF → RGB → long side ≤ 1600 px → JPEG; id = SHA-256 prefix. One image basis for both models |
| [meta_client.py](backend/proofcam/meta_client.py) | **The only code that talks to Meta.** Muse via Chat Completions + JSON schema; SAM via streaming Responses; retries, `Retry-After`, hard call cap, redacted trace |
| [observation.py](backend/proofcam/observation.py) | Strict Pydantic shapes for model output: devices, ports, cables, boxes (0–1000 grid), next-view plan |
| [wire_schema.py](backend/proofcam/wire_schema.py) | Converts those shapes into the flat JSON schema Meta's API accepts |
| [prompts.py](backend/proofcam/prompts.py) ✏️ | Prompt text for observing and planning (observe prompt is *not* told the expected cable colour; planner is told what is established and what already failed) |
| [muse.py](backend/proofcam/muse.py) ✏️ | `extract_observations()`, `plan_next_view()`, deterministic `fallback_plan()`, one validation-repair retry |
| [spec.py](backend/proofcam/spec.py) ✏️ | Inspection-spec models; `normalize_label()` so "LAN 1" = "lan-1" = "LAN1"; device `port_rows`, requirement `port_identity` |
| [geometry.py](backend/proofcam/geometry.py) | Mask → full-image placement, IoU, box expansion, mask-pixel counting |
| [grounding.py](backend/proofcam/grounding.py) | Runs SAM per concept; links SAM masks to Muse devices (IoU ≥ 0.5) and ports (cable mask must reach the port region) |
| [evidence.py](backend/proofcam/evidence.py) ✏️ | Record types: observations (with `epoch`), links, evidence items (with `port_basis`), gaps, assessments, next-view requests |
| [policy.py](backend/proofcam/policy.py) ✏️ | **The rulebook — the only place verdicts are set**: port identification (direct label / opt-in layout inference), endpoint support, separable cable identity, gap selection |
| [agent.py](backend/proofcam/agent.py) ✏️ | The bounded loop, one agent per inspection, photos in any order: `observe()` (live), `observe_recorded()` (replay), duplicate detection, `mark_installation_changed()`, per-photo `history` |
| [trace.py](backend/proofcam/trace.py) | Audit log; every event tagged `source` (`live`/`mock`/`replay`/`local`), usage and cost totals |
| [overlay.py](backend/proofcam/overlay.py) | Draws SAM masks (filled) and Muse boxes (dashed) on the captured image |
| [report.py](backend/proofcam/report.py) ✏️ | Writes `report.md` (final verdict + why, timeline, per-photo contributions), `report.json`, `trace.jsonl`, images, overlays |
| [cli.py](backend/proofcam/cli.py) ✏️ | `python -m proofcam.cli --spec … --image … [--interactive]`; interactive `!changed <reason>` |
| [\_\_init\_\_.py](backend/proofcam/__init__.py) | Package marker |

### `backend/tests/` — 98 pass, 1 live test skipped by default

| File | Covers |
|---|---|
| [fakes.py](backend/tests/fakes.py) | Not a test: the mock Meta API (canned Muse JSON, real-format SAM streams). Tagged `source="mock"` |
| [test_policy.py](backend/tests/test_policy.py) | Verdict rules and every false-positive trap |
| [test_schemas_geometry.py](backend/tests/test_schemas_geometry.py) | Malformed model output rejected; mask/box coordinates correct |
| [test_meta_client.py](backend/tests/test_meta_client.py) | Request formats, retries, timeouts, stream errors, call budget |
| [test_agent.py](backend/tests/test_agent.py) ✏️ | Full loop with mocks: multi-photo verification in several orders, stopping rules, failures, planner context, report files |
| [test_evidence_fusion.py](backend/tests/test_evidence_fusion.py) ✏️ new | Synthetic: separable cable identity, all orders → VERIFIED; every refusal case for traces and layout inference |
| [test_sequences.py](backend/tests/test_sequences.py) ✏️ new | Replays the recorded live m1–m7 observations through one agent: order independence, negatives, declared change, duplicates, unusable photos, budget, report |
| [test_live.py](backend/tests/test_live.py) | Real API (opt-in); asserts safety properties only, never specific verdicts |

### `backend/experiments/` (all ✅) — real-API scripts

| File | Does |
|---|---|
| [probe_api.py](backend/experiments/probe_api.py) | 4 quick real calls (ping, structured text, structured + image, SAM), ≈ $0.01 |
| [run_scenarios.py](backend/experiments/run_scenarios.py) | Runs each image as its own independent inspection with its own spec; writes `runs/scenarios-<time>/` |
| [run_sequences.py](backend/experiments/run_sequences.py) ✏️ new | Multi-photo order experiment on `my_setup.json` (positive m2/m3/m7 in 3 orders; negatives m1, m5, m3+m1, m1→change→m2/m3/m7; strict and layout variants). Offline replay by default; `--mode live` costs money |

---

## 5. How one photo flows through the code

```
cli.py  →  images.load_image()  →  agent.observe():
   1 OBSERVE  muse.extract_observations()   Muse reports claims (strict JSON; one repair retry)
   2 GROUND   grounding.run_sam()           SAM masks; link to Muse devices/ports
   3 ASSESS   policy.assess_requirement()   VERIFIED / VIOLATED / INSUFFICIENT + typed gaps
   4 STOP?    all settled / photo budget used / gap tried twice
   5 PLAN     policy.select_gap() → muse.plan_next_view()  (fallback template if Muse fails)
→  report.write_report()   runs/<id>/…
```
The next photo (any order) re-runs the assessment over **all** photos of the current configuration, so the verdict
depends only on the evidence collected, not on its order; only the guidance depends on what has been seen so far.
Earlier photos are never discarded. Identical repeat photos are ignored. After a declared installation change,
earlier photos stay in the report but stop counting.

---

## 6. Key concepts

- **Claims vs verdicts.** Weak wording (`uncertain`, `partial`, `partially_legible`, unknown colour) can never count toward `VERIFIED`.
- **An endpoint is supported** only when, in one photo: device identified `clear`; port identified (own label `legible` and
  matching — or, only if the spec opts in, inferred from legible neighbours + declared layout); a cable `cable_inserted`
  with `clear` visibility; colour matches; and SAM's mask of the required cable reaches that port.
- **A violation** is a clear view of the correctly labelled port that is empty, or holds a different-coloured plug
  (or, if the spec declares the cable unique, the required cable sits in a different port). Violations don't need SAM.
- **Cable identity:** both ends supported still isn't enough — need one photo with the cable `fully_traced` between the two
  identified ports (that photo may differ from the close-ups that prove the ends), or the spec author's explicit
  `unique_in_installation` assertion (reported as an assumption).
- **Static verification:** all photos are assumed to show one unchanged installation; a clear violation ends the
  inspection. A physical change must be declared (CLI `!changed`); undeclared mixes surface as contradictions.
- **Gaps:** contradictions first, then gaps on the device in the latest photo, then by type: `CONTRADICTION` › `DEVICE_NOT_SEEN` › `PORTS_NOT_VISIBLE` › `LABEL_ILLEGIBLE` › `PORT_NOT_FOUND` ›
  `INSERTION_UNCLEAR` › `GROUNDING_MISSING` › `CABLE_CONTINUITY`. Each gap is asked about at most twice.
- **Coordinates** always refer to the normalized image. Muse boxes use a 0–1000 grid; SAM boxes are pixels.
- **Budgets per inspection:** 6 photos, 40 model calls (hard-enforced), 2 attempts per gap, 4 SAM calls per photo.

More detail: [GUIDE.md](GUIDE.md).

---

## 7. Setup and run

Windows / PowerShell shown; Python 3.11+ (3.12 used). From `backend/`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install pydantic httpx pillow python-dotenv meta-sam-parser numpy pytest
copy ..\.env.example ..\.env        # then put your key in MODEL_API_KEY

# Tests (mocked, free)
.venv\Scripts\python.exe -m pytest -q
# Live tests (costs money)
$env:PROOFCAM_LIVE_IMAGES = "a.png;b.png"; .venv\Scripts\python.exe -m pytest -q -m live

# Live API probe (~$0.01)
.venv\Scripts\python.exe experiments\probe_api.py --image ..\data\images\04_blue_cable.png

# Multi-photo order experiment on your own photos — offline replay, free
.venv\Scripts\python.exe experiments\run_sequences.py
# ... LIVE (needs approval; ~$0.3-0.5): perceive each photo once, live planner per order
.venv\Scripts\python.exe experiments\run_sequences.py --mode live

# The five reference photos as independent scenarios (~$0.10)
.venv\Scripts\python.exe experiments\run_scenarios.py          # or --only s04

# A real multi-photo inspection
.venv\Scripts\python.exe -m proofcam.cli --spec ..\data\specs\my_setup.json `
    --image ..\data\images\m1_front.png --image ..\data\images\m2_router_rear_close.png
# ...or get asked for each next photo:
.venv\Scripts\python.exe -m proofcam.cli --spec ..\data\specs\my_setup.json --image ..\data\images\m1_front.png --interactive

# Faster Muse (same verdicts on the reference set)
$env:PROOFCAM_MUSE_REASONING_EFFORT = "low"
```

**HTTP API (Milestone 1).** Needs `fastapi uvicorn python-multipart` in the venv. One worker only. The key stays
server-side (`.env`); the database defaults to `var/proofcam.db` (git-ignored; override with `PROOFCAM_DB_PATH`).
Creating and reading inspections is free; **every photo uploaded to `/captures` makes live, paid Meta API calls.**

```powershell
.venv\Scripts\python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --port 8000
# http://localhost:8000/docs lists the routes:
#   POST /api/inspections {"spec_id":"my_setup"} · GET /api/inspections/{id}
#   POST /api/inspections/{id}/captures (multipart file, optional responding_to, header Idempotency-Key)
#   POST /api/inspections/{id}/events {"type":"installation_changed","reason":"..."}
#   GET  /api/inspections/{id}/report[?format=md] · /photos/{image_id} · /overlays/{image_id} · GET /api/health
```

---

## 8. Where results live and what it costs

Each run writes `runs/<id>/`: `report.md` (start here), `report.json`, `trace.jsonl` (raw Muse JSON and SAM output
per call, latency, tokens), `overlays/*.jpg`, `images/*.jpg`. `runs/` is git-ignored.

Existing runs: `probe-20261031-133004.json`; `scenarios-20261031-133028/-133122/-133211/-133237/-133322` (default
reasoning, s04/s01/s02/s03/s05); `scenarios-20261031-133450` (`reasoning_effort=low`);
`scenarios-m-20261031-154423` (own photos m1–m7, one independent inspection each; written up in PROGRESS);
`sequences-replay-20261031-172829` (offline order experiment: `<variant>/<sequence>/report.md` + `summary.json`).
A live order experiment will write `runs/sequences-live-<time>/` (plus `perceptions.json` for free re-replays).

| Item | Price |
|---|---|
| Muse Spark 1.3 | $1.25 / 1M input tokens ($0.15 cached), $4.25 / 1M output (hidden reasoning counts) |
| SAM 3.1 | $2.50 per 1,000 images (≈ $0.0025 per call) |

One photo through the full pipeline ≈ $0.01–0.03. Meta's dashboard matched our traces for the first live runs
(40 requests, ≈ $0.20).

---

## 9. What's next

1. **With approval:** run `experiments/run_sequences.py --mode live` — the missing live multi-photo proof.
2. Decide whether `my_setup.json` should opt in to `port_identity: "label_or_layout"`; capture a photo that can prove
   cable identity (wide shot with legible port labels on both devices).
3. Colour-word tolerance, SAM switch concept, cumulative spend cap; commit this work and decide on merging into `main`.
4. Milestone 1: FastAPI + SQLite. Then the camera app (M3), evaluation (M4), deploy and demo (M5) before 2026-11-04.

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
| Spec | The JSON file describing devices and requirements |
| Normalized image | The resized, rotated JPEG sent to both models; all coordinates refer to it |
| Trace | Per-call audit log (`trace.jsonl`) |
| Reference images | The five photos `01`–`05`; separate setups, never combined |
| Own-setup photos | `m1`–`m7`: the user's router + switch; m2/m3/m7 one configuration, m1 and m5 different ones |
| Layout inference | Identifying a port whose label is hidden from its legible neighbours and declared port order (opt-in) |
| Replay | Feeding recorded model output back through the agent with no API calls (`source="replay"`) |
