# Safe cutover: run only after "Exit manager" from the legacy PolyStrata tray.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$old = Join-Path (Split-Path $root -Parent) 'polystrata'
$engine = Join-Path $root 'backend\polystrata'
$binary = Join-Path $root 'frontend\launcher\portable\Mikuchin.exe'
$config = Join-Path $root 'config\active.json'
$python = Join-Path $engine '.venv\Scripts\python.exe'
if (-not (Test-Path $binary) -or -not (Test-Path $python) -or -not (Test-Path $config)) {
    throw 'Mikuchin executable, Python runtime or active.json is missing.'
}
if (Get-Process -Name PolyStrataManager -ErrorAction SilentlyContinue) {
    throw 'Please exit the old PolyStrata Manager from its tray menu first; do not force-kill an active chat.'
}
$listener = Get-NetTCPConnection -LocalPort 18081 -State Listen -ErrorAction SilentlyContinue
if ($listener) { throw 'Port 18081 is still in use. Old API service must be stopped before cutover.' }
$legacyData = Join-Path $old 'chat-history'
$legacyKV = Join-Path $old 'kv-cache'
if (Test-Path $legacyData) {
    & $python (Join-Path $PSScriptRoot 'snapshot-chat.py') --source $legacyData --destination (Join-Path $root 'chat') --kv-source $legacyKV --final
    if ($LASTEXITCODE -ne 0) { throw 'Final chat and KV snapshot failed; new Manager was not started.' }
}
$previousState = Join-Path $env:LOCALAPPDATA 'PolyStrataManager'
$newState = Join-Path $env:LOCALAPPDATA 'Mikuchin'
New-Item -ItemType Directory $newState -Force | Out-Null
foreach ($name in @('api-key.dpapi', 'cf-tunnel-token.dpapi')) {
    if ((Test-Path (Join-Path $previousState $name)) -and -not (Test-Path (Join-Path $newState $name))) {
        Copy-Item (Join-Path $previousState $name) (Join-Path $newState $name)
    }
}
$oldSettings = Join-Path $previousState 'settings.json'
$newSettings = Join-Path $newState 'settings.json'
if (Test-Path $oldSettings) {
    $p = Get-Content $oldSettings -Raw -Encoding UTF8 | ConvertFrom-Json
    $p.project_path = $engine
    $p.config_path = $config
    if (Test-Path $newSettings) { Copy-Item $newSettings ($newSettings + '.before-cutover.bak') -Force }
    $p | ConvertTo-Json -Depth 12 | Set-Content -Path $newSettings -Encoding UTF8
}
Start-Process -FilePath $binary -ArgumentList '--background' -WorkingDirectory (Split-Path $binary -Parent)
$port = (Get-Content $config -Raw | ConvertFrom-Json).port
if (-not $port) { $port = 18081 }
$healthy = $false
for ($i=0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try { $res = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 2 -Proxy $null
        if ($res.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
}
if (-not $healthy) { throw "Mikuchin started but health check on port $port failed. See $newState\service.log; old files are untouched." }
Write-Output "Mikuchin is running: http://127.0.0.1:$port/"
