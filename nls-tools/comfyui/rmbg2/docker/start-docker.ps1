param([switch]$OpenBrowser)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$runtimeRoot = Join-Path $PSScriptRoot "..\..\..\ai-runtime"

& (Join-Path $runtimeRoot "scripts\Initialize-NjsAiRuntime.ps1") -Worker rmbg2

docker compose -f $composeFile --profile light config --quiet
if ($LASTEXITCODE -ne 0) { throw "Konfiguracja Compose RMBG-2.0 jest nieprawidłowa." }

docker compose -f $composeFile --profile light up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) {
    throw "Budowanie lub uruchomienie kontenera RMBG-2.0 nie powiodło się."
}

$port = if ($env:NJS_RMBG2_PORT) { $env:NJS_RMBG2_PORT } else { "8189" }
& python (Join-Path $runtimeRoot "scripts\smoke_light_workers.py") rmbg2 --base-url "http://127.0.0.1:$port"
if ($LASTEXITCODE -ne 0) { throw "Smoke test RMBG-2.0 nie powiódł się." }

Write-Host "ComfyUI RMBG-2.0 jest gotowe pod adresem http://127.0.0.1:$port"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$port" }
