# ProofCam — Repository Guide

Read this file first. It explains what ProofCam is, where the project stands, how one inspection flows through
the code, what every file does, and where to find results. The other docs go deeper on specific topics
(listed at the end).

---

## 1. What we are building

**ProofCam is a camera-guided AI agent that verifies physical equipment installations.**

You point a phone at an installation and give it a written requirement, for example:

> "The blue Ethernet cable must connect Router LAN 1 to Switch Port 3."

Ordinary visual-inspection tools analyze whichever photo you give them. ProofCam instead **works out what it
still needs to see** and asks for that view:

> "I can identify both devices, but I cannot see the router's connection ports. Move around to the rear of the router."

Each new photo updates its findings. Every requirement ends in exactly one of three states:

| State | Meaning |
|---|---|
| `VERIFIED` | The photos clearly show the requirement is met |
| `VIOLATED` | The photos clearly show it is not met (e.g. the port is empty, wrong colour plug) |
| `INSUFFICIENT_EVIDENCE` | The photos don't settle it, so ProofCam won't guess |

The core idea, **active visual evidence acquisition under uncertainty**, is a bounded loop:

```
OBSERVE → GROUND → ASSESS → IDENTIFY THE GAP → SELECT NEXT VIEW → (user moves camera) → REOBSERVE → …
```

It stops when every requirement is settled, when nothing more can be learned visually, or when a budget runs out.

**Two rules shape the whole design:**
1. **The AI model never decides a verdict.** Muse Spark only reports what it sees (claims). A plain Python
   rulebook ([policy.py](backend/proofcam/policy.py)) decides what those claims prove.
2. **Missing evidence is never treated as a pass.** A cable *near* a port isn't proof it's plugged in. Two blue
   cables in two photos aren't assumed to be the same cable. Contradictions stay visible.

ProofCam verifies visually observable conditions only. It does not certify electrical safety, hidden
connectivity, operational performance, or regulatory compliance.

### Context
- **Event:** Meta Global AI Developer Hackathon 2026, Indie Developer track, theme "Push the Frontier".
- **Deadline:** 2026-11-04, 21:00 ET.
- **Runtime AI:** Meta Model API only: **Muse Spark 1.3** (vision + reasoning) and **SAM 3.1** (segmentation).
  Claude Code is used to *write* the code; no Anthropic model runs inside ProofCam.
- **Final product:** a mobile web app with a live camera preview. What exists today is the backend engine and a
  command-line tool. The photo-based CLI is the foundation for the app, not a change of scope.

---

## 2. Where the project stands

| Milestone | What | Status |
|---|---|---|
| 0 | Technical feasibility: live Muse + SAM, the loop, the policy | **Done.** Live API works, overlays aligned. Multi-view on one real device still unproven |
| 1 | Core backend: FastAPI endpoints, SQLite persistence | Not started |
| 2 | Active agent refinements: better gap planning, contradiction handling | Not started |
| 3 | Live camera web app (React) | Not started; no `frontend/` folder yet |
| 4 | Evaluation: real physical scenarios, passive-vs-active baseline | Not started |
| 5 | Deploy, README, 3-minute demo, submission | Not started |

**Proven live (2026-10-31):** Muse returns valid structured observations; SAM returns masks that line up with the
photo; the whole single-photo pipeline runs end to end; it abstains correctly on all five reference images.

**Not yet proven:** a follow-up photo of the *same* device resolving a gap; any live VERIFIED or VIOLATED verdict.
The five reference photos come from different setups, so they cannot show that.

**Known weaknesses to fix next** (details in [docs/PROGRESS.md](docs/PROGRESS.md)):
1. A clear plug on a blue cable can't be verified, because colour is checked only on the plug.
2. Guidance can target an absent device instead of the device already in view (photo 02 asked to find the switch
   rather than "go to the rear").
3. Similar colour words ("beige" vs "off-white") could produce a false VIOLATED.
4. Muse's port-level boxes are imprecise (about one port width off); device-level boxes are good.
5. One photo takes 25–48 s at default reasoning, 6–29 s with `reasoning_effort=low`.

---

## 3. Repository map

