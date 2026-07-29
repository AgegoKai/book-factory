$ErrorActionPreference = "Stop"

$directories = @(
    "D:\NlsTools\lama\models",
    "D:\NlsTools\lama\input",
    "D:\NlsTools\lama\output"
)
$directories | ForEach-Object { New-Item -ItemType Directory -Force $_ | Out-Null }

$composeFile = Join-Path $PSScriptRoot "compose.yaml"

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop nie działa. Uruchom Docker Desktop i spróbuj ponownie."
}

docker compose -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Budowanie lub uruchomienie LaMa Cleanup nie powiodło się."
}

$ready = $false
Write-Host "Czekam na załadowanie LaMa na GPU..."
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        Invoke-WebRequest -Uri "http://localhost:8090/api/v1/server-config" `
            -UseBasicParsing -TimeoutSec 3 | Out-Null
        $ready = $true
        break
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    throw "LaMa nie zgłosiła gotowości. Sprawdź logi poleceniem: docker compose -f `"$composeFile`" logs"
}

Write-Host "LaMa Cleanup działa na GPU pod adresem http://localhost:8090"
Start-Process "http://localhost:8090"
