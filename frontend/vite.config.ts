/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend (FastAPI) runs separately on 127.0.0.1:8000; /api is proxied so the app is same-origin and no CORS or
// browser-side credentials are needed. The Meta API key stays in the backend's .env.
const API_TARGET = process.env.PROOFCAM_API_TARGET ?? 'http://127.0.0.1:8000'
// Captures can take minutes; keep the proxy from cutting them off.
const proxy = { '/api': { target: API_TARGET, changeOrigin: false, timeout: 15 * 60 * 1000, proxyTimeout: 15 * 60 * 1000 } }
// Both servers listen on loopback only. Phone access goes through `tailscale serve` (HTTPS, tailnet only), which
// connects to 127.0.0.1 and presents the request with the machine's *.ts.net name; that name must be allowed.
const allowedHosts = ['.ts.net']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, allowedHosts, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, allowedHosts, proxy },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
})
