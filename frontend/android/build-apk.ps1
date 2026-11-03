# One-click APK build script for Mikuchin Android Client (including built-in user-space Tailscale tsnet).
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$projDir = $PSScriptRoot
$toolchainDir = Join-Path $projDir ".toolchain"
New-Item -ItemType Directory -Force -Path $toolchainDir | Out-Null

Write-Host "==> [1/5] Checking JDK 17..."
$jdkDir = Join-Path $toolchainDir "jdk-17"
$javaExe = Get-ChildItem -Path $jdkDir -Filter "java.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($javaExe) {
    $env:JAVA_HOME = $javaExe.Directory.Parent.FullName
} elseif (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
    New-Item -ItemType Directory -Force -Path $jdkDir | Out-Null
    $jdkZip = Join-Path $toolchainDir "jdk17.zip"
    Write-Host "    Downloading portable OpenJDK 17..."
    & curl.exe -fL --retry 3 -o $jdkZip "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
    & tar.exe -xf $jdkZip -C $jdkDir
    Remove-Item $jdkZip -Force -ErrorAction SilentlyContinue
    $javaExe = Get-ChildItem -Path $jdkDir -Filter "java.exe" -Recurse | Select-Object -First 1
    $env:JAVA_HOME = $javaExe.Directory.Parent.FullName
}
$env:PATH = "$($env:JAVA_HOME)\bin;$($env:PATH)"
Write-Host "    JAVA_HOME = $($env:JAVA_HOME)"

