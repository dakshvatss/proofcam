# ProofCam frontend (Milestone 3.1)

Mobile-first React + TypeScript + Vite + Tailwind CSS app for the ProofCam HTTP API. API contract:
[../docs/FRONTEND_HANDOFF.md](../docs/FRONTEND_HANDOFF.md). The browser talks only to relative `/api` URLs; Vite
proxies them to FastAPI on `127.0.0.1:8000`. No credentials exist in the browser.

## One-time setup
Node.js 20+ (installed here: v26 via `winget install OpenJS.NodeJS.LTS`). Open a **new** terminal after installing so
`node`/`npm` are on PATH.

```powershell
cd frontend
npm install
```

## Run (two terminals)

**Terminal 1 — backend.** Choose one:

```powershell
cd backend
# A) MOCK models: free, no key, no network. Scripted results (verify | review | violated | hidden).
.venv\Scripts\python.exe experiments\dev_mock_server.py --scenario verify
# B) REAL models: every photo you analyse makes paid Meta API calls (key from the repo-root .env).
.venv\Scripts\python.exe -m uvicorn proofcam.api:app_from_env --factory --workers 1 --host 127.0.0.1 --port 8000
```

**Terminal 2 — frontend:**

```powershell
cd frontend
npm run dev          # http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173** (or http://localhost:5173) in Chrome. With the mock server a purple "Mock models" banner
is shown on every screen.

## Testing in Chrome
- Desktop: the camera works on `localhost`/`127.0.0.1` (a secure context). Chrome asks for permission on
  "Open camera". Without a webcam, use **Upload photo**.
- Phone emulation: DevTools → Toggle device toolbar (Ctrl+Shift+M) → pick a phone.
- iPhone: follow [../docs/IPHONE_SETUP.md](../docs/IPHONE_SETUP.md) (Tailscale Serve HTTPS, tailnet only, access code).
  Do not use `--host` or a public tunnel: the camera needs HTTPS anyway, and the backend refuses non-local requests
  unless an access code is set.
- Mock scenarios: `verify` (photo 1 → guidance, photo 2 → VERIFIED), `review` (photo 2 → contradiction → review;
  declare a change; photo 3 → VERIFIED), `violated`, `hidden`. The script is global to the server process: restart
  it (or use a new `--db`) for a clean run. Its default database is `var/dev-mock.db` (git-ignored), separate from the
  real `var/proofcam.db`.

## Checks
```powershell
npm test             # Vitest + Testing Library, mocked fetch, fixtures from the real API (mock models)
npm run typecheck    # tsc -b
npm run lint         # oxlint
npm run build        # production bundle in dist/ (PWA manifest + service worker)
npm run preview      # serve dist/ on http://127.0.0.1:4173 with the same /api proxy (used for the phone)
```
Fixtures in `src/test/fixtures/` are regenerated with
`backend\.venv\Scripts\python.exe backend\experiments\dev_mock_server.py --export-fixtures frontend\src\test\fixtures`.

## Layout
`src/api/` types + client · `src/state/useInspection.ts` session state and the capture/retry protocol ·
`src/components/` screens (`Landing`, `InspectionView`, `CameraPanel`, `Evidence`, `Photos`, `Dialogs`,
`ReportView`) and shadcn-style primitives in `ui/` · `src/test/` setup, fetch mock, fixtures.
