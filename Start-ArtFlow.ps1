param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectDir "backend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$frontendIndex = Join-Path $projectDir "frontend\dist\index.html"
$appUrl = "http://127.0.0.1:8000"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Backend environment is missing. Run .\Setup-ArtFlow.cmd first."
}
if (-not (Test-Path -LiteralPath $frontendIndex)) {
    throw "Frontend build is missing. Run .\Setup-ArtFlow.ps1 -BuildFrontend."
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    8000
)
try {
    $listener.Start()
}
catch [System.Net.Sockets.SocketException] {
    Write-Host "Port 8000 is already in use:" -ForegroundColor Red
    netstat -ano -p tcp | Select-String -Pattern ":8000\s"
    throw "Stop the process using port 8000, then launch ArtFlow again."
}
finally {
    $listener.Stop()
}

$envPath = Join-Path $backendDir ".env"
$mode = "mock"
$agentMode = "mock"
if (Test-Path -LiteralPath $envPath) {
    $modeLine = Get-Content -LiteralPath $envPath -Encoding utf8 |
        Where-Object { $_ -match "^\s*ARTFLOW_IMAGE_BACKEND\s*=" } |
        Select-Object -Last 1
    if ($modeLine) {
        $mode = ($modeLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
    }
    $agentModeLine = Get-Content -LiteralPath $envPath -Encoding utf8 |
        Where-Object { $_ -match "^\s*ARTFLOW_AGENT_BACKEND\s*=" } |
        Select-Object -Last 1
    if ($agentModeLine) {
        $agentMode = ($agentModeLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
    }
}

Write-Host "Configuration file: $envPath" -ForegroundColor DarkGray

if ($mode -eq "comfyui") {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 3 | Out-Null
        Write-Host "ComfyUI connected: http://127.0.0.1:8188" -ForegroundColor Green
    }
    catch {
        Write-Warning "ComfyUI mode is enabled, but port 8188 is unavailable. Start ComfyUI before generating."
    }
}
elseif ($mode -eq "qwen_image" -or $agentMode -eq "qwen") {
    $qwenConfig = Get-Content -LiteralPath $envPath -Encoding utf8
    $hasKey = $qwenConfig | Where-Object { $_ -match "^\s*DASHSCOPE_API_KEY\s*=\s*\S+" }
    $hasWorkspace = $qwenConfig | Where-Object { $_ -match "^\s*DASHSCOPE_WORKSPACE_ID\s*=\s*\S+" }
    $hasApiHost = $qwenConfig | Where-Object { $_ -match "^\s*DASHSCOPE_API_HOST\s*=\s*\S+" }
    if (-not $hasKey -or (-not $hasWorkspace -and -not $hasApiHost)) {
        throw "Qwen mode is selected, but the actual backend\.env is incomplete. Add DASHSCOPE_API_KEY and DASHSCOPE_WORKSPACE_ID (or DASHSCOPE_API_HOST) to: $envPath"
    }
}
else {
    Write-Host "DEMO MODE: Qwen will NOT be called and generated images are local examples." -ForegroundColor Yellow
    Write-Host "To enable Qwen, set ARTFLOW_AGENT_BACKEND=qwen and ARTFLOW_IMAGE_BACKEND=qwen_image in the configuration file above." -ForegroundColor Yellow
}

$browserJob = $null
if (-not $NoBrowser) {
    $browserJob = Start-Job -ScriptBlock {
        param($url)
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try {
                Invoke-WebRequest -UseBasicParsing -Uri "$url/api/health" -TimeoutSec 1 | Out-Null
                Start-Process $url
                return
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
    } -ArgumentList $appUrl
}

Write-Host ""
Write-Host "Starting ArtFlow Studio: $appUrl" -ForegroundColor Cyan
Write-Host "Agent backend: $agentMode | Image backend: $mode. Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host ""

Push-Location $backendDir
try {
    # Packaged mode intentionally avoids --reload so no watcher process is left behind.
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
    if ($browserJob) {
        Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
