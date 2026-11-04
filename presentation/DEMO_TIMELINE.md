# ProofCam — demo timeline and edit decision list

Target length **2:55** · 1920×1080 · 30 fps · H.264 MP4. Slide timings are already set in the PPTX (Transitions → After = slot minus its fade, because the video export plays each fade on top), so PowerPoint's *Create a Video* follows this table.

| # | In–out (video time) | Dur | Visual | Source | Speed | Transition | Caption on screen |
|---|---|---|---|---|---|---|---|
| 1 | 0:00–0:07 | 7 s | The hook | Slide (static, real assets) | — | fade through black, slow | AI can recognise what it sees. But can it prove what's true? |
| 2 | 0:07–0:18 | 11 s | The real-world problem | Slide (static, real assets) | — | fade, 0.5 s | A cable is visible ≠ the required connection is proven. |
| 3 | 0:18–0:28 | 10 s | Seeing is not verifying | Slide (static, real assets) | — | fade, 0.5 s | From passive recognition to active evidence investigation. |
| 4 | 0:28–0:37 | 9 s | Meet ProofCam | Slide (static, real assets) | — | fade, 0.5 s | Inspect → Reason → Request → Verify. |
| 5 | 0:37–0:57 | 20 s | Demo A — VIOLATED | Recording A (phone frame) + real verdict card | see clip plan | fade, 0.5 s | A model's observation is not enough. The requirement must be satisfied. |
| 6 | 0:57–1:10 | 13 s | The active inspection loop | Slide (static, real assets) | — | fade, 0.5 s | ProofCam knows what it still needs to see. |
| 7 | 1:10–1:24 | 14 s | Two Meta models, one system | Slide (static, real assets) | — | fade, 0.5 s | Muse reasons. SAM grounds. Policy verifies. |
| 8 | 1:24–1:49 | 25 s | Demo B — evidence accumulates | Recording B part 1 (phone frame) + real photo timeline | see clip plan | fade, 0.5 s | Real equipment · 4 photos · every requirement re-checked after each photo. |
| 9 | 1:49–2:03 | 14 s | Human-in-the-loop assurance | Slide (static, real assets) | — | fade, 0.5 s | When the camera can't prove it, ProofCam says so. |
| 10 | 2:03–2:14 | 11 s | The result | Slide (static, real assets) | — | fade, 0.5 s | VERIFIED — OPERATOR-ATTESTED: every claim has an evidence trail. |
| 11 | 2:14–2:25 | 11 s | Technical depth | Slide (static, real assets) | — | fade, 0.5 s | Built for evidence, not just predictions. |
| 12 | 2:25–2:38 | 13 s | The bigger opportunity | Slide (static, real assets) | — | fade, 0.5 s | Today, cables. Tomorrow, infrastructure. (Vision — not current deployments.) |
| 13 | 2:38–2:47 | 9 s | Why this matters | Slide (static, real assets) | — | fade, 0.5 s | What if every physical installation could explain why it was trusted? |
| 14 | 2:47–2:55 | 8 s | Close | Slide (static, real assets) | — | fade through black, slow | PROOFCAM — the verification layer for the physical world. |

## Recording A — clip plan (slide 5, video time 0:37–0:57)

Source: Recording A — VIOLATED (router LAN 1 → switch port 3, AI-generated test photos).

| Clip time | Content | Speed |
|---|---|---|
| 0–3 s | Requirement / template on screen (or the inspection header) | 1.5–2× |
| 3–11 s | Photos 1–3 uploaded and analysed (the ‘Analysing your photo…’ waits) | 6–8×, show ‘PROCESS ACCELERATED’ |
| 11–16 s | Violated verdict card: ‘Router LAN 1 · clearly wrong’ | 1× (real time) |
| 16–20 s | ‘Clearly observed: … LAN 1 … target port is empty’ / analysis overlay of photo 3 | 1×, optional slow zoom |

## Recording B — clip plan (slide 8, video time 1:24–1:49)

Source: Recording B — real Jio set-top box, PS5 and TV, VERIFIED — operator-attested.

| Clip time | Content | Speed |
|---|---|---|
| 0–5 s | Overview photo captured and analysed; first ‘Next view’ card | waits 6–8×; card 1× |
| 5–11 s | Set-top box rear photo → result card (RJ45 plug) | waits 6–8×; result 1.5× |
| 11–17 s | TV panel photo → result card (HDMI 1 (ARC) plug) | waits 6–8×; result 1.5× |
| 17–25 s | PS5 rear photo → result; connection rows (LAN ✓, HDMI OUT seen by Muse only) | waits 6–8×; rows 1× |

## Speed conventions

- Model processing (‘Analysing your photo…’, typically 30–60 s per photo in these runs): **6–8×**, with the *PROCESS ACCELERATED* caption visible for the whole sped-up stretch.
- Ordinary navigation and scrolling: **1.5–3×**.
- Verdict reveals, the confirmation sheet, and any card the narration names: **1× (real time)**, readable for ≥2–3 s.
- Never cut a model wait so that inference looks instant; the caption must say it was accelerated.

## Audio

- Narration only (record in a quiet room, phone 20 cm away, or the laptop mic with a headset). Normalise to about −16 LUFS.
- Recordings muted. Optional: a quiet royalty-free music bed at −28 LUFS under slides 1–4 and 12–14 only.

## Hard checks before upload

- Duration ≤ 2:58 (planned 2:55).
- Slide 5 shows the ‘AI-generated test image’ disclosure; slide 8/10 never says ‘independently verified’.
- The final card shows github.com/dakshvatss/proofcam for the full 8 s, and the repository is public.
