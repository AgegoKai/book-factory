from __future__ import annotations

import re
import threading
import time
from textwrap import dedent
from typing import Callable

from ..models import BookProject, UserSettings
from ..models import BOOK_WRITER_DEFAULT_PROMPT
from .llm import LLMConfig, LLMError, llm_service

# ── In-memory progress store ───────────────────────────────────────────────────
# Lightweight — keyed by project_id; cleared when step finishes.
# Thread-safe enough for SQLite single-instance deployments.

_progress_lock = threading.Lock()
_PROGRESS: dict[int, dict] = {}


def set_progress(project_id: int, *, step: str, msg: str, chapter: int = 0, total: int = 0):
    with _progress_lock:
        _PROGRESS[project_id] = {
            "step": step,
            "msg": msg,
            "chapter": chapter,
            "total": total,
            "ts": time.time(),
        }


def get_progress(project_id: int) -> dict | None:
    with _progress_lock:
        return _PROGRESS.get(project_id)


def clear_progress(project_id: int):
    with _progress_lock:
        _PROGRESS.pop(project_id, None)


MARKET_LABELS = {
    "en-US": "Amazon US (English)",
    "de-DE": "Amazon DE (Deutsch)",
    "es-ES": "Amazon ES (Español)",
    "pl-PL": "Amazon PL (Polski)",
}

MARKET_LANGUAGES = {
    "en-US": "English",
    "de-DE": "Deutsch",
    "es-ES": "Español",
    "pl-PL": "Polski",
}

# System prompts — jawna rola, protokół wyjścia, bez konwersacji z użytkownikiem
SYS_OUTLINE_ARCHITECT = """[Rola] Architekt informacji / redaktor merytoryczny (non-fiction, długa forma).
[Zadanie] Zbuduj hierarchiczny konspekt książki: wstęp, rozdziały z podrozdziałami, zakończenie; głębokość dopasowana do docelowej liczby słów.
[Wyjście] Wyłącznie treść konspektu w języku wskazanym w briefie użytkownika; bez pytań, bez komentarzy metapoziomu."""

SYS_CHAPTER_PROMPT_ENGINEER = """[Rola] Inżynier promptów dla etapu generacji rozdziałów (pipeline LLM).
[Zadanie] Na podstawie konspektu wygeneruj zestaw gotowych promptów — jeden na każdy rozdział/sekcję wymienioną w konspekcie.
[Specyfikacja promptu rozdziału] Cel, zakres merytoryczny, punkty obowiązkowe, ton, ograniczenia formatu; język = język docelowej książki z briefu.
[Wyjście] Tekst zgodny z formatem żądanym w sekcji USER (etykiety ROZDZIAŁ X / Prompt)."""

SYS_EDITOR_FULL = """[Rola] Redaktor naczelny + korektor (język, styl, spójność narracji).
[Zadanie] Redakcja pełnego manuskryptu: płynność, usuwanie powtórzeń, ujednolicenie terminologii; zachowanie sensu i faktów z draftu.
[Wyjście] Wyłącznie zredagowany tekst końcowy — bez komentarzy redakcyjnych i bez metanarracji."""

SYS_EDITOR_CHUNK = """[Rola] Redaktor naczelny (praca na fragmencie większej całości).
[Zadanie] Redakcja przekazanego fragmentu zgodnie z preferencjami stylu; bez zmiany sensu merytorycznego.
[Wyjście] Wyłącznie zredagowany fragment."""


def _sys_seo_specialist(market_label: str) -> str:
    return (
        f"[Rola] Specjalista copywritingu produktowego i pozycjonowania opisów w księgarni "
        f"(Amazon / meta dane dla rynku: {market_label}).\n"
        "[Zadanie] Opis listingu produktu (książka): hook, korzyści, przekaz wartości, wezwanie do działania.\n"
        "[Ograniczenia] ≤ 2500 znaków (łącznie ze spacjami); pierwsze zdanie = silny hook; czysty tekst, bez Markdown; "
        "słowa kluczowe osadzone naturalnie, bez keyword stuffing.\n"
        "[Wyjście] Wyłącznie treść opisu."
    )


