# RemoveBg: RMBG-2.0 i SAM2 dla ComfyUI

Repozytorium zawiera dwa niezależne workflow do usuwania tła:

- **RMBG-2.0** — tryb automatyczny. Wysyłasz obraz, uruchamiasz workflow i dostajesz PNG RGBA oraz osobną maskę alfa. Nie podajesz punktów ani tekstu.
- **SAM 2.1 Large** — tryb ręczny. Lewym kliknięciem zaznaczasz obiekt, prawym tło. Przydaje się, gdy automat wybierze niewłaściwy obiekt.

Oba warianty działają w oddzielnych kontenerach, więc mogą być uruchamiane niezależnie:

| Usługa | Adres | Zastosowanie |
|---|---|---|
| RMBG-2.0 | `http://localhost:8189` | automatyczne usuwanie tła i API |
| SAM2 | `http://localhost:8188` | interaktywne zaznaczanie punktami |

## Wymagania

- Windows 10/11;
- karta NVIDIA; 16 GB VRAM wystarcza dla ustawień dostarczonych w workflow;
- [Docker Desktop dla Windows](https://docs.docker.com/desktop/setup/install/windows-install/) z backendem WSL 2;
- aktualny [sterownik NVIDIA](https://www.nvidia.com/en-us/drivers/).

Obsługa GPU w Docker Desktop na Windows wymaga WSL 2: [dokumentacja Docker GPU](https://docs.docker.com/desktop/features/gpu/).

## RMBG-2.0 — automatyczne usuwanie tła

### Model i licencja

- [oficjalny RMBG-2.0 firmy BRIA](https://huggingface.co/briaai/RMBG-2.0)
- [pliki modelu używane przez node ComfyUI-RMBG](https://huggingface.co/1038lab/RMBG-2.0/tree/main)
- [rozszerzenie ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG)

Oficjalny model BRIA jest modelem z ograniczonym dostępem. Należy zalogować się na Hugging Face i zaakceptować warunki. Wagi są przeznaczone do użycia niekomercyjnego zgodnie z warunkami podanymi na stronie modelu; zastosowanie komercyjne wymaga odpowiedniej licencji BRIA. Repozytorium nie zawiera wag modelu.

Kontener korzysta z noda `ComfyUI-RMBG`, który przy pierwszym uruchomieniu workflow automatycznie pobiera cztery wymagane pliki do:

```text
D:\ComfyAi\models\RMBG\RMBG-2.0\
├── config.json
├── model.safetensors
├── birefnet.py
└── BiRefNet_config.py
```

Można też pobrać te cztery pliki ręcznie z podanego wyżej repozytorium integracyjnego i umieścić dokładnie w tym katalogu.

### Uruchomienie kontenera RMBG

Uruchom Docker Desktop, a następnie:

```powershell
cd docker-rmbg
.\start-docker.ps1
```

Skrypt tworzy wymagane katalogi na dysku `D:`, buduje kontener i otwiera `http://localhost:8189`.

Bez skryptu:

```powershell
docker compose -f docker-rmbg\compose.yaml up -d --build
```

Pierwsza budowa obrazu oraz pierwsze pobranie modelu mogą potrwać kilka–kilkanaście minut. Kolejne uruchomienia używają cache.

### Workflow RMBG w panelu ComfyUI

Plik: `RemoveBg_by_RMBG2.json`

1. Otwórz `http://localhost:8189`.
2. W panelu **Workflows** wybierz `RemoveBg by RMBG-2.0`.
3. W `Load Image` wgraj zdjęcie lub wybierz plik z `D:\ComfyAi\input`.
4. Kliknij **Run**.
5. Wyniki znajdziesz w `D:\ComfyAi\output\RMBG2`:
   - `cutout_....png` — obraz z przezroczystym tłem;
   - `alpha_mask_....png` — osobna maska alfa.

Workflow analizuje obraz w rozdzielczości 1024×1024, po czym skaluje miękką maskę do oryginalnego rozmiaru. Dlatego można podać również obraz 8K bez przetwarzania całej sieci w 8K. Ustawienia `refine_foreground=true`, `mask_blur=0` i `mask_offset=-1` ograniczają ciemną obwódkę na krawędzi obiektu.

Jeśli maska ucina włosy, futro albo bardzo cienkie elementy, zmień `mask_offset` z `-1` na `0`. Jeśli nadal zostaje kolor starego tła, ustaw `mask_offset=-2`.

### RMBG przez API

Plik `RemoveBg_by_RMBG2_API.json` jest gotowym promptem w formacie API ComfyUI. Typowy przebieg wygląda tak:

1. Wyślij plik jako `multipart/form-data`:

```powershell
curl.exe -X POST `
  -F "image=@C:\obrazy\mis.png" `
  -F "overwrite=true" `
  http://localhost:8189/upload/image
```

2. W kopii `RemoveBg_by_RMBG2_API.json` ustaw w nodzie `1` nazwę zwróconą przez upload, np. `mis.png`.
3. Wyślij workflow do kolejki:

```powershell
$prompt = Get-Content .\RemoveBg_by_RMBG2_API.json -Raw | ConvertFrom-Json
$job = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8189/prompt `
  -ContentType "application/json" `
  -Body (@{ prompt = $prompt } | ConvertTo-Json -Depth 100)
$processId = $job.prompt_id
$processId
```

`prompt_id` pełni rolę `processID`. Można go od razu zachować w bazie i później użyć jako identyfikatora kolejki.

4. Sprawdź status:

```powershell
Invoke-RestMethod "http://localhost:8189/history/$processId"
```

Brak wpisu oznacza, że zadanie nadal oczekuje albo trwa. Gotowy wpis zawiera sekcję `outputs` z nazwą pliku, `subfolder` i `type`.

5. Pobierz gotowy plik wartościami zwróconymi w `outputs`:

```text
GET /view?filename=cutout_00001_.png&subfolder=RMBG2&type=output
```

To są natywne endpointy ComfyUI. Jeśli aplikacja kliencka wymaga własnych ścieżek typu `/jobs/{processID}` i `/jobs/{processID}/download`, można nad nimi dodać cienką usługę API bez zmieniania workflow.

## SAM2 — ręczne zaznaczanie punktami

### Pobranie modelu

- [SAM 2.1 Hiera Large — bezpośrednie pobieranie](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt)
- [oficjalne repozytorium Meta SAM2](https://github.com/facebookresearch/sam2)

Docelowa lokalizacja:

```text
D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt
```

Jeżeli checkpoint znajduje się już w `D:\ComfyAi\models\checkpoints`, nie pobieraj go ponownie. Utwórz hardlink:

```powershell
New-Item -ItemType Directory -Force "D:\ComfyAi\models\sam2" | Out-Null
New-Item -ItemType HardLink `
  -Path "D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt" `
  -Target "D:\ComfyAi\models\checkpoints\sam2.1_hiera_large.pt"
```

### Uruchomienie i użycie SAM2

```powershell
cd docker-sam2
.\start-docker.ps1
```

Następnie otwórz `http://localhost:8188`, wybierz workflow `RemoveBg by SAM2`, załaduj obraz, zaznacz obiekt lewym przyciskiem, tło prawym przyciskiem i kliknij **Run**.

Plik workflow: `RemoveBg_by_SAM2.json`.

## Katalogi na hoście

| Zawartość | Lokalizacja na Windows |
|---|---|
| model RMBG-2.0 | `D:\ComfyAi\models\RMBG\RMBG-2.0` |
| checkpoint SAM2.1 Large | `D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt` |
| obrazy wejściowe | `D:\ComfyAi\input` |
| gotowe PNG | `D:\ComfyAi\output` |
| workflow użytkownika | `D:\ComfyAi\user\default\workflows` |
| cache Hugging Face | `D:\ComfyAi\hf_cache` |

## Diagnostyka

```powershell
docker compose -f docker-rmbg\compose.yaml ps
docker compose -f docker-rmbg\compose.yaml logs -f
docker compose -f docker-sam2\compose.yaml ps
```

Zatrzymanie wybranego kontenera:

```powershell
docker compose -f docker-rmbg\compose.yaml down
docker compose -f docker-sam2\compose.yaml down
```

## Testowy miś

`examples/SAM2_bear_edge_test.png` jest kopiowany do katalogu wejściowego obu kontenerów. Workflow RMBG ma go ustawionego jako obraz startowy, dzięki czemu po pobraniu modelu można od razu uruchomić test automatycznego wycinania.

## Źródła

- [BRIA RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0)
- [ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG)
- [Meta SAM2](https://github.com/facebookresearch/sam2)
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)
- [ComfyUI-SAM2](https://github.com/neverbiasu/ComfyUI-SAM2)
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes)
