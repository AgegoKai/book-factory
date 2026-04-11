#!/bin/sh
set -e
# Persistent SQLite lives on mounted volume /app/data
mkdir -p /app/data

DB_FILE="${BOOK_FACTORY_DB_PATH:-/app/data/book_factory.db}"
RESTORE_FILE="/app/data/book_factory.restore.sqlite"

if [ ! -f "$DB_FILE" ] && [ -f "$RESTORE_FILE" ]; then
  echo "book-factory: brak $DB_FILE — przywracam z $RESTORE_FILE"
  cp "$RESTORE_FILE" "$DB_FILE"
elif [ ! -f "$DB_FILE" ]; then
  echo "book-factory: nowa pusta baza zostanie utworzona przy starcie ($DB_FILE)"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8008
