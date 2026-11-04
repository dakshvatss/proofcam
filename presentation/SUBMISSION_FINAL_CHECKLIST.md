# Submission final checklist: Meta Global AI Developer Hackathon (Cerebral Valley)

**Deadline (per the project brief): 4 Nov 2026, 21:00 ET**, which is **5 Nov 2026, 07:30 IST** (US clocks changed to
EST on 1 Nov). Confirm on the official event page; when this was written (5 Nov ≈ 01:00 IST) about 6.5 h remained.

Status: ✅ verified now · ⚠️ your action needed · ❓ your decision.

## 1. Repository (mandatory: public GitHub repo)
- ⚠️ **Make the repo public.** `https://api.github.com/repos/dakshvatss/proofcam` returned **404** on 5 Nov, so it is
  private or not at that URL. To fix: GitHub → repo → *Settings* → *General* → *Danger Zone* → *Change visibility*
  → *Public*. Then open the URL in a private browser window.
- ⚠️ **Commit and push the work shown in Recording B.** The latest pushed commit is `e7b6ef9` (4 Nov 22:32). The
  Jio set-top box spec (`ps5_home_setup_assisted.json` v2) and the written-attestation feature used in the VERIFIED
  run are **uncommitted**:
  - `backend/proofcam/`: agent.py, api.py, api_models.py, evidence.py, policy.py, report.py, service.py, spec.py
  - `data/specs/ps5_home_setup_assisted.json`, `docs/PROGRESS.md`
  - `frontend/src/`: api/types.ts, components/Dialogs.tsx, components/Evidence.tsx, components/InspectionView.tsx, lib/utils.ts
  - tests: test_m37_evidence.py, test_m38_assisted.py (modified); test_m39_source_device.py, test_m40_attestation.py,
    fixtures/assisted_router_spec.json, frontend `m40.test.tsx` (new)
  ```powershell
  cd C:\Users\Daksh\Documents\GitHub\proofcam
  git add backend data docs frontend
  git commit -m "Operator-assisted home inspection: Ethernet source device (router or set-top box), written attestations"
  git push
  ```
  All tests pass on this state (backend 499, frontend 57, verified 5 Nov 00:55 IST).
- ✅ **No secrets or databases are tracked.** `git ls-files` shows no `.env`, `*.db`, `var/` or private photos;
  `.gitignore` covers them.
- ❓ **Commit the presentation?**
  - `presentation/.gitignore` already keeps the raw home photos (`assets/photos/`), recordings and previews out of git.
  - The PPTX and PDF embed photos of your TV, PS5 and set-top box. They are in the public video anyway, but decide
    before running `git add presentation`.
- ⚠️ **Update the stale README status block.** It says 439/43 tests and "has not yet run on real hardware". Paste:
  > **Status (2026-11-05): working prototype; demo recorded with live Meta models.**
  > - **Automated checks:** 499 backend tests and 57 frontend tests pass (mocked models; 1 live test excluded by
  >   default), plus TypeScript, lint and the production build.
  > - **Live runs:** a VIOLATED inspection on AI-generated test photos (router → switch) and a VERIFIED —
  >   operator-attested inspection of real equipment (Jio set-top box, PlayStation 5, Samsung TV), both analysed by
  >   Muse Spark 1.3 and SAM 3.1.
  > - **No accuracy figures:** nothing here is a measured field accuracy.
  > - **Demo video:** <link>

## 2. Video (mandatory: three-minute demo)
- ⚠️ Recordings A and B are **not on this PC**. Import them (VIDEO_INSERTION_GUIDE.md §1).
- ⚠️ Trim and speed up, insert on slides 5 and 8, record the narration, then export
  (VIDEO_INSERTION_GUIDE.md §2–5).
- ✅ The export pipeline was test-run on 5 Nov.
  - A first test measured **3:06**, because PowerPoint adds the fades on top of the timers. Fixed: timers are now
    slot minus fade.
  - Re-test with the placeholder deck measured **2:56** (Windows file properties, 5 Nov).
  - The script `tools/export_video.ps1` also excludes the appendix and warns if over 2:58.
- ⚠️ The final MP4 must be **≤ 3:00**. Aim for ≤ 2:58.
- ⚠️ Upload to a host that plays without login (YouTube Unlisted or Public). Test the link in a private window.
- ✅ The disclosures are on screen: *AI-generated test image* (slide 5), *PROCESS ACCELERATED* (slides 5 and 8),
  *operator-attested* (slides 9 and 10), *vision, not deployments* (slide 12).

## 3. Submission form
- ❓ Track: **Indie Developer Track** (confirm it matches your registration).
- ✅ Problem statement: **Push the Frontier** (a machine gains a new capability: verifying a physical installation
  against a specification with active evidence gathering).
- ✅ Originality:
  - All 18 commits are dated 30 Oct – 4 Nov 2026, and the repository was created 30 Oct.
  - The appendix slide *What I built during the hackathon* separates own work from libraries and Meta's models.
- ✅ Meta tooling: Muse Spark 1.3 (structured observation + next-view planning) and SAM 3.1 (concept segmentation),
  via the Meta Model API. Runtime AI is Meta-only.
- ❓ **AI-assisted development.** The code was written with help from an AI coding assistant (Claude Code). If the
  rules or form ask, disclose it, for example: "Development used an AI coding assistant; all runtime AI is Meta Muse
  Spark 1.3 and SAM 3.1."
- ✅ Not affiliated with or endorsed by Meta (on the close slide and in the app).

## 4. Claims you must not make (in the form, video or Q&A)
- "Independently verified" or "proved end to end" for the VERIFIED run. It is **operator-attested**: both cable runs
  were declared, and the PS5 HDMI OUT end was attested in writing.
- Any accuracy percentage, benchmark win, customer, pilot or deployment.
- That SAM verified a cable's identity or connector type (it corroborates a region; the type is Muse's reading).
- That ProofCam certifies electrical safety, connectivity, signal or compliance.

## 5. Optional, if time allows (each needs your go-ahead; app changes were out of scope here)
- Fix the VERIFIED caption so it is assurance-aware: today "Proven by the photos." appears even under
  operator-attested verdicts (`frontend/src/lib/verdict.ts`). It is already visible in Recording B; fixing it only
  improves the repo.
- Add the video link and two screenshots from `presentation/previews/` to the README.

## 6. Suggested order for the remaining time (≈ 90 min of work)
| # | Step | Time |
|---|---|---|
| 1 | Commit + push; make the repo public; update the README | 15 min |
| 2 | Copy recordings to the PC; trim/speed in Clipchamp | 25 min |
| 3 | Insert the clips on slides 5 and 8; record the narration in PowerPoint | 25 min |
| 4 | `export_video.ps1`; watch once muted; upload; test the link logged-out | 15 min |
| 5 | Fill in the submission form (repo URL, video URL, track, description) | 10 min |