def _sys_keywords_specialist(market_label: str) -> str:
    return (
        f"[Rola] Analityk słów kluczowych dla wyszukiwarki produktów Amazon (rynek: {market_label}).\n"
        "[Zadanie] Wygeneruj dokładnie 7 fraz kluczowych (2–5 słów), zgodnych z intencją wyszukiwania kupującego.\n"
        "[Wyjście] Lista numerowana 1–7, jedna fraza na linię; bez duplikacji tokenów z tytułu, jeśli to możliwe."
    )


def _sys_catalog_specialist(market_label: str) -> str:
    return (
        f"[Rola] Kategoryzacja produktów książkowych / drzewo Browse dla {market_label} (Kindle / Books).\n"
        "[Zadanie] (1) Hierarchiczne drzewo kategorii najlepiej dopasowanych do tematu. "
        "(2) Trzy rekomendowane pełne ścieżki kategorii z oceną konkurencji i uzasadnieniem.\n"
        "[Wyjście] Strukturalny tekst zgodny z instrukcją formatu w sekcji USER."
    )


SYS_COVER_ART_DIRECTOR = """[Rola] Art director / brief dla projektu okładki (print + digital thumbnail).
[Zadanie] Brief produkcyjny: koncepcja wizualna, typografia, paleta HEX, kompozycja, trzy prompty do generatora obrazu.
[Wyjście] Wyłącznie treść briefu; bez dyskusji z klientem."""

SYS_PUBLISH_OPS = """[Rola] Specjalista operacyjny Amazon KDP / self-publishing.
[Zadanie] Checklista wdrożenia: plik, metadane, okładka, ceny, kategorie, pre-launch, launch — zadań punktowanych z krótką racją.
[Wyjście] Wyłącznie checklista w strukturze sekcji → punkty."""

SYS_IDEAS_STRATEGIST = """[Rola] Strateg produktu książkowego / research komercyjny.
[Zadanie] Analiza niszy: propozycje tytułów, persony czytelników, problemy do rozwiązania, słowa kluczowe, diferencjacja vs konkurencja.
[Wyjście] Tekst zgodny z numeracją sekcji w sekcji USER; bez pytań zwrotnych."""


def _sys_translation_seo(market_label: str, lang_name: str) -> str:
    return (
        f"[Rola] Lokalizacja opisu produktu (książka) pod kątem {market_label} — język wyjściowy: {lang_name}.\n"
        "[Zadanie] Oryginalny opis sprzedażowy z uwzględnieniem norm kulturowych rynku (nie tłumaczenie dosłowne 1:1).\n"
        "[Ograniczenia] ≤ 2500 znaków; mocny hook w pierwszej linii; czysty tekst.\n"
        "[Wyjście] Wyłącznie opis."
    )


def _sys_translation_keywords(market_label: str) -> str:
    return (
        f"[Rola] Słowa kluczowe Amazon dla {market_label} (lokalny język wyszukiwania).\n"
        "[Zadanie] 7 fraz (2–5 słów); format lista 1–7.\n"
        "[Wyjście] Wyłącznie lista."
    )


def _sys_translation_catalog(market_label: str, lang_name: str) -> str:
    return (
        f"[Rola] Kategoryzacja i ścieżki BISAC/browse dla {market_label}; język wyjściowy: {lang_name}.\n"
        "[Zadanie] Drzewo + 3 ścieżki z konkurencją i uzasadnieniem.\n"
        "[Wyjście] Wyłącznie treść strukturalna zgodna z USER."
    )


def _build_cfg(user_settings: UserSettings | None) -> LLMConfig:
    if not user_settings:
        return LLMConfig()
    return LLMConfig(
        lm_studio_base_url=user_settings.lm_studio_base_url or "",
        lm_studio_api_key=user_settings.lm_studio_api_key or "",
        lm_studio_model=user_settings.lm_studio_model or "",
        google_api_key=user_settings.google_api_key or "",
        google_model=user_settings.google_model or "",
        openrouter_api_key=user_settings.openrouter_api_key or "",
        openrouter_model=user_settings.openrouter_model or "",
        preferred_llm_provider=(user_settings.preferred_llm_provider or "").strip(),
    )


ProgressCallback = Callable[[str, int, int], None]  # (msg, chapter, total)


