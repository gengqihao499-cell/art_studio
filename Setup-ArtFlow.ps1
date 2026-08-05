param(
    [switch]$BuildFrontend
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectDir "backend"
$frontendDir = Join-Path $projectDir "frontend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$frontendIndex = Join-Path $frontendDir "dist\index.html"

Write-Host "[1/3] Checking Python environment..." -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $venvPython)) {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python was not found. Install Python 3.11 or 3.12 and enable Add Python to PATH."
    }
    & $python.Source -m venv (Join-Path $backendDir ".venv")
}

Write-Host "[2/3] Installing backend dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency installation failed."
}

if ($BuildFrontend -or -not (Test-Path -LiteralPath $frontendIndex)) {
    Write-Host "[3/3] Building frontend assets..." -ForegroundColor Cyan
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "The prebuilt frontend is missing and Node.js/npm was not found. Install Node.js 20+ and retry."
    }
    Push-Location $frontendDir
    try {
        & $npm.Source install
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "[3/3] Prebuilt frontend found; Node.js is not required." -ForegroundColor Green
}

$envFile = Join-Path $backendDir ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $backendDir ".env.example") -Destination $envFile
    Write-Host "Created backend\.env in safe Mock mode. Run Configure-Qwen.cmd to enable Qwen." -ForegroundColor Green
}

Write-Host ""
Write-Host "Setup complete. Run .\Start-ArtFlow.cmd to launch ArtFlow Studio." -ForegroundColor Green
