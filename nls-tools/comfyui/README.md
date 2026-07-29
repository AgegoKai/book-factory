# Workflow ComfyUI

Ten katalog grupuje workflow ComfyUI wraz z definicjami Dockerów potrzebnymi
do ich odtworzenia na innym komputerze.

| Narzędzie | Tryb | Port | Start z katalogu repozytorium |
|---|---|---:|---|
| [RMBG-2.0](rmbg2/README.md) | automatyczne usuwanie tła | 8189 | `.\nls-tools\comfyui\rmbg2\docker\start-docker.ps1` |

Kontener korzysta z GPU NVIDIA i katalogów na dysku `D:`.

Workflow w formacie edytora ComfyUI znajduje się w katalogu `workflows`.
Pliki z dopiskiem `_API` mają format promptu akceptowany przez endpoint
`POST /prompt`.
