<#
  End-to-end, no-GPU smoke test of our *actual official PolyStrata server*
  behind the native Mikuchin Gateway. Uses only the official mock engine,
  generates temporary API keys, and closes both child processes on exit.

  Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke-native-transport.ps1
  No model, PyTorch, key, chat history, or paid image provider is used.
#>
[CmdletBinding()]
param(
  [int]$UpstreamPort = 15240,
  [int]$GatewayPort = 15249,
  [string]$RuntimeRoot = '',
  [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$upstream = Join-Path $root 'backend\polystrata'
$runtime = if ($RuntimeRoot) {$RuntimeRoot} else {Join-Path (Split-Path $root -Parent) 'mikuchin-native-runtime'}
if (-not $Python) {$Python = Join-Path $runtime '.venv\Scripts\python.exe'}
$logs = Join-Path $runtime 'smoke-logs'
$smokeData = Join-Path $runtime ('smoke-data-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
if (-not (Test-Path $Python)) { throw "Missing isolated Python runtime: $Python" }
if ($UpstreamPort -eq $GatewayPort -or $UpstreamPort -eq 15239 -or $GatewayPort -eq 15239) {
  throw 'Ports must be separate and must never use the stable Mikuchin 15239.'
}
foreach ($port in @($UpstreamPort, $GatewayPort)) {
  if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Port $port is occupied; refusing to touch an existing service."
  }
}
$random = [byte[]]::new(32)
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($random)
$upstreamKey = [Convert]::ToBase64String($random)
$rng.GetBytes($random)
$gatewayKey = [Convert]::ToBase64String($random)
[Array]::Clear($random, 0, $random.Length)
$rng.Dispose()

$officialProcess = $null
$gatewayProcess = $null
$previous = @{}
foreach ($name in @('STRATA_API_KEY','MIKUCHIN_GATEWAY_API_KEY','MIKUCHIN_UPSTREAM_API_KEY','MIKUCHIN_NATIVE_DATA_DIR','PYTHONDONTWRITEBYTECODE')) {
  $previous[$name] = [Environment]::GetEnvironmentVariable($name,'Process')
}
function Set-Env([string]$key,[string]$value) {
  [Environment]::SetEnvironmentVariable($key,$value,'Process')
}
function Check-Ready([string]$name,[string]$url,[hashtable]$headers,[int]$timeoutSeconds=15) {
  $deadline = [DateTime]::UtcNow.AddSeconds($timeoutSeconds)
  do {
    try {
      $result = Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 2
      if ($result.status -eq 'ok') { return $result }
    } catch {}
    Start-Sleep -Milliseconds 200
  } while ([DateTime]::UtcNow -lt $deadline)
  throw "$name failed to start; inspect local smoke-logs (never includes API keys)."
}

try {
  Set-Env 'PYTHONDONTWRITEBYTECODE' '1'
  Set-Env 'STRATA_API_KEY' $upstreamKey
  $officialProcess = Start-Process -FilePath $Python -WorkingDirectory $upstream -ArgumentList @(
    '-B','-m','serve.server','--engine','mock','--host','127.0.0.1',
    '--port',"$UpstreamPort",'--script','Official_mock_OK') `
    -RedirectStandardOutput (Join-Path $logs 'official.out.log') `
    -RedirectStandardError (Join-Path $logs 'official.err.log') -PassThru -WindowStyle Hidden

  $upHeaders = @{ Authorization = 'Bearer ' + $upstreamKey }
  $upStatus = Check-Ready 'Official PolyStrata mock' "http://127.0.0.1:$UpstreamPort/health" $upHeaders
  Write-Output ('OFFICIAL_MOCK_OK port=' + $UpstreamPort)

  Set-Env 'MIKUCHIN_GATEWAY_API_KEY' $gatewayKey
  Set-Env 'MIKUCHIN_UPSTREAM_API_KEY' $upstreamKey
  Set-Env 'MIKUCHIN_NATIVE_DATA_DIR' $smokeData
  $gatewayProcess = Start-Process -FilePath $Python -WorkingDirectory $root -ArgumentList @(
    '-B','-m','backend.gateway.app','--host','127.0.0.1',
    '--port',"$GatewayPort",'--upstream-port',"$UpstreamPort") `
    -RedirectStandardOutput (Join-Path $logs 'gateway.out.log') `
    -RedirectStandardError (Join-Path $logs 'gateway.err.log') -PassThru -WindowStyle Hidden

  $headers = @{ Authorization = 'Bearer ' + $gatewayKey }
  $status = Check-Ready 'Mikuchin Gateway' "http://127.0.0.1:$GatewayPort/health" $headers
  if (-not $status.official_polystrata_reachable) { throw 'Gateway cannot reach official engine' }
  $models = Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/v1/models" -Headers $headers -TimeoutSec 5
  if (-not $models.data) { throw 'Official /v1/models returned no data' }
  Write-Output ('GATEWAY_MODELS_OK count=' + @($models.data).Count)

  $headers['Content-Type'] = 'application/json'
  $payload = '{"model":"mock","messages":[{"role":"user","content":"ping"}],"stream":false,"max_tokens":64}'
  $response = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:$GatewayPort/v1/chat/completions" `
    -Headers $headers -Body $payload -TimeoutSec 15
  if (-not @($response.choices).Count) { throw 'Official chat response did not pass Gateway' }
  Write-Output 'GATEWAY_CHAT_OK'

  # Native conversation CRUD happens entirely inside Gateway's own isolated
  # SQLite file. It must not reach official PolyStrata or touch existing chats.
  $testId = [Guid]::NewGuid().ToString('N')
  $charApi = "http://127.0.0.1:$GatewayPort/v1/strata/characters"
  $world = Join-Path $smokeData 'smoke-world.md'
  $workflow = Join-Path $smokeData 'smoke-workflow.md'
  [IO.File]::WriteAllText($world, "# Starlight`nStarlight lessons are at night.")
  [IO.File]::WriteAllText($workflow, "## Initialization`nGreet once`n## Persistent rules`nBe concise")
  $newCard = @{action='save';card=@{
    name=('Native role ' + $testId.Substring(0,8));
    sources=@(@{kind='file';path=$world;recursive=$false});
    workflow_path=$workflow
  }} | ConvertTo-Json -Depth 8 -Compress
  $card = (Invoke-RestMethod -Method POST -Uri $charApi -Headers $headers -Body $newCard -TimeoutSec 5).card
  if (-not $card.id) {throw 'Cannot save native role card'}
  $assign = @{action='assign';session_id=$testId;card_id=$card.id}|ConvertTo-Json -Compress
  $assigned=Invoke-RestMethod -Method POST -Uri $charApi -Headers $headers -Body $assign -TimeoutSec 5
  if (-not $assigned.saved) {throw 'Cannot assign role to new empty session'}
  $retrieval = @{action='retrieve';session_id=$testId;query='Starlight lessons'}|ConvertTo-Json -Compress
  $hits=Invoke-RestMethod -Method POST -Uri $charApi -Headers $headers -Body $retrieval -TimeoutSec 5
  if (-not $hits.snippets -or $hits.snippets[0].content -notmatch 'night') {
    throw 'Independent Markdown worldbook retrieval failed'
  }
  $flowPrepare=@{action='prepare_workflow';session_id=$testId;first_user_turn=$true}|ConvertTo-Json -Compress
  $prepared=Invoke-RestMethod -Method POST -Uri $charApi -Headers $headers -Body $flowPrepare -TimeoutSec 5
  if (-not $prepared.initial_pending) {throw 'First-turn workflow was not prepared'}
  $flowCommit=@{action='commit_workflow';session_id=$testId}|ConvertTo-Json -Compress
  $committed=Invoke-RestMethod -Method POST -Uri $charApi -Headers $headers -Body $flowCommit -TimeoutSec 5
  if (-not $committed.committed) {throw 'Workflow first-turn commit failed'}
  Write-Output 'GATEWAY_CHARACTER_WORLD_WORKFLOW_OK'

  $sessionBody = @{id=$testId;web_messages=@(@{role='user';text='Native smoke turn'})} | ConvertTo-Json -Depth 6 -Compress
  $saved = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:$GatewayPort/v1/strata/sessions" `
    -Headers $headers -Body $sessionBody -TimeoutSec 5
  if (-not $saved.saved -or $saved.id -ne $testId) {throw 'Native conversation save failed'}
  $loaded = Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/v1/strata/sessions/$testId" `
    -Headers $headers -TimeoutSec 5
  if ($loaded.web_messages[0].text -ne 'Native smoke turn') {throw 'Native conversation read failed'}
  try {
    $move=@{action='assign';session_id=$testId;card_id='ordinary'}|ConvertTo-Json -Compress
    Invoke-RestMethod -Method POST -Uri $charApi -Headers $headers -Body $move -TimeoutSec 5|Out-Null
    throw 'Role changed after first turn, expected HTTP 400'
  } catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 400) {throw}
  }
  $deleted = Invoke-RestMethod -Method DELETE -Uri "http://127.0.0.1:$GatewayPort/v1/strata/sessions/$testId" `
    -Headers $headers -TimeoutSec 5
  if (-not $deleted.deleted) {throw 'Native conversation delete failed'}
  $roles=Invoke-RestMethod -Uri $charApi -Headers $headers -TimeoutSec 5
  if ($roles.assignments.PSObject.Properties.Name -contains $testId) {
    throw 'Deleted conversation still holds a character assignment'
  }
  Write-Output 'GATEWAY_NATIVE_SESSIONS_OK'

  # Native online image adapter: service registry and drafts are offline.
  # Never activate a task in this smoke test: even a local fake service can
  # accidentally become chargeable if a user substitutes their configuration.
  $imageApi = "http://127.0.0.1:$GatewayPort/v1/mikuchin/image-api-services"
  $jobApi = "http://127.0.0.1:$GatewayPort/v1/mikuchin/image-jobs"
  $imageSettings = @{action='save';service=@{
    name='Offline native smoke';model='fake-image';api_key='DO_NOT_USE_ON_PUBLIC_PROVIDERS';
    base_url='http://127.0.0.1:19999/v1';sizes='standard'
  }} | ConvertTo-Json -Depth 5 -Compress
  $profile=(Invoke-RestMethod -Method POST -Uri $imageApi -Headers $headers `
    -Body $imageSettings -TimeoutSec 5).service
  if (-not $profile.id -or $profile.api_key -or -not $profile.has_key) {
    throw 'Native image service credentials leaked or failed to save'
  }
  $imageReq=@{action='draft';request=@{prompt='Offline native smoke';size='1536x1536';
    strata_image_profile=$profile.id;strata_upscale='off'}} | ConvertTo-Json -Depth 6 -Compress
  $draft=Invoke-RestMethod -Method POST -Uri $jobApi -Headers $headers -Body $imageReq -TimeoutSec 5
  if ($draft.state -ne 'draft') {throw 'Native image draft was not persisted offline'}
  $galleryItems=Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/v1/mikuchin/gallery" `
    -Headers $headers -TimeoutSec 5
  if ($galleryItems.total -ne 0) {throw 'Offline smoke unexpectedly generated an image'}
  $remove=@{action='delete';id=$draft.id}|ConvertTo-Json -Compress
  $removed=Invoke-RestMethod -Method POST -Uri $jobApi -Headers $headers -Body $remove -TimeoutSec 5
  if ($removed.deleted -ne 1) {throw 'Cannot delete native image draft'}
  Write-Output 'GATEWAY_IMAGE_SERVICES_DRAFT_GALLERY_OFFLINE_OK'

  $sseBody = '{"model":"mock","messages":[{"role":"user","content":"ping"}],"stream":true,"max_tokens":32}'
  $sse = Invoke-WebRequest -Method POST -Uri "http://127.0.0.1:$GatewayPort/v1/chat/completions" `
    -Headers $headers -Body $sseBody -UseBasicParsing -TimeoutSec 15
  if ($sse.Content -notmatch 'data:') { throw 'SSE frames did not pass Gateway' }
  Write-Output 'GATEWAY_SSE_OK'

  try {
    $bad = '{"model":"mock","messages":[],"answer_budget_tokens":128,"max_tokens":8}'
    Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:$GatewayPort/v1/chat/completions" `
      -Headers $headers -Body $bad -TimeoutSec 5 | Out-Null
    throw 'Gateway silently accepted unported visible-answer-budget semantics'
  } catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 501) { throw }
  }
  Write-Output 'UNPORTED_SEMANTICS_BLOCKED_OK'
  Write-Output 'NATIVE_OFFICIAL_TRANSPORT_SMOKE_PASS'
} finally {
  foreach ($p in @($gatewayProcess,$officialProcess)) {
    if ($null -ne $p) {
      try {
        $proc = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
        if ($proc) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
      } catch {}
      $p.Dispose()
    }
  }
  foreach ($entry in $previous.GetEnumerator()) {Set-Env $entry.Key $entry.Value}
  if (Test-Path $smokeData) {
    Remove-Item -LiteralPath $smokeData -Recurse -Force -ErrorAction SilentlyContinue
  }
  $upstreamKey = $null
  $gatewayKey = $null
}
