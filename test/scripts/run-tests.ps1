$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$testRoot = Join-Path $root 'test'
$tempDir = Join-Path $testRoot 'temp'
$resultDir = Join-Path $testRoot 'results'
New-Item -ItemType Directory -Force -Path $tempDir,$resultDir | Out-Null

# Route every ordinary tempfile/TMP file created by children away from real chat.
$env:TMP = $tempDir
$env:TEMP = $tempDir
$env:TMPDIR = $tempDir
$env:MIKUCHIN_TEST_ROOT = $testRoot
$py = Join-Path $root 'backend\polystrata\.venv\Scripts\python.exe'
if (!(Test-Path $py)) { throw "Missing test Python environment: $py" }

try {
    & $py (Join-Path $root 'scripts\audit-local-paths.py')
    if ($LASTEXITCODE -ne 0) { throw 'Local-path audit failed' }

    Push-Location (Join-Path $root 'backend\polystrata')
    try {
        & $py -m unittest serve.test_character_cards serve.test_image_tools serve.test_images serve.test_session_v1 serve.test_history_v2 -q
        if ($LASTEXITCODE -ne 0) { throw 'Backend unit tests failed' }
    } finally { Pop-Location }

    Push-Location (Join-Path $root 'frontend\launcher')
    try {
        $tests = Get-ChildItem -Path '.\tests' -Filter '*.test.mjs' -File | ForEach-Object FullName
        & node --test $tests
        if ($LASTEXITCODE -ne 0) { throw 'Frontend launcher tests failed' }
    } finally { Pop-Location }

    & $py (Join-Path $root 'test\scripts\test_ui_language.py')
    if ($LASTEXITCODE -ne 0) { throw 'UI language smoke test failed' }
    Write-Output 'Mikuchin isolated regression tests passed.'
} finally {
    # Never leave test-only chat replicas or generated-image staging files
    # behind. All temporary artifacts are strictly below test/temp/.
    Get-ChildItem -LiteralPath $tempDir -Force -ErrorAction SilentlyContinue |
      Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
