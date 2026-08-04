# RemoveBg przez RMBG-2.0

Automatyczny worker usuwania tła. Zwraca PNG RGBA i osobną maskę alfa. Jest
częścią profilu `light` opisanego w `nls-tools/ai-runtime/README.md`.

## Powtarzalność, źródła i licencja

- ComfyUI i custom node są przypięte pełnymi commitami;
- repozytoria mają konfigurowalne adresy podstawowe i mirrory, ale checkout
  musi odpowiadać przypiętemu commitowi;
- cztery artefakty RMBG-2.0 mają stałe rozmiary i SHA-256 w manifeście modelu;
- adres Hugging Face zawiera niezmienny revision, a prywatny mirror może być
  ustawiony przez `NJS_AI_MODEL_MIRROR`;
- model jest przygotowywany przed startem i montowany tylko do odczytu;
- entrypoint sprawdza pełne SHA-256, a readiness sprawdza model, CUDA i node.

Wagi BRIA RMBG-2.0 do samodzielnego hostowania nie są automatycznie objęte
licencją komercyjną. Po potwierdzeniu właściwej licencji dla planowanego użycia
ustaw w ignorowanym `nls-tools/ai-runtime/.env`:

```dotenv
NJS_RMBG2_LICENSE_ACCEPTED=1
```

Bez jawnej akceptacji inicjalizator nie pobierze ani nie przeniesie wag.

## Uruchomienie

Wymagane są Docker Desktop z WSL2 i NVIDIA GPU. Wybierz odpowiedni przykład z
`nls-tools/ai-runtime`, zapisz go jako `.env`, przejrzyj rooty hosta i uruchom z
głównego katalogu repozytorium:

```powershell
.\nls-tools\comfyui\rmbg2\docker\start-docker.ps1 -OpenBrowser
```

Bez `-OpenBrowser` skrypt tylko buduje, uruchamia, czeka na healthcheck i
wykonuje smoke test. Domyślny adres to `http://127.0.0.1:8189`; port jest
związany z loopbackiem. Gateway powinien korzystać z sieci `njs-ai` i aliasu
`rmbg2-worker`.

Trwały układ jest względny wobec wybranych rootów hosta:

```text
${NJS_AI_MODELS_ROOT}/comfyui/RMBG
${NJS_AI_DATA_ROOT}/workers/rmbg2/{input,output,user,temp}
${NJS_AI_CACHE_ROOT}/rmbg2
```

Zweryfikowane pliki z opcjonalnych `NJS_AI_MODEL_IMPORT_ROOTS` są kopiowane;
źródłowe katalogi nie są modyfikowane ani usuwane.

## API

```powershell
python .\nls-tools\comfyui\rmbg2\scripts\rmbg_api_client.py `
  ".\zdjecie.png" `
  --output-dir ".\api-results"
```

Klient wykonuje upload, kolejkuje wersjonowany workflow, czeka po `processID`
i pobiera wycięty PNG oraz maskę do osobnego katalogu zadania. W GUI wybierz
`RemoveBg by RMBG-2.0`; domyślne parametry krawędzi to
`refine_foreground=true`, `mask_blur=0`, `mask_offset=-1`.

```powershell
docker compose -f .\nls-tools\comfyui\rmbg2\docker\compose.yaml --profile light logs -f
docker compose -f .\nls-tools\comfyui\rmbg2\docker\compose.yaml --profile light down
python .\nls-tools\ai-runtime\scripts\smoke_light_workers.py rmbg2
```
