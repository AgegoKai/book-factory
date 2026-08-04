param([switch]$OpenBrowser)

$ErrorActionPreference = "Stop"
$canonicalScript = Join-Path $PSScriptRoot "..\nls-tools\comfyui\rmbg2\docker\start-docker.ps1"
Write-Warning "docker-rmbg jest ścieżką zgodności. Używam kanonicznego setupu nls-tools/comfyui/rmbg2."
& $canonicalScript -OpenBrowser:$OpenBrowser
