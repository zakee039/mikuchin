# Safe PREVIEW-ONLY NSIS packaging. It cannot bundle GGUF or Python runtime.
# Stop only the separate Native scheduled preview after a strict idle check;
# always restart it even if packaging fails. Never touch main / port 15239.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$runtime=Join-Path (Split-Path $root -Parent) 'mikuchin-native-runtime'
$python=Join-Path $runtime '.venv\Scripts\python.exe'
$cli=Join-Path $root 'frontend\launcher\node_modules\.bin\tauri.cmd'
$task='Mikuchin-Native-Dev-Launch'
$log=Join-Path $runtime 'native-p3-nsis-build.log'
if (!(Test-Path $python -PathType Leaf) -or !(Test-Path $cli -PathType Leaf)) { throw 'Native Python or Tauri CLI missing' }
$repoBranch=(git -C $root branch --show-current).Trim()
if($repoBranch -ne 'refactor/official-polystrata-gateway'){throw 'Not on the isolated Native development branch'}
$checker=@'
from pathlib import Path
from backend.gateway.image_jobs import ImageJobStore
from backend.gateway.gpu_gate import read_state
p=Path(r'E:\LLM\deploy\mikuchin-native-runtime\launcher-user-data')
s=ImageJobStore(p/'images')
activity=s.activity()
with s._db() as db:
 pending=list(db.execute("SELECT id,state FROM jobs WHERE state IN ('queued','working','running')"))
lock=read_state(p)
print('IMAGE_ACTIVITY',activity,'GPU_LOCK',lock,'PENDING',len(pending))
if activity['running'] or lock['busy'] or pending:raise SystemExit(10)
'@
Push-Location $root
try {
    $checker | & $python -B - 2>&1 | ForEach-Object { Write-Host $_ }
    if($LASTEXITCODE -ne 0){throw 'Image jobs or GPU lease busy: installer build cancelled'}
} finally { Pop-Location }
Add-Type -AssemblyName System.Security
$keyFile=Join-Path $env:LOCALAPPDATA 'MikuchinNativeLauncher\api-key.dpapi'
$secret=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($keyFile),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
try {
    $headers=@{Authorization='Bearer '+[Text.Encoding]::UTF8.GetString($secret)}
    $health=Invoke-RestMethod 'http://127.0.0.1:15249/health' -Headers $headers -TimeoutSec 8
    $metrics=Invoke-RestMethod 'http://127.0.0.1:15249/metrics' -Headers $headers -TimeoutSec 8
    $monitor=Invoke-RestMethod 'http://127.0.0.1:15249/v1/mikuchin/request-monitor' -Headers $headers -TimeoutSec 8
    if($health.native_gpu.busy -or $health.native_image_jobs.running -gt 0 -or
       $monitor.active -gt 0 -or $metrics.live.state -in @('reading','generating','loading')){
        throw 'Native currently serving user requests: do not interrupt'
    }
    Write-Host ('NATIVE_SAFE_TO_PACKAGE: LLM='+$metrics.live.state+' active='+$monitor.active)
} finally { [Array]::Clear($secret,0,$secret.Length) }
$old = Get-ScheduledTask -TaskName $task -ErrorAction Stop
if($old.State -notin @('Running','Ready')){throw 'Unexpected Native preview task state; abort'}
$stopped=$false
try {
    Stop-ScheduledTask -TaskName $task
    $stopped=$true
    Start-Sleep -Seconds 5
    $listeners=@(Get-NetTCPConnection -State Listen -LocalPort 15249,15240 -ErrorAction SilentlyContinue)
    if($listeners.Count -gt 0 -or (Get-Process mikuchin -ErrorAction SilentlyContinue)){
        throw 'Native processes not cleanly stopped; refusing to package over a running EXE'
    }
    $env:CARGO_TARGET_DIR=Join-Path $runtime 'tauri-target'
    Push-Location (Join-Path $root 'frontend\launcher')
    try {
        # Invoke through cmd so ordinary Rust/Tauri stderr progress does not
        # become terminating PowerShell NativeCommandError under WinPS5.1.
        $command='"'+$cli+'" build --debug --bundles nsis > "'+$log+'" 2>&1'
        & cmd.exe /d /s /c $command
        if($LASTEXITCODE -ne 0){throw "Tauri NSIS bundling failed. Inspect $log"}
    } finally {Pop-Location}
} finally {
    if($stopped){Start-ScheduledTask -TaskName $task}
}
Start-Sleep -Seconds 12
$proc=Get-Process mikuchin -ErrorAction Stop
if(-not $proc.Responding){throw 'Native launcher restarted but not responding'}
$ports=Get-NetTCPConnection -State Listen -LocalPort 15249,15240 -ErrorAction Stop
if(-not (@($ports.LocalPort) -contains 15249) -or -not (@($ports.LocalPort) -contains 15240)){throw 'Native stack did not come back'}
$bundles=Get-ChildItem (Join-Path $runtime 'tauri-target\debug\bundle\nsis') -Filter '*.exe' -File -ErrorAction Stop
$latest=$bundles|Sort-Object LastWriteTime -Descending|Select-Object -First 1
if(!$latest){throw 'No Native NSIS installer found'}
Write-Host "NATIVE_DEV_NSIS_PREVIEW=$($latest.FullName)"
Write-Host "NSIS_BYTES=$($latest.Length)"
Write-Host "NSIS_SHA256=$((Get-FileHash -Path $latest.FullName -Algorithm SHA256).Hash)"
Write-Host 'Native preview restarted. Installer is LAUNCHER-ONLY and requires separate Native backend/runtime and model files.'
