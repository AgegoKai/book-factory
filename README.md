# Book Factory

Book Factory to webowa aplikacja do automatyzacji pisania książek dla klienta, który dziś działa ręcznie: prompt w ChatGPT, kopiowanie tekstu, formatowanie, poprawki i przygotowanie pod Amazon.

## Co robi projekt

Aplikacja prowadzi książkę przez cały pipeline:

1. wejście: tytuł, pomysł, źródła inspiracji, liczba stron, liczba słów, styl
2. generacja konspektu książki
3. generacja promptów per rozdział
4. generacja draftu książki
5. redakcja i poprawa stylu
6. wygenerowanie opisu SEO na Amazon
7. wygenerowanie briefu okładki, pod grafikę lub image model
8. wygenerowanie checklisty publikacji na Amazon KDP
9. eksport do DOCX i PDF
10. ręczne poprawki z poziomu panelu
11. zakładka do generowania pomysłów i researchu

## Najważniejsze założenia

- login page jest domyślny
- backend jest w Pythonie, na FastAPI
- jeśli działa LM Studio, aplikacja używa lokalnego modelu jako primary
- jeśli LM Studio nie odpowiada, aplikacja przełącza się na Google Gemini API
- jeśli Gemini nie działa, aplikacja przełącza się na OpenRouter free
- jeśli wszystkie źródła są niedostępne, aplikacja nadal działa na fallbackach szablonowych, żeby flow się nie wywracał
- short book i long book można obsłużyć przez target pages i target words
- UI prowadzi użytkownika krok po kroku i blokuje następne etapy, dopóki poprzednie nie są gotowe

## Stack

- FastAPI
- Jinja2 templates
- SQLAlchemy + SQLite na start
- session cookie auth
- python-docx
- reportlab
- requests

## Struktura

```text
book-factory/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── security.py
│   ├── session.py
│   ├── bootstrap.py
│   ├── deps.py
│   ├── services/
│   │   ├── llm.py
│   │   ├── book_pipeline.py
│   │   └── exporter.py
│   ├── static/
│   │   └── styles.css
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── dashboard.html
│       ├── project_new.html
│       └── project_detail.html
├── tests/
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

## Konfiguracja `.env`

Skopiuj plik przykładowy:

```bash
cp .env.example .env
```

Ustaw minimum:

```env
SECRET_KEY=zmien-to-na-dlugie-losowe
DEFAULT_ADMIN_EMAIL=twoj@email.pl
DEFAULT_ADMIN_PASSWORD=superhaslo123
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=gemma-3-27b-it
GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-2.5-flash
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openrouter/free
```

## Jak działa routing modeli

### 1. LM Studio
Aplikacja najpierw wysyła request do lokalnego LM Studio:
- endpoint: `LM_STUDIO_BASE_URL/chat/completions`
- model: `LM_STUDIO_MODEL`

### 2. Google Gemini API fallback
Jeśli LM Studio nie odpowie lub rzuci błąd:
- aplikacja odpytuje Google Gemini API
- używa `GOOGLE_API_KEY`
- używa `GOOGLE_MODEL`

### 3. OpenRouter free fallback
Jeśli Gemini też nie odpowie:
- aplikacja odpytuje OpenRouter
- używa `OPENROUTER_API_KEY`
- używa `OPENROUTER_MODEL`, domyślnie `openrouter/free`

### 4. Template fallback
Jeśli wszystko zawiedzie:
- pipeline i tak zwraca placeholder output
- dzięki temu UI, eksport i testy dalej działają

## Darmowe API znalezione i sensownie dobrane

Po researchu najlepsze praktyczne darmowe opcje do testów tego produktu to:

- **Google Gemini API / AI Studio**
  - oficjalne API Google
  - mocna darmowa ścieżka testowa
  - dobre jako główny zewnętrzny fallback
- **OpenRouter free**
  - oficjalny router darmowych modeli
  - można używać `openrouter/free` albo modeli z sufiksem `:free`
- **LM Studio**
  - nie jest API cloudowe, ale dla Ciebie to najtańsza opcja, bo jedzie lokalnie na Gemma 3 27B

Uczciwie: nie dodałem żadnego "kilka bilionów parametrów za darmo", bo takie publiczne, stabilne darmowe API nie jest dziś realnym standardem. Najmocniejsze praktyczne darmowe opcje zwykle nie publikują parametrów albo nie są naprawdę darmowe w sensie produkcyjnym.

## Uruchomienie lokalne

### Opcja A, venv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8008
```

