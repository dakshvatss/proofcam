# Video insertion guide: from the deck + two recordings to a sub-3-minute MP4

No recordings were found on this PC (repo, Desktop, Downloads, Videos, Pictures checked on 5 Nov 2026), so the deck
contains **clearly labelled placeholders**. Nothing in the deck is fake footage.

| Slide | Placeholder (Home → Arrange → Selection Pane) | Recording | Clip length | Slide timing |
|---|---|---|---|---|
| 5 | `VIDEO PLACEHOLDER · RECORDING A` | A: the VIOLATED router → switch run (AI-generated test photos) | ≈ 20 s | 20 s |
| 8 | `VIDEO PLACEHOLDER · RECORDING B` | B: the real Jio set-top box / PS5 / TV run, photos 1 → 4 | ≈ 25 s | 25 s |
| 18, 19 (hidden) | `VIDEO PLACEHOLDER 16:9 · …` | only if a recording is **landscape** | same | same |

The placeholders are portrait phone frames, sized for iPhone screen recordings (≈ 9:19.5). Screen area on slides 5
and 8: **left 0.83 in, top 0.53 in, width 2.90 in, height 6.45 in**.

## 1. Get the recordings onto this PC (≈ 5 min)
- **USB (best quality):** connect the iPhone, tap *Trust*, open the Windows **Photos** app → *Import* → *From a
  connected device* → pick the two screen recordings.
- **Or iCloud:** icloud.com/photos → select → *Download* (choose *Unmodified Original*).
- Avoid WhatsApp or e-mail: they recompress and blur the small text.
- Save them as `presentation\media\RecordingA.mp4` and `RecordingB.mp4`. The folder is git-ignored.

## 2. Trim and speed up (Clipchamp, built into Windows 11, ≈ 10 min per clip)
PowerPoint cannot change playback speed, so do this first.
1. Clipchamp → *Create a new video* → *Import media* → drag the recording onto the timeline.
2. Drag the clip's ends to trim. Move the playhead to each boundary in the plan below and press **S** to split.
3. Select each *Analysing your photo…* segment → **Speed** (right panel) → **6×–8×**.
4. Keep these at **1×**: the verdict reveal, any card the narration names, and the confirmation sheet.
5. *Export* → **1080p** → `RecordingA_edit.mp4` (≈ 20 s) and `RecordingB_edit.mp4` (≈ 25 s).

| Recording A (target 20 s) | Speed |
|---|---|
| Requirement / inspection header | 1.5–2× |
| Photos 1–3 uploaded and analysed | 6–8× |
| Violated card: *Router LAN 1 · clearly wrong* | 1×, hold ≥ 3 s |
| *Clearly observed … LAN 1 … target port is empty* (or the photo 3 overlay) | 1× |

| Recording B part 1 (target 25 s) | Speed |
|---|---|
| Overview photo → first *Next view* card | waits 6–8×, card 1× (≥ 2 s) |
| Set-top box rear → result card | waits 6–8×, result 1.5× |
| TV panel → result card | waits 6–8×, result 1.5× |
| PS5 rear → result; connection rows (*LAN ✓*, *HDMI OUT seen by Muse only*) | waits 6–8×, rows 1× |

The slides already carry an amber **PROCESS ACCELERATED** pill above each video. Keep it in front of the video
(*Arrange → Bring to Front*) so viewers always know the model waits were sped up.

## 3. Insert into the deck (≈ 3 min per slide)
1. Open `ProofCam_Meta_Global_AI_Hackathon.pptx` and go to slide **5**.
2. *Insert → Video → This Device…* → `RecordingA_edit.mp4`.
3. Right-click the video → *Size and Position*: tick *Lock aspect ratio*; height **6.45 in**; position **left 0.83 in,
   top 0.53 in**.
4. In the Selection Pane, delete `VIDEO PLACEHOLDER · RECORDING A` (the dashed frame) and
   `VIDEO PLACEHOLDER LABEL · RECORDING A`. Keep `PHONE FRAME · RECORDING A · bezel` and the `CAPTION · PROCESS ACCELERATED` pill, and bring
   the pill to front.
5. *Playback* tab: **Start: Automatically**, **Volume: Mute**. If needed, *Trim Video* to exactly 20 s.
6. *Transitions* tab → *After*: **00:19.50**. This is already set: the 20 s slot minus the 0.5 s fade, which PowerPoint plays on top. Adjust only if your clip is shorter.
7. Repeat on slide **8** with `RecordingB_edit.mp4` (After: **00:24.50**).

If a recording is **landscape**, use the hidden alternates: unhide slide 18 or 19, insert the clip there, and hide
slide 5 or 8.

## 4. Record the narration (≈ 10 min)
**Option A, all in PowerPoint (recommended):**
1. *Slide Show → Record → From Beginning*.
2. Read `NARRATION_SCRIPT.md`; the notes pane shows each slide's lines.
3. Advance when the line ends. On slides 5 and 8, wait until the clip finishes.
4. Keep the total under **2:58**. The planned total is 2:55.

**Option B, separate voice track:**
1. Record a voice memo following `NARRATION_SCRIPT.md` timings.
2. Export the deck silently (step 5).
3. Lay the voice track over it in Clipchamp.

## 5. Export the MP4 (5–10 min, unattended)
- **Scripted:** `cd presentation\tools` then
  `.\export_video.ps1 -Pptx ..\ProofCam_Meta_Global_AI_Hackathon.pptx -Out ..\ProofCam_Final_Demo.mp4`.
  It exports 1080p, uses your slide timings and narration, and excludes the appendix (slides 15+). It warns if
  placeholders remain or the length exceeds 2:58. This script was test-run on 5 Nov 2026.
- **Or by hand:** first hide slides 15–17 (right-click → *Hide Slide*; 18–19 are already hidden). Then
  *File → Export → Create a Video → Full HD (1080p) → Use Recorded Timings and Narrations*.

## 6. Upload and check
1. Upload to YouTube (Unlisted or Public) or another host whose link works logged-out.
2. If you read the script verbatim, add `ProofCam_Narration.srt` as captions.
3. Watch the upload once, muted. The captions on the slides should still tell the story.
4. Check that slide 5 shows *AI-generated test image* and that slide 10 says **operator-attested**.

| Problem | Fix |
|---|---|
| PowerPoint: *cannot play media* | Re-export the clip from Clipchamp as MP4 (H.264) |
| Small UI text unreadable | In Clipchamp, crop or zoom (*Crop* / *Transform*) onto the verdict card for its 1× hold |
| Video longer than 3:00 | Shorten Recording B's waits (8×) or trim slide timings on 12–14 |
