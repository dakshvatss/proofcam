# ProofCam

**Visual proof for physical work.** AI-guided inspections that know what evidence is missing.

ProofCam is a camera-guided inspection agent for physical installations. A technician points a phone at the
equipment. ProofCam works out which facts the photos have not yet established, and asks for the specific view that
would establish them. A deterministic verification engine then decides each requirement from the accumulated
evidence. The result is an auditable record: what was proven, by which photo, and what is still unproven.

Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer track, theme **Push the Frontier**) with
**Meta Muse Spark 1.3** and **SAM 3.1** through the Meta Model API. ProofCam is an independent project, not affiliated
with or endorsed by Meta.

> **Status (2026-11-04): complete. All milestones (0–5) are done; this is the hackathon release.**
> - **Automated checks:** 493 backend tests pass (mocked models; 1 live test excluded by default), plus 54 frontend
>   tests, TypeScript, lint and the production build.
> - **Ideal product:** the roadmap beyond this release is in
>   [docs/PROGRESS.md → Future work](docs/PROGRESS.md#future-work-the-ideal-product).
> - **No accuracy figures:** nothing here is a measured field accuracy.

---

## 1. The problem
Installation work is checked by photos that nobody can really check. A single snapshot rarely shows enough: the
port is on the back, the label is too small, the cable disappears behind furniture. Today a person either trusts
the photo or redoes the visit. Asking a vision model "is this connected correctly?" does not fix it either: you get
a confident answer that may rest on nothing visible.

## 2. ProofCam's answer: active evidence acquisition
**ProofCam doesn't just answer questions about photographs. It actively asks for the photographs needed to
establish a claim.**

```
OBSERVE → GROUND → ASSESS → IDENTIFY WHAT IS MISSING → REQUEST THE NEXT VIEW → OBSERVE AGAIN → VERIFY
```

| Part | Role | What it never does |
|---|---|---|
| **Muse Spark 1.3** | Reads each photo into structured observations (devices, ports, printed labels, plugs, cables, socket shapes) and plans the next camera instruction for the most important missing fact | Decide a verdict. Its output is a claim, not proof |
| **SAM 3.1** | Segments equipment and cables; the engine checks that a cable mask actually reaches each claimed port | Assert connectivity. Segmentation is not a connection |
| **Deterministic policy** | Decides `VERIFIED`, `VIOLATED` or `INSUFFICIENT_EVIDENCE` from the evidence alone, with explicit gaps and contradictions | Guess. Unknown stays unknown |

Every result is backed by photographs, and the report shows exactly which photo supports which claim.

## 3. What a requirement can say
A company (here: the spec author) writes the requirements in a JSON specification. Two styles are supported:

- **Exact:** "The blue Ethernet cable must connect Router **LAN 1** to Switch **Port 3**." The exact printed port
  labels, the cable colour, the connector family, and one photo tracing the cable between both ports are all
  required. An empty LAN 1 is a violation.
- **Flexible:** "Connect the PS5 LAN port to **any LAN port** on the router." Several ports are acceptable:
  - **Which ports count:** a list of labels, or a label group ("LAN" accepts "LAN 3", never "WAN"). Where the
    author asserts it, any socket of the right connector family also counts, identified only by its *observed*
    shape and disclosed in every report.
  - **What is not a violation:** an empty permitted port, because another permitted port may hold the cable.
  - **Unknown ports never qualify.**
- **Any colour:** `cable_color: null`. Colour stops being a criterion, but the same cable must still be traced
  between both ports. "Any colour" never means "any cable".
- **Connector families:** Ethernet and HDMI (and others) are kept apart. A socket observed as HDMI never counts
  for an Ethernet requirement.

One inspection can hold several requirements across several devices. Each is verified independently, and the
**installation is verified only when every requirement is verified**. If any requirement is violated, the
installation is violated; otherwise it has insufficient evidence. Contradictions always stay visible.

## 4. Inspection templates in this repository
| Template | Spec | What it checks |
|---|---|---|
| **Network Connection Verification** | `data/specs/my_setup.json` | Exact: the blue Ethernet cable, router LAN 1 → switch port 3 |
| Router LAN 1 → Switch Port 3 | `data/specs/router_switch.json` | The original reference scenario (exact) |
| **Home Entertainment Installation** | `data/specs/ps5_home_setup.json` | Flexible, any colour: Wi-Fi router (any LAN port) → PS5 LAN (Ethernet); PS5 HDMI OUT → any Samsung TV HDMI input (HDMI). 3 devices, 2 connections, up to 8 photos |

## 5. Honest limitations
- **Visual only:** ProofCam verifies what photographs show. It does not test network connectivity, video
  output, electrical safety or regulatory compliance, and its reports are not certifications.
- **Labels must be readable.** A router port counts as LAN only if its printed text (or the LAN heading above it)
  is legible. Icon-only ports are identified only where the spec explicitly accepts any socket of that family, and
  only from an observed socket shape.
- **One photo must trace each cable.** With the default `require_trace`, a cable that runs through a wall, behind
  furniture or across a room cannot be shown end to end, so that connection stays `INSUFFICIENT_EVIDENCE`. That is
  likely for a wall-mounted router.
- **Bounded:**
  - **Per inspection:** 6 photos by default (a spec may set up to 10; the home setup uses 8) and 40 model calls.
  - **Server-wide:** a model-call cap. Insufficient evidence is a normal, honest outcome.
- **Device identity:** recognising a device in two photos does not prove they show the same physical unit. This
  is disclosed in every report.
- **Not field-validated:** model behaviour on new hardware is unmeasured. Tests use mocked model outputs.

## 6. Run it
Requirements: Windows (PowerShell), Python 3.12 venv in `backend/.venv`, Node 20+, a Meta Model API key in the
repo-root `.env` (never sent to the browser).

```powershell
# backend tests (mocked models, free)
cd backend; .venv\Scripts\python.exe -m pytest -q
# frontend checks
cd frontend; npm test; npm run typecheck; npm run lint; npm run build
```

**Mock mode (free; scripted results, labelled "Mock models" in the app):**
```powershell
cd backend; .venv\Scripts\python.exe experiments\dev_mock_server.py --scenario verify
cd frontend; npm run dev        # http://127.0.0.1:5173
```

**Live mode (paid; labelled "Live models" with the calls left):**
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-live.ps1 -Db var/live-demo.db   # 127.0.0.1:8000, access code, call cap
cd frontend; npm run build; npm run preview                                                # 127.0.0.1:4173
```
**iPhone:** private HTTPS through Tailscale Serve (tailnet only, never Funnel). The complete demo runbook, the iPhone
checklist and the recording sequence are in [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md); setup background is in
[docs/IPHONE_SETUP.md](docs/IPHONE_SETUP.md).

## 7. Architecture
`backend/proofcam`:
- `spec` (requirements, port selectors);
- `meta_client` (HTTP, retries, call reservation before every attempt);
- `muse` / `prompts` (observation and next-view planning);
- `grounding` / `geometry` (SAM ↔ Muse linking);
- `policy` (deterministic verdicts, gap selection, overall verdict);
- `agent` (bounded loop);
- `service` / `store` / `api` (FastAPI, SQLite, idempotent captures, leases, access code);
- `report` / `overlay`.

`frontend/`: React 19 + TypeScript + Vite + Tailwind PWA (camera workspace, guidance, progress, evidence, report).
The details are in [GUIDE.md](GUIDE.md), the decisions in [docs/DECISIONS.md](docs/DECISIONS.md), the API contract in
[docs/FRONTEND_HANDOFF.md](docs/FRONTEND_HANDOFF.md) and the log in [docs/PROGRESS.md](docs/PROGRESS.md).

## 8. Future work
*An intelligence layer between physical work and digital verification.* The full roadmap toward the ideal product
covers field-scale validation, perception, product and platform work. It is kept in one place:
[docs/PROGRESS.md → Future work](docs/PROGRESS.md#future-work-the-ideal-product).
