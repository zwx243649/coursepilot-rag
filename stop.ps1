param(
    [int]$Port = 8000
)

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "Nothing is listening on port $Port."
    exit 0
}

$stopped = @()
foreach ($procId in ($listeners.OwningProcess | Sort-Object -Unique)) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.CommandLine -notlike '*uvicorn*') {
        Write-Host "Port $Port is held by PID $procId, which is not a uvicorn process. Skipping."
        continue
    }

    Stop-Process -Id $procId -Force
    $stopped += $procId

    $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)" -ErrorAction SilentlyContinue
    if ($parentProc -and $parentProc.CommandLine -like '*uvicorn*') {
        Stop-Process -Id $parentProc.ProcessId -Force
        $stopped += $parentProc.ProcessId
    }
}

if ($stopped.Count -gt 0) {
    Write-Host "Stopped PID(s): $($stopped -join ', ')"
} else {
    Write-Host "No uvicorn process was stopped."
}