Write-Host "==> [2/5] Checking Android SDK & NDK..."
$sdkRoot = Join-Path $toolchainDir "android-sdk"
if (-not (Test-Path $sdkRoot)) {
    if ($env:ANDROID_HOME -and (Test-Path $env:ANDROID_HOME)) { $sdkRoot = $env:ANDROID_HOME }
    elseif (Test-Path "$env:LOCALAPPDATA\Android\Sdk") { $sdkRoot = "$env:LOCALAPPDATA\Android\Sdk" }
}
$sdkManager = Join-Path $sdkRoot "cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path (Join-Path $sdkRoot "platforms\android-34")) -or -not (Test-Path (Join-Path $sdkRoot "build-tools\34.0.0"))) {
    if (-not (Test-Path $sdkManager)) {
        New-Item -ItemType Directory -Force -Path (Join-Path $sdkRoot "cmdline-tools") | Out-Null
        $cmdZip = Join-Path $toolchainDir "cmdline-tools.zip"
        Write-Host "    Downloading Android Command-Line Tools..."
        & curl.exe -fL --retry 3 -o $cmdZip "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
        $extractTmp = Join-Path $toolchainDir "cmdline-tmp"
        New-Item -ItemType Directory -Force -Path $extractTmp | Out-Null
        & tar.exe -xf $cmdZip -C $extractTmp
        $latestDir = Join-Path $sdkRoot "cmdline-tools\latest"
        if (Test-Path $latestDir) { Remove-Item $latestDir -Recurse -Force }
        Move-Item -Path (Join-Path $extractTmp "cmdline-tools") -Destination $latestDir -Force
        Remove-Item $cmdZip, $extractTmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    $licensesDir = Join-Path $sdkRoot "licenses"
    New-Item -ItemType Directory -Force -Path $licensesDir | Out-Null
    Set-Content -Path (Join-Path $licensesDir "android-sdk-license") -Value "`n24333f8a63b6825ea9c5514f83c2829b004d1fee`nd56f5187479451eabf01fb78af6dfcb131a6481e`n84831b9409646a918e30573bab4c9c91346d8abd" -NoNewline
    & cmd.exe /c "echo y| `"$sdkManager`" --sdk_root=`"$sdkRoot`" `"platform-tools`" `"platforms;android-34`" `"build-tools;34.0.0`" `"ndk;26.1.10909125`""
}
$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot
$env:ANDROID_NDK_HOME = Join-Path $sdkRoot "ndk\26.1.10909125"
$escapedSdk = $sdkRoot.Replace("\", "\\").Replace(":", "\:")
Set-Content -Path (Join-Path $projDir "local.properties") -Value "sdk.dir=$escapedSdk" -Encoding ASCII

Write-Host "==> [3/5] Checking Go + gomobile & verifying tsnetbridge..."
$tsDir = Join-Path $projDir "tsnetbridge"
$aarPath = Join-Path $projDir "app\libs\tsnetbridge.aar"
$goSrcTime = (Get-Item (Join-Path $tsDir "tsnetbridge.go")).LastWriteTime
$needsAarBuild = (-not (Test-Path $aarPath)) -or ((Get-Item $aarPath).LastWriteTime -lt $goSrcTime)

$goBin = Join-Path $toolchainDir "go-1.23\go\bin"
if (-not (Test-Path (Join-Path $goBin "go.exe")) -and $needsAarBuild) {
    $goZip = Join-Path $toolchainDir "go1.23.4.zip"
    Write-Host "    Downloading portable Go 1.23.4..."
    & curl.exe -fL --retry 3 -o $goZip "https://golang.google.cn/dl/go1.23.4.windows-amd64.zip"
    New-Item -ItemType Directory -Force -Path (Join-Path $toolchainDir "go-1.23") | Out-Null
    & tar.exe -xf $goZip -C (Join-Path $toolchainDir "go-1.23")
    Remove-Item $goZip -Force -ErrorAction SilentlyContinue
}

if (Test-Path (Join-Path $goBin "go.exe")) {
    $env:GOTOOLCHAIN = "local"
    $env:GOPATH = Join-Path $toolchainDir "gopath"
    $env:GOCACHE = Join-Path $toolchainDir "gocache"
    $env:GOPROXY = "https://goproxy.cn,direct"
    $env:PATH = "$goBin;$($env:GOPATH)\bin;$($env:PATH)"

    Push-Location $tsDir
    try {
        & (Join-Path $goBin "go.exe") test -v ./...
        if ($LASTEXITCODE -ne 0) { throw "tsnetbridge unit tests failed" }
        if ($needsAarBuild) {
            Write-Host "    Building tsnetbridge.aar via gomobile bind (Go 1.23.4, GOTOOLCHAIN=local)..."
            New-Item -ItemType Directory -Force -Path (Split-Path $aarPath) | Out-Null
            & (Join-Path $env:GOPATH "bin\gomobile.exe") bind -target=android/arm64 -androidapi 26 -ldflags="-X tailscale.com/version.longStamp=1.102.3 -X tailscale.com/version.shortStamp=1.102.3 -extldflags=-Wl,-z,max-page-size=16384" -o $aarPath .
            if ($LASTEXITCODE -ne 0) { throw "gomobile bind failed" }
        }
    } finally {
        Pop-Location
    }
}

Write-Host "==> [4/5] Checking Gradle 8.7..."
$gradleDir = Join-Path $toolchainDir "gradle-8.7"
$gradleExe = Get-ChildItem -Path $gradleDir -Filter "gradle.bat" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gradleExe) {
    New-Item -ItemType Directory -Force -Path $gradleDir | Out-Null
    $gradleZip = Join-Path $toolchainDir "gradle.zip"
    & curl.exe -fL --retry 3 -o $gradleZip "https://mirrors.cloud.tencent.com/gradle/gradle-8.7-bin.zip"
    & tar.exe -xf $gradleZip -C $gradleDir
    Remove-Item $gradleZip -Force -ErrorAction SilentlyContinue
    $gradleExe = Get-ChildItem -Path $gradleDir -Filter "gradle.bat" -Recurse | Select-Object -First 1
}
$gradleBat = $gradleExe.FullName

Write-Host "==> [5/5] Building Mikuchin.apk..."
Push-Location $projDir
try {
    & $gradleBat assembleDebug --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE" }
    $apkPath = Join-Path $projDir "app\build\outputs\apk\debug\app-debug.apk"
    $outApk = Join-Path $projDir "Mikuchin.apk"
    Copy-Item -Path $apkPath -Destination $outApk -Force
    Write-Host ""
    Write-Host "SUCCESS! APK generated at: $outApk" -ForegroundColor Green
} finally {
    Pop-Location
}
