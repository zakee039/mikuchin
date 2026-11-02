$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$engine = Join-Path $root 'backend\polystrata'
$patch = Join-Path $PSScriptRoot 'polystrata-web-root.patch'
$server = Join-Path $engine 'serve\server.py'
if (-not (Test-Path $server)) { throw 'PolyStrata submodule missing. Run git submodule update --init --recursive.' }
if (Select-String -Path $server -Pattern 'MIKUCHIN_WEB_DIR' -Quiet) { Write-Output 'Mikuchin web-root support already applied.'; exit 0 }
& git -C $engine apply --check $patch
if ($LASTEXITCODE -ne 0) { throw 'PolyStrata changed upstream; review web-root compatibility patch before updating.' }
& git -C $engine apply $patch
if ($LASTEXITCODE -ne 0) { throw 'Failed to apply web-root compatibility patch.' }
Write-Output 'Applied Mikuchin frontend web-root compatibility patch.'
