<#
.SYNOPSIS
  Start the ProofCam backend with REAL Meta models (Muse Spark 1.3 + SAM 3.1). Every analysed photo is paid.

.DESCRIPTION
  Private and capped by construction:
    - binds 127.0.0.1 only (the phone reaches it through vite preview + Tailscale Serve, tailnet only);
    - refuses to start without an access code (>= 12 chars) and refuses if the port is already in use;
    - separate live database (default var/live-m33.db), so mock history never mixes with real evidence;
    - global model-call cap for that database (default 20, retries included, enforced before every HTTP attempt);
      a new photo is refused with nothing sent unless >= 8 calls remain.
  The access code is read from $env:PROOFCAM_ACCESS_CODE, else the repo-root .env, else asked for (hidden input).
  It is never printed. Environment changes are undone when the server stops.

.EXAMPLE
  .\scripts\start-live.ps1                      # 20-call cap, var/live-m33.db, reasoning effort low, port 8000
#>
param(
    [ValidateRange(1, 200)][int]$CallLimit = 20,
    [string]$Db = "var/live-m33.db",
    [int]$Port = 8000,
    [ValidateSet("minimal", "low", "medium", "high")][string]$ReasoningEffort = "low"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Python venv not found at $py" }

# 1. The port must be free: an old mock or live server would otherwise answer the phone.
$listeners = netstat -ano | Select-String "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)"
if ($listeners) {
    foreach ($m in $listeners) {
        $procId = [int]$m.Matches[0].Groups[1].Value
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        Write-Host "Port $Port is in use by pid $procId ($($p.Name)) started $($p.CreationDate)" -ForegroundColor Red
    }
    Write-Host "Stop that server first (Ctrl+C in its terminal, or: Stop-Process -Id <pid>)." -ForegroundColor Red
    exit 1
}

# 2. Access code: required, never printed.
$saved = @{}
foreach ($n in "PROOFCAM_ACCESS_CODE", "PROOFCAM_GLOBAL_CALL_LIMIT", "PROOFCAM_DB_PATH", "PROOFCAM_MUSE_REASONING_EFFORT") {
    $saved[$n] = [Environment]::GetEnvironmentVariable($n, "Process")
}
$envFile = Join-Path $repo ".env"
$inDotEnv = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern "^\s*PROOFCAM_ACCESS_CODE\s*=\s*\S" -Quiet)
if (-not $env:PROOFCAM_ACCESS_CODE -and -not $inDotEnv) {
    $s = Read-Host "Access code for the phone (min 12 chars, hidden)" -AsSecureString
    $env:PROOFCAM_ACCESS_CODE = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
if ($env:PROOFCAM_ACCESS_CODE -and $env:PROOFCAM_ACCESS_CODE.Trim().Length -lt 12) {
    $env:PROOFCAM_ACCESS_CODE = $saved["PROOFCAM_ACCESS_CODE"]
    Write-Host "Access code must be at least 12 characters." -ForegroundColor Red
    exit 1
}

# 3. Live settings for this process only.
$env:PROOFCAM_GLOBAL_CALL_LIMIT = "$CallLimit"
$env:PROOFCAM_DB_PATH = $Db
$env:PROOFCAM_MUSE_REASONING_EFFORT = $ReasoningEffort

Push-Location $backend
try {
    $used = & $py -c "import sys; from proofcam.config import database_path; from proofcam.store import Store; p = database_path(); print(Store(p).total_model_calls() if p.exists() else 0)"
    if ($LASTEXITCODE -ne 0) { throw "could not read the live database" }
    $remaining = $CallLimit - [int]$used
    Write-Host ""
    Write-Host "  ProofCam LIVE backend - REAL, PAID Meta calls (Muse Spark 1.3 + SAM 3.1)" -ForegroundColor Yellow
    Write-Host "  bind          http://127.0.0.1:$Port (not reachable from other devices directly)"
    Write-Host "  database      $Db  (calls already used: $used)"
    Write-Host "  global cap    $CallLimit calls, $remaining left; a photo is refused unless >= 8 remain"
    Write-Host "  reasoning     $ReasoningEffort"
    Write-Host "  access code   set (from $(if ($inDotEnv -and -not $saved['PROOFCAM_ACCESS_CODE']) {'.env'} else {'environment/prompt'}); not shown)"
    Write-Host "  stop          Ctrl+C"
    Write-Host ""
    if ($remaining -lt 8) {
        Write-Host "Fewer than 8 calls remain in $Db : every photo would be refused. Use a new -Db or a higher -CallLimit (needs approval)." -ForegroundColor Red
        exit 1
    }
    & $py -m uvicorn proofcam.api:app_from_env --factory --workers 1 --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
    foreach ($n in $saved.Keys) { [Environment]::SetEnvironmentVariable($n, $saved[$n], "Process") }
}
