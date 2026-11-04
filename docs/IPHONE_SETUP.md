# Testing ProofCam on an iPhone (private HTTPS via Tailscale)

Goal: open ProofCam in Safari on your iPhone with a working camera, served from your Windows laptop, **without**
putting the backend on the public internet. Status: prepared and tested locally on Windows; **not yet tested on the
iPhone** (needs the approvals in step 0).

## Why this approach
- iPhone Safari only allows the camera on HTTPS pages (or localhost). A plain `http://<laptop-ip>:5173` page cannot
  use the camera.
- **Tailscale Serve** gives your laptop a real HTTPS name (`https://<machine>.<tailnet>.ts.net`, Let's Encrypt
  certificate) that only devices signed in to *your* tailnet can reach. It is not a public tunnel (that is
  "Funnel", which we do not use). No Mac, Xcode, root-certificate profile or router change is needed.
- Rejected: public tunnels (ngrok, Cloudflare quick tunnels, Tailscale Funnel) expose the server to everyone;
  a self-signed/mkcert certificate on the LAN needs a root CA profile installed on the iPhone and exposes the server
  to the whole Wi-Fi network.

How the pieces connect (everything listens on 127.0.0.1 only):
```
iPhone Safari --HTTPS (tailnet only)--> tailscale serve on laptop --> vite preview 127.0.0.1:4173
                                                                       └─ /api proxy --> FastAPI 127.0.0.1:8000
```
Layers of protection: tailnet membership → ProofCam access code (HttpOnly session cookie) → server-wide model-call
cap. The Meta API key stays in the laptop's `.env`; the browser never receives it.

## 0. Needs your approval (not done yet)
| Step | What it changes |
|---|---|
| Install Tailscale for Windows (`winget install --id Tailscale.Tailscale -e`, or the installer from tailscale.com/download) | System software + a VPN network adapter; UAC prompt |
| Sign in to Tailscale (Google/Microsoft/GitHub/Apple account) | Creates a tailnet in your name |
| Install the Tailscale app on the iPhone (App Store) and sign in with the **same** account | iOS VPN profile |
| Admin console → DNS (login.tailscale.com/admin/dns): enable **MagicDNS** and **HTTPS Certificates** | Tailnet setting. Warning: certificates are logged publicly (Certificate Transparency), so the laptop's machine name becomes public. Rename it first to something neutral (e.g. `proofcam-dev`) in the admin console → Machines |

Optional hardening: in the admin console Access controls, do not grant the `funnel` node attribute (Funnel then
cannot be enabled by mistake).

## 1. Choose an access code (once)
```powershell
cd backend
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(18))"
```
Put it in the repo-root `.env` (git-ignored; server-side only):
```
PROOFCAM_ACCESS_CODE=<the printed code>
```
Keep it somewhere you can type it on the phone (a password manager). Without an access code the backend refuses
every request that is not made directly on the laptop (HTTP 403 `remote_access_requires_auth`).

## 2. Start the backend (terminal 1)
**Mock models (free; recommended first):**
```powershell
cd backend
$env:PROOFCAM_ACCESS_CODE = "<code>"      # the mock server reads the environment, not .env
.venv\Scripts\python.exe experiments\dev_mock_server.py --scenario verify
```
**Real models (paid; only after you approve a live test, see section 6):**
```powershell
cd backend
$env:PROOFCAM_GLOBAL_CALL_LIMIT = "30"            # hard cap on paid calls across ALL inspections in this DB
$env:PROOFCAM_DB_PATH = "var/live-phone.db"        # fresh database = fresh cap accounting
$env:PROOFCAM_MUSE_REASONING_EFFORT = "low"        # ~2x faster per photo (same verdicts on the reference set)
.venv\Scripts\python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --host 127.0.0.1 --port 8000
```
(`PROOFCAM_ACCESS_CODE` comes from `.env`.) Only one server can use port 8000: stop any other backend first.

## 3. Build and serve the frontend (terminal 2)
```powershell
cd frontend
npm run build
npm run preview          # http://127.0.0.1:4173 (production build + service worker; /api proxied to :8000)
```
Check on the laptop first: open http://127.0.0.1:4173 in Chrome, enter the code, start an inspection.

## 4. Share it on your tailnet (terminal 3; after step 0)
```powershell
tailscale serve --bg 4173
tailscale serve status        # shows https://<machine>.<tailnet>.ts.net -> http://127.0.0.1:4173
```
Stop sharing when you are done: `tailscale serve --https=443 off` (or `tailscale serve reset`).
Never run `tailscale funnel`.

## 5. On the iPhone 16
1. Open the Tailscale app → make sure it is **Connected**.
2. Safari → `https://<machine>.<tailnet>.ts.net` (from `tailscale serve status`).
3. Enter the access code → **Start Inspection**.
4. **Open camera** → Safari asks for camera access → **Allow**. The rear camera is used by default.
   If you denied it: tap **aA** in the address bar → Website Settings → Camera → Allow.
5. Capture → **Analyse photo**. The banner says **Mock models** (purple) or **Live models** (amber, with the calls left).
6. Add to Home Screen: Share → **Add to Home Screen**. The home-screen app has its own storage, so enter the access
   code again there, and allow the camera again when asked. If denied there: Settings → Apps → Safari → Camera.

Please report back: camera opens (rear), capture works, upload from Photos works, overlay shows, guidance shows,
the app survives locking the phone mid-analysis (it should reload the saved result), Add to Home Screen works.

## 6. Controlled live-model test (needs separate approval)
**Superseded for M3.3 by [LIVE_TEST_M33.md](LIVE_TEST_M33.md):** `scripts/start-live.ps1`, cap 20,
`var/live-m33.db`. The original proposal follows.

Proposed: real Muse Spark 1.3 + SAM 3.1 from the iPhone, `PROOFCAM_GLOBAL_CALL_LIMIT=30`, fresh DB, reasoning
`low`. One photo ≈ 4–6 calls ≈ $0.03–0.05 (M1 smoke test: 4 calls, $0.035), so the cap allows ~5 photos and at most
≈ $0.30. The cap is enforced in the database before every HTTP attempt (retries included); when fewer than 8 calls
remain, new photos are refused with nothing sent. Idempotency keys + the saved-state check prevent duplicate paid
steps when a phone connection drops.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| "Blocked request. This host is not allowed" | Vite host check: `.ts.net` is allowed in `vite.config.ts`; restart `npm run preview` after pulling |
| 403 `remote_access_requires_auth` | No access code configured on the backend you started |
| Access screen keeps reappearing | Wrong backend (port 8000 used by another process) or the code changed; cookies are per origin and per home-screen app |
| Camera button disabled, "needs a secure page" | Opened over http:// — use the `https://…ts.net` address |
| Page loads but every action fails | Backend not running on 127.0.0.1:8000 |
| Analysis interrupted when the phone locked | Reopen the app: it checks the saved state and fetches the stored result (no new paid call) |
