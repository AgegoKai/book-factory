param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("sam2", "rmbg2", "lama", "all")]
    [string]$Worker,
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$runtimeRoot = Split-Path -Parent $PSScriptRoot

function Import-DotEnv([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $name, $value = $trimmed.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Set-DefaultEnvironment([string]$Name, [string]$Value) {
    if (-not [Environment]::GetEnvironmentVariable($Name, "Process")) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

function Invoke-DockerQuiet([string[]]$Arguments) {
    # Windows PowerShell turns native stderr into an ErrorRecord. Docker uses
    # stderr for expected negative probes (for example a missing network), so
    # temporarily keep those probes non-terminating and return only the code.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & docker @Arguments *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

if (-not $EnvFile) {
    $EnvFile = Join-Path $runtimeRoot ".env"
}
Import-DotEnv $EnvFile
Set-DefaultEnvironment "NJS_AI_NETWORK" "njs-ai"
Set-DefaultEnvironment "NJS_AI_BIND_ADDRESS" "127.0.0.1"

$modelsRoot = [Environment]::GetEnvironmentVariable("NJS_AI_MODELS_ROOT", "Process")
$dataRoot = [Environment]::GetEnvironmentVariable("NJS_AI_DATA_ROOT", "Process")
$cacheRoot = [Environment]::GetEnvironmentVariable("NJS_AI_CACHE_ROOT", "Process")

if (-not $modelsRoot -or -not $dataRoot -or -not $cacheRoot) {
    throw "Brak konfiguracji katalogów runtime. Skopiuj nls-tools/ai-runtime/.env.example jako .env i ustaw NJS_AI_MODELS_ROOT, NJS_AI_DATA_ROOT oraz NJS_AI_CACHE_ROOT."
}

$requireDDrive = $env:NJS_AI_REQUIRE_D_DRIVE -and $env:NJS_AI_REQUIRE_D_DRIVE.Trim().ToLowerInvariant() -in @("1", "true", "yes")
if ($env:OS -eq "Windows_NT" -and $requireDDrive) {
    foreach ($path in @($modelsRoot, $dataRoot, $cacheRoot)) {
        $fullPath = [IO.Path]::GetFullPath($path)
        if (-not $fullPath.StartsWith("D:\AI\", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Na stacji Windows wszystkie dane AI muszą znajdować się pod D:\AI. Nieprawidłowa ścieżka: $path"
        }
    }
}

$workers = if ($Worker -eq "all") { @("sam2", "rmbg2", "lama") } else { @($Worker) }
$manifestNames = @{
    sam2 = "sam2.1-hiera-large.json"
    rmbg2 = "rmbg-2.0.json"
    lama = "big-lama.json"
}

foreach ($name in $workers) {
    foreach ($folder in @("input", "output", "user", "temp")) {
        New-Item -ItemType Directory -Force (Join-Path $dataRoot "workers/$name/$folder") | Out-Null
    }
    New-Item -ItemType Directory -Force (Join-Path $cacheRoot "$name/huggingface") | Out-Null
    $manifest = Join-Path $runtimeRoot "models/$($manifestNames[$name])"
    $prepareArguments = @(
        $manifest,
        "--models-root", $modelsRoot,
        "--cache-root", (Join-Path $cacheRoot "model-downloads")
    )
    if ($env:NJS_AI_MODEL_MIRROR) {
        $prepareArguments += @("--mirror", $env:NJS_AI_MODEL_MIRROR)
    }
    if ($env:NJS_AI_MODEL_IMPORT_ROOTS) {
        $separator = [Regex]::Escape([string][IO.Path]::PathSeparator)
        foreach ($importRoot in ($env:NJS_AI_MODEL_IMPORT_ROOTS -split $separator)) {
            if ($importRoot.Trim()) {
                $prepareArguments += @("--import-root", $importRoot.Trim())
            }
        }
    }
    & python (Join-Path $PSScriptRoot "prepare_model_artifacts.py") @prepareArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Przygotowanie modeli dla $name nie powiodło się."
    }
}

if ((Invoke-DockerQuiet @("info")) -ne 0) {
    throw "Docker Desktop nie działa. Uruchom Docker Desktop i spróbuj ponownie."
}

$network = $env:NJS_AI_NETWORK
if ((Invoke-DockerQuiet @("network", "inspect", $network)) -ne 0) {
    if ((Invoke-DockerQuiet @("network", "create", "--driver", "bridge", $network)) -ne 0) {
        throw "Nie udało się utworzyć sieci Docker $network."
    }
}

Write-Host "NJS AI runtime przygotowany: modele=$modelsRoot dane=$dataRoot sieć=$network"