class BookPipelineService:
    step_order = ["outline", "prompts", "draft", "edit", "seo", "keywords", "catalog", "cover", "publish"]

    def run_full_pipeline(
        self,
        project: BookProject,
        user_settings: UserSettings | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BookProject:
        def _prog(msg, ch=0, tot=0):
            if on_progress:
                on_progress(msg, ch, tot)
        cfg = _build_cfg(user_settings)
        _prog("Generuję konspekt...")
        self.generate_outline(project, cfg)
        _prog("Generuję prompty rozdziałów...")
        self.generate_prompts(project, cfg)
        self.generate_draft(project, cfg, on_progress=on_progress)
        self.generate_edit(project, cfg, on_progress=on_progress)
        _prog("Generuję opis SEO...")
        self.generate_seo(project, cfg)
        _prog("Generuję słowa kluczowe...")
        self.generate_keywords(project, cfg)
        _prog("Generuję drzewo katalogu...")
        self.generate_catalog(project, cfg)
        _prog("Generuję brief okładki...")
        self.generate_cover(project, cfg)
        _prog("Generuję checklistę publikacji...")
        self.generate_publish(project, cfg)
        project.status = "ready"
        return project

    def run_step(
        self,
        project: BookProject,
        step: str,
        user_settings: UserSettings | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BookProject:
        cfg = _build_cfg(user_settings)
        if step == "draft":
            return self.generate_draft(project, cfg, on_progress=on_progress)
        if step == "edit":
            return self.generate_edit(project, cfg, on_progress=on_progress)
        handlers = {
            "outline": self.generate_outline,
            "prompts": self.generate_prompts,
            "seo": self.generate_seo,
            "keywords": self.generate_keywords,
            "catalog": self.generate_catalog,
            "cover": self.generate_cover,
            "publish": self.generate_publish,
        }
        if step not in handlers:
            raise ValueError(f"Unknown step: {step}")
        return handlers[step](project, cfg)

    # ------------------------------------------------------------------ steps

    def generate_outline(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        context = self._context(project)
        outline, provider = self._generate(
            SYS_OUTLINE_ARCHITECT,
            dedent(f"""
            Stwórz szczegółowy konspekt książki w języku: {project.language}.
            Konspekt musi zawierać: wstęp, {max(5, project.target_pages // 4)} rozdziałów z podrozdziałami, zakończenie.
            Każdy rozdział powinien mieć tytuł i 2-3 zdania opisu zawartości.
            Liczba rozdziałów powinna odpowiadać docelowej liczbie słów: {project.target_words}.

            {context}
            """),
            cfg,
        )
        project.outline_text = outline
        project.llm_provider_used = provider
        project.status = "outline_ready"
        return project

    def generate_prompts(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        context = self._context(project)
        chapter_prompts, provider = self._generate(
            SYS_CHAPTER_PROMPT_ENGINEER,
            dedent(f"""
            Na podstawie poniższego konspektu, napisz osobny prompt do napisania każdego rozdziału.
            Format: "ROZDZIAŁ X: [Tytuł]\nPrompt: [treść prompta]"
            Każdy prompt powinien zawierać: główny temat, kluczowe punkty do omówienia, styl narracji.

            KONSPEKT:
            {project.outline_text}

            {context}
            """),
            cfg,
        )
        project.chapter_prompts = chapter_prompts
        project.llm_provider_used = provider
        project.status = "prompts_ready"
        return project

    def generate_draft(
        self,
        project: BookProject,
        cfg: LLMConfig | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BookProject:
        """Generate draft chapter by chapter to avoid timeout and improve coherence."""
        cfg = cfg or LLMConfig()
        system_prompt = (project.custom_system_prompt or "").strip() or BOOK_WRITER_DEFAULT_PROMPT

        chapters = self._parse_chapters(project.outline_text)
        if not chapters:
            if on_progress:
                on_progress("Generuję draft (jeden blok)...", 1, 1)
            manuscript, provider = self._generate(
                system_prompt,
                dedent(f"""
                Napisz pełny draft książki w języku: {project.language}.
                Stosuj styl: {project.tone_preferences}
                Docelowa objętość: {project.target_words} słów.

                KONSPEKT:
                {project.outline_text}

                PROMPTY ROZDZIAŁÓW:
                {project.chapter_prompts}

                WAŻNE — FORMAT WYJŚCIA:
                - Pisz wyłącznie czysty tekst narracji, bez Markdown (**bold**, *italic*, list punktowanych).
                - Nie dodawaj linków URL, hasztagów (#słowo), ani ozdobnych separatorów (---, ***).
                - Rozdziały zaznaczaj: "Rozdział N: Tytuł" lub "# Tytuł".
                - Podrozdziały zaznaczaj: "## Tytuł". Nic więcej.
                """),
                cfg,
            )
            project.manuscript_text = manuscript
            project.llm_provider_used = provider
        else:
            parts: list[str] = []
            last_provider = "template_fallback"
            context_window = ""
            total = len(chapters)

            for i, chapter_title in enumerate(chapters, 1):
                if on_progress:
                    on_progress(f"Piszę rozdział {i}/{total}: {chapter_title[:60]}", i, total)
                chapter_prompt = self._get_chapter_prompt(project.chapter_prompts, chapter_title, i)
                continuation = (
                    f"\n\nKontynuacja od: ...{context_window[-600:]}" if context_window else ""
                )
                user_msg = dedent(f"""
                Napisz rozdział dla: "{chapter_title}"
                Język: {project.language}
                Styl: {project.tone_preferences}
                To jest rozdział {i} z {total}.{continuation}

                Instrukcje dla tego rozdziału:
                {chapter_prompt}

                Konspekt całości (dla zachowania ciągłości):
                {project.outline_text[:2000]}

                WAŻNE — FORMAT WYJŚCIA:
                - Pisz wyłącznie czysty tekst narracji, bez Markdown (**bold**, *italic*, list punktowanych).
                - Nie dodawaj linków URL, hasztagów (#słowo), ani ozdobnych separatorów (---, ***).
                - Podrozdziały zaznaczaj tylko: "## Tytuł" — nic więcej.
                - Bez metakomentarzy typu "W tym rozdziale omówię...".
                """)

                text, provider = self._generate(system_prompt, user_msg, cfg)
                parts.append(f"\n\n{'=' * 40}\n{chapter_title}\n{'=' * 40}\n\n{text}")
                context_window = text
                last_provider = provider

            project.manuscript_text = "\n".join(parts).strip()
            project.llm_provider_used = last_provider

        project.status = "draft_ready"
        return project

    def generate_edit(
        self,
        project: BookProject,
        cfg: LLMConfig | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BookProject:
        cfg = cfg or LLMConfig()
        system_prompt = (project.custom_system_prompt or "").strip() or BOOK_WRITER_DEFAULT_PROMPT
        draft = project.manuscript_text or ""
        chunk_size = 8000
        if len(draft) <= chunk_size:
            if on_progress:
                on_progress("Redaguję manuskrypt...", 1, 1)
            edited, provider = self._generate(
                system_prompt + "\n\n" + SYS_EDITOR_FULL,
                dedent(f"""
                Zredaguj poniższy draft: popraw flow, styl, spójność narracyjną, usuń powtórzenia.
                Zachowaj naturalny ludzki głos. Preferencje stylu: {project.tone_preferences}

                DRAFT:
                {draft}
                """),
                cfg,
            )
            project.edited_text = edited
            project.llm_provider_used = provider
        else:
            chunks = [draft[i:i + chunk_size] for i in range(0, len(draft), chunk_size)]
            total = len(chunks)
            edited_parts = []
            last_provider = "template_fallback"
            for idx, chunk in enumerate(chunks, 1):
                if on_progress:
                    on_progress(f"Redaguję fragment {idx}/{total}...", idx, total)
                edited_chunk, provider = self._generate(
                    system_prompt + "\n\n" + SYS_EDITOR_CHUNK,
                    dedent(f"""
                    Zredaguj ten fragment książki: popraw flow, styl, usuń powtórzenia.
                    Preferencje stylu: {project.tone_preferences}

                    FRAGMENT:
                    {chunk}
                    """),
                    cfg,
                )
                edited_parts.append(edited_chunk)
                last_provider = provider
            project.edited_text = "\n\n".join(edited_parts)
            project.llm_provider_used = last_provider

        project.status = "edit_ready"
        return project

    def generate_seo(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon")
        market_lang = MARKET_LANGUAGES.get(project.target_market or "en-US", project.language)

        audience_info = ""
        if project.target_audience:
            audience_info = f"\nODBIORCA: {project.target_audience}"
        if project.emotions_to_convey:
            audience_info += f"\nEMOCJE DO PRZEKAZANIA: {project.emotions_to_convey}"
        if project.writing_style:
            audience_info += f"\nSTYL PISANIA: {project.writing_style}"
        if project.author_bio:
            audience_info += f"\nAUTOR: {project.author_bio}"

        seo, provider = self._generate(
            _sys_seo_specialist(market_label),
            dedent(f"""
            Napisz przekonujący opis sprzedażowy na {market_label}.
            Język opisu: {market_lang}.

            WYMAGANIA:
            - Maksymalnie 2500 znaków (WAŻNE: nie przekraczaj limitu)
            - Zacznij od MOCNEGO HOOKA — pierwsze zdanie musi natychmiast przyciągnąć uwagę i wzbudzić ciekawość
            - Następnie: korzyści dla czytelnika, kluczowe tematy, call-to-action
            - Używaj słów kluczowych organicznie
            - Format: czysty tekst, bez nagłówków Markdown

            TYTUŁ: {project.title}
            STRESZCZENIE: {project.concept}
            {audience_info}
            FRAGMENT KSIĄŻKI:
            {(project.edited_text or project.manuscript_text)[:4000]}
            """),
            cfg,
        )
        project.seo_description = seo
        project.llm_provider_used = provider
        project.status = "seo_ready"
        return project

    def generate_keywords(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon")
        market_lang = MARKET_LANGUAGES.get(project.target_market or "en-US", project.language)

        keywords, provider = self._generate(
            _sys_keywords_specialist(market_label),
            dedent(f"""
            Wygeneruj dokładnie 7 słów kluczowych (keyword phrases) do tej książki na {market_label}.
            Język słów kluczowych: {market_lang}.

            ZASADY:
            - Każde keyword to fraza 2-5 słów (nie pojedyncze słowo)
            - Frazy muszą być tym, co kupujący FAKTYCZNIE wpisują w Amazon
            - Nie powtarzaj słów z tytułu książki (Amazon już je indeksuje)
            - Uwzględnij różne kąty: problem, rozwiązanie, persona czytelnika, podobne tematy
            - Format odpowiedzi: lista numerowana 1-7, każde keyword w osobnej linii

            TYTUŁ: {project.title}
            TEMAT: {project.concept}
            ODBIORCA: {project.target_audience or 'ogólny'}
            SEO OPIS (dla kontekstu):
            {project.seo_description[:1500]}
            """),
            cfg,
        )
        project.amazon_keywords = keywords
        project.llm_provider_used = provider
        project.status = "keywords_ready"
        return project

    def generate_catalog(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon")
        market_lang = MARKET_LANGUAGES.get(project.target_market or "en-US", project.language)

        catalog, provider = self._generate(
            _sys_catalog_specialist(market_label),
            dedent(f"""
            Przygotuj kompletne drzewo katalogu i ścieżki dla tej książki na {market_label}.
            Język odpowiedzi: {market_lang}.

            CZĘŚĆ 1 — DRZEWO KATALOGU AMAZON:
            Podaj hierarchiczne drzewo kategorii Amazon (Browse Nodes) najlepiej pasujące do tej książki.
            Format:
            > Kategoria główna
              > Podkategoria
                > Podkategoria szczegółowa

            CZĘŚĆ 2 — 3 IDEALNE ŚCIEŻKI:
            Podaj 3 najlepsze ścieżki kategorii Amazon KDP (Kindle lub Books) dla tej książki.
            Dla każdej ścieżki podaj:
            - Pełna ścieżka kategorii (np. Books > Self-Help > Creativity)
            - Poziom konkurencji (niski/średni/wysoki)
            - Uzasadnienie dlaczego ta ścieżka

            TYTUŁ: {project.title}
            TEMAT: {project.concept}
            ODBIORCA: {project.target_audience or 'ogólny'}
            RYNEK: {market_label}
            """),
            cfg,
        )
        project.catalog_tree = catalog
        project.llm_provider_used = provider
        project.status = "catalog_ready"
        return project

    def generate_cover(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        cover, provider = self._generate(
            SYS_COVER_ART_DIRECTOR,
            dedent(f"""
            Stwórz kompletny brief okładki dla tej książki. Uwzględnij:
            1. Koncepcja wizualna (główny motyw, nastrój, symbolika)
            2. Typografia (family, weight, rozmiar tytułu i autora)
            3. Paleta kolorów (z kodami hex)
            4. Kompozycja (co na pierwszym planie, tło, układ)
            5. Trzy warianty promptów do generatora AI (Midjourney/DALL-E style)

            TYTUŁ: {project.title}
            OPIS: {project.concept}
            STYL: {project.writing_style or project.tone_preferences}
            ODBIORCA: {project.target_audience or 'ogólny'}
            SEO: {project.seo_description[:800]}
            """),
            cfg,
        )
        project.cover_brief = cover
        project.llm_provider_used = provider
        project.status = "cover_ready"
        return project

    def generate_publish(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon KDP")
        checklist, provider = self._generate(
            SYS_PUBLISH_OPS + f"\n[Kontekst rynku] {market_label}",
            dedent(f"""
            Stwórz kompletną checklistę publikacji na {market_label} dla tej książki.
            Podziel na sekcje: przygotowanie pliku, metadane, okładka, pricing, kategorie, pre-launch, launch.
            Format: sekcja → punktorowane zadania z krótkim wyjaśnieniem.

            TYTUŁ: {project.title}
            DOCELOWE SŁOWA: {project.target_words}
            RYNEK: {market_label}
            SEO:
            {project.seo_description[:1500]}
            """),
            cfg,
        )
        project.publish_checklist = checklist
        project.llm_provider_used = provider
        project.status = "ready"
        return project

    def generate_translation(
        self,
        project: BookProject,
        target_lang: str,
        user_settings: UserSettings | None = None,
    ) -> dict:
        """Generate a full localization pack (SEO + keywords + catalog) for target_lang."""
        cfg = _build_cfg(user_settings)
        lang_map = {
            "de": ("de-DE", "Deutsch", "Amazon DE"),
            "es": ("es-ES", "Español", "Amazon ES"),
            "en": ("en-US", "English", "Amazon US"),
            "pl": ("pl-PL", "Polski", "Amazon PL"),
        }
        market_code, lang_name, market_label = lang_map.get(target_lang, ("en-US", "English", "Amazon US"))

        seo, _ = self._generate(
            _sys_translation_seo(market_label, lang_name),
            dedent(f"""
            Napisz przekonujący opis sprzedażowy na {market_label}.
            Język opisu: {lang_name}.

            WYMAGANIA:
            - Maksymalnie 2500 znaków
            - Zacznij od MOCNEGO HOOKA dostosowanego kulturowo do rynku {market_label}
            - Korzyści dla czytelnika, kluczowe tematy, call-to-action
            - Styl i ton odpowiedni dla rynku {market_label} (Niemcy preferują konkretność, Hiszpanie — emocje)
            - Format: czysty tekst

            TYTUŁ: {project.title}
            STRESZCZENIE: {project.concept}
            ODBIORCA: {project.target_audience or 'ogólny'}
            ORYGINALNY OPIS SEO (dla kontekstu, nie tłumacz 1:1):
            {project.seo_description[:2000]}
            """),
            cfg,
        )

        keywords, _ = self._generate(
            _sys_translation_keywords(market_label),
            dedent(f"""
            Wygeneruj 7 słów kluczowych (keyword phrases) dla tej książki na {market_label}.
            Język: {lang_name}.
            - Frazy 2-5 słów, które kupujący wpisują w Amazon {market_label.split()[-1]}
            - Nie powtarzaj słów z tytułu
            - Format: lista numerowana 1-7

            TYTUŁ: {project.title}
            TEMAT: {project.concept}
            ODBIORCA: {project.target_audience or 'ogólny'}
            """),
            cfg,
        )

        catalog, _ = self._generate(
            _sys_translation_catalog(market_label, lang_name),
            dedent(f"""
            Przygotuj drzewo katalogu i 3 idealne ścieżki dla tej książki na {market_label}.
            Język: {lang_name}.

            CZĘŚĆ 1 — DRZEWO KATEGORII {market_label.upper()}:
            Hierarchiczne drzewo kategorii właściwych dla rynku {market_label}.

            CZĘŚĆ 2 — 3 IDEALNE ŚCIEŻKI:
            Dla każdej: pełna ścieżka, poziom konkurencji, uzasadnienie.

            TYTUŁ: {project.title}
            TEMAT: {project.concept}
            """),
            cfg,
        )

        return {
            "seo": seo,
            "keywords": keywords,
            "catalog": catalog,
            "lang": target_lang,
            "market": market_label,
        }

    def generate_ideas(
        self,
        niche: str,
        notes: str = "",
        user_settings: UserSettings | None = None,
    ) -> tuple[str, str]:
        cfg = _build_cfg(user_settings)
        return self._generate(
            SYS_IDEAS_STRATEGIST,
            dedent(f"""
            Wygeneruj pomysły na książki w tej niszy, hooks sprzedażowe, kąty dla czytelnika i notatki research.
            Skup się na komercyjnie opłacalnych kątach.

            NISZA: {niche}
            NOTATKI: {notes or 'brak'}

            Format:
            1. Top 5 pomysłów na tytuły z jednozdaniowym opisem
            2. Idealni czytelnicy (3 persony)
            3. Kluczowe problemy, które książka rozwiązuje
            4. Sugerowane słowa kluczowe Amazon
            5. Konkurencja (co robić inaczej)
            """),
            cfg,
        )

    # --------------------------------------------------------------- internals

    def _context(self, project: BookProject) -> str:
        lines = [
            f"TYTUŁ: {project.title}",
            f"POMYSŁ: {project.concept}",
            f"DOCELOWE STRONY: {project.target_pages}",
            f"DOCELOWE SŁOWA: {project.target_words}",
            f"STYL: {project.tone_preferences}",
            f"JĘZYK: {project.language}",
            f"RYNEK: {MARKET_LABELS.get(project.target_market or 'en-US', project.target_market)}",
        ]
        if project.writing_style:
            lines.append(f"STYL PISANIA: {project.writing_style}")
        if project.target_audience:
            lines.append(f"ODBIORCA: {project.target_audience}")
        if project.emotions_to_convey:
            lines.append(f"EMOCJE DO PRZEKAZANIA: {project.emotions_to_convey}")
        if project.knowledge_to_share:
            lines.append(f"WIEDZA/EKSPERTYZA: {project.knowledge_to_share}")
        if project.author_bio:
            lines.append(f"AUTOR: {project.author_bio}")
        if project.inspiration_sources:
            lines.append(f"ŹRÓDŁA INSPIRACJI: {project.inspiration_sources}")
        return "\n".join(lines)

    def _parse_chapters(self, outline: str) -> list[str]:
        """Extract chapter titles from outline text."""
        if not outline:
            return []
        chapters = []
        patterns = [
            r"(?:Rozdział|Chapter|ROZDZIAŁ|CHAPTER|Kapitel|Capítulo)\s+\d+[:\.]?\s*(.+)",
            r"^\s*(\d+)\.\s+(.+)",
            r"^#{1,3}\s+(.+)",
        ]
        for line in outline.splitlines():
            line = line.strip()
            if not line:
                continue
            for pattern in patterns:
                m = re.match(pattern, line, re.IGNORECASE)
                if m:
                    title = m.group(len(m.groups()))
                    title = title.strip().rstrip(":")
                    if len(title) > 3:
                        chapters.append(title)
                    break
        return chapters[:30]

    def _get_chapter_prompt(self, prompts_text: str, chapter_title: str, index: int) -> str:
        """Find chapter-specific prompt from chapter_prompts text."""
        if not prompts_text:
            return f"Napisz treść rozdziału: {chapter_title}"
        lines = prompts_text.splitlines()
        for i, line in enumerate(lines):
            if chapter_title.lower()[:20] in line.lower() or f"rozdział {index}" in line.lower():
                prompt_lines = lines[i: i + 8]
                return "\n".join(prompt_lines).strip()
        chunk_size = max(1, len(prompts_text) // 10)
        start = (index - 1) * chunk_size
        return prompts_text[start: start + chunk_size].strip() or f"Napisz treść rozdziału: {chapter_title}"

    def _generate(
        self,
        system_prompt: str,
        user_prompt: str,
        cfg: LLMConfig | None = None,
    ) -> tuple[str, str]:
        try:
            return llm_service.generate(system_prompt, user_prompt, cfg)
        except LLMError:
            fallback = self._fallback_text(system_prompt, user_prompt)
            return fallback, "template_fallback"

    def _fallback_text(self, system_prompt: str, user_prompt: str) -> str:
        from textwrap import dedent as _d
        return _d(f"""
        [Fallback output — brak połączenia z LLM]
        Zadanie systemu: {system_prompt[:200]}

        Ta sekcja została wygenerowana bez odpowiedzi LLM. Podłącz LM Studio, Gemini lub OpenRouter w ustawieniach.

        Podsumowanie żądania:
        {user_prompt[:2000]}
        """).strip()


book_pipeline_service = BookPipelineService()
