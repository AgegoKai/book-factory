# Book Factory

Book Factory to webowa aplikacja (FastAPI + Jinja2) do **pipeline’u pisania książek pod self-publishing** (np. Amazon KDP): od konspektu i draftu, przez SEO i kategorie, po brief okładki i checklistę publikacji — z możliwością ręcznej edycji na każdym etapie.

---

## Na czym to polega

1. **Wejście (wizard)** — tytuł, pomysł, wiedza do przekazania, **język**, **rynek docelowy** (np. Amazon US / DE / ES / PL), **styl pisania**, emocje, odbiorca, bio autora, opcjonalnie własny **system prompt pisarza**.
2. **Pipeline LLM** — kolejne kroki generują treść; kolejny krok odblokowuje się po ukończeniu poprzedniego (można też regenerować).
3. **Wyjście** — edycja w panelu, eksport **DOCX** i **PDF** (PDF z obsługą znaków Unicode dzięki czcionkom w obrazie Docker), opcjonalnie **pakiety tłumaczeniowe** (DE / ES) z lokalnym SEO i katalogiem.

Krótko: jeden spójny flow zamiast kopiowania z ChatGPT do Worda — z kontrolą nad modelem, rynkiem i metadanymi książki.

---

## Pipeline (9 kroków)

| # | Krok | Opis |
|---|------|------|
| 1 | **Konspekt** | Hierarchiczna struktura książki pod docelową objętością. |
| 2 | **Prompty rozdziałów** | Jedna instrukcja na rozdział na bazie konspektu. |
| 3 | **Draft** | Manuskrypt **rozdział po rozdziale** (lepsza ciągłość, mniejsze ryzyko timeoutów). |
| 4 | **Redakcja** | Korekta stylu i spójności (w całości lub w fragmentach przy długim tekście). |
| 5 | **SEO Amazon** | Opis sprzedażowy do **max. 2500 znaków**, mocny hook, dopasowanie do rynku/języka z briefu. |
| 6 | **7 keywords** | Frazy pod wyszukiwarkę Amazon dla wybranego rynku. |
| 7 | **Drzewo katalogu** | Hierarchia kategorii + **3 rekomendowane ścieżki** browse. |
| 8 | **Brief okładki** | Koncepcja, typografia, paleta, prompty do generatorów obrazów. |
| 9 | **Checklista publikacji** | Kroki pod Amazon KDP. |

Dodatkowo: zakładka **Research / pomysły** (nisza, persony, słowa kluczowe), **Tłumaczenia** — generacja pakietu SEO + keywords + katalog dla **DE** i **ES** (osobne reguły niż dla EN).

---

## Styl i prompty (jak „piszemy” książkę)

- **Domyślny prompt pisarza** (`BOOK_WRITER_DEFAULT_PROMPT` w `app/models.py`) ustawia rolę **ghostwritera / autora długiej formy**: wyłącznie treść manuskryptu, bez metakomentarzy i sztucznych wstępów („w tym rozdziale…”), preferencja **precyzji, sensoryki, show don’t tell**, spójności narracji, sensownej długości bloku (~500–700 słów tam, gdzie to ma sens).
- **Kroki specjalistyczne** (konspekt, SEO, keywords, katalog, okładka, publikacja, tłumaczenia) mają **osobne, techniczne system prompty** w `app/services/book_pipeline.py` — jasna rola, format wyjścia, ograniczenia (np. długość SEO).
- **Własny system prompt** — pole w projekcie; jeśli puste, używany jest domyślny pisarz.

Styl **UI** to prosty panel (ciemny motyw, karty, kroki pipeline’u), **wizard** nowego projektu w kilku krokach oraz krótkie **podpowiedzi / tutorial** przy pipeline.

---

## Metadane projektu (brief)

W kreatorze i w bazie są m.in.:

- `writing_style`, `language`, `target_market` (np. `en-US`, `de-DE`, `es-ES`, `pl-PL`)
- `author_bio`, `emotions_to_convey`, `knowledge_to_share`, `target_audience`
- `tone_preferences`, `inspiration_sources`

Wpływają na konspekt, draft, SEO, keywords i drzewo katalogu oraz na tłumaczenia.

---

## LLM: providery i routing

1. **LM Studio** (lokalnie, OpenAI-compatible `/chat/completions`) — domyślnie pierwszy w trybie **automatycznym**.
2. **Google Gemini** — oficjalne API (`generateContent`).
3. **OpenRouter** — `/chat/completions`, routing po modelu (np. `google/gemma-3-27b-it:free`, sufiks `:online` → wtyczka web zamiast przestarzałego `:online` w nazwie modelu).

**Ustawienia użytkownika** (per konto w bazie, nadpisują `.env`):

- Klucze i modele dla każdego providera.
- **Provider do generowania** — `auto` (kolejka LM → Gemini → OpenRouter) albo **tylko** LM Studio / Gemini / OpenRouter (żeby nie dostawać błędów połączenia, gdy LM Studio jest wyłączone).
- **Wybór modelu OpenRouter** — siatka kart z orientacyjnym kosztem i oznaczeniem „web”.
- **Test połączenia** — osobno per provider oraz zbiorczy; komunikaty błędów z ciałem odpowiedzi OpenRouter (w tym `metadata.raw` od upstreamu).

**OpenRouter — technicznie:**

- Limit `max_tokens` dostosowany do typowych limitów kontekstu na darmowych modelach.
- Modele **Gemma** przez Google AI Studio nie akceptują osobnej wiadomości `system` w tym samym kształcie — aplikacja: heurystyka `gemma` w ID modelu **albo** jeden retry z scalonym promptem po błędzie 400 o „developer instruction”; pozostałe modele dostają klasyczny **system + user**.

