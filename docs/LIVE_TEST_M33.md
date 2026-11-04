# M3.3 — first real Muse + SAM test from the iPhone (runbook)

Status 2026-11-03: configured and probed with **zero** model calls. The first paid capture needs explicit approval.

## What the test can truthfully show
The real installation is a **wall-mounted router with no switch**. `my_setup` (router LAN 1 → switch port 3, blue
cable) is used as a work order that this installation does **not** fulfil. VERIFIED is impossible: the switch
endpoint can never be supported. That is the point of the test. No spec, threshold or policy rule is changed.

What `policy.py` will decide (a requirement is VIOLATED as soon as one endpoint is violated without
contradiction; anything less than both endpoints and the cable identity is INSUFFICIENT_EVIDENCE):

| What the photos show | Verdict | Why |
|---|---|---|
| The router is not recognised as the spec router with *clear* certainty (the spec text describes a black TP-Link with a 4-port LAN row; a different router should **not** match) | INSUFFICIENT_EVIDENCE (`DEVICE_NOT_SEEN`) | No device hit, so nothing is supported or violated |
| Router recognised, ports on the underside/back not visible | INSUFFICIENT (`PORTS_NOT_VISIBLE`) | |
| Ports visible but "LAN 1" not legibly printed (icons, glare, plug hides it, or only "1") | INSUFFICIENT (`LABEL_ILLEGIBLE` / `PORT_NOT_FOUND`) | "1" ≠ "LAN 1" by design; inference never produces a violation |
| LAN 1 legibly labelled and **clearly empty** | **VIOLATED** | The work order requires a blue cable there |
| LAN 1 legibly labelled, clearly holds a plug of a clearly different colour (yellow, white, grey, black…; *not* purple, which is near blue) | **VIOLATED** | |
| LAN 1 holds a blue plug, SAM-grounded | INSUFFICIENT (switch `DEVICE_NOT_SEEN`) | One endpoint is supported; the switch and the cable trace are missing |
| Any VIOLATED on a router that does **not** match the TP-Link description | Treat as a **model misidentification**, not a demo result | Record it in PROGRESS as an observed error |

The agent counts no attempt for a photo in which the targeted device isn't seen at any certainty ("off target"). So
while the router isn't recognised at all, the agent keeps asking for it until the 6-photo or call budget runs out.
If the router is seen with *uncertain* identity, attempts count and the gap is given up after 2. The stop conditions
below stop earlier.

## Configuration (verified by a zero-call probe)
| Item | Value |
|---|---|
| Models / base | `muse-spark-1.3`, `sam-3.1`, `https://api.meta.ai/v1` (from `.env`; key present, never printed) |
| Backend | `scripts/start-live.ps1`: `127.0.0.1:8000` only, 1 worker, refuses a busy port and a missing or short access code |
| Database | `var/live-m33.db` (new; git-ignored), separate from `var/dev-mock.db` and `var/proofcam.db` |
| Global cap | **20 calls** in that DB, retries included, reserved before every HTTP attempt; a photo is refused (429, nothing sent) unless ≥ 8 remain |
| Per inspection | 6 photos, 40 calls (unchanged; the global 20 binds first) |
| Reasoning | `low` (6–29 s per photo instead of 25–48 s) |
| Frontend | `vite preview` 127.0.0.1:4173 (`dist` is current); amber **Live models · N of 20 calls left** banner |
| Tailscale | `tailscale serve` → `https://desktop-bn5ul8e.tail4f0791.ts.net` → 127.0.0.1:4173, **tailnet only**; Funnel off |

## Launch (three terminals)
```powershell
# 1. Backend, LIVE. Asks for the access code (hidden) unless it is in $env or .env.
#    Using the code the phone already used keeps its cookie valid.
cd C:\Users\Daksh\Documents\GitHub\proofcam
.\scripts\start-live.ps1
#   If PowerShell blocks scripts: powershell -ExecutionPolicy Bypass -File .\scripts\start-live.ps1

# 2. Frontend
cd C:\Users\Daksh\Documents\GitHub\proofcam\frontend
npm run preview

# 3. Check the share (already configured; persists across restarts)
& "C:\Program Files\Tailscale\tailscale.exe" serve status
```
On the iPhone, reload the page. The banner must read **Live models · 20 of 20 calls left** (amber). If it is purple
or the number differs, stop.

