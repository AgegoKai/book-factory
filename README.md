# nls-tools — workflow ComfyUI

Aktualne, uruchamialne narzędzia są przechowywane w katalogu
[`nls-tools`](nls-tools/README.md). Każde narzędzie ma w jednym miejscu
workflow, definicję Dockera, skrypty i instrukcję użycia.

## RemoveBg RMBG-2.0

Automatyczne usuwanie tła: wejściem jest zdjęcie, a wyjściem PNG RGBA z
przezroczystym tłem oraz osobna maska alfa.

Dokumentacja: [`nls-tools/comfyui/rmbg2/README.md`](nls-tools/comfyui/rmbg2/README.md)

Uruchomienie z głównego katalogu repozytorium:

```powershell
.\nls-tools\comfyui\rmbg2\docker\start-docker.ps1
```

Panel ComfyUI i API:

```text
http://localhost:8189
```

Wywołanie przez klienta API:

```powershell
python .\nls-tools\comfyui\rmbg2\scripts\rmbg_api_client.py `
  ".\zdjecie.png" `
  --output-dir ".\api-results"
```

Wagi modelu nie są przechowywane w Git. Ich trwałe położenie wybiera host w
ignorowanym `nls-tools/ai-runtime/.env`:

```text
${NJS_AI_MODELS_ROOT}/comfyui/RMBG/RMBG-2.0
```

Gotowe przykłady konfiguracji istnieją osobno dla bieżącej stacji Windows i
hosta Linux; definicje Compose nie zawierają domyślnej ścieżki dyskowej.

Warunki użycia modelu: https://huggingface.co/briaai/RMBG-2.0

Starsze pliki w katalogu głównym pozostają wyłącznie dla zgodności z
wcześniejszą wersją repozytorium. Nowe workflow należy dodawać do `nls-tools`.

## LaMa Cleanup

Lokalny retusz pędzlem do usuwania włosków, kropek, zabrudzeń i innych małych
elementów. Działa na karcie NVIDIA przez CUDA i udostępnia panel pod
`http://localhost:8090`.

Dokumentacja i uruchomienie:
[`nls-tools/image-cleanup/lama/README.md`](nls-tools/image-cleanup/lama/README.md)
