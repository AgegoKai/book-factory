# Benchmark AI #1678 — 2026-08-04

## Środowisko

- host Windows build 26200, Docker Engine 29.2.0;
- Linux runtime: Ubuntu 24.04.1 LTS przez WSL2;
- GPU: NVIDIA GeForce RTX 5070 Ti 16 GB, driver 596.21;
- obrazy: SAM2 `0.13.0` (`sha256:b57bfea...`), RMBG2 `0.13.0`
  (`sha256:a8f48a6...`), LaMa `1.1.0` (`sha256:fedc121...`);
- 5 bezpiecznych zdjęć produktowych, 3 warianty retuszu, 3 powtórzenia warm;
- surowe wyniki: `2026-08-04-windows-wsl2-gpu.json`, `cold-*.json`,
  `lama-resolution.json`; artefakty ręcznej oceny pozostają pod jawnie wybranym
  rootem danych na `D:` i nie są częścią storage produkcyjnego.

Windows + WSL2 potwierdza host Windows/GPU i Linux/CUDA w kontenerze. Osobny
bare-metal Linux/GPU nie był dostępny; przed produkcyjnym rolloutem wymagany jest
ten sam smoke test na docelowym hoście Linux.

## Wyniki

| Kandydat | Readiness cold | Pierwsza inferencja | Mediana warm | Izolowany przyrost VRAM | Jakość automatyczna |
| --- | ---: | ---: | ---: | ---: | --- |
| RMBG-2.0 | 14.39 s | 5.81 s | 0.34 s | 4133 MiB | IoU 0.907, F1 0.951 |
| SAM 2.1 Hiera Large | 16.70 s | 10.97 s | 0.60 s | 1670 MiB | IoU 0.880, F1 0.936; 1–3 punkty |
| Big-LaMa / IOPaint | 11.37 s | 1.93 s | 0.83 s | 360 MiB | poza maską max delta 0 |

IoU/F1 pochodzi z fixture'a z prawdziwą alfą. Pozostałe produkty oceniono ręcznie
w `quality-review-2026-08-04.csv`. RMBG przeszedł wszystkie pięć przypadków bez
interakcji. SAM2 dobrze działa jako korekta kierowana, ale pojedynczy nieprecyzyjny
punkt zawodzi na szkle i w pustych przestrzeniach słuchawek; dlatego nie jest
automatycznym zamiennikiem RMBG.

LaMa zachowała rozmiar i piksele poza maską dokładnie (`max delta = 0`) dla maski
cienkiej, grubej i trybu pełnego obrazu. Średni błąd w edytowanym obszarze wobec
syntetycznego clean targetu wyniósł odpowiednio 3.99, 6.07 i 12.44 poziomu RGB.

| LaMa Crop + margin | Latencja | Przyrost VRAM | Rozmiar zachowany | Max delta poza maską |
| --- | ---: | ---: | --- | ---: |
| 2048 px | 1.30 s | 94 MiB | tak | 0 |
| 3072 px | 2.38 s | 166 MiB | tak | 0 |
| 4096 px | 3.69 s | 206 MiB | tak | 0 |

Maksymalny zweryfikowany długi bok to 4096 px w trybie Crop + margin 128. Nie jest
to deklaracja nieograniczonego maksimum; większy obraz wymaga osobnego testu.

## Decyzja modeli

1. Techniczny domyślny model automatycznego usuwania tła: **RMBG-2.0**, ponieważ
   ma lepszą jakość golden, nie wymaga punktów i ma niższą latencję warm.
2. Produkcyjne włączenie RMBG-2.0 jest **zablokowane do potwierdzenia licencji**.
   Self-hosted weights mają warunki CC BY-NC 4.0 dla użycia niekomercyjnego, a
   użycie komercyjne wymaga osobnej umowy BRIA. Gate
   `NJS_RMBG2_LICENSE_ACCEPTED` pozostaje wymagany.
3. Awaryjny i korekcyjny model: **SAM 2.1 Hiera Large**, przypięty checkpointem
   `264787...318` i kodem custom node do pełnego commita. Kod i oficjalny
   checkpoint SAM2 są Apache-2.0. SAM nie jest fallbackiem zero-click: UI/Gateway
   musi przekazać punkty operatora.
4. Retusz: **Big-LaMa przez przypięty IOPaint 1.6.0** z kontraktem `image + mask`.
   To prostszy i już zweryfikowany adapter niż bezpośrednia integracja oryginalnego
   repo LaMa. Upstream IOPaint jest zarchiwizowany, więc przed produkcją trzeba
   utrzymywać własny pin/fork i poprawki bezpieczeństwa. Kod LaMa jest Apache-2.0,
   ale pochodzenie/licencja dokładnego checkpointu `344c77...ea9` nadal wymaga
   przeglądu; gate `NJS_BIG_LAMA_LICENSE_ACCEPTED` pozostaje wymagany.

Źródła decyzji licencyjnej i wersji:

- https://github.com/facebookresearch/sam2
- https://huggingface.co/briaai/RMBG-2.0
- https://github.com/advimman/lama
- https://github.com/Sanster/IOPaint/releases

## Kryteria przejścia dalej

- uzyskać zgodę/licencję dla RMBG-2.0 albo wybrać automatyczny model z warunkami
  zgodnymi z użyciem komercyjnym;
- rozstrzygnąć pochodzenie dokładnego checkpointu Big-LaMa;
- uruchomić smoke na niezależnym docelowym Linux/GPU;
- manualny reviewer produktu może powtórzyć ocenę z pustego scorecarda przed
  zamknięciem jakości UX.
