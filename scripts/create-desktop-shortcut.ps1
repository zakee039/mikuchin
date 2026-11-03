# Create or repair the Mikuchin desktop shortcut.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$exe = Join-Path $root 'frontend\launcher\portable\Mikuchin.exe'
$icon = Join-Path $root 'frontend\launcher\src-tauri\icons\icon.ico'
if (-not (Test-Path -LiteralPath $exe)) { throw "Mikuchin.exe missing: $exe" }
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$dest = Join-Path $desktop 'Mikuchin.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($dest)
$link.TargetPath = $exe
$link.WorkingDirectory = Split-Path -Parent $exe
$link.IconLocation = "$icon,0"
$link.Arguments = ''
$link.Description = 'Mikuchin - personal AI platform'
$link.Save()
if ($shell.CreateShortcut($dest).TargetPath -ne $exe) {
    throw 'Mikuchin desktop shortcut verification failed'
}
Write-Output "Shortcut created: $dest"
