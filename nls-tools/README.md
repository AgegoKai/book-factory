# nls-tools

Wspólny katalog na małe, uruchamialne narzędzia i workflow używane w
projektach NLS. Każde narzędzie powinno być możliwie samodzielne: zawierać
workflow, definicję Dockera, skrypty pomocnicze, przykład oraz własny README.

## Dostępne narzędzia

| Katalog | Opis |
|---|---|
| `comfyui/rmbg2` | automatyczne usuwanie tła przez RMBG-2.0, GUI i API |

Szczegółowe polecenia znajdują się w README każdego narzędzia oraz w
[`comfyui/README.md`](comfyui/README.md).

## Zasady dodawania kolejnych workflow

Nowy workflow zapisujemy w osobnym katalogu:

```text
nls-tools/comfyui/<nazwa-narzędzia>/
├── README.md
├── workflows/
├── docker/
├── scripts/       # opcjonalnie
├── patches/       # opcjonalnie
└── examples/      # małe pliki testowe
```

Do repozytorium nie dodajemy checkpointów, wag modeli, obrazów Dockera,
cache, plików wejściowych ani wyników. README powinien podawać link do modelu,
jego lokalizację na hoście oraz kompletne polecenie uruchomienia.
