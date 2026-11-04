"""Write NARRATION_SCRIPT.md, DEMO_TIMELINE.md and ProofCam_Narration.srt from content.py (same data as the deck).
Usage: python write_docs.py <presentation_dir>"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from content import CLIPS, SLIDES, TOTAL_S  # noqa: E402

out = Path(sys.argv[1])


def mmss(s: float) -> str:
    m, s = divmod(int(round(s)), 60)
    return f"{m}:{s:02d}"


def words(t: str) -> int:
    return len(re.findall(r"[A-Za-z0-9’'-]+", t))


total_words = sum(words(n) for *_, n, _c, _p in [(a, b, c, d, e, f, g) for a, b, c, d, e, f, g in SLIDES])
# ------------------------------------------------------------------------------------------------ narration
L = ["# ProofCam — narration script (3-minute demo video)", "",
     f"Total running time **{mmss(TOTAL_S)}** (5 s under the 3:00 limit) · **{total_words} words** of narration · "
     "average ≈ 2 words/s, with silence over the demo footage.", "",
     "Delivery: calm and confident, like explaining it to one engineer. Slow down on the verdict words "
     "(*Violated*, *operator-attested*). Pronounce “SAM three point one”, “Muse Spark one point three”.", "",
     "Never say: “independently verified”, “proves the cable”, “accuracy”, “deployed”, “customers”. The VERIFIED run "
     "is **operator-attested**; the VIOLATED run uses **AI-generated test photos** (say so, as the script does).", "",
     "| Time | Slide | Narration | On-screen caption (muted viewing) |", "|---|---|---|---|"]
for n, ttl, start, dur, narr, cap, _ in SLIDES:
    L.append(f"| {mmss(start)}–{mmss(start + dur)} | {n} · {ttl} | {narr} | {cap} |")
L += ["", "## Teleprompter (read straight through)", ""]
for n, ttl, start, dur, narr, *_ in SLIDES:
    L += [f"**[{mmss(start)}] {ttl}**  ", narr, ""]
L += ["## Fact check for every spoken claim", "",
      "| Claim | Source |", "|---|---|",
      "| Recording A uses AI-generated test photos; LAN 1 clearly empty → VIOLATED | inspection insp_f1bb… (live-m33.db): photos IMG_6171–6173, photo 3 ‘LAN 1’ legible, empty, clear; re-assessed with the current policy: still VIOLATED |",
      "| Muse Spark reads labels; SAM grounds the plug (Recording A) | photo 3 port claims + SAM ‘blue ethernet cable’ link corroborated at the plugged socket |",
      "| Real setup: Jio set-top box, PS5, TV; four photos | inspection insp_92cc… (live-final.db), 4 photos of physical equipment |",
      "| Three plug ends established from photos; one HDMI plug Muse saw, SAM could not confirm | R1 ends: photo 2 + photo 4; R2 TV end: photo 3; PS5 HDMI OUT: Muse-only candidate (SAM ‘hdmi cable’ 0 objects) |",
      "| ‘records exactly what I confirmed, labelled as human’ | 3 operator declarations od1–od3 with timestamps; R1 operator-assisted, R2 operator-attested |",
      "| ‘verified, operator-attested’ | overall assurance of insp_92cc… |",
      "| ‘over five hundred automated tests’ | 499 backend (pytest) + 57 frontend (vitest) passing on 5 Nov 2026, mocked models |",
      "| Data centres, telecom… ‘could serve’ | stated as vision; no deployments |", ""]
(out / "NARRATION_SCRIPT.md").write_text("\n".join(L), encoding="utf-8")

# ------------------------------------------------------------------------------------------------ timeline
L = ["# ProofCam — demo timeline and edit decision list", "",
     f"Target length **{mmss(TOTAL_S)}** · 1920×1080 · 30 fps · H.264 MP4. Slide timings are already set in the PPTX "
     "(Transitions → After = slot minus its fade, because the video export plays each fade on top), so PowerPoint's *Create a Video* follows this table.", "",
     "| # | In–out (video time) | Dur | Visual | Source | Speed | Transition | Caption on screen |",
     "|---|---|---|---|---|---|---|---|"]
for n, ttl, start, dur, narr, cap, prod in SLIDES:
    src = ("Recording A (phone frame) + real verdict card" if n == 5 else
           "Recording B part 1 (phone frame) + real photo timeline" if n == 8 else "Slide (static, real assets)")
    speed = "see clip plan" if n in (5, 8) else "—"
    tr = "fade through black, slow" if n in (1, 14) else "fade, 0.5 s"
    L.append(f"| {n} | {mmss(start)}–{mmss(start + dur)} | {dur} s | {ttl} | {src} | {speed} | {tr} | {cap} |")
for key, c in CLIPS.items():
    L += ["", f"## Recording {key} — clip plan (slide {c['slide']}, video time {mmss(c['start'])}–{mmss(c['start'] + c['dur'])})", "",
          f"Source: {c['source']}.", "", "| Clip time | Content | Speed |", "|---|---|---|"]
    L += [f"| {a} | {b} | {s} |" for a, b, s in c["segments"]]
L += ["", "## Speed conventions", "",
      "- Model processing (‘Analysing your photo…’, typically 30–60 s per photo in these runs): **6–8×**, with the "
      "*PROCESS ACCELERATED* caption visible for the whole sped-up stretch.",
      "- Ordinary navigation and scrolling: **1.5–3×**.",
      "- Verdict reveals, the confirmation sheet, and any card the narration names: **1× (real time)**, readable for ≥2–3 s.",
      "- Never cut a model wait so that inference looks instant; the caption must say it was accelerated.", "",
      "## Audio", "",
      "- Narration only (record in a quiet room, phone 20 cm away, or the laptop mic with a headset). Normalise to about −16 LUFS.",
      "- Recordings muted. Optional: a quiet royalty-free music bed at −28 LUFS under slides 1–4 and 12–14 only.", "",
      "## Hard checks before upload", "",
      f"- Duration ≤ 2:58 (planned {mmss(TOTAL_S)}).",
      "- Slide 5 shows the ‘AI-generated test image’ disclosure; slide 8/10 never says ‘independently verified’.",
      "- The final card shows github.com/dakshvatss/proofcam for the full 8 s, and the repository is public.", ""]
(out / "DEMO_TIMELINE.md").write_text("\n".join(L), encoding="utf-8")


# ------------------------------------------------------------------------------------------------ SRT
def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


cues, idx = [], 1
for n, ttl, start, dur, narr, *_ in SLIDES:
    sentences = [x.strip() for x in re.split(r"(?<=[.?!])\s+", narr) if x.strip()]
    total = sum(words(x) for x in sentences) or 1
    t = start + 0.3
    span = dur - 0.6
    for sen in sentences:
        d = span * words(sen) / total
        cues.append(f"{idx}\n{srt_time(t)} --> {srt_time(t + d - 0.05)}\n{sen}\n")
        idx += 1
        t += d
(out / "ProofCam_Narration.srt").write_text("\n".join(cues), encoding="utf-8")
print("narration words:", total_words, "| cues:", idx - 1, "| total:", mmss(TOTAL_S))