## Proposed test (after approval)
1. Start Inspection (`my_setup`). Free.
2. **Photo 1, overview:** the whole router, front and port side if possible, with the port labels in frame and lit.
   ≈ 4 calls (Muse observe, SAM × 1–3, Muse plan).
3. Read the verdict, the evidence and the guidance. **Photo 2, close-up, only if requested:** follow the
   instruction (e.g. the port row with LAN 1 legible). ≈ 4–6 calls.
4. Stop. Open the report and download the Markdown/JSON.

Estimated: 8–12 calls, **≈ $0.06–0.12**. Hard ceiling: 20 calls ≈ **$0.20** (≈ $0.30 if every call were a Muse call).
Recorded basis: 4 calls = $0.035; 12 calls = $0.094.

**Stop conditions (do not take another photo):**
- the banner is not amber "Live", or the calls-left number is not what you expect;
- any request fails, times out, or shows an error. Wait for the app to recover the saved result; never re-shoot
  the same view just to retry;
- a verdict is reached (VIOLATED) or the inspection stops;
- after photo 2, regardless of outcome;
- fewer than 8 calls left (the server refuses anyway).

## Second inspection spec (not written: needs facts about real equipment)
A spec is plain JSON in `data/specs/` (not engine code; the engine fingerprint is unchanged), but it must describe
real devices and real printed labels. I need from you: router make/model, the exact printed port labels (e.g.
`LAN1`, `WAN`, `Internet`), and what is plugged in, with cable colours. Then either:
- **Truthful incomplete work order on the real router:** the real router's description plus a required cable to a
  device that does not exist yet. An empty or wrongly coloured LAN port then gives a correct **VIOLATED**;
  otherwise INSUFFICIENT_EVIDENCE.
- **VERIFIED needs**, in **one** photo (`require_trace`): two identifiable devices, each port's own label printed
  and legible (icons don't count; aliases can cover `INTERNET` vs `WAN`), one cable of a single nameable colour
  (blue, yellow… not grey/white/black lookalikes), plugs clearly inserted, and the whole cable visible end to end.
  - *Existing equipment, if present:* router `WAN` ↔ ISP modem/ONT `LAN`/`GE1` port, when both ends and the
    cable fit in one photo.
  - *Not suitable:* a laptop or USB adapter Ethernet port (usually an icon only, so the port is never identified).
  - *Smallest purchase:* a 5-port unmanaged switch (ports printed 1–5) and one short blue patch cable, mounted
    next to the router. Connect **one** cable only: two cables between the same devices, or a cable from a router
    port to another port on the same router, creates a network loop.

## Demo essentials (tomorrow)
- **Laptop must not sleep** (sleep stops the backend and the share): plug it in and set *Settings → System → Power →
  Screen and sleep → Never* while recording.
- iPhone: Tailscale **Connected**; Safari tab, not a Home Screen app (that needs the code and camera permission
  again); turn on Control Center **Screen Recording** first.
- Use a **fresh DB and a new cap** for the recording (e.g. `.\scripts\start-live.ps1 -Db var/live-demo.db
  -CallLimit 40`). This is a new spend decision that needs approval.
- Light the port labels; hold steady; allow 6–29 s per photo (narrate or cut in editing, and say so).
- Keep the amber **Live** banner, the verdict, the evidence list, the SAM overlay and the report in the video. Never
  show mock-mode results as real.
- Any AI-generated reference image shown must be labelled synthetic. Don't present the router–switch reference
  images as the user's installation.
- After recording: export the report (MD + JSON). Don't commit `var/` or photos.
- Stop sharing when done: `tailscale serve --https=443 off`.
