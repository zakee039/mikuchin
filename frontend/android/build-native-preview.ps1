# Build an isolated Native preview APK. Never overwrite the stable
# com.mikuchin.client Android package, its signing keys, or main artifacts.
[CmdletBinding()]
param(
    [string]$ToolchainRoot = '',
    [string]$OutputDir = ''
)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
if (-not $ToolchainRoot) {
    $ToolchainRoot = Join-Path $project '.toolchain'
}
$ToolchainRoot = [IO.Path]::GetFullPath($ToolchainRoot)
if (-not $OutputDir) {
    $OutputDir = Join-Path $project 'native-preview-output'
}
$jdk = Get-ChildItem -Path (Join-Path $ToolchainRoot 'jdk-17') -Recurse -File -Filter 'java.exe' -ErrorAction SilentlyContinue |
    Where-Object { $_.Directory.Name -eq 'bin' } | Select-Object -First 1
$gradle = Get-ChildItem -Path (Join-Path $ToolchainRoot 'gradle-8.7') -Recurse -File -Filter 'gradle.bat' -ErrorAction SilentlyContinue |
    Where-Object { $_.Directory.Name -eq 'bin' } | Select-Object -First 1
$sdk = Join-Path $ToolchainRoot 'android-sdk'
$aar = Join-Path $project 'app\libs\tsnetbridge.aar'
if (-not $jdk -or -not $gradle -or
    -not (Test-Path (Join-Path $sdk 'platforms\android-34')) -or
    -not (Test-Path (Join-Path $sdk 'build-tools\34.0.0')) -or
    -not (Test-Path $aar -PathType Leaf)) {
    throw 'Native preview prerequisites missing. Pass -ToolchainRoot with a prepared JDK17, Gradle8.7, SDK34 and tsnetbridge.aar; this script does not download or alter stable installation files.'
}
$env:JAVA_HOME = $jdk.Directory.Parent.FullName
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
$env:PATH = (Join-Path $env:JAVA_HOME 'bin') + ';' + $env:PATH
# Gradle reads only this isolated worktree's local.properties.
$escaped = $sdk.Replace('\','\\').Replace(':','\:')
$props = Join-Path $project 'local.properties'
$previous = if (Test-Path $props) { Get-Content $props -Encoding UTF8 | Where-Object { $_ -notmatch '^sdk\.dir=' } } else { @() }
@("sdk.dir=$escaped") + $previous | Set-Content $props -Encoding UTF8
Push-Location $project
try {
    & $gradle.FullName ':app:testNativePreviewUnitTest' ':app:assembleNativePreview' '--no-daemon'
    if ($LASTEXITCODE -ne 0) { throw "Gradle Native preview build failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}
$apk = Join-Path $project 'app\build\outputs\apk\nativePreview\app-nativePreview.apk'
if (-not (Test-Path $apk -PathType Leaf)) { throw "Native preview APK not produced: $apk" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$destination = Join-Path $OutputDir 'Mikuchin-Native-Android-Preview.apk'
Copy-Item $apk $destination -Force
$sha256 = (Get-FileHash -Algorithm SHA256 -Path $destination).Hash
Write-Host "Native Android preview APK: $destination"
Write-Host "SHA256: $sha256"
Write-Host 'Package: com.mikuchin.client.nativepreview (separate from stable)'
