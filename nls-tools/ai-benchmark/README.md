# NJS AI model benchmark

Powtarzalny benchmark do Story #1678. Fixture'y są lokalne w repozytorium, mają
udokumentowane źródła CC0/public domain i nie zawierają danych produkcyjnych.
Generowane artefakty oceny zapisujemy pod wybranym rootem danych, nie w storage
produkcyjnym ani w katalogach modeli.

## Zakres

- automatyczne usuwanie tła: RMBG-2.0;
- korekta/promptowana segmentacja: SAM 2.1 Hiera Large;
- retusz: Big-LaMa przez przypięty wrapper IOPaint;
- cold start kontenera, pierwsza inferencja, warm latency, VRAM, IoU/F1 maski;
- cienka/gruba maska LaMa, Crop + margin, pełny obraz i sweep do 4096 px;
- kontrola wymiarów i niezmienności pikseli poza maską.

## Uruchomienie

Wymagane jest Python 3 z Pillow, `nvidia-smi`, Docker z GPU i przygotowane
checkpointy. Najpierw przygotuj fixture'y:

```powershell
python .\nls-tools\ai-benchmark\scripts\fetch_fixtures.py
```

Benchmark działających workerów:

```powershell
python .\nls-tools\ai-benchmark\scripts\benchmark_workers.py all `
  --repeats 3 `
  --artifacts-dir D:\AI\data\benchmarks\artifacts\run `
  --output .\nls-tools\ai-benchmark\results\run.json
```

Izolowany cold start używa unikalnego kontenera, alternatywnego portu i usuwa
wyłącznie ten kontener po pomiarze. `--model-dir` jest jawny, dzięki czemu harness
nie zakłada konkretnego dysku ani układu hosta. Przykład:

```powershell
python .\nls-tools\ai-benchmark\scripts\benchmark_cold_start.py sam2 `
  --model-dir D:\ComfyAi\models `
  --work-root D:\AI\data\benchmarks\cold-start `
  --port 9188 --output .\nls-tools\ai-benchmark\results\cold-sam2.json
```

Sweep rozdzielczości LaMa:

```powershell
python .\nls-tools\ai-benchmark\scripts\benchmark_lama_resolution.py `
  --work-dir D:\AI\data\benchmarks\lama-resolution `
  --output .\nls-tools\ai-benchmark\results\lama-resolution.json
```

`vramPeakMiB` jest całkowitym użyciem GPU, a `vramDeltaMiB` różnicą wobec próbki
bezpośrednio przed inferencją. Na współdzielonym GPU do decyzji pojemnościowej
używamy izolowanego cold startu, nie sumy z równolegle załadowanych workerów.

## Ocena ręczna

Skopiuj `fixtures/quality-scorecard.csv`, wypełnij oceny 1–5 oraz czas operatora.
Jedna ocena obejmuje krawędź, cienkie detale, przezroczystość, spill koloru,
blend retuszu i nienaruszenie obszaru poza maską. Zakładany czas: 30–60 s na
artefakt; dla SAM2 dolicz 2–6 s na 1–3 punkty operatora, RMBG nie wymaga punktów.

Wyniki i decyzja z bazowego uruchomienia znajdują się w
`results/2026-08-04-windows-wsl2-gpu.md`.