```
proofcam/
├── GUIDE.md                 ← this file
├── README.md                ← short setup / run instructions
├── CLAUDE.md                ← rules and context for Claude Code (kept short and stable)
├── .env.example             ← template for .env (MODEL_API_KEY etc.). Real .env is git-ignored
├── .gitignore
│
├── docs/
│   ├── SPEC.md              ← product requirements and acceptance criteria per milestone
│   ├── META_API_FACTS.md    ← what the Meta API does, marked DOC / SRC / LIVE / UNVERIFIED
│   ├── DECISIONS.md         ← technical decisions D1–D12 and why
│   └── PROGRESS.md          ← dated log: what was done, test results, findings, blockers
│
├── data/
│   ├── images/              ← your photos (git-ignored except README.md)
│   └── specs/
│       ├── router_switch.json   ← example spec: blue cable, Router LAN 1 → Switch port 3
│       └── reference/           ← one spec per reference photo (s01–s05), used by run_scenarios.py
│
├── backend/
│   ├── pyproject.toml       ← dependencies and pytest settings
│   ├── .venv/               ← Python 3.12 virtual environment (local only)
│   ├── proofcam/            ← THE ENGINE (all application code)
│   ├── tests/               ← unit tests (mocked API) + live tests
│   └── experiments/         ← scripts that call the real API for validation
│
└── runs/                    ← output of every real run (git-ignored; contains your photos)
```

---

## 4. How one photo flows through the code

This is the path a single photo takes when you run the CLI. File names link to the code.

```
cli.py                       reads --spec and --image arguments
  │
  ▼
images.py   load_image()     open file → apply EXIF rotation → RGB → shrink long side to ≤1600 px → JPEG
  │                          → image_id = first 12 hex chars of SHA-256 (e.g. img_bedb24ea6dbf)
  ▼
agent.py    observe()        one step of the loop:
  │
  ├─ 1. OBSERVE   muse.py  extract_observations()
  │                 sends photo + device list to Muse Spark with a strict JSON schema.
  │                 Muse returns CLAIMS: devices, ports, labels, plug colours, cables, boxes.
  │                 Invalid JSON → one repair attempt → otherwise recorded as a failure (no facts used).
  │
  ├─ 2. GROUND    grounding.py  run_sam()
  │                 asks SAM 3.1 to segment each concept ("blue ethernet cable", "router", …) in parallel.
  │                 link_devices(): does SAM's router box match Muse's router box?
  │                 link_ports():   does SAM's cable mask actually reach the port Muse described?
  │                 Skipped if the photo doesn't show the equipment.
  │
  ├─ 3. ASSESS    policy.py  assess_requirement()
  │                 deterministic rules over ALL photos so far →
  │                 VERIFIED / VIOLATED / INSUFFICIENT_EVIDENCE + a list of typed "gaps".
  │
  ├─ 4. STOP?     all settled? photo budget used? gap tried twice already? → stop.
  │
  └─ 5. PLAN      policy.py select_gap() picks the most basic missing piece.
                  muse.py plan_next_view() asks Muse for a concrete camera instruction.
                  If Muse fails, a fixed template is used instead (still names the device/port).
  │
  ▼
report.py   write_report()   writes runs/<id>/report.md, report.json, trace.jsonl, overlays/, images/
```

