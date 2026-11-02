$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$launcher = Join-Path $root 'frontend\launcher'
Push-Location $launcher
try {
  if (-not (Test-Path 'node_modules')) { & 'C:\Program Files\nodejs\npm.cmd' ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' } }
  & cmd.exe /c 'build.bat'
  if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed' }
} finally { Pop-Location }
