# RemoveBg by SAM2 dla ComfyUI

Gotowy workflow do precyzyjnego usuwania tła w ComfyUI za pomocą **SAM 2.1
Hiera Large**. Obiekt zaznacza się zwykłym lewym kliknięciem, a tło prawym
kliknięciem. Wynikiem jest PNG z przezroczystością i oczyszczoną krawędzią,
bez ciemnej obwódki po kolorze starego tła.

Repozytorium zawiera:

- ComfyUI 0.12.2 uruchamiane w Dockerze z obsługą GPU NVIDIA;
- SAM2 i KJNodes `PointsEditor` do zaznaczania punktami;
- workflow `RemoveBg by SAM2`;
- poprawki domykania maski, lekkiego zwężania i zmiękczania krawędzi oraz
  usuwania koloru starego tła;
- przykładowy obraz misia i sprawdzony wynik PNG.

Checkpoint modelu nie jest przechowywany w repozytorium ani kopiowany do
obrazu Dockera. Kontener montuje istniejący katalog modeli z dysku hosta tylko
do odczytu.

## Wymagania

- Windows 10/11;
- karta NVIDIA; 16 GB VRAM wystarcza dla wariantu Large i obrazów 8K, choć
  chwilowe zużycie zależy od rozdzielczości;
- [Docker Desktop dla Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
  z backendem WSL 2;
- aktualny [sterownik NVIDIA](https://www.nvidia.com/en-us/drivers/).

Obsługa GPU w Docker Desktop na Windows wymaga backendu WSL 2:
[dokumentacja Docker GPU](https://docs.docker.com/desktop/features/gpu/).

## Pobranie modelu

Używany checkpoint:

- [SAM 2.1 Hiera Large — bezpośrednie pobieranie](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt)
- [oficjalne repozytorium Meta SAM2](https://github.com/facebookresearch/sam2)

Utwórz katalog i zapisz plik dokładnie tutaj:

```text
D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt
```

Można to zrobić w PowerShell:

```powershell
New-Item -ItemType Directory -Force "D:\ComfyAi\models\sam2" | Out-Null
Invoke-WebRequest `
  -Uri "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt" `
  -OutFile "D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt"
```

Jeżeli checkpoint już znajduje się w `D:\ComfyAi\models\checkpoints`, nie
trzeba pobierać go ponownie. Można utworzyć hardlink:

```powershell
New-Item -ItemType Directory -Force "D:\ComfyAi\models\sam2" | Out-Null
New-Item -ItemType HardLink `
  -Path "D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt" `
  -Target "D:\ComfyAi\models\checkpoints\sam2.1_hiera_large.pt"
```

## Katalogi na hoście

Przed pierwszym uruchomieniem utwórz katalogi:

```powershell
$directories = @(
  "D:\ComfyAi\models\sam2",
  "D:\ComfyAi\input",
  "D:\ComfyAi\output",
  "D:\ComfyAi\user\default\workflows",
  "D:\ComfyAi\temp",
  "D:\ComfyAi\hf_cache"
)
$directories | ForEach-Object { New-Item -ItemType Directory -Force $_ | Out-Null }
```

| Zawartość | Lokalizacja na Windows |
|---|---|
| checkpoint SAM2.1 Large | `D:\ComfyAi\models\sam2\sam2.1_hiera_large.pt` |
| obrazy do obróbki | `D:\ComfyAi\input` |
| gotowe PNG | `D:\ComfyAi\output` |
| workflow użytkownika | `D:\ComfyAi\user\default\workflows` |
| pliki tymczasowe | `D:\ComfyAi\temp` |
| cache Hugging Face | `D:\ComfyAi\hf_cache` |

## Uruchomienie przez Docker

Uruchom Docker Desktop, a następnie w katalogu `docker-sam2` wykonaj:

```powershell
.\start-docker.ps1
```

Albo bez skryptu:

```powershell
docker compose up -d --build
```

Pierwsza budowa pobiera obraz PyTorch/CUDA, ComfyUI i custom nodes, więc może
potrwać kilkanaście minut. Następne uruchomienia korzystają z cache.

Po uzyskaniu statusu `healthy` otwórz:

- [http://localhost:8188](http://localhost:8188)

Workflow `RemoveBg by SAM2` jest automatycznie kopiowany do katalogu workflow
przy starcie kontenera. Jeżeli w katalogu wejściowym nie ma jeszcze obrazu
testowego, kontener skopiuje również `SAM2_bear_edge_test.png` do
`D:\ComfyAi\input`.

Stan kontenera:

```powershell
docker compose ps
docker compose logs -f
```

Zatrzymanie:

```powershell
docker compose down
```

## Użycie workflow

1. Otwórz `RemoveBg by SAM2` w panelu **Workflows**.
2. W `Load Image` wybierz plik z `D:\ComfyAi\input`.
3. Na obrazie w `PointsEditor` kliknij lewym przyciskiem kilka miejsc obiektu.
4. Prawym przyciskiem kliknij miejsca należące do tła, szczególnie w pobliżu
   trudnych krawędzi.
5. Kliknij **Run**.
6. Gotowy PNG znajdziesz w `D:\ComfyAi\output`.

Domyślne ustawienia oczyszczania krawędzi:

| Parametr | Wartość |
|---|---:|
| `close_holes_px` | 5 |
| `background_tolerance` | 0.10 |
| `edge_shrink_px` | 3 |
| `edge_feather_px` | 1.2 |
| `decontaminate_px` | 10 |

Jeżeli maska ucina cienkie elementy, zmniejsz `edge_shrink_px` do 1–2. Jeżeli
na krawędzi pozostaje kolor starego tła, dodaj czerwone punkty na tym tle albo
zwiększ `decontaminate_px`.

## Ręczna instalacja w istniejącym ComfyUI

Docker jest zalecany, ale pliki można również skopiować do istniejącej
instalacji. Najpierw zainstaluj:

- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)
- [ComfyUI-SAM2](https://github.com/neverbiasu/ComfyUI-SAM2)
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes)

Następnie skopiuj pliki z repozytorium:

| Plik z repozytorium | Miejsce docelowe względem katalogu ComfyUI |
|---|---|
| `comfyui_sam2_node.py` | `custom_nodes/comfyui-sam2/node.py` |
| `comfyui_sam2_init.py` | `custom_nodes/comfyui-sam2/__init__.py` |
| `kjnodes_curve_nodes.py` | `custom_nodes/ComfyUI-KJNodes/nodes/curve_nodes.py` |
| `kjnodes_point_editor_canvas.js` | `custom_nodes/ComfyUI-KJNodes/web/js/editors/point_editor_canvas.js` |
| `kjnodes_editor_base.js` | `custom_nodes/ComfyUI-KJNodes/web/js/editors/editor_base.js` |
| `RemoveBg_by_SAM2.json` | `user/default/workflows/RemoveBg by SAM2.json` |

Po skopiowaniu plików całkowicie zrestartuj ComfyUI i odśwież stronę
`Ctrl+F5`.

## Test

Do katalogu `examples` w repozytorium dołączono:

- `examples/SAM2_bear_edge_test.png` — obraz wejściowy;
- `examples/SAM2_docker_bear_test_00001_.png` — wynik z przezroczystością.

Test kontrolny wykazał poprawny kanał alfa i brak czarnych pikseli na miękkiej
krawędzi obiektu.

## Źródła

- [Meta SAM2](https://github.com/facebookresearch/sam2)
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)
- [ComfyUI-SAM2](https://github.com/neverbiasu/ComfyUI-SAM2)
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes)
- [Docker Desktop GPU](https://docs.docker.com/desktop/features/gpu/)
