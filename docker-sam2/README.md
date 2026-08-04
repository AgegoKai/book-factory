# SAM2 point segmentation worker

Interaktywny worker segmentacji SAM2.1 do korekty maski punktami. Jest częścią
profilu `light` i korzysta ze wspólnego runtime w `nls-tools/ai-runtime`.

Setup przypina digest obrazu CUDA, pełne commity ComfyUI/custom nodes oraz
dokładne wersje bezpośrednich zależności Pythona. Checkpoint ma stały rozmiar i
SHA-256 w `nls-tools/ai-runtime/models/sam2.1-hiera-large.json`; może pochodzić
z oficjalnego adresu Meta, przypiętej rewizji zapasowej lub kontrolowanego
mirrora. Kontener nie pobiera modelu i montuje go tylko do odczytu.

Wybierz odpowiedni przykład konfiguracji z `nls-tools/ai-runtime`, zapisz go
jako ignorowany `.env` i uruchom z katalogu głównego repozytorium:

```powershell
.\docker-sam2\start-docker.ps1 -OpenBrowser
```

Domyślny adres to `http://127.0.0.1:8188`. Gateway powinien korzystać z
zewnętrznej sieci Docker `njs-ai` oraz aliasu `sam2-worker`.

Trwały układ jest względny wobec wybranych rootów hosta:

```text
${NJS_AI_MODELS_ROOT}/comfyui/sam2
${NJS_AI_DATA_ROOT}/workers/sam2/{input,output,user,temp}
${NJS_AI_CACHE_ROOT}/sam2
```

Opcjonalne rooty importu pozwalają ponownie wykorzystać zweryfikowany
checkpoint bez wiązania setupu z poprzednią ścieżką. Wersjonowany workflow i
jego manifest są kopiowane bez nadpisywania zmian użytkownika.

```powershell
docker compose -f .\docker-sam2\compose.yaml --profile light logs -f
docker compose -f .\docker-sam2\compose.yaml --profile light down
python .\nls-tools\ai-runtime\scripts\smoke_light_workers.py sam2
```
