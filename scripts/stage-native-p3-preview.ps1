# Stage ONLY preview installers with bounded hashes and prerequisite metadata.
# Not an update feed, signed release, portable runtime, or Github release.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$AndroidApk,
    [string]$OutputDir = ''
)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
if(-not $OutputDir){
    $OutputDir=Join-Path (Split-Path $root -Parent) 'mikuchin-native-runtime\p3-preview-artifacts'
}
if(!(Test-Path $Installer -PathType Leaf) -or !(Test-Path $AndroidApk -PathType Leaf)){
    throw 'Both local Native NSIS and isolated Android preview APK must exist'
}
$config=Get-Content (Join-Path $root 'frontend\launcher\src-tauri\tauri.conf.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if($config.identifier -ne 'fun.zakee.mikuchin.native-dev'){throw 'Installer is not the isolated Native app'}
$version=Get-Content (Join-Path $root 'versions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$sha=(git -C $root rev-parse HEAD).Trim()
if($LASTEXITCODE -ne 0 -or !$sha){throw 'Cannot identify current Native commit'}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$files=@()
foreach($source in @(
    @{path=$Installer;name='Mikuchin-Native-Dev-Launcher-Only-Setup.exe'},
    @{path=$AndroidApk;name='Mikuchin-Native-Android-Preview.apk'}
)){
    $dest=Join-Path $OutputDir $source.name
    Copy-Item -LiteralPath $source.path -Destination $dest -Force
    $file=Get-Item $dest
    $files+=@{
        name=$source.name
        bytes=[long]$file.Length
        sha256=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest=[ordered]@{
    format='mikuchin-native-preview-v1'
    stable_releases_unmodified=$true
    formal_release=$false
    portable_or_self_contained=$false
    updater_feed=$false
    git_commit=$sha
    native_branch='refactor/official-polystrata-gateway'
    official_engine_submodule='unmodified'
    launcher_identifier=$config.identifier
    launcher_version=$version.components.launcher.version
    android_package='com.mikuchin.client.nativepreview'
    android_version=$version.components.android.version
    gateway_port=15249
    reserved_stable_port=15239
    prerequisites=@('Native backend sources', 'Official PolyStrata runtime',
        'Windows Python venv and model JSON', 'Local GGUF and Image Worker assets',
        'Separately configured Native API Key and optional new Tunnel token')
    artifacts=$files
}
$manifestFile=Join-Path $OutputDir 'preview-manifest.json'
$manifest|ConvertTo-Json -Depth 12|Set-Content -Path $manifestFile -Encoding UTF8
$readme=@'
Mikuchin Native P3 PREVIEW (not a release)
========================================
Windows NSIS: launcher-only developer candidate.
It deliberately does NOT contain Python, PolyStrata, model weights,
GPU binaries, local image engines, user data or secrets.
Set MIKUCHIN_NATIVE_HOME to a verified Native backend tree, and optionally
MIKUCHIN_NATIVE_RUNTIME_HOME to its matching isolated .venv/config root.
Production 15239 and stable Android package must remain unchanged.

Android APK: com.mikuchin.client.nativepreview; installs alongside
com.mikuchin.client and owns separate app/Keystore/Tailscale state.
Configure an explicit Native Gateway address and its independent API Key.
For Tailscale, use the host's Tailnet IP:15249, not its private engine 15240.
Do not auto-connect a plaintext LAN endpoint on an untrusted Wi-Fi.
Permanent Cloudflare requires a *new* Native-only named Tunnel and token.

Hashes in preview-manifest.json detect file changes only. No signatures
or secure automatic updates are provided by this preview manifest.
Do not upload as a public GitHub Release.
'@
Set-Content -LiteralPath (Join-Path $OutputDir 'README-PREVIEW.txt') -Value $readme -Encoding UTF8
Write-Host "Staged isolated P3 preview artifacts in: $OutputDir"
$files|ForEach-Object {Write-Host ($_.name + ' SHA256=' + $_.sha256)}
Write-Host 'Not self-contained, not a signed update feed and not formally released.'
