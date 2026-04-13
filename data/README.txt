Katalog danych Dockera (montowany jako /app/data)

- book_factory.db — żywa baza SQLite (tworzona przez aplikację; nie commituj).
- book_factory.restore.sqlite — opcjonalny „złoty” backup: gdy przy starcie kontenera
  NIE MA book_factory.db, entrypoint skopiuje ten plik jako book_factory.db.
- backups/ — automatyczne snapshoty wykonywane przy każdym starcie kontenera Docker.
  Domyślnie trzymane jest 30 ostatnich kopii.

Jak zrobić backup z działającego kontenera i ustawić przywracanie (z katalogu głównego repozytorium book-factory):
  ./scripts/backup_db_docker.sh

  Albo z dowolnego katalogu (pełna ścieżka do skryptu):
  /ścieżka/do/book-factory/scripts/backup_db_docker.sh

  NIE używaj samego „/scripts/...” — to katalog u roota dysku, nie Twój projekt.

Po `docker compose down` + `docker compose up` dane zostają (wolumen ./data).
Przy każdym starcie kontenera entrypoint:
- robi timestamped backup do `./data/backups/`
- nadpisuje `./data/book_factory.restore.sqlite` aktualną bazą

Po skasowaniu ./data/book_factory.db (lub całego ./data) przy następnym starcie
wczyta się book_factory.restore.sqlite, jeśli istnieje.