The user (or the CLI's next `--image`) provides the next photo, and `observe()` runs again with everything
learned so far. Earlier photos are never thrown away.

---

## 5. What every file does

### `backend/proofcam/` — the engine

| File | Role | Key things inside |
|---|---|---|
| [config.py](backend/proofcam/config.py) | Settings and limits | `Settings.from_env()` reads `MODEL_API_KEY` from root `.env`; `Budget` (6 photos, 40 model calls, 2 attempts per gap, 4 SAM calls per photo); optional `PROOFCAM_MUSE_REASONING_EFFORT` |
| [images.py](backend/proofcam/images.py) | Photo loading | `load_image()`, `NormalizedImage` (id, size, JPEG bytes, `data_url()`). The same normalized image goes to both Muse and SAM so their coordinates agree |
| [meta_client.py](backend/proofcam/meta_client.py) | **Only place that talks to Meta** | `chat_structured()` (Muse via `/v1/chat/completions` + JSON schema); `sam_segment()` (SAM via streaming `/v1/responses`, decoded with the official `meta_sam_parser`); retries on 429/5xx honouring `Retry-After`; hard call cap (`BudgetExhausted`); every call logged to the trace with image data stripped |
| [observation.py](backend/proofcam/observation.py) | Shape of model output | `ObservationExtraction` (what Muse sees in one photo), `SeenDevice`, `PortObservation`, `CableObservation`, `Box1000`, `NextViewPlan`. Strict: unknown fields, broken references, off-grid boxes are rejected |
| [wire_schema.py](backend/proofcam/wire_schema.py) | Schema conversion | Turns the Pydantic models into the flat JSON schema Meta's API accepts |
| [prompts.py](backend/proofcam/prompts.py) | Prompt text | `OBSERVE_SYSTEM` ("report only what is visible, unknown is a valid answer") and `PLAN_SYSTEM`. The observe prompt is deliberately **not told** the expected cable colour, to avoid priming the model |
| [muse.py](backend/proofcam/muse.py) | Muse calls | `extract_observations()`, `plan_next_view()`, `fallback_plan()` (deterministic templates per gap type), validation-repair retry |
| [spec.py](backend/proofcam/spec.py) | Inspection specs | `InspectionSpec`, `DeviceSpec`, `ConnectionRequirement`, `EndpointSpec`; `normalize_label()` makes "LAN 1" = "lan-1" = "LAN1" and "Port 3" = "3" |
| [geometry.py](backend/proofcam/geometry.py) | Coordinate maths | `mask_to_image()` places a SAM mask into full-image pixels; `box_iou()`, `expand_box()`, `mask_pixels_in_box()` |
| [grounding.py](backend/proofcam/grounding.py) | SAM ↔ Muse linking | `run_sam()`, `link_devices()` (IoU ≥ 0.5), `link_ports()` (cable mask must cover ≥30 px and ≥5% of the port region expanded by 50%) |
| [evidence.py](backend/proofcam/evidence.py) | Evidence record types | `ObservationRecord` (one per photo), `GroundingLink`, `EvidenceItem`, `Gap`, `EndpointAssessment`, `RequirementAssessment`, `NextViewRequest` |
| [policy.py](backend/proofcam/policy.py) | **The rulebook — the only place verdicts are set** | `assess_endpoint()`, `assess_requirement()`, `select_gap()`, `base_color()`, `label_matches()` |
| [agent.py](backend/proofcam/agent.py) | The loop | `InspectionAgent.observe(image)` → `StepResult` (assessments, next view or stop reason) |
| [trace.py](backend/proofcam/trace.py) | Audit log | `Trace`, `TraceEvent` (each tagged `source`: `live`, `mock`, `replay`, `local`); `summary()` totals calls, tokens, estimated cost |
| [overlay.py](backend/proofcam/overlay.py) | Pictures | `render_overlay()`: SAM masks filled + solid boxes; Muse boxes dashed; legend on the image |
| [report.py](backend/proofcam/report.py) | Output files | `write_report()` → `report.json`, `report.md`, `trace.jsonl`, images, overlays |
| [cli.py](backend/proofcam/cli.py) | Command line | `python -m proofcam.cli --spec … --image … [--image …] [--interactive]` |

### `backend/tests/` — tests

| File | What it checks |
|---|---|
| [fakes.py](backend/tests/fakes.py) | Not a test: the **mock Meta API**. Returns canned Muse JSON and real-format SAM streams with validly encoded masks. Everything it produces is tagged `source="mock"` |
| [test_policy.py](backend/tests/test_policy.py) | The rulebook: verified, violated, missing evidence, contradictions, unrelated photos, and every "false positive" trap (illegible label, partial view, uncertain device, no SAM support, similar cables in different photos) |
| [test_schemas_geometry.py](backend/tests/test_schemas_geometry.py) | Malformed model output rejected; SAM box/mask coordinates land in the right pixels; zero matches; size mismatch |
| [test_meta_client.py](backend/tests/test_meta_client.py) | Exact request formats; retries; 400 not retried; timeouts; stream errors; hard call budget |
| [test_agent.py](backend/tests/test_agent.py) | The full loop with mocks: two-photo verification, unrelated follow-up, stopping rules, model failures, planner fallback, report files |
| [test_live.py](backend/tests/test_live.py) | **Real API** (skipped by default). Asserts only safety properties, never specific verdicts |

### `backend/experiments/` — real-API scripts

| File | What it does |
|---|---|
| [probe_api.py](backend/experiments/probe_api.py) | 4 quick real calls (ping, structured text, structured + image, SAM) to confirm the API works |
| [run_scenarios.py](backend/experiments/run_scenarios.py) | Runs each of the 5 reference photos as a **separate** inspection with its own spec; writes `runs/scenarios-<time>/` |

---

## 6. Key concepts

### Claims vs verdicts
Muse's JSON is a **claim** ("I see a blue plug in a port labelled LAN 1"). The policy decides whether that claim
is strong enough. Weak wording (`uncertain`, `partial`, `partially_legible`, unknown colour) can never count
towards VERIFIED.

### What counts as support for one end of a cable (an "endpoint")
All of these must hold in a single photo:
- the device is identified with `clear` certainty;
- the port label is `legible` and matches the spec (after normalization, or via `label_aliases`);
- a cable is `cable_inserted` with `clear` visibility;
- the plug colour matches the required colour;
- SAM's mask of the required cable reaches that port (can be switched off with `--no-grounding-requirement`,
  for comparison experiments only).

