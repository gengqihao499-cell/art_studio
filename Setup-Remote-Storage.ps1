$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectDir "backend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$envFile = Join-Path $backendDir ".env"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Backend environment is missing. Run Setup-ArtFlow.cmd first."
}
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $backendDir ".env.example") -Destination $envFile
}

Write-Host "Installing optional OSS and Milvus adapters..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $backendDir "requirements-remote.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Remote storage dependency installation failed."
}

Write-Host "Optional adapters installed." -ForegroundColor Green
Write-Host "Configure OSS/Milvus in: $envFile" -ForegroundColor Yellow
Write-Host "Detailed steps: docs\remote-storage-guide.md" -ForegroundColor Yellow
Start-Process -FilePath "notepad.exe" -ArgumentList $envFile
