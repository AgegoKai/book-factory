# RemoveBg przez RMBG-2.0

Automatyczny wariant usuwania tła. Podajesz całe zdjęcie, a model zwraca PNG
RGBA z przezroczystym tłem oraz osobną maskę alfa. Nie wymaga punktów ani
promptu tekstowego.

## Zawartość

```text
rmbg2/
├── docker/       # Dockerfile, Compose i skrypt startowy
├── workflows/    # workflow GUI oraz prompt API
├── scripts/      # klient API w Pythonie
└── examples/     # mały obraz testowy
```

## Uruchomienie z repozytorium

Wymagane są Docker Desktop z WSL 2, sterownik NVIDIA oraz działająca obsługa
GPU w Dockerze. Z głównego katalogu repozytorium uruchom:

```powershell
.\nls-tools\comfyui\rmbg2\docker\start-docker.ps1
```

Panel ComfyUI i API będą dostępne pod adresem:

```text
http://localhost:8189
```

Pierwsza budowa pobiera środowisko CUDA i ComfyUI. Przy pierwszym wykonaniu
workflow pobierane są również wagi RMBG-2.0 do:

```text
D:\ComfyAi\models\RMBG\RMBG-2.0
```

Wagi nie są przechowywane w repozytorium. Informacje o modelu i licencji:
https://huggingface.co/briaai/RMBG-2.0

Rozszerzenie ComfyUI i pliki zgodne z jego automatycznym downloaderem:
https://github.com/1038lab/ComfyUI-RMBG oraz
https://huggingface.co/1038lab/RMBG-2.0/tree/main

## Użycie przez API

Z głównego katalogu repozytorium:

```powershell
python .\nls-tools\comfyui\rmbg2\scripts\rmbg_api_client.py `
  "C:\obrazy\zdjecie.png" `
  --output-dir "D:\ComfyAi\api-results"
```

Skrypt wykonuje cały przebieg:

1. `POST /upload/image` — wysyła zdjęcie;
2. `POST /prompt` — uruchamia workflow i odbiera `prompt_id` jako `processID`;
3. `GET /history/{processID}` — czeka na zakończenie;
4. `GET /view` — pobiera wycięty PNG i maskę alfa.

Każde zadanie otrzymuje osobny katalog wynikowy nazwany jego `processID`.

## Użycie przez GUI

Otwórz `http://localhost:8189`, wybierz workflow `RemoveBg by RMBG-2.0`,
wgraj zdjęcie w `Load Image` i kliknij `Run`. Pliki zostaną zapisane w:

```text
D:\ComfyAi\output\RMBG2
```

Domyślne parametry krawędzi to `refine_foreground=true`, `mask_blur=0` oraz
`mask_offset=-1`.

## Zatrzymanie

```powershell
docker compose -f .\nls-tools\comfyui\rmbg2\docker\compose.yaml down
```
