param([switch]$OpenBrowser)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$runtimeRoot = Join-Path $PSScriptRoot "..\nls-tools\ai-runtime"

& (Join-Path $runtimeRoot "scripts\Initialize-NjsAiRuntime.ps1") -Worker sam2

docker compose -f $composeFile --profile light config --quiet
if ($LASTEXITCODE -ne 0) { throw "Konfiguracja Compose SAM2 jest nieprawidłowa." }

docker compose -f $composeFile --profile light up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) {
    throw "Budowanie lub uruchomienie kontenera nie powiodło się."
}

$port = if ($env:NJS_SAM2_PORT) { $env:NJS_SAM2_PORT } else { "8188" }
& python (Join-Path $runtimeRoot "scripts\smoke_light_workers.py") sam2 --base-url "http://127.0.0.1:$port"
if ($LASTEXITCODE -ne 0) { throw "Smoke test SAM2 nie powiódł się." }

Write-Host "ComfyUI SAM2 jest gotowe pod adresem http://127.0.0.1:$port"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$port" }
