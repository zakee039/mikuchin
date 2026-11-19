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
Push-Location $root
try {
  & python -m backend.gateway.app --host 127.0.0.1 --port $Port --upstream-port $OfficialPort
  if ($LASTEXITCODE -ne 0) {throw "Gateway exited with status $LASTEXITCODE"}
} finally {Pop-Location}
