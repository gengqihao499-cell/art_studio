$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectDir "backend\.env"

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "backend\.env is missing. Copy backend\.env.example and configure ComfyUI first."
}

$settings = @{}
foreach ($line in Get-Content -LiteralPath $envPath -Encoding utf8) {
    if ($line -match "^\s*([^#][^=]*)=(.*)$") {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim().Trim('"').Trim("'")
        $settings[$key] = $value
    }
}

$baseUrl = if ($settings["COMFYUI_BASE_URL"]) {
    $settings["COMFYUI_BASE_URL"].TrimEnd("/")
} else {
    "http://127.0.0.1:8188"
}
$model = $settings["ARTFLOW_BASE_MODEL"]
$lora = $settings["ARTFLOW_DEFAULT_LORA"]

Write-Host "[1/3] Checking ComfyUI service: $baseUrl" -ForegroundColor Cyan
Invoke-RestMethod -Uri "$baseUrl/system_stats" -TimeoutSec 5 | Out-Null
Write-Host "Service is available." -ForegroundColor Green

Write-Host "[2/3] Checking checkpoint: $model" -ForegroundColor Cyan
$checkpointInfo = Invoke-RestMethod -Uri "$baseUrl/object_info/CheckpointLoaderSimple" -TimeoutSec 10
$checkpoints = @($checkpointInfo.CheckpointLoaderSimple.input.required.ckpt_name[0])
if (-not $model -or $checkpoints -notcontains $model) {
    Write-Host "The configured checkpoint is unavailable. ComfyUI reports:" -ForegroundColor Red
    $checkpoints | ForEach-Object { Write-Host "  - $_" }
    throw "Fix ARTFLOW_BASE_MODEL in backend\.env."
}
Write-Host "Checkpoint matched." -ForegroundColor Green

Write-Host "[3/3] Checking LoRA" -ForegroundColor Cyan
if ($lora) {
    $loraInfo = Invoke-RestMethod -Uri "$baseUrl/object_info/LoraLoader" -TimeoutSec 10
    $loras = @($loraInfo.LoraLoader.input.required.lora_name[0])
    if ($loras -notcontains $lora) {
        Write-Host "The configured LoRA is unavailable: $lora" -ForegroundColor Red
        $loras | ForEach-Object { Write-Host "  - $_" }
        throw "Fix ARTFLOW_DEFAULT_LORA in backend\.env or leave it empty."
    }
    Write-Host "LoRA matched." -ForegroundColor Green
}
else {
    Write-Host "LoRA is not configured; skipped." -ForegroundColor Yellow
}

if ($settings["ARTFLOW_IMAGE_BACKEND"] -ne "comfyui") {
    Write-Warning "Connectivity passed, but ARTFLOW_IMAGE_BACKEND is not set to comfyui."
}
else {
    Write-Host ""
    Write-Host "All ComfyUI integration checks passed." -ForegroundColor Green
}
