# Start StutterCut on Windows with one command:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# Builds the UI when its sources changed, starts the API (which starts the worker process and
# serves the UI) on http://127.0.0.1:$env:STUTTERCUT_PORT (default 8000), and opens the browser.
# Ctrl+C stops everything. STUTTERCUT_NO_BROWSER=1 skips the browser. Setup: docs\guides\setup-windows.md
$ErrorActionPreference = 'Stop'

Set-Location (Join-Path $PSScriptRoot '..')
$port = if ($env:STUTTERCUT_PORT) { $env:STUTTERCUT_PORT } else { '8000' }
$url = "http://127.0.0.1:$port"

$py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
# Python 3.11 reads the editable install's .pth file as cp1252, so a checkout path with
# Vietnamese letters is not importable; PYTHONPATH reaches Python as Unicode (lesson 005).
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend') + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { '' })
if (-not (Test-Path $py)) {
    Write-Error 'No .venv found. Set up first: docs\guides\setup-windows.md (py -3.11 -m venv .venv ...)'
}
foreach ($tool in 'ffmpeg', 'ffprobe', 'node', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Error "$tool is not installed (see docs\guides\setup-windows.md)."
    }
}

if (-not (Test-Path 'frontend\node_modules')) {
    Push-Location frontend; npm ci; Pop-Location
}
$built = 'frontend\dist\index.html'
$stale = -not (Test-Path $built)
if (-not $stale) {
    $builtAt = (Get-Item $built).LastWriteTime
    $stale = [bool](Get-ChildItem -Recurse -File frontend\src, frontend\index.html |
        Where-Object { $_.LastWriteTime -gt $builtAt } | Select-Object -First 1)
}
if ($stale) {
    Write-Host 'Building the UI...'
    Push-Location frontend; npm run build; Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Error 'The UI build failed.' }
}

# Open the browser once the API answers, without blocking the server.
if (-not $env:STUTTERCUT_NO_BROWSER) { Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 120; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing "$u/api/health" -TimeoutSec 2 | Out-Null
            Start-Process $u
            return
        } catch { Start-Sleep -Milliseconds 500 }
    }
} -ArgumentList $url | Out-Null }

Write-Host "StutterCut on $url (Ctrl+C to stop)"
& $py -m uvicorn stuttercut.api.main:app --host 127.0.0.1 --port $port
