param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw "Virtual environment not found: $python. Create it first (see README)."
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "Port $Port is already in use by PID $($listener.OwningProcess -join ', ')."
    Write-Host "Open http://127.0.0.1:$Port"
    exit 0
}

$logDir = Join-Path $root 'data'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$outLog = Join-Path $logDir 'uvicorn.log'
$errLog = Join-Path $logDir 'uvicorn.err.log'

Start-Process -FilePath $python `
    -ArgumentList "-m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog | Out-Null

for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/system/health" -TimeoutSec 3
        Write-Host "CoursePilot is up: http://127.0.0.1:$Port"
        Write-Host ("embedding={0}  llm={1}/{2}" -f $health.embedding_provider, $health.llm.provider, $health.llm.model)
        Write-Host "logs: $outLog"
        exit 0
    } catch {
        # server not ready yet, keep polling
    }
}

Write-Host "Server did not become healthy within 30s. Last lines of $errLog :"
Get-Content $errLog -Tail 20 -ErrorAction SilentlyContinue
exit 1
