$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectDir "backend\.env"
$examplePath = Join-Path $projectDir "backend\.env.example"

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $examplePath -Destination $envPath
}

# This helper is explicitly for enabling Qwen. Set only the two provider
# switches; credentials and every other user setting are preserved verbatim.
$lines = [System.Collections.Generic.List[string]]::new()
[System.IO.File]::ReadAllLines($envPath) | ForEach-Object { [void]$lines.Add($_) }
$agentFound = $false
$imageFound = $false
for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index] -match "^\s*ARTFLOW_AGENT_BACKEND\s*=") {
        $lines[$index] = "ARTFLOW_AGENT_BACKEND=qwen"
        $agentFound = $true
    }
    if ($lines[$index] -match "^\s*ARTFLOW_IMAGE_BACKEND\s*=") {
        $lines[$index] = "ARTFLOW_IMAGE_BACKEND=qwen_image"
        $imageFound = $true
    }
}
if (-not $agentFound) { $lines.Insert(0, "ARTFLOW_AGENT_BACKEND=qwen") }
if (-not $imageFound) { $lines.Insert(1, "ARTFLOW_IMAGE_BACKEND=qwen_image") }
[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))

Write-Host "Opening the configuration file used by this ArtFlow copy:" -ForegroundColor Cyan
Write-Host $envPath -ForegroundColor Yellow
Write-Host "Qwen mode is enabled. Fill the API Key and ws- Workspace ID, save, then restart ArtFlow." -ForegroundColor Green
Start-Process -FilePath "notepad.exe" -ArgumentList $envPath
