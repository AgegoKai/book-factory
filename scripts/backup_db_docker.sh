#!/usr/bin/env bash
# Zapisz kopię SQLite z kontenera Docker na host (./data/).
# Użycie: ./scripts/backup_db_docker.sh [nazwa_usługi]
# Wymaga: docker compose, uruchomiony stack w katalogu repozytorium.

set -euo pipefail
SERVICE="${1:-book-factory}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data backups

TS="$(date +%Y%m%d-%H%M%S)"
OUT_TS="backups/book_factory-${TS}.sqlite"
OUT_RESTORE="data/book_factory.restore.sqlite"

# Ścieżki w kontenerze: stara (WORKDIR) i nowa (wolumen)
for SRC in "/app/data/book_factory.db" "/app/book_factory.db"; do
  if docker compose exec -T "$SERVICE" test -f "$SRC" 2>/dev/null; then
    echo "Kopiuję $SRC -> $OUT_TS"
    docker compose cp "${SERVICE}:${SRC}" "$OUT_TS"
    cp "$OUT_TS" "$OUT_RESTORE"
    echo "Zaktualizowano też plik seed: $OUT_RESTORE (używany po twardym resecie, gdy brak book_factory.db)"
    exit 0
  fi
done

echo "Nie znaleziono book_factory.db w kontenerze ($SERVICE). Uruchom: docker compose up -d" >&2
exit 1