### What counts as a violation
In a clear view of the correctly labelled port: it is **empty**, or it holds a **different-coloured** plug. If the
spec declares the cable unique (`cable_identity: "unique_in_installation"`), the required cable sitting in a
*different* port also counts. Violations don't need SAM, because SAM can't segment something that's absent.

### Cable identity
Both ends supported still isn't enough. ProofCam also needs either one photo where the same cable is
`fully_traced` between the two ports, or the spec author's explicit statement that only one such cable exists
(reported in the output as an assumption).

### Endpoint states
`established` (supported) · `violated` · `contradicted` (photos disagree; blocks a verdict) · `unknown`.

### Gaps: what's missing, in priority order
| Gap code | Meaning | Typical next view |
|---|---|---|
| `CONTRADICTION` | Photos disagree about a port | Close, steady view of that port |
| `DEVICE_NOT_SEEN` | Device not identified with certainty | Step back, frame the whole device |
| `PORTS_NOT_VISIBLE` | Device seen, ports not | Move to the side with the ports |
| `LABEL_ILLEGIBLE` | Ports seen, labels unreadable | Move closer to the label |
| `PORT_NOT_FOUND` | Readable labels, but not the required one | Show the full port row |
| `INSERTION_UNCLEAR` | Port found, plug state unclear | Closer view of the plug |
| `GROUNDING_MISSING` | Muse claims a plug, SAM doesn't confirm it | Closer, unobstructed view |
| `CABLE_CONTINUITY` | Both ends OK, cable not shown to be one cable | Wide shot of the whole cable run |

Each gap is requested at most twice. Muse's planner can also declare a gap impossible to resolve visually
(e.g. the cable runs inside a wall); that gap is then abandoned.

### Coordinates
- Every coordinate refers to the **normalized image** (after rotation and resizing), never the original file.
- Muse boxes use a **0–1000 grid** (0,0 = top-left); `Box1000.to_pixels()` converts them.
- SAM boxes are **pixels** with inclusive right/bottom edges on the wire; the parser converts them to half-open.
  Masks arrive as height × width rasters covering their box.
- Overlays are drawn on the captured image, never on a live camera preview.

### Budgets
Per inspection: 6 photos, 40 model calls (hard-enforced inside `meta_client.py`), 2 attempts per gap, 4 SAM calls
per photo. There is **no cumulative spend limit across inspections yet**.

---

## 7. The inspection spec (input)

A spec is a JSON file listing devices and requirements. Example: [data/specs/router_switch.json](data/specs/router_switch.json).

```json
{
  "id": "router_switch_v1",
  "title": "Router LAN 1 to Switch Port 3 (blue patch cable)",
  "devices": [
    {"id": "router", "name": "Router", "description": "what it looks like", "sam_concept": "router"},
    {"id": "switch", "name": "Switch", "description": "…", "sam_concept": "network switch"}
  ],
  "requirements": [{
    "id": "R1", "kind": "connection",
    "text": "The blue Ethernet cable must connect Router LAN 1 to Switch Port 3.",
    "cable_color": "blue", "cable_type": "ethernet cable",
    "endpoints": [
      {"device_id": "router", "port_label": "LAN 1", "label_aliases": []},
      {"device_id": "switch", "port_label": "3",     "label_aliases": []}
    ],
    "cable_identity": "require_trace"
  }]
}
```

- `description` helps Muse recognise the device. Write what it actually looks like (brand, colour, antennas).
- `sam_concept` is the short noun SAM searches for (one concept per request; keep it simple).
- `cable_identity`: `require_trace` (default, strict) or `unique_in_installation` (you vouch there's only one
  such cable).
- Only `connection` requirements exist so far; `kind` leaves room for more types later.

---

## 8. Output: where to read results

Every real run writes to `runs/` (git-ignored, because it contains photos).

```
runs/<run-id>/                         one CLI run (or runs/scenarios-<time>/<scenario>/)
├── report.md        ← start here: verdicts, evidence with source photo, gaps, next-view requests, usage
├── report.json      ← everything structured; Muse's claims are under observations[i].extraction
├── trace.jsonl      ← one line per event; on "muse_observe" lines, response_text = Muse's exact raw JSON;
│                      on "sam_segment:*" lines, SAM's raw output; plus latency, tokens, errors
├── overlays/*.jpg   ← photo with SAM masks (filled) and Muse boxes (dashed)
└── images/*.jpg     ← the normalized photo actually sent to the models
```

