# Przestarzała ścieżka zgodności RMBG-2.0

Kanoniczny i utrzymywany setup znajduje się w
`nls-tools/comfyui/rmbg2/docker`. Ten katalog pozostaje wyłącznie po to, aby
stare polecenia nadal trafiały do tej samej definicji Compose i skryptu startu.

Nie dodawaj tutaj nowych zmian infrastruktury. Pliki `Dockerfile` i
`entrypoint.sh` są zachowane dla historii, ale `compose.yaml` już ich nie używa.
