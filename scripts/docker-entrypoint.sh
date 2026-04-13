#!/bin/sh
set -e

DB_FILE="${BOOK_FACTORY_DB_PATH:-/app/data/book_factory.db}"
RESTORE_FILE="${BOOK_FACTORY_RESTORE_PATH:-$(dirname "$DB_FILE")/book_factory.restore.sqlite}"
BACKUP_DIR="${BOOK_FACTORY_BACKUP_DIR:-/app/data/backups}"
BACKUP_KEEP="${BOOK_FACTORY_BACKUP_KEEP:-30}"
BOOT_CMD="${BOOK_FACTORY_BOOT_CMD:-uvicorn app.main:app --host 0.0.0.0 --port 8008}"

mkdir -p "$(dirname "$DB_FILE")"
mkdir -p "$(dirname "$RESTORE_FILE")"
mkdir -p "$BACKUP_DIR"

create_backup_snapshot() {
  if [ ! -f "$DB_FILE" ]; then
    return 0
  fi

  TS="$(date +%Y%m%d-%H%M%S)"
  SNAPSHOT_FILE="${BACKUP_DIR}/book_factory-${TS}.sqlite"
  TMP_RESTORE="${RESTORE_FILE}.tmp"

  cp "$DB_FILE" "$SNAPSHOT_FILE"
  cp "$DB_FILE" "$TMP_RESTORE"
  mv "$TMP_RESTORE" "$RESTORE_FILE"
  echo "book-factory: zapisano backup bazy -> $SNAPSHOT_FILE"
  echo "book-factory: zaktualizowano restore seed -> $RESTORE_FILE"

  if [ "${BACKUP_KEEP}" -gt 0 ] 2>/dev/null; then
    old_files="$(ls -1t "${BACKUP_DIR}"/book_factory-*.sqlite 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) || true)"
    if [ -n "$old_files" ]; then
      echo "$old_files" | xargs rm -f
    fi
  fi
}

if [ ! -f "$DB_FILE" ] && [ -f "$RESTORE_FILE" ]; then
  echo "book-factory: brak $DB_FILE — przywracam z $RESTORE_FILE"
  cp "$RESTORE_FILE" "$DB_FILE"
elif [ ! -f "$DB_FILE" ]; then
  echo "book-factory: nowa pusta baza zostanie utworzona przy starcie ($DB_FILE)"
fi

create_backup_snapshot

exec sh -c "$BOOT_CMD"
