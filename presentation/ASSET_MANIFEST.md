# Asset manifest: every visual in the deck and where it came from

**Principles:**
- No stock footage, no AI-generated decoration, and no invented screenshots.
- Product visuals are either real app captures or real stored model output.
- The one synthetic image (a test input) is labelled on its slide.
- Diagrams, text and placeholders are native, editable PowerPoint shapes.

## A. Source inspections (read-only; databases were copied, never modified)
| Id | Database | What it is | Photos | Result |
|---|---|---|---|---|
| **Recording A run**: `insp_f1bb0d48…` | `var/live-m33.db` | Spec `router_switch` (*Router LAN 1 → Switch Port 3, blue cable*), 4 Nov 2026 19:18 IST | 3 **AI-generated test images** (IMG_6171–6173, 492×440), as stated by the author | **VIOLATED** (LAN 1 legibly and clearly empty). Re-assessed with today's policy: still VIOLATED |
| **Recording B run**: `insp_92cc5136…` | `var/live-final.db` | Spec `ps5_home_setup_assisted` (operator-assisted template), 5 Nov 2026 00:09 IST | 4 photos of **physical equipment**: the author's Jio set-top box, PS5 and Samsung TV | **VERIFIED, operator-attested** (R1 operator-assisted, R2 operator-attested), 22 live calls (8 Muse Spark 1.3, 14 SAM 3.1), est. $0.128 |

Physical vs synthetic was judged by the author's statements and by inspecting the images:
- **Recording B:** a real room and wall socket, a hand holding the box, the TV's rear label.
- **Recording A:** clearly rendered.

## B. Files in `assets/`
| File | Used on | Provenance |
|---|---|---|
| `photos/B4_photo.jpg` | 1, 2, 8 | Real photo 4 of insp_92cc… (PS5 rear) as stored by ProofCam. The slide 1 boxes use Muse's **recorded** port boxes for this photo |
| `photos/B1_photo.jpg` | 2, 3, 8 | Real photo 1 (overview). Slide 3 overlays **illustrative** object labels, captioned as such |
| `photos/B2_photo.jpg` | 2, 8 | Real photo 2 (set-top box rear, hand-held) |
| `photos/B3_photo.jpg` | 8 (thumbnail) | Real photo 3 (TV connection panel). The TV's rear label is **not** legible at thumbnail size |
| `photos/B4_overlay.jpg` | 7 | ProofCam's **stored analysis overlay** for photo 4 (SAM 3.1 masks + Muse Spark boxes), drawn at capture time |
| `photos/A3_overlay.jpg` | 5 | Stored overlay of photo 3 of insp_f1bb…, an **AI-generated test image**. Labelled *AI-GENERATED TEST IMAGE* on the slide |
| `photos/*` (others) | not used | Remaining photos and overlays of both runs, kept for editing |
| `ui/landing_phone_screen.png` | 4 | Real app (current build), start screen |
| `ui/B_phone_screen.png` | 4 | Real app showing the stored insp_92cc… (installation summary + R1 card) |
| `ui/A_violated_card.png` | 5 | Real app, R1 verdict card of insp_f1bb… (see note 1) |
| `ui/B_R2_card.png` | 9 | Real app, R2 card of insp_92cc… (operator-attested; statements listed verbatim) |
| `ui/B_installation.png` | 10 | Real app, installation summary of insp_92cc… (*Verified — operator-attested*) |
| `ui/B_R1_card.png`, `ui/B_R1_statements.png`, `ui/A_header.png` | not used | Spare crops |
| `icons/*.png` | 2–4, 6–9, 11–14 | Lucide icons (ISC licence; `lucide-react` is already a ProofCam dependency), rendered by `tools/icons.mjs` |

**How the UI captures were made:**
- `tools/build_assets.py` takes headless-Chrome captures of the real ProofCam frontend build.
- That build was served by the real FastAPI app over **copies** of the two databases.
- The settings held a dummy key, and every read path used the service's read-only transport, so **no model call
  was possible**.
- Captures were taken at a 500-CSS-px phone layout at 3×. Crops only; no pixels were edited.
- The app bar reads *Live models* because the stored inspections were produced live.

**Note 1:** in the app, the VIOLATED card of this older run sits under a notice: *"recorded by an earlier version of
the verification engine … the current rules would assess R1 differently"*.
- The crop on slide 5 omits that notice.
- The notice is caused by new metadata fields (assurance) that older records lack.
- Re-running today's policy on the same stored evidence gives the **same VIOLATED verdict** (verified on 5 Nov 2026).

## C. Text quoted from the real runs
| Where | Quote | Source |
|---|---|---|
| Slide 6 | nv1: *"Walk around to behind the blue table and photograph the rear panel of the dark set-top box on the left…"* (Muse Spark 1.3) | `next_view_requests` of insp_92cc… |
| Slide 6 | nv5: *"Step back so one photo shows the hdmi cable run between both endpoints, from one device to the other…"* (fixed template) | same |
| Slide 10 | Condensed lines of the generated Markdown report: verdict labels, supporting photos, provenance, statement times 00:13:49 / 00:14:10 / 00:14:19 | `GET /api/inspections/insp_92cc…/report?format=md` |
| Slide 9 (UI crop) | The attestation note *"It's correct"*, shown verbatim | operator declaration od2 |

## D. Numbers on slides
| Number | Source (checked 5 Nov 2026) |
|---|---|
| 22 calls (8 Muse, 14 SAM), ≈ $0.13 | trace summary of insp_92cc… |
| 5 calls, 3 photos (Recording A) | trace summary of insp_f1bb… |
| 499 backend + 57 frontend tests | `pytest -q`: 499 passed, 1 deselected; `vitest run`: 57 passed |
| ≈ 6,300 / ≈ 4,100 lines | `wc -l backend/proofcam/*.py` (6,277); `frontend/src` TS/TSX (4,088) |
| 18 commits, 30 Oct – 4 Nov 2026 | `git log` |

## E. Not included, on purpose
- No stock photos for slide 12: tasteful line icons stand in for the vision, and the slide is labelled *potential
  applications, not current deployments*.
- No Meta logos or brand imagery: attribution is text only ("Built with Meta Muse Spark 1.3 and SAM 3.1"), and the
  close says the project is not affiliated with or endorsed by Meta.
