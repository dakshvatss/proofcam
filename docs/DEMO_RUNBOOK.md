# Demo runbook: final live iPhone inspection and recording (Windows PowerShell)

Nothing here prints or stores secrets. The access code is typed into a hidden prompt (or read from `.env`); the Meta
API key stays in the repo-root `.env` on the laptop.

## 0. Before you start
- **Restart any running backend.** A server started before M3.7 still runs the old engine; stop it (Ctrl+C) first.
- Laptop: plugged in, sleep **Never** (Settings → System → Power). The laptop's own internet carries the Meta calls.
- iPhone: Tailscale **Connected** (same account), a Safari tab (not a Home Screen app), Control Center **Screen
  Recording** on.
- **Physical setup check (from the recorded Report B photos):**
  - In the iPhone photos 5–7 Muse reported the PS5's LAN socket **empty**, with a clear view. If the Ethernet cable is
    meant to be connected, seat it in the PS5 LAN port now, before the first photo.
  - Confirm the HDMI cable runs from PS5 HDMI OUT to a TV HDMI input. Moving anything mid-inspection requires
    "I changed the installation…", after which earlier photos stop counting.
- **Never mix synthetic images into the recorded inspection.** Mixed photos produced the PS5 LAN contradiction in
  Report B. Run any synthetic evaluation on its **own database**, and say in the video that it is synthetic.
- **Spend (needs your explicit approval).**
  - Today's live runs cost about **$0.005–0.006 per call** (Report A $0.031 / 5 calls; Report B $0.198 / 39 calls).
  - The Home inspection now allows 12 photos at about 4–5 calls each.
  - Proposed: per-inspection limit **70** and global cap **80** on a **new** database. Worst case 80 calls ≈ $0.50
    (budget up to $0.80 for safety).
  - A photo is refused unless 8 calls remain under the global cap. The app turns the camera off when the inspection
    has fewer than 2 left.

## 1. Start the backend (terminal 1, LIVE, new database)
```powershell
cd C:\Users\Daksh\Documents\GitHub\proofcam
powershell -ExecutionPolicy Bypass -File .\scripts\start-live.ps1 -Db var/live-final.db -CallLimit 80 -InspectionCallLimit 70
```
The banner must show `database var/live-final.db (calls already used: 0)`, `global cap 80` and `per new inspection
70 calls`. The script binds 127.0.0.1 only and refuses a busy port or a short access code. Existing databases are
untouched (`var/live-m33.db` keeps Reports A and B).

## 2. Start the frontend (terminal 2)
```powershell
cd C:\Users\Daksh\Documents\GitHub\proofcam\frontend
npm run build
npm run preview          # http://127.0.0.1:4173, /api proxied to 127.0.0.1:8000
```
If `npm` is not found in this terminal: `$env:Path = "C:\Program Files\nodejs;$env:Path"`.

## 3. Share it privately (terminal 3)
```powershell
& "C:\Program Files\Tailscale\tailscale.exe" serve status
# If nothing is listed: & "C:\Program Files\Tailscale\tailscale.exe" serve --bg 4173
```
Tailnet only. Never run `tailscale funnel`. Afterwards: `tailscale serve --https=443 off`.

## 4. Verify health and LIVE mode
```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health        # status ok, model_source live
```
On the phone the app bar must show **Live models · 80 of 80 calls left**. If it says Mock or Replay, stop.

## 5. Choose the specification (decide before recording)
| Template on the landing screen | What it can conclude |
|---|---|
| **Home Entertainment Installation** (strict) | Photos only. Cable identity needs ONE photo tracing each cable between two identified ports, so the most likely honest result is **Not enough evidence** |
| **Home Entertainment · operator-assisted** | Same evidence rules, plus two statements you may make after the photos: "Photo N shows the Samsung Television" (only for a photo where Muse saw a TV but was unsure) and "It is one cable: I checked" (only once both ends are confirmed by photos). A verdict that uses them is shown as **Relies on your statements: not independently verified** |

Recommended for the video: **operator-assisted**. It shows what the models proved, what SAM could not corroborate,
and what rests on you, and keeps them separate. Only use a statement after checking it physically.

