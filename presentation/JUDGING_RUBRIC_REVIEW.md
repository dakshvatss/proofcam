# Judging rubric review (strict self-review, no scores invented)

Reviewed against the official rubric: Impact 30 % · Use of Meta AI tooling 25 % · Technical depth and execution 20 %
· Demo 25 %. Every claim in the deck was checked against the repository or the two recorded inspections (section 5).
The review led to concrete revisions (section 4). Prizes and scores are not predictable and none are claimed.

## 1. Category by category

### Impact (30 %)
- **Strongest evidence:**
  - Slides 2–3 frame a general problem: photos and checklists versus requirements actually being proven.
  - Slide 12 shows one abstraction (requirement → evidence → verification → audit trail) across five infrastructure
    domains.
  - Slide 13 lands the "explain why it was trusted" question.
  - The demo shows both outcomes judges care about, *reject* and *verify with disclosed human input*, on a real home
    setup.
- **Weak points:**
  - The working scope is cable connections between devices.
  - The bigger markets are vision only, with no pilots, users or measurements, and the deck says so.
  - Recording A uses synthetic images.
- **Mitigation:**
  - Slide 12 carries a visible *potential applications, not current deployments* tag.
  - Slide 4 and the VERIFIED demo use real equipment.
  - The narration says "could".

### Use of Meta AI tooling (25 %)
- **Strongest evidence:**
  - Slide 7 shows three layers with distinct jobs: Muse Spark plans and reasons, SAM 3.1 grounds independently, and
    the policy decides.
  - A real stored overlay shows SAM masks next to Muse boxes.
  - Real request texts on slide 6 show Muse Spark planning the next camera view (nv1), not only describing images.
  - Real numbers: 22 calls in a 4-photo run (8 Muse, 14 SAM).
- **What may genuinely surprise judges:**
  - Muse is used twice per photo (structured extraction plus view planning).
  - SAM is an *independent check*, not decoration.
  - The system reports when SAM *disagrees* (slide 8: "HDMI OUT: Muse only").
- **Weak point:** SAM's specific `hdmi cable` concept found nothing in 12/12 recorded photos. Two of the three
  photo-established ends in Recording B rely on the generic `cable` fallback.
- **Mitigation:** this is shown openly ("generic 'cable' mask" on slides 8 and 10; appendix 17). It turns into a
  credibility point: the system knows the limits of its grounding.

### Technical depth and execution (20 %)
- **Strongest evidence:**
  - Slide 11 architecture: schema-validated outputs, policy-only verdicts, append-only SQLite evidence, call budget
    reserved before every request, idempotent and resumable captures.
  - 499 + 57 tests, re-run on 5 Nov.
  - The appendix covers the evidence model and limits.
  - Slide 10 shows a real, time-stamped report.
- **Weak point:** judges cannot see code in the video.
- **Mitigation:** the public repository plus the architecture slide; slide 11's notes give exact facts. Tests are
  described as regression tests, not accuracy benchmarks.

### Demo (25 %)
- **Strongest evidence:**
  - Two real live recordings with opposite outcomes.
  - Real UI crops support each recording, so the story survives muted viewing and small screens.
  - The verdict cards are legible at 1080p.
- **Weak point:** portrait phone footage occupies about 23 % of a 16:9 frame, so small UI text in the recording can
  be hard to read.
- **Mitigation:**
  - Side panels repeat the key facts using real crops.
  - VIDEO_INSERTION_GUIDE.md recommends a Clipchamp zoom on the verdict card during its 1× hold.
  - Hidden landscape alternates exist.

## 2. Stress tests
| Question | Answer |
|---|---|
| Impact: does it matter beyond a home setup? | **Yes, as a credible direction**: slide 12 abstracts the loop. **No proof yet** of value in those settings; the deck says so |
| Meta tooling: are Muse and SAM central, not superficial? | **Yes**: removing either breaks the verdict path (SAM corroboration is required for photo evidence; Muse produces every claim and plans views). Shown on slides 6–8 with real outputs |
| Technical depth: real engineering and uncertainty handling? | **Yes**: INSUFFICIENT EVIDENCE, contradictions, Muse-only candidates, assurance levels, budgets, persistence; all in code and tests |
| Demo: understandable with the sound muted? | **Yes**: every slide has a one-line on-screen claim; demo slides carry real verdict crops and explicit captions; the SRT file provides subtitles |

## 3. Risks still open (action needed: see SUBMISSION_FINAL_CHECKLIST.md)
1. **The repository is not public.** `api.github.com/repos/dakshvatss/proofcam` returned 404 on 5 Nov. A public repo
   is mandatory.
