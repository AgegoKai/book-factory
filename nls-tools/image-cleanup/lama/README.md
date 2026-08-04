# LaMa Cleanup — lokalny worker retuszu

Worker usuwa ręcznie zamaskowane drobne elementy zdjęcia przy użyciu LaMa i
IOPaint. Jest częścią profilu `light` opisanego w
`nls-tools/ai-runtime/README.md`; nie jest NJS AI Gatewayem.

## Powtarzalność i źródła

- obraz PyTorch/CUDA jest przypięty tagiem i digestem;
- IOPaint oraz jego kluczowe zależności mają dokładne wersje;
- checkpoint Big-LaMa ma stały rozmiar i SHA-256 w
  `nls-tools/ai-runtime/models/big-lama.json`;
- model jest przygotowywany na hoście przed startem kontenera, z cache,
  opcjonalnym mirrorem i zapasowym adresem HTTPS;
- kontener nie pobiera wag i widzi katalog modeli tylko do odczytu;
- entrypoint wykonuje pełną kontrolę SHA-256, a healthcheck sprawdza model,
  CUDA oraz `/api/v1/server-config`.

Sam fakt, że kod LaMa jest udostępniany na Apache-2.0, nie rozstrzyga warunków
dystrybucji konkretnego checkpointu Big-LaMa. Po weryfikacji prawnej ustaw w
ignorowanym `nls-tools/ai-runtime/.env`:

```dotenv
NJS_BIG_LAMA_LICENSE_ACCEPTED=1
```

Bez tego inicjalizator celowo odmówi przygotowania modelu.

## Wymagania i uruchomienie

- Windows 11, Docker Desktop z WSL2 i dostępem do NVIDIA GPU;
- trzy bezwzględne rooty runtime dobrane do hosta;
- wolny port `8090` lub własny `NJS_LAMA_PORT`.

Wybierz odpowiedni przykład z `nls-tools/ai-runtime`, zapisz go jako ignorowany
`.env`, przejrzyj ustawienia i uruchom z głównego katalogu repozytorium:

```powershell
.\nls-tools\image-cleanup\lama\docker\start-docker.ps1 -OpenBrowser
```

Bez `-OpenBrowser` skrypt tylko uruchamia i testuje usługę. Domyślny adres to
`http://127.0.0.1:8090`; port nie jest wystawiany na LAN. Przyszły Gateway
powinien łączyć się po zewnętrznej sieci Docker `njs-ai`, alias `lama-worker`.

Trwały układ jest względny wobec wybranych rootów hosta:

```text
${NJS_AI_MODELS_ROOT}/lama
${NJS_AI_DATA_ROOT}/workers/lama/{input,output}
${NJS_AI_CACHE_ROOT}/lama
```

Inicjalizator może skopiować i zweryfikować istniejący model z opcjonalnego
roota importu; nie modyfikuje ani nie usuwa źródła.

## Obsługa i API

```powershell
docker compose -f .\nls-tools\image-cleanup\lama\docker\compose.yaml --profile light logs -f
docker compose -f .\nls-tools\image-cleanup\lama\docker\compose.yaml --profile light down
python .\nls-tools\ai-runtime\scripts\smoke_light_workers.py lama
```

Dokumentacja API działa pod `http://127.0.0.1:8090/docs`. Endpoint
`POST /api/v1/inpaint` przyjmuje obraz i maskę jako Base64. LaMa służy do
inpaintingu zaznaczonego fragmentu; RMBG-2.0 pozostaje osobnym workerem do
automatycznego usuwania tła.
