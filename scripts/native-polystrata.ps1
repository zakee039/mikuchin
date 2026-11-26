<#
  Manage the *unmodified* official PolyStrata submodule.

  .\scripts\native-polystrata.ps1 status
  .\scripts\native-polystrata.ps1 verify
  .\scripts\native-polystrata.ps1 pin -Tag v0.1.45-poly.10

  'pin' stages only the Git submodule pointer; it never edits upstream files,
  commits or deploys to the running desktop service.
#>
[CmdletBinding()]
param(
  [ValidateSet('status','verify','pin')]
  [string]$Action='status',
  [string]$Tag='',
  [string]$ExpectedCommit=''
)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sub=Join-Path $root 'backend\polystrata'
$originExpected='https://github.com/simplexai-labs/PolyStrata.git'

function CheckGitExit([string]$message) {
  if ($LASTEXITCODE -ne 0) {throw "$message (git exit: $LASTEXITCODE)"}
}

if (-not ((Test-Path (Join-Path $sub 'serve\server.py')) -or (Test-Path (Join-Path $sub 'terminal\serve\server.py')))) {
  Write-Host 'Initializing the official upstream checkout...'
  & git -C $root -c core.longpaths=true submodule update --init --depth 1 backend/polystrata
  CheckGitExit 'Submodule checkout failed'
}
& git -C $sub config core.longpaths true
CheckGitExit 'Could not set Windows long path support'
$origin=(& git -C $sub remote get-url origin).Trim()
CheckGitExit 'Cannot read upstream remote'
if ($origin -ne $originExpected) {throw "Unexpected upstream remote: $origin"}

if ($Action -eq 'pin') {
  if ($Tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+-poly\.[0-9]+$') {
    throw 'Supply an explicit official release tag, e.g. -Tag v0.1.45-poly.10'
  }
  $changes=@(& git -C $sub status --porcelain)
  CheckGitExit 'Could not check the upstream working tree'
  if ($changes.Count -gt 0 -and $changes[0]) {throw 'Upstream has local modifications. Never overwrite them.'}
  if (Get-NetTCPConnection -State Listen -LocalPort 15239,15240 -ErrorAction SilentlyContinue) {
    throw 'Stop the production launcher cooperatively before changing the official checkout.'
  }
  if ($ExpectedCommit) {
    if ($ExpectedCommit -notmatch '^[0-9a-f]{40}$') {throw 'ExpectedCommit must be a full commit SHA'}
    $cached=(& git -C $sub rev-parse "refs/tags/${Tag}^{commit}").Trim()
    CheckGitExit 'Expected fetched tag is missing'
    if ($cached -ne $ExpectedCommit) {throw 'Fetched release tag does not match the verified commit'}
  } else {
    & git -C $sub -c core.longpaths=true fetch --depth 1 origin "refs/tags/${Tag}:refs/tags/${Tag}"
    CheckGitExit 'Failed to fetch the requested official tag'
  }
  & git -C $sub -c core.longpaths=true checkout --detach "refs/tags/$Tag"
  CheckGitExit 'Could not check out the official tag'
  & git -C $root add backend/polystrata
  CheckGitExit 'Could not stage the submodule pointer'
  Write-Host "Pinned the official engine to $Tag. Run the Gateway and engine compatibility tests before committing."
}

$sha=(& git -C $sub rev-parse HEAD).Trim()
CheckGitExit 'Could not resolve upstream commit'
$exact=@(& git -C $sub describe --tags --exact-match HEAD 2>$null)
$name=if($LASTEXITCODE -eq 0 -and $exact.Count -gt 0){$exact[0]}else{'(no exact release tag)'}
Write-Host ('PolyStrata upstream: '+$origin)
Write-Host ('Pinned SHA: '+$sha)
Write-Host ('Release tag: '+$name)
if ($Action -eq 'verify' -or $Action -eq 'pin') {
  $dirty=@(& git -C $sub status --porcelain)
  CheckGitExit 'Cannot check upstream integrity'
  if ($dirty.Count -gt 0 -and $dirty[0]) {throw 'Official upstream working tree is dirty'}
  $record=@(& git -C $root ls-files -s -- backend/polystrata)
  if ($record.Count -ne 1 -or -not $record[0].StartsWith('160000 ')) {
    throw 'Official engine is not registered as a Git submodule (160000 mode)'
  }
  $indexed=($record[0] -split '\s+')[1]
  if ($indexed -ne $sha) {throw 'Submodule directory is not at the committed/staged pin'}
  if ($name -eq '(no exact release tag)') {throw 'Pin must reference a named upstream release tag'}
  Write-Host 'PASS: official source is clean, tagged, and matches the Git submodule pointer.'
}
