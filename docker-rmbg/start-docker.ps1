$ErrorActionPreference = "Stop"

$directories = @(
    "D:\ComfyAi\models\RMBG",
    "D:\ComfyAi\input",
    "D:\ComfyAi\output",
    "D:\ComfyAi\user\default\workflows",
    "D:\ComfyAi\temp-rmbg",
    "D:\ComfyAi\hf_cache"
)
$directories | ForEach-Object { New-Item -ItemType Directory -Force $_ | Out-Null }

$composeFile = Join-Path $PSScriptRoot "compose.yaml"

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop nie działa. Uruchom Docker Desktop i spróbuj ponownie."
}

docker compose -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Budowanie lub uruchomienie kontenera RMBG-2.0 nie powiodło się."
}

Write-Host "ComfyUI RMBG-2.0 uruchamia się pod adresem http://localhost:8189"
Start-Process "http://localhost:8189"