`runs/scenarios-<time>/summary.json` condenses one scenario run. `runs/probe-<time>.json` holds a probe run.

**Results so far (2026-10-31):** the default-reasoning run is split across
`runs/scenarios-20261031-133028` (s04), `-133122` (s01), `-133211` (s02), `-133237` (s03), `-133322` (s05). The
`reasoning_effort=low` run is all in `runs/scenarios-20261031-133450`. The Meta dashboard matched our traces
exactly: 40 requests, 27.2k input tokens, 29k output tokens, ≈ $0.20.

---

## 9. How to run things

All commands from `backend/` (Windows paths shown).

```powershell
# One-time setup
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install pydantic httpx pillow python-dotenv meta-sam-parser numpy pytest
# then put MODEL_API_KEY=... in the repo-root .env

# Unit tests (no network, free)
.venv\Scripts\python.exe -m pytest -q

# Live API check (4 calls, ~$0.01)
.venv\Scripts\python.exe experiments\probe_api.py --image ..\data\images\04_blue_cable.png

# Five reference scenarios (~$0.10 per full run)
.venv\Scripts\python.exe experiments\run_scenarios.py            # or --only s04

# A real multi-photo inspection
.venv\Scripts\python.exe -m proofcam.cli --spec ..\data\specs\router_switch.json `
    --image ..\data\images\m1_front.jpg --image ..\data\images\m2_router_rear_close.jpg
# or ask for each next photo interactively:
.venv\Scripts\python.exe -m proofcam.cli --spec ..\data\specs\router_switch.json --image first.jpg --interactive

# Faster Muse (same verdicts on the reference set, less reasoning)
$env:PROOFCAM_MUSE_REASONING_EFFORT = "low"

# Live tests (real API, costs money)
$env:PROOFCAM_LIVE_IMAGES = "a.jpg;b.jpg"; .venv\Scripts\python.exe -m pytest -q -m live
```

---

## 10. Cost reference

| Item | Price (standard mode) |
|---|---|
| Muse Spark 1.3 input | $1.25 per 1M tokens ($0.15 cached) |
| Muse Spark 1.3 output | $4.25 per 1M tokens (hidden reasoning tokens count as output) |
| SAM 3.1 image | $2.50 per 1,000 images (≈ $0.0025 per call) |

One photo through the full pipeline costs about $0.01–0.03. The $150 credit covers several thousand photos.
The cheaper `-contributor` models let Meta train on your data, so they are not used.

---

## 11. What's next

1. Fix the three policy issues above (plug vs cable colour, gap priority for the device in view, colour-word
   tolerance), with tests.
2. Capture same-device photos (`m1_front`, `m2_router_rear_close`, `m3_switch_ports_close`, `m4_wide_run`,
   `m5_wrong_port`, `m6_occluded`) and run the real multi-view loop. This is the missing proof.
3. Optionally add a cumulative spend cap before running evaluations.
4. Then Milestone 1: FastAPI + SQLite, so the web app has something to call.

---

## 12. Other docs

| Doc | Read it for |
|---|---|
| [README.md](README.md) | Short setup and run instructions |
| [docs/SPEC.md](docs/SPEC.md) | Product requirements, acceptance criteria per milestone |
| [docs/META_API_FACTS.md](docs/META_API_FACTS.md) | Exactly how the Meta API behaves, with each fact's source |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Why things are built the way they are |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Dated log of work, test results, live findings |
| [CLAUDE.md](CLAUDE.md) | Rules Claude Code follows in this repo |

## Glossary

| Term | Meaning |
|---|---|
| Muse Spark | Meta's multimodal reasoning model; here it reads photos and plans camera moves |
| SAM 3.1 | Meta's Segment Anything Model; finds and outlines objects matching a short phrase |
| Claim | Something a model says it sees. Never a verdict by itself |
| Grounding / corroboration | Checking a Muse claim against a real SAM mask in the same photo |
| Endpoint | One end of a required connection (device + port label) |
| Gap | A specific missing fact that blocks a verdict, with a type code |
| Next view | The camera instruction ProofCam gives to close a gap |
| Spec | The JSON file describing devices and requirements |
| Normalized image | The resized, rotated JPEG actually sent to the models; all coordinates refer to it |
| Trace | The per-call audit log (`trace.jsonl`) |
| Reference images | The five photos in `data/images/`; separate setups, never combined |
