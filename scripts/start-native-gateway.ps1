<# Isolated native Gateway only; does not start or touch the existing Mikuchin. #>
[CmdletBinding()]
param(
  [int]$Port=15249,
  [int]$OfficialPort=15240
)
$ErrorActionPreference='Stop'
if (-not $env:MIKUCHIN_GATEWAY_API_KEY -or -not $env:MIKUCHIN_UPSTREAM_API_KEY) {
  throw 'Set MIKUCHIN_GATEWAY_API_KEY and MIKUCHIN_UPSTREAM_API_KEY in this PowerShell session.'
}
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime=Join-Path $root 'runtime'
$python=Join-Path $runtime '.venv\Scripts\python.exe'
if(-not(Test-Path $python)){throw "Isolated Python not found: $python"}
Push-Location $root
try {
  & $python -B -m backend.gateway.app --host 127.0.0.1 --port $Port --upstream-port $OfficialPort
  if ($LASTEXITCODE -ne 0) {throw "Gateway exited with status $LASTEXITCODE"}
} finally {Pop-Location}
