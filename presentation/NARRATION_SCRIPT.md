# ProofCam — narration script (3-minute demo video)

Total running time **2:55** (5 s under the 3:00 limit) · **322 words** of narration · average ≈ 2 words/s, with silence over the demo footage.

Delivery: calm and confident, like explaining it to one engineer. Slow down on the verdict words (*Violated*, *operator-attested*). Pronounce “SAM three point one”, “Muse Spark one point three”.

Never say: “independently verified”, “proves the cable”, “accuracy”, “deployed”, “customers”. The VERIFIED run is **operator-attested**; the VIOLATED run uses **AI-generated test photos** (say so, as the script does).

| Time | Slide | Narration | On-screen caption (muted viewing) |
|---|---|---|---|
| 0:00–0:07 | 1 · The hook | AI can recognise what's in a photo. But can it prove what's true? | AI can recognise what it sees. But can it prove what's true? |
| 0:07–0:18 | 2 · The real-world problem | Installations are signed off on photos and checklists. But a cable you can see is not proof that the right two ports are connected. | A cable is visible ≠ the required connection is proven. |
| 0:18–0:28 | 3 · Seeing is not verifying | Image AI asks: what's in this picture? ProofCam asks: what evidence establishes this requirement, and what's still missing? | From passive recognition to active evidence investigation. |
| 0:28–0:37 | 4 · Meet ProofCam | This is ProofCam: an AI agent that inspects physical installations, decides what it still needs to see, and asks for that exact view. | Inspect → Reason → Request → Verify. |
| 0:37–0:57 | 5 · Demo A — VIOLATED | First, a failure case, on AI-generated test photos. The requirement: a blue cable into LAN 1. Muse Spark reads the port labels, SAM grounds the plug, and the policy sees LAN 1 clearly empty. Violated. Not ‘looks plugged in’. Violated. | A model's observation is not enough. The requirement must be satisfied. |
| 0:57–1:10 | 6 · The active inspection loop | Every photo re-evaluates every requirement. When a fact is missing, like whether one cable joins both ends, ProofCam plans the next camera view to close that gap. | ProofCam knows what it still needs to see. |
| 1:10–1:24 | 7 · Two Meta models, one system | Two Meta models, one system. Muse Spark reasons: photos become structured claims and next-view plans. SAM 3.1 grounds those claims in real pixels. A deterministic policy decides. | Muse reasons. SAM grounds. Policy verifies. |
| 1:24–1:49 | 8 · Demo B — evidence accumulates | Now my real setup: a Jio set-top box, a PlayStation 5 and a TV. Four photos. Each time, Muse observes, SAM segments, and the policy re-checks both connections. Three plug ends are established from photos. One HDMI plug Muse saw, but SAM could not confirm. | Real equipment · 4 photos · every requirement re-checked after each photo. |
| 1:49–2:03 | 9 · Human-in-the-loop assurance | That is where ProofCam stays honest. When the camera can't prove something, it says so, and records exactly what I confirmed, labelled as human, not as vision. | When the camera can't prove it, ProofCam says so. |
| 2:03–2:14 | 10 · The result | The result: verified, operator-attested. Every claim links to a photo, a model output or a time-stamped statement. | VERIFIED — OPERATOR-ATTESTED: every claim has an evidence trail. |
| 2:14–2:25 | 11 · Technical depth | Under the hood: structured model outputs, policy-only verdicts, an append-only evidence store, call budgets, and over five hundred automated tests. | Built for evidence, not just predictions. |
| 2:25–2:38 | 12 · The bigger opportunity | Today it's cables. But the same loop, requirement, evidence, verification, audit trail, could serve data centres, telecom, factories, energy and field maintenance. | Today, cables. Tomorrow, infrastructure. (Vision — not current deployments.) |
| 2:38–2:47 | 13 · Why this matters | What if every physical installation could explain why it was trusted? | What if every physical installation could explain why it was trusted? |
| 2:47–2:55 | 14 · Close | ProofCam. Muse reasons. SAM grounds. Policy verifies. | PROOFCAM — the verification layer for the physical world. |

