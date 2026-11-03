# Optional manual backup tool. Never writes outside <Mikuchin>/test/backups.
# Stop the managed service before running this command to capture consistent KV.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$port = 15239
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Mikuchin API port $port is active. Stop the service before backing up the runtime state."
}
if (Get-Process -Name Mikuchin -ErrorAction SilentlyContinue) {
    throw 'Mikuchin Manager is running. Exit the Manager before creating a consistent backup.'
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$destination = Join-Path $root "test\backups\runtime-$stamp"
if (Test-Path $destination) { throw "Backup already exists: $destination" }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($dir in @('chat', 'character', 'config')) {
    $source = Join-Path $root $dir
    if (!(Test-Path $source)) { throw "Missing runtime directory: $source" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $destination $dir) -Recurse -Force -ErrorAction Stop
}
Write-Output "Backup stored only at $destination"
