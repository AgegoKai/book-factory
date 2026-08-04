param([switch]$OpenBrowser)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$runtimeRoot = Join-Path $PSScriptRoot "..\..\..\ai-runtime"

& (Join-Path $runtimeRoot "scripts\Initialize-NjsAiRuntime.ps1") -Worker lama

docker compose -f $composeFile --profile light config --quiet
if ($LASTEXITCODE -ne 0) { throw "Konfiguracja Compose LaMa jest nieprawidłowa." }

docker compose -f $composeFile --profile light up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) {
    throw "Budowanie lub uruchomienie LaMa Cleanup nie powiodło się."
}

$port = if ($env:NJS_LAMA_PORT) { $env:NJS_LAMA_PORT } else { "8090" }
& python (Join-Path $runtimeRoot "scripts\smoke_light_workers.py") lama --base-url "http://127.0.0.1:$port"
if ($LASTEXITCODE -ne 0) { throw "Smoke test LaMa nie powiódł się." }

Write-Host "LaMa Cleanup jest gotowe pod adresem http://127.0.0.1:$port"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$port" }
