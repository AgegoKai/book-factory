param(
    [string]$EnvFile = "",
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$runtimeRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $runtimeRoot)
if (-not $EnvFile) { $EnvFile = Join-Path $runtimeRoot ".env" }

& (Join-Path $PSScriptRoot "Initialize-NjsAiRuntime.ps1") -Worker all -EnvFile $EnvFile

$composeFiles = @(
    (Join-Path $repoRoot "docker-sam2\compose.yaml"),
    (Join-Path $repoRoot "nls-tools\comfyui\rmbg2\docker\compose.yaml"),
    (Join-Path $repoRoot "nls-tools\image-cleanup\lama\docker\compose.yaml")
)

foreach ($composeFile in $composeFiles) {
    docker compose -f $composeFile --profile light config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Nieprawidłowa konfiguracja Compose: $composeFile" }
}
foreach ($composeFile in $composeFiles) {
    docker compose -f $composeFile --profile light up -d --build --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw "Nie udało się uruchomić: $composeFile" }
}

$smokeScript = Join-Path $PSScriptRoot "smoke_light_workers.py"
$workerPorts = @{
    sam2 = if ($env:NJS_SAM2_PORT) { $env:NJS_SAM2_PORT } else { "8188" }
    rmbg2 = if ($env:NJS_RMBG2_PORT) { $env:NJS_RMBG2_PORT } else { "8189" }
    lama = if ($env:NJS_LAMA_PORT) { $env:NJS_LAMA_PORT } else { "8090" }
}
foreach ($worker in @("sam2", "rmbg2", "lama")) {
    & python $smokeScript $worker --base-url "http://127.0.0.1:$($workerPorts[$worker])"
    if ($LASTEXITCODE -ne 0) { throw "Smoke test $worker nie powiódł się." }
}

Write-Host "Profil light jest gotowy: SAM2, RMBG-2.0 i LaMa."
if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$($workerPorts.sam2)"
    Start-Process "http://127.0.0.1:$($workerPorts.rmbg2)"
    Start-Process "http://127.0.0.1:$($workerPorts.lama)"
}
