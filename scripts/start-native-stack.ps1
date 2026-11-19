<# Development-only three-process supervisor, not the production Launcher. #>
[CmdletBinding()]
param(
  [ValidateSet('mock','strata')][string]$Engine = 'mock',
  [string]$ConfigPath = '',
  [int]$GatewayPort = 15249,
  [int]$OfficialPort = 15240,
  [string]$DataDir = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime = Join-Path (Split-Path $root -Parent) 'mikuchin-native-runtime'
$python = Join-Path $runtime '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {throw "Native Python runtime missing: $python"}
if (-not $env:MIKUCHIN_GATEWAY_API_KEY -or $env:MIKUCHIN_GATEWAY_API_KEY.Length -lt 12) {
  throw 'Set MIKUCHIN_GATEWAY_API_KEY in your current PowerShell session before launching.'
}
if ($Engine -eq 'strata' -and -not (Test-Path $ConfigPath)) {
  throw 'Pass -ConfigPath with the existing isolated official model JSON.'
}
if (-not $DataDir) {$DataDir = Join-Path $runtime 'native-user-data'}
$arguments = @('-u','-B','-m','backend.gateway.supervisor','--engine',$Engine,
  '--data-dir',$DataDir,'--gateway-port',"$GatewayPort",'--upstream-port',"$OfficialPort")
if ($Engine -eq 'strata') {$arguments += @('--config',(Resolve-Path $ConfigPath).Path)}
Push-Location $root
try {
  & $python @arguments
  if ($LASTEXITCODE -ne 0) {throw "Native supervisor failed: exit $LASTEXITCODE"}
} finally {Pop-Location}