Zmienne środowiskowe: zobacz `.env.example` (`LLM_MAX_OUTPUT_TOKENS`, `OPENROUTER_HTTP_REFERER`, `PREFERRED_LLM_PROVIDER`, itd.).

---

## Eksport i PDF

- **DOCX** (`python-docx`) — pełny eksport sekcji.
- **PDF** (`reportlab`) — szablon z nagłówkami; w **Dockerze** instalowane są **DejaVu / Liberation**, żeby polskie (i inne) znaki nie znikały. Nazwa pliku pobierania jest **ASCII-safe** (uniknięcie błędów nagłówka HTTP przy polskich znakach w tytule).

---

## UX podczas generacji

- Przy **Uruchom** kroku lub **Uruchom wszystko** — żądanie w tle + **polling** postępu; dla draftu widać m.in. **numer rozdziału** i krótki opis (subtelny pasek na dole ekranu).

---

## Stack

- Python **FastAPI**, **Jinja2**, **SQLAlchemy** + **SQLite**
- Sesja cookie (signed)
- **requests** — LM Studio / OpenRouter
- **python-docx**, **reportlab**
- **pytest**, **httpx** (testy)

---

## Struktura repozytorium (skrót)

```text
book-factory/
├── app/
│   ├── main.py              # trasy, ustawienia, eksport, tłumaczenia
│   ├── config.py
│   ├── models.py            # BookProject, UserSettings, domyślny prompt pisarza
│   ├── bootstrap.py         # init_db + migrate_db (nowe kolumny)
│   ├── services/
│   │   ├── llm.py           # LM Studio, Gemini, OpenRouter
│   │   ├── book_pipeline.py # kroki pipeline + prompty
│   │   └── exporter.py      # DOCX / PDF
│   ├── templates/           # login, dashboard, project_new, project_detail, settings
│   └── static/
├── scripts/
│   └── seed_test.py         # szybki projekt testowy + opcjonalnie --run outline|all
├── tests/
├── requirements.txt
├── Dockerfile               # m.in. fontconfig + fonts dla PDF
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Konfiguracja

```bash
cp .env.example .env
```

Ustaw m.in. `SECRET_KEY`, `DEFAULT_ADMIN_EMAIL`, `DEFAULT_ADMIN_PASSWORD`, oraz opcjonalnie klucze LM Studio / Gemini / OpenRouter. Szczegóły i domyślne wartości — w `.env.example`.

---

## Uruchomienie

**Lokalnie (venv):**

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8008
```

**Docker:**

```bash
docker compose up --build
```

Obraz instaluje **fontconfig** oraz pakiety czcionek potrzebne do PDF z Unicode.
Przy każdym starcie kontenera entrypoint automatycznie:
- zapisuje timestamped backup SQLite do `./data/backups/`
- aktualizuje `./data/book_factory.restore.sqlite`

Jeśli po update albo twardym resecie zniknie `./data/book_factory.db`, kontener spróbuje odtworzyć bazę z `book_factory.restore.sqlite`.

---

## Logowanie

Przy pierwszym starcie tworzony jest użytkownik z `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` (patrz `bootstrap.ensure_default_admin`).

---

## Szybki projekt testowy (CLI)

Do szybkich testów bez wypełniania pełnego kreatora:

```bash
python scripts/seed_test.py
python scripts/seed_test.py --run outline --provider openrouter
python scripts/seed_test.py --clean --run all --provider openrouter
```

Tworzy mały projekt (np. krótki poradnik), opcjonalnie uruchamia kroki i najpierw sprawdza połączenie z LLM.

---

## Testy automatyczne

```bash
pytest
```

Sprawdzają m.in. health, logowanie, CRUD projektu, eksport, ustawienia, parsowanie odpowiedzi LLM, routing OpenRouter.

---

## Co jest zaimplementowane (skrót)

- Pełny **9-krokowy pipeline** + edycja w panelu + **Uruchom wszystko**
- **SEO** (limit znaków, hook), **7 keywords**, **drzewo + 3 ścieżki katalogu** pod wybrany rynek
- **Tłumaczenia** DE / ES (SEO + keywords + katalog w JSON)
- **Ustawienia API** per użytkownik, wybór **providera**, picker modeli OpenRouter, testy połączenia
- **Eksport DOCX/PDF**, PDF z Unicode w Dockerze
- **Postęp** przy generacji (rozdział / krok)
- **Migracje SQLite** (`migrate_db`) bez kasowania danych przy dodawaniu kolumn
- Obsługa błędów OpenRouter (HTTP, treść z providera, retry przy Gemma / system prompt)

---

## Czego świadomie brakuje / możliwe rozszerzenia

| Obszar | Uwagi |
|--------|--------|
| **Bardzo długie manuskrypty** (70k+ słów) | Warto rozbić na więcej pod-kroków, pamięć stylu między partiami, osobny „continuity pass”. |
| **Kolejka / worker** | Generacja jest synchroniczna w żądaniu HTTP — przy timeoutach reverse proxy warto background job (Celery/RQ) + status joba. |
| **Postgres** | SQLite wystarcza na MVP jednego użytkownika / małego zespołu; produkcja często Postgres. |
---

## Jakość treści

Jakość zależy od **modelu**, **promptów** i **briefu**. Book Factory daje spójny proces i metadane; redakcja merytoryczna i zgodność z regulaminem platformy nadal są po stronie autora / wydawcy.

---

## Licencja / autor

Repozytorium projektu Book Factory — dostosuj sekcję licencji do własnych potrzeb.