2. **The code shown in Recording B is not on GitHub.** The assisted-template, set-top box and attestation changes are
   uncommitted.
3. **App copy contradiction (visible in the recording and in slide 9's crop):**
   - The VERIFIED caption reads "Proven by the photos." even when the assurance line below says operator-assisted or
     operator-attested.
   - A judge may notice. The one-line fix is in `frontend/src/lib/verdict.ts`. It was not applied, because this task
     excluded app changes.
4. **Thin attestation note.** The PS5 HDMI OUT attestation reads only "It's correct" (shown verbatim on slide 9 and
   in the report). This is honest, and it illustrates the point that ProofCam records statements and does not judge
   them. Be ready to say so.
5. **Synthetic Recording A.** It is disclosed on screen and in the narration. Do not cut the disclosure.
6. **README is stale.** It says 439/43 tests and "not yet run on real hardware". Paste-ready replacement text is in
   the checklist.

## 4. Revisions made during this review
- Slide 10 and the narration say **VERIFIED — OPERATOR-ATTESTED**. The brief asked for "operator-assisted", but the
  recorded run's overall label is *operator-attested* (R2's PS5 HDMI OUT end rests on a written attestation).
- Slide 3: the cable row was corrected to "in no photo · gap stays open". No continuity request was ever issued for
  R1; you declared it first.
- Slide 6: "not traceable in one photo" was replaced by "no such photo was taken", since we never observed whether
  it was traceable.
- Slide 8: "no ports visible" was replaced by "set-top box ports not visible", because Muse did see PS5 ports
  partially in photo 1.
- Slide 5: the synthetic-image tag is large and amber, not a footnote.
- Slide 12: a vision tag was added. Slide 11: tests are labelled "regression, not accuracy".
- Video length: a test export measured 3:06 (PowerPoint adds the fades on top of the slide timers). The timers now
  equal slot minus fade (planned 2:55); the re-test result is in the checklist.

## 5. Claims audit
| On-screen claim | Slide | Source | Status |
|---|---|---|---|
| Labels on the PS5 photo (LAN: SAM ✓; HDMI OUT: no SAM) | 1 | port links of photo 4, insp_92cc… | verified |
| Set-top box end photo 2, PS5 LAN photo 4 (Muse + SAM) | 3, 9, 10 | assessment R1 support items | verified |
| VIOLATED: LAN 1 clearly empty; 3 synthetic photos; 5 calls | 5 | insp_f1bb… record + re-assessment | verified |
| nv1 planned by Muse Spark; nv5 fixed template | 6 | `next_view_requests` (planner field) | verified |
| 22 calls: 8 Muse, 14 SAM; ≈ $0.13 | 7, 8, 10 | trace summary (list-price estimate) | verified |
| Photos 2–4 were requested views | 8 | `responding_to` = nv1, nv2, nv3 | verified |
| Two ends via generic `cable` mask | 8, 10 | port_links concept = `cable` | verified |
| 3 statements at 00:13:49 / 00:14:10 / 00:14:19 | 9, 10 | `declarations` | verified |
| R1 operator-assisted; R2 and overall operator-attested | 9, 10 | `assurance` fields | verified |
| 499 + 57 tests | 11 | pytest + vitest, 5 Nov 2026 | verified |
| ≈ 6,300 / 4,100 lines; built 30 Oct – 4 Nov | 11, 15 | `wc -l`; `git log` | verified |
| Installable PWA | 4, 11 | `frontend/public/manifest.webmanifest`, `sw.js` | verified |
| Data centres, telecom… | 12 | none: vision | labelled as vision |

## 6. Likely judge questions, honest answers
- **"Why not just ask Muse Spark if the cable is connected?"** A model's "yes" isn't evidence. Each claim must be
  grounded by SAM at the port, and the verdict is computed by a deterministic policy over all photos. Recording B
  shows a case where Muse saw a plug and SAM didn't agree, so it wasn't counted.
- **"How accurate is it?"** Not measured yet. The tests cover policy behaviour with mocked models; no field accuracy
  study exists.
- **"Isn't operator attestation a loophole?"** It's opt-in per specification, refused when a photo contradicts it,
  recorded verbatim with a time, and the verdict changes its label to *operator-attested*. It makes the trust boundary
  visible instead of hiding it.
- **"What did you build versus Meta?"** Meta provides the two models via the Meta Model API. Everything else is in
  this repository, built 30 Oct – 4 Nov: the agent loop, the policy, grounding, persistence, the PWA, reports and
  tests.
- **"Why is Recording A synthetic?"** It was a controlled wrong-port test case that was easy to stage safely. The
  VERIFIED run used real equipment.