## Teleprompter (read straight through)

**[0:00] The hook**  
AI can recognise what's in a photo. But can it prove what's true?

**[0:07] The real-world problem**  
Installations are signed off on photos and checklists. But a cable you can see is not proof that the right two ports are connected.

**[0:18] Seeing is not verifying**  
Image AI asks: what's in this picture? ProofCam asks: what evidence establishes this requirement, and what's still missing?

**[0:28] Meet ProofCam**  
This is ProofCam: an AI agent that inspects physical installations, decides what it still needs to see, and asks for that exact view.

**[0:37] Demo A — VIOLATED**  
First, a failure case, on AI-generated test photos. The requirement: a blue cable into LAN 1. Muse Spark reads the port labels, SAM grounds the plug, and the policy sees LAN 1 clearly empty. Violated. Not ‘looks plugged in’. Violated.

**[0:57] The active inspection loop**  
Every photo re-evaluates every requirement. When a fact is missing, like whether one cable joins both ends, ProofCam plans the next camera view to close that gap.

**[1:10] Two Meta models, one system**  
Two Meta models, one system. Muse Spark reasons: photos become structured claims and next-view plans. SAM 3.1 grounds those claims in real pixels. A deterministic policy decides.

**[1:24] Demo B — evidence accumulates**  
Now my real setup: a Jio set-top box, a PlayStation 5 and a TV. Four photos. Each time, Muse observes, SAM segments, and the policy re-checks both connections. Three plug ends are established from photos. One HDMI plug Muse saw, but SAM could not confirm.

**[1:49] Human-in-the-loop assurance**  
That is where ProofCam stays honest. When the camera can't prove something, it says so, and records exactly what I confirmed, labelled as human, not as vision.

**[2:03] The result**  
The result: verified, operator-attested. Every claim links to a photo, a model output or a time-stamped statement.

**[2:14] Technical depth**  
Under the hood: structured model outputs, policy-only verdicts, an append-only evidence store, call budgets, and over five hundred automated tests.

**[2:25] The bigger opportunity**  
Today it's cables. But the same loop, requirement, evidence, verification, audit trail, could serve data centres, telecom, factories, energy and field maintenance.

**[2:38] Why this matters**  
What if every physical installation could explain why it was trusted?

**[2:47] Close**  
ProofCam. Muse reasons. SAM grounds. Policy verifies.

## Fact check for every spoken claim

| Claim | Source |
|---|---|
| Recording A uses AI-generated test photos; LAN 1 clearly empty → VIOLATED | inspection insp_f1bb… (live-m33.db): photos IMG_6171–6173, photo 3 ‘LAN 1’ legible, empty, clear; re-assessed with the current policy: still VIOLATED |
| Muse Spark reads labels; SAM grounds the plug (Recording A) | photo 3 port claims + SAM ‘blue ethernet cable’ link corroborated at the plugged socket |
| Real setup: Jio set-top box, PS5, TV; four photos | inspection insp_92cc… (live-final.db), 4 photos of physical equipment |
| Three plug ends established from photos; one HDMI plug Muse saw, SAM could not confirm | R1 ends: photo 2 + photo 4; R2 TV end: photo 3; PS5 HDMI OUT: Muse-only candidate (SAM ‘hdmi cable’ 0 objects) |
| ‘records exactly what I confirmed, labelled as human’ | 3 operator declarations od1–od3 with timestamps; R1 operator-assisted, R2 operator-attested |
| ‘verified, operator-attested’ | overall assurance of insp_92cc… |
| ‘over five hundred automated tests’ | 499 backend (pytest) + 57 frontend (vitest) passing on 5 Nov 2026, mocked models |
| Data centres, telecom… ‘could serve’ | stated as vision; no deployments |
