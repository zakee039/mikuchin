<# Independent Image Worker; no official source modifications or launcher restart. #>
[CmdletBinding()]
param([string]$RuntimeRoot = '')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = if ($RuntimeRoot) {$RuntimeRoot} else {Join-Path (Split-Path $root -Parent) 'mikuchin-native-runtime'}
$python = Join-Path $runtime '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {throw "Isolated Python not installed: $python"}
Push-Location $root
try {
  & $python -B -m backend.gateway.worker
  if ($LASTEXITCODE -ne 0) {throw "Image Worker failed: exit $LASTEXITCODE"}
} finally {Pop-Location}
