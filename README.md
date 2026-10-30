# ProofCam

**A camera-guided AI agent that verifies physical equipment installations — and decides what it needs to see next.**

Built for the Meta Global AI Developer Hackathon 2026 (Indie Developer track). All code in this repository
was created for the hackathon. Runtime AI is exclusively Meta Model API: **Muse Spark 1.3** (perception,
next-view planning) and **SAM 3.1** (segmentation / grounding).

> Status: **Milestone 0 (technical feasibility)**. Backend inspection loop, deterministic verification
> policy, SAM grounding, CLI, and tests are implemented. Live API validation is pending a key and real photos.
> The live camera web app is Milestone 3.

## How it works

```
photo ─▶ Muse Spark: per-image claims (devices, ports, labels, plugs, cables, 0–1000 boxes)
      ─▶ SAM 3.1: concept masks (cable, devices) ─▶ link masks to Muse claims (corroboration)
      ─▶ deterministic policy: VERIFIED / VIOLATED / INSUFFICIENT_EVIDENCE + typed evidence gaps
      ─▶ pick the most fundamental gap ─▶ Muse plans a specific camera move ─▶ user captures ─▶ repeat
```

Models never set verdicts. A requirement is VERIFIED only if every endpoint has a clear, legible,
SAM-corroborated observation **and** cable identity is established in one image (or explicitly asserted by
the spec author, disclosed as an assumption). See [docs/DECISIONS.md](docs/DECISIONS.md).

## Setup (Windows / PowerShell shown; Python 3.11+)

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install pydantic httpx pillow python-dotenv meta-sam-parser numpy pytest
copy ..\.env.example ..\.env    # then put your key in MODEL_API_KEY
```

## Run

```powershell
# 1. Probe the API (4 calls, ~$0.01). Without --image it uses a synthetic image (format check only).
.venv\Scripts\python.exe experiments\probe_api.py --image ..\data\images\s01_1_front.jpg

# 2. Inspect: first photo, then follow-up photo(s) answering each next-view request
.venv\Scripts\python.exe -m proofcam.cli --spec ..\data\specs\router_switch.json `
    --image ..\data\images\s01_1_front.jpg --image ..\data\images\s01_2_rear.jpg
# or interactively: --image first.jpg --interactive
```

Each run writes `runs/<id>/report.md`, `report.json`, `trace.jsonl`, normalized images and overlays
(SAM masks filled; Muse boxes dashed). `runs/` and `data/images/` are git-ignored.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q          # unit tests, mocked Meta API (no network)
.venv\Scripts\python.exe -m pytest -q -m live  # real API; set PROOFCAM_LIVE_IMAGES="a.jpg;b.jpg"
```

Mocked results are tagged `source="mock"` in traces; real calls are `source="live"`.

## Docs
[SPEC](docs/SPEC.md) · [META_API_FACTS](docs/META_API_FACTS.md) · [DECISIONS](docs/DECISIONS.md) · [PROGRESS](docs/PROGRESS.md)

ProofCam verifies visually observable conditions only. It does not certify electrical safety, hidden
connectivity, operational performance, or regulatory compliance.
