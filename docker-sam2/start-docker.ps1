$ErrorActionPreference = "Stop"

$composeFile = Join-Path $PSScriptRoot "compose.yaml"

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop nie działa. Uruchom Docker Desktop i spróbuj ponownie."
}

docker compose -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Budowanie lub uruchomienie kontenera nie powiodło się."
}

Write-Host "ComfyUI SAM2 uruchamia się pod adresem http://localhost:8188"
Start-Process "http://localhost:8188"
