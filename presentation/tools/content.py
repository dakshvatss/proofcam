"""Single source for the narration, timings, captions and production notes.

build_deck.py writes these into the PPTX speaker notes and slide timings; write_docs.py turns the same data into
NARRATION_SCRIPT.md, DEMO_TIMELINE.md and ProofCam_Narration.srt, so the deck and the scripts cannot drift apart.

Facts quoted here were checked against the repository and the recorded inspections on 5 Nov 2026 (see
ASSET_MANIFEST.md): Recording A = insp_f1bb… (router→switch, AI-generated test photos, VIOLATED);
Recording B = insp_92cc… (real Jio set-top box, PS5 and TV, VERIFIED — operator-attested).
"""

# (no, short title, start_s, dur_s, narration, on-screen caption, production note)
SLIDES = [
    (1, "The hook", 0, 7,
     "AI can recognise what's in a photo. But can it prove what's true?",
     "AI can recognise what it sees. But can it prove what's true?",
     "Slow fade in from black. Hold the real PS5 photo; the two evidence labels are the story in one frame."),
    (2, "The real-world problem", 7, 11,
     "Installations are signed off on photos and checklists. But a cable you can see is not proof that the right two "
     "ports are connected.",
     "A cable is visible ≠ the required connection is proven.",
     "Fade. Let the bottom ‘≠’ bar land on the word ‘proof’."),
    (3, "Seeing is not verifying", 18, 10,
     "Image AI asks: what's in this picture? ProofCam asks: what evidence establishes this requirement, and what's "
     "still missing?",
     "From passive recognition to active evidence investigation.",
     "Fade. Signature slide: left panel = labels, right panel = evidence + gap + next photo (real values)."),
    (4, "Meet ProofCam", 28, 9,
     "This is ProofCam: an AI agent that inspects physical installations, decides what it still needs to see, and "
     "asks for that exact view.",
     "Inspect → Reason → Request → Verify.",
     "Fade. Real app screens (landing + the completed real inspection)."),
    (5, "Demo A — VIOLATED", 37, 20,
     "First, a failure case, on AI-generated test photos. The requirement: a blue cable into LAN 1. Muse Spark reads "
     "the port labels, SAM grounds the plug, and the policy sees LAN 1 clearly empty. Violated. Not ‘looks plugged "
     "in’. Violated.",
     "A model's observation is not enough. The requirement must be satisfied.",
     "RECORDING A in the phone frame. Requirement/start 1.5×; ‘Analysing…’ waits 6–8×; violated card at 1×, hold ≥3 s "
     "on ‘Router LAN 1 · clearly wrong’. Keep the ‘AI-generated test images’ disclosure visible."),
    (6, "The active inspection loop", 57, 13,
     "Every photo re-evaluates every requirement. When a fact is missing, like whether one cable joins both ends, "
     "ProofCam plans the next camera view to close that gap.",
     "ProofCam knows what it still needs to see.",
     "Fade. Loop diagram, then the two real requests from the final inspection (nv1 by Muse, nv5 template)."),
    (7, "Two Meta models, one system", 70, 14,
     "Two Meta models, one system. Muse Spark reasons: photos become structured claims and next-view plans. SAM 3.1 "
     "grounds those claims in real pixels. A deterministic policy decides.",
     "Muse reasons. SAM grounds. Policy verifies.",
     "Fade. Real stored overlay of photo 4 (SAM masks + Muse boxes) on the right."),
    (8, "Demo B — evidence accumulates", 84, 25,
     "Now my real setup: a Jio set-top box, a PlayStation 5 and a TV. Four photos. Each time, Muse observes, SAM "
     "segments, and the policy re-checks both connections. Three plug ends are established from photos. One HDMI plug "
     "Muse saw, but SAM could not confirm.",
     "Real equipment · 4 photos · every requirement re-checked after each photo.",
     "RECORDING B (part 1) in the phone frame: photos 1→4 with their result cards. Waits 6–8× with ‘PROCESS "
     "ACCELERATED’ visible; each ‘Next view’ card 1–1.5×, readable for ≥2 s."),
    (9, "Human-in-the-loop assurance", 109, 14,
     "That is where ProofCam stays honest. When the camera can't prove something, it says so, and records exactly "
     "what I confirmed, labelled as human, not as vision.",
     "When the camera can't prove it, ProofCam says so.",
     "Fade. Static, readable split (photos vs operator). Optional: 3–4 s of Recording B at 1× showing the "
     "confirmation sheet."),
    (10, "The result", 123, 11,
     "The result: verified, operator-attested. Every claim links to a photo, a model output or a time-stamped "
     "statement.",
     "VERIFIED — OPERATOR-ATTESTED: every claim has an evidence trail.",
     "Fade. Real installation card + condensed lines from the generated report. Do not call this ‘independently "
     "verified’."),
    (11, "Technical depth", 134, 11,
     "Under the hood: structured model outputs, policy-only verdicts, an append-only evidence store, call budgets, "
     "and over five hundred automated tests.",
     "Built for evidence, not just predictions.",
     "Fade. Architecture snake; tests are mocked-model regression tests, not accuracy benchmarks (say nothing more)."),
    (12, "The bigger opportunity", 145, 13,
     "Today it's cables. But the same loop, requirement, evidence, verification, audit trail, could serve data "
     "centres, telecom, factories, energy and field maintenance.",
     "Today, cables. Tomorrow, infrastructure. (Vision — not current deployments.)",
     "Fade. Keep the ‘potential applications, not current deployments’ tag on screen."),
    (13, "Why this matters", 158, 9,
     "What if every physical installation could explain why it was trusted?",
     "What if every physical installation could explain why it was trusted?",
     "Fade. Let the question breathe; no extra narration."),
    (14, "Close", 167, 8,
     "ProofCam. Muse reasons. SAM grounds. Policy verifies.",
     "PROOFCAM — the verification layer for the physical world.",
     "Fade through black. End card holds the GitHub URL for the full 8 s."),
]

TOTAL_S = SLIDES[-1][2] + SLIDES[-1][3]  # 175 s = 2:55

# Clip-level plan for the two recordings (times are positions in the FINAL video).
CLIPS = {
    "A": dict(slide=5, start=37, dur=20, source="Recording A — VIOLATED (router LAN 1 → switch port 3, AI-generated test photos)",
              segments=[
                  ("0–3 s", "Requirement / template on screen (or the inspection header)", "1.5–2×"),
                  ("3–11 s", "Photos 1–3 uploaded and analysed (the ‘Analysing your photo…’ waits)", "6–8×, show ‘PROCESS ACCELERATED’"),
                  ("11–16 s", "Violated verdict card: ‘Router LAN 1 · clearly wrong’", "1× (real time)"),
                  ("16–20 s", "‘Clearly observed: … LAN 1 … target port is empty’ / analysis overlay of photo 3", "1×, optional slow zoom"),
              ]),
    "B": dict(slide=8, start=84, dur=25, source="Recording B — real Jio set-top box, PS5 and TV, VERIFIED — operator-attested",
              segments=[
                  ("0–5 s", "Overview photo captured and analysed; first ‘Next view’ card", "waits 6–8×; card 1×"),
                  ("5–11 s", "Set-top box rear photo → result card (RJ45 plug)", "waits 6–8×; result 1.5×"),
                  ("11–17 s", "TV panel photo → result card (HDMI 1 (ARC) plug)", "waits 6–8×; result 1.5×"),
                  ("17–25 s", "PS5 rear photo → result; connection rows (LAN ✓, HDMI OUT seen by Muse only)", "waits 6–8×; rows 1×"),
              ]),
}
