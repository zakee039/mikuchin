# Provision the isolated Native Image Worker without reading/migrating old app state.
# Model files remain in E:\LLM\models; executable and ESRGAN assets belong to
# the dedicated Native runtime, not backend/polystrata.
[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime'),
    [string]$ModelsRoot = 'E:\LLM\models',
    [string]$DataDir = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not $DataDir) { $DataDir = Join-Path $RuntimeRoot 'launcher-user-data' }
$engine = Join-Path $RuntimeRoot 'image-engines\sd-cli\sd-cli.exe'
$esrgan = Join-Path $RuntimeRoot 'image-engines\esrgan\realesrgan-ncnn-vulkan.exe'
$esrganModels = Join-Path $RuntimeRoot 'image-engines\esrgan\models'
$destination = Join-Path $DataDir 'images\config\native-local-images.json'

if (-not (Test-Path $engine -PathType Leaf)) {
    throw "Native sd-cli executable is not installed: $engine"
}
if (-not (Test-Path $esrgan -PathType Leaf)) {
    throw "Native ESRGAN executable is not installed: $esrgan"
}
if ((Test-Path $destination) -and -not $Force) {
    throw "Native image config already exists; use -Force to explicitly overwrite it: $destination"
}

$official = Join-Path $ModelsRoot 'Qwen-Image-2.1-Official-Components'
$uncensored = Join-Path $ModelsRoot 'Qwen-Image-2.1-Turbo-Uncensored-AD-Q4_K'
$loras = Join-Path $ModelsRoot 'Mikuchin-LoRA'
$args = @('--flash-attn', 'off,diffusion=on', '--backend', 'vulkan1', '--offload-to-cpu', '--vae-tiling')
$profiles = @(
    @{
        id = 'local-qwen-official'; name = 'Qwen-Image 2.1 Turbo Official'
        model = 'qwen-image-2.1-turbo-official'; family = 'qwen_turbo'
        exe = $engine; diffusion_model = (Join-Path $official 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf')
        vae = (Join-Path $official 'qwen_image_2.1_vae_bf16.safetensors')
        llm = (Join-Path $official 'Qwen3VL-8B-Instruct-Q4_K_M.gguf')
        args = $args; max_side = 1024; timeout_seconds = 1200
    },
    @{
        id = 'local-qwen-uncensored'; name = 'Qwen-Image 2.1 Turbo Uncensored'
        model = 'qwen-image-2.1-turbo-uncensored'; family = 'qwen_turbo'
        exe = $engine; diffusion_model = (Join-Path $uncensored 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf')
        vae = (Join-Path $uncensored 'qwen_image_2.1_vae_bf16.safetensors')
        llm = (Join-Path $uncensored 'Qwen-Image-2.1-Turbo-Uncensored-AD-Q4_K.gguf')
        args = $args; max_side = 1024; timeout_seconds = 1200
    }
)
# This optional projector belongs to Official's Qwen3VL-8B LLM only.
# Uncensored uses a different LLM and must not inherit it.
$officialVision = Join-Path $official 'mmproj-Qwen3VL-8B-Instruct-F16.gguf'
if (Test-Path -LiteralPath $officialVision -PathType Leaf) {
    $profiles[0].llm_vision = $officialVision
}
$loraEntries = @(
    @{ id = 'female-anatomy-v3'; name = 'Eastern Female v3'; path = (Join-Path $loras 'easternfemale_v2.1_v3.safetensors') },
    @{ id = 'anatomy-fix'; name = 'Anatomy Fix'; path = (Join-Path $loras 'Genitalia-Anatomy-2.1-v1.safetensors') },
    @{ id = 'nsfw-qwen'; name = 'NSFW Qwen'; path = (Join-Path $loras 'NSFW-Qwen-Lora.safetensors') }
)
$upscaler = @{
    enabled = $true; exe = $esrgan; model_dir = $esrganModels
    model = 'realesrgan-x4plus-anime'; tile = 128; gpu = 1
    timeout_seconds = 180; max_output_side = 3072
}
foreach ($profile in $profiles) {
    foreach ($key in @('exe','diffusion_model','vae','llm')) {
        if (-not (Test-Path $profile[$key] -PathType Leaf)) {
            throw "$($profile.id) missing $key = $($profile[$key])"
        }
    }
}
foreach ($entry in $loraEntries) {
    if (-not (Test-Path $entry.path -PathType Leaf)) { throw "LoRA file missing: $($entry.path)" }
}
foreach ($suffix in @('bin','param')) {
    if (-not (Test-Path (Join-Path $esrganModels "realesrgan-x4plus-anime.$suffix") -PathType Leaf)) {
        throw "ESRGAN model is missing $suffix"
    }
}
New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
@{ profiles=$profiles; loras=$loraEntries; upscaler=$upscaler } |
    ConvertTo-Json -Depth 12 |
    Set-Content -Path $destination -Encoding UTF8
Write-Host "Native image configuration written: $destination"
Write-Host "2 Qwen-Image profiles, 3 LoRAs, Real-ESRGAN 4x. No model copied or charged."