## 6a. Short demonstration (operator-assisted template, about 5–7 photos)
1. **Overview** of router, PS5 and TV from the front (device identity context).
2. **Router rear**, close and straight on: the plug in a `LAN n` socket with the label readable.
3. **PS5 rear**: one photo showing BOTH the Ethernet plug (LAN) and the HDMI plug (HDMI OUT). It can establish both
   PS5 ends at once.
4. **TV HDMI panel** at an angle that also shows the TV's body or logo, with the `HDMI n` label readable.
5. **Whatever the Next view card asks** (one request per missing fact, no re-framing loops).
6. Then, only for what you have physically checked, use the buttons the app offers under "Missing evidence":
   - **The plug is seated: I checked** (when SAM missed a plug Muse saw clearly);
   - **Photo N shows the Samsung Television**;
   - **It is one cable: I checked**, for each connection.
7. Optional: one wide photo from behind the desk, if a cable run is fully visible. A real trace beats a statement.

Expected result if everything is connected: **Verified — operator-assisted**, with the statements listed. If a
photo shows a port empty, the statement buttons are refused: that is correct.

## 6. Shot plan (adaptive: always follow the actual Next view card after each photo)
1. **Overview**: router, PS5 and TV together from the front. Expect "ports not visible" guidance.
2. **Deliberately incomplete view**: the router's back from a steep angle or far away. Expect "port label not
   readable" or "ports not visible", and a precise Next view. This shows the guidance working.
3. **Router rear LAN port**: close and straight on, so the printed `LAN n` beside the plug is readable.
4. **PS5 LAN**: the PS5's rear, with the Ethernet plug in its LAN socket in focus.
5. **PS5 HDMI OUT**: from 20–30 cm, the plug body plus a long stretch of the black cable against a plain background.
   If SAM still cannot corroborate it, the card says "seen by Muse only" and the guidance moves on after one retry.
6. **TV HDMI input**: one angled photo showing the TV's body or logo **and** the HDMI panel, with the `HDMI n` label
   readable. If the TV is "not identified with certainty", take the one requested identity view. Then, only on the
   assisted template and only if true, tap **Photo N shows the Samsung Television…**.
7. **Cable continuity**: one wide photo from behind the table where each cable can be followed from port to port. If
   that is impossible (hidden run), the assisted template offers **It is one cable: I checked…** once both ends are
   confirmed.
8. **Further requested views** until the inspection stops or you choose to end. Watch the "Approaching this
   inspection's limits" banner.

Do not guarantee or chase a verdict. **Not enough evidence** with its missing facts is a correct result. Never
re-shoot to force a different one.

## 7. Recording sequence (hackathon video)
1. App bar **Live models**, which proves this is not mock output. Mention that the laptop runs the server.
2. Landing: headline, the three parts (Muse Spark, SAM, deterministic policy), then the chosen template.
3. **Start inspection**, then the overview photo and **Analyse photo**. Keep the wait, or cut it and say so.
4. Next view card: read it aloud; point out that it names the connection.
5. Photo overlay: SAM masks and Muse boxes, labelled "not proof".
6. Per connection: endpoint rows ("seen by Muse · grounded by SAM", "seen by Muse only"), the cable row, and any
   **Photos disagree** review card.
7. If you make a statement: show the confirmation sheet, then the blue **Relies on your statements** block.
8. Final result, whatever it is, then **Report**: overall verdict, "Rests on …" line, photos per claim, the
   statements section, the models called, the disclaimer, **Download**.

## 8. If something goes wrong
| Symptom | Fix |
|---|---|
| Access screen keeps returning | Wrong backend on 8000, or the code changed; the cookie is per origin |
| "Server unreachable" | The backend isn't running; tap Try again |
| A capture times out | Don't re-shoot. The app checks the saved state and fetches the stored result (same idempotency key) |
| "spend cap reached" | The photo is kept and nothing was sent. Raise the cap only deliberately (new decision) |
| "Model-call limit reached" banner | The inspection's own limit; the verdicts stand. Open the report |
| "Review the installation" | Photos contradict each other. Check in person; a new photo of the same setup cannot fix it |
| Camera blocked | aA → Website Settings → Camera → Allow |
