# Demo runbook: live iPhone inspection and recording (Windows PowerShell)

Nothing here prints or stores secrets. The access code is typed into a hidden prompt (or read from `.env`); the Meta
API key stays in the repo-root `.env` on the laptop.

## 0. Before you start
- Laptop: plugged in, sleep set to **Never** (Settings → System → Power). Sleep stops the backend and the share.
- iPhone: Tailscale app **Connected** with the same account. Use a Safari tab, not a Home Screen app (that one needs
  the access code and camera permission again). Turn on Control Center **Screen Recording**.
- Spend: decide a call cap.
  - The Home Entertainment inspection may use up to 8 photos, about 4–6 calls each, but the per-inspection limit
    stops it at 40 calls.
  - A photo is refused unless at least 8 calls remain under the server cap.
  - Estimated cost is roughly $0.008–0.015 per call. Example: `-CallLimit 50` (at most ≈ $0.50–0.75).

## 1. Start the backend (terminal 1, LIVE)
```powershell
cd C:\Users\Daksh\Documents\GitHub\proofcam
powershell -ExecutionPolicy Bypass -File .\scripts\start-live.ps1 -Db var/live-demo.db -CallLimit 50
```
The script refuses a busy port 8000 or a missing or short access code. It binds 127.0.0.1 only, uses a separate
database, and prints the cap (never the code). Stop it with Ctrl+C.

## 2. Start the frontend (terminal 2)
```powershell
cd C:\Users\Daksh\Documents\GitHub\proofcam\frontend
npm run build
npm run preview          # http://127.0.0.1:4173, /api proxied to 127.0.0.1:8000
```

## 3. Share it privately (terminal 3)
```powershell
& "C:\Program Files\Tailscale\tailscale.exe" serve status
# If nothing is listed: & "C:\Program Files\Tailscale\tailscale.exe" serve --bg 4173
```
The URL shown (`https://<machine>.<tailnet>.ts.net`) works only for devices in your tailnet. Never run
`tailscale funnel`. Afterwards: `tailscale serve --https=443 off`.

## 4. Verify health and LIVE mode (laptop)
```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health        # status ok, model_source live
```
On the phone, the app bar must show **Live models · N of 50 calls left** (blue). If it says Mock or Replay, stop.

## 5. iPhone manual checklist
1. Open the tailnet URL, enter the access code, then tap **Continue**.
2. On the landing screen, choose **Home Entertainment Installation**. Check the three-device diagram and the two
   requirements.
3. Tap **Start inspection** (free; no model calls). Both connections should show **Pending**.
4. Tap **Open camera** and allow camera access. The rear camera is used.
5. Take an overview of the router, PS5 and TV, then tap **Analyse photo**. The analysing screen shows elapsed time.
6. Read the result card and the **Next view** card (real Muse guidance; it names the connection it is for).
7. Open the photo and toggle **Showing analysis overlay** (SAM masks and Muse boxes).
8. Follow the guidance for 1–3 more photos. Check the Ethernet and HDMI statuses in **Inspection summary**.
9. **Refresh test:** reload the page mid-inspection. The same inspection reloads from the server, with no new calls.
10. Tap **Report**. Check the overall verdict, the per-requirement photos, **Download** and **JSON**.
11. Stop conditions:
    - an error you don't understand;
    - the calls left are lower than expected;
    - the banner isn't Live.

## 6. Recording sequence (hackathon video)
1. Show the app bar with **Live models**, which proves this is not mock output.
2. Landing: the headline, then the three parts (Muse Spark, SAM, deterministic policy).
3. Select **Home Entertainment Installation**: the diagram and the two requirements. Then tap **Start inspection**.
4. Overview photo, then **Analyse photo**. Keep the waiting time, or cut it and say so.
5. The Next view card: read the instruction aloud, and point out that it names the connection.
6. The photo overlay: segmentation and Muse boxes, labelled "not proof".
7. Follow 1–2 instructions. Show the Ethernet and HDMI statuses changing independently.
8. Show the overall result, whatever it is. If it is **Not enough evidence**, show the missing facts: that is the
   product working honestly. Never re-shoot to force a verdict.
9. Report: the overall verdict, the photo-backed claims, the disclaimer, and Download.

## 7. If something goes wrong
| Symptom | Fix |
|---|---|
| Access screen keeps returning | Wrong backend on 8000, or the code changed; the cookie is per origin |
| "Server unreachable" | The backend isn't running; tap Try again |
| A capture times out | Don't re-shoot. The app checks the saved state and fetches the stored result (same idempotency key) |
| "spend cap reached" | The photo is kept; nothing was sent. Raise the cap only deliberately (new decision) |
| Camera blocked | aA → Website Settings → Camera → Allow |
