# One-way secure staged move of an existing named Tunnel identity.
# No plaintext token output. Never activate two connectors simultaneously.
$ErrorActionPreference='Stop'
$old=Join-Path $env:LOCALAPPDATA 'Mikuchin'
$native=Join-Path $env:LOCALAPPDATA 'MikuchinNativeLauncher'
$source=Join-Path $old 'cf-tunnel-token.dpapi'
$destination=Join-Path $native 'native-cf-tunnel-token.dpapi'
$legacyPrefs=Get-Content (Join-Path $old 'settings.json') -Raw -Encoding UTF8|ConvertFrom-Json
$newFile=Join-Path $native 'preferences.json'
$newPrefs=Get-Content $newFile -Raw -Encoding UTF8|ConvertFrom-Json
if($legacyPrefs.cf_hostname -notmatch '^[A-Za-z0-9.-]+$' -or !$legacyPrefs.cf_enabled){
    throw 'Old-mixed Tunnel is not configured; nothing to stage'
}
if($newPrefs.cf_enabled){
    throw 'Native Tunnel is already enabled; refuse simultaneous connector migration'
}
if(!(Test-Path $source -PathType Leaf)){throw 'Old encrypted token does not exist'}
Add-Type -AssemblyName System.Security
$blob=[IO.File]::ReadAllBytes($source)
$raw=[Security.Cryptography.ProtectedData]::Unprotect($blob,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
try{
    $token=[Text.Encoding]::UTF8.GetString($raw)
    if($token.Length -lt 80 -or $token.Length -gt 8000 -or $token -notmatch '^[A-Za-z0-9_.-]+$'){
        throw 'Legacy DPAPI token has unsupported shape'
    }
    if(Test-Path $destination){
        if((Get-FileHash $destination -Algorithm SHA256).Hash -ne (Get-FileHash $source -Algorithm SHA256).Hash){
            throw 'Native already has a distinct token; refusing to overwrite'
        }
    }else{
        [IO.File]::WriteAllBytes($destination,$blob)
    }
}finally{
    [Array]::Clear($raw,0,$raw.Length)
    Remove-Variable token -ErrorAction SilentlyContinue
}
if($newPrefs.cf_hostname -and $newPrefs.cf_hostname -ne $legacyPrefs.cf_hostname){
    throw 'Native hostname conflicts with legacy; refuse overwrite'
}
$newPrefs.cf_hostname=$legacyPrefs.cf_hostname
$newPrefs.cf_enabled=$false
if(-not $newPrefs.PSObject.Properties['model_config']){
    $newPrefs|Add-Member -NotePropertyName model_config -NotePropertyValue 'official-sm86-model-test.json'
}
if(-not $newPrefs.PSObject.Properties['idle_unload_s']){
    $newPrefs|Add-Member -NotePropertyName idle_unload_s -NotePropertyValue 900
}
$temp=$newFile+'.stage.tmp'
$json=$newPrefs|ConvertTo-Json -Depth 16
# Windows PowerShell 5.1 Set-Content -Encoding UTF8 writes a BOM which Rust
# serde_json::from_slice rejects. Use a BOM-less atomic JSON write.
[IO.File]::WriteAllText($temp,$json,(New-Object Text.UTF8Encoding($false)))
Move-Item $temp $newFile -Force
Write-Host 'STAGED_CLOUD_FLARE_TOKEN_DPAPI=true; NATIVE_TUNNEL_ACTIVE=false; old token unchanged'
Write-Host ('STAGED_HOSTNAME='+$legacyPrefs.cf_hostname)
Write-Host 'Enable Native only AFTER old connector has stopped and gateway moved to the target port.'