### Opcja B, Docker Compose

```bash
docker compose up --build
```

## Logowanie

Przy pierwszym starcie aplikacja tworzy domyślnego admina z `.env`:

- email: `DEFAULT_ADMIN_EMAIL`
- hasło: `DEFAULT_ADMIN_PASSWORD`

## Ekrany aplikacji

### Login
Prosty ekran logowania.

### Dashboard
Lista projektów książek i statusów.

### New Project
Wizard wejściowy krok po kroku:
- tytuł i pomysł
- liczba stron i liczba słów
- styl i język
- źródła inspiracji

Nie da się przejść dalej bez wymaganych pól.

### Project Detail
Tu jest cały workflow:
- tutorial dla usera
- lista darmowych providerów i status konfiguracji
- zakładka pomysłów / research
- etapy automatyzacji z blokadą kolejnych kroków
- ręczna edycja każdego etapu
- export DOCX / PDF

## Automatyzacja etapów

Aplikacja automatyzuje etapy, które opisałeś:

### etap 1
Użytkownik wpisuje tytuł, pomysł, liczbę stron, liczbę słów i źródła.

### etap 2
System tworzy konspekt książki.

### etap 3
System tworzy prompty do napisania rozdziałów.

### etap 4a
System pisze draft książki według outline i promptów.

### etap 4b
System robi redakcję draftu.

### etap 5
Użytkownik może nanieść ręczne poprawki bezpośrednio w panelu.

### etap 6
System generuje SEO description pod Amazon.

### etap 7
System generuje brief okładki z wariantami promptów.

### etap 8
System tworzy checklistę publikacji pod Amazon KDP.

## Co jest teraz automatyczne, a co półautomatyczne

### Automatyczne
- outline
- chapter prompts
- draft
- redakcja
- SEO
- cover brief
- publish checklist
- eksport DOCX/PDF
- idea research tab
- fallback model routing

### Półautomatyczne
- final manual edit
- final cover creation in external tool
- realne wrzucenie książki na Amazon

Powód jest prosty: Amazon KDP nie ma tu bezpiecznej, gotowej integracji plug-and-play bez danych klienta, UI automations albo dedykowanego private workflow. Dlatego system przygotowuje wszystko pod publikację, ale ostatni klik warto zostawić człowiekowi.

## Testy

Uruchom:

```bash
pytest
```

Test sprawdza:
- start aplikacji
- stworzenie admina
- logowanie
- utworzenie projektu
- wejście na detail page
- uruchomienie kroku outline
- uruchomienie kroku prompts
- health endpoint

## Następne rozszerzenia

Jeśli będziesz chciał rozwinąć v2:
- Postgres zamiast SQLite
- background jobs
- wersjonowanie książki
- bardziej granularne jobs w tle i kolejka workerów
- realne web scraping / research connectors
- image generation pod okładki
- Playwright flow do półautomatycznej publikacji na Amazon
- multi-user roles
- billing

## Ważna uwaga jakościowa

Dla dużych książek typu 70k+ słów najlepiej będzie w v2 przejść na:
- generację sekcjami
- pamięć stylu i summary per chapter
- stitching / continuity pass

Obecne MVP dowozi kompletny flow produktu, ale przy bardzo dużych manuskryptach warto rozbić pipeline na bardziej granularne kroki.
