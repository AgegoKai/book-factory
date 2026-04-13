from __future__ import annotations

import re
import threading
import time
from math import ceil
from textwrap import dedent
from typing import Callable

from ..models import (
    BookProject,
    UserSettings,
    deserialize_writing_styles,
    get_book_writer_default_prompt,
)
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

def _prompt_locale(language: str | None) -> str:
    raw = (language or "").strip().lower()
    if raw.startswith("pl"):
        return "pl"
    if raw.startswith("de"):
        return "de"
    return "en"


def _language_name(language: str | None) -> str:
    raw = (language or "").strip().lower()
    names = {
        "pl": "Polish",
        "en": "English",
        "de": "German",
        "es": "Spanish",
        "fr": "French",
    }
    return names.get(raw.split("-")[0], language or "English")


def _sys_outline_architect(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Informationsarchitekt / Fachredakteur fuer Sachbuch und Langform.
[Aufgabe] Erstelle eine hierarchische Buchgliederung mit exakt der geforderten Kapitelzahl; jedes Kapitel braucht Unterkapitel und muss zur Zielwortzahl passen.
[Grenzen] Keine erfundenen Quellen, Fussnoten oder Bibliografien. Kapitel- und Untertitel nicht im uebertriebenen Title Case schreiben.
[Ausgabe] Nur die Gliederung in der im Briefing vorgegebenen Buchsprache; keine Fragen, keine Metakommentare."""
    if locale == "en":
        return """[Role] Information architect / developmental editor for non-fiction long-form books.
[Task] Build a hierarchical outline with exactly the requested number of chapters; each chapter needs subsections and must fit the target word count.
[Constraints] No invented citations, footnotes, bibliography, or fabricated sources. Do not use all-words title case for headings.
[Output] Return only the outline in the book language specified in the brief. No questions, no meta commentary."""
    return """[Rola] Architekt informacji / redaktor merytoryczny (non-fiction, długa forma).
[Zadanie] Zbuduj hierarchiczny konspekt książki z dokładnie wskazaną liczbą rozdziałów; każdy rozdział ma mieć podrozdziały i pasować do docelowej liczby słów.
[Ograniczenia] Bez zmyślonych przypisów, bibliografii i źródeł. Tytuły zapisuj normalną kapitalizacją zdaniową, nie title case dla każdego słowa.
[Wyjście] Wyłącznie treść konspektu w języku wskazanym w briefie użytkownika; bez pytań, bez komentarzy metapoziomu."""


def _sys_chapter_prompt_engineer(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Prompt-Ingenieur fuer die Kapitelgenerierung in einer LLM-Pipeline.
[Aufgabe] Erzeuge auf Basis der Gliederung Prompt-Bloecke fuer die Kapitelgenerierung.
[Kapitel-Prompt] Ziel, inhaltlicher Umfang, Pflichtpunkte, Mindest- und Zielwortzahl, Ton und Formatregeln; Sprache = Zielsprache des Buchs.
[Grenzen] Keine erfundenen Quellen oder Fussnoten; nie weniger Prompt-Bloecke als Kapitel.
[Ausgabe] Text im vom USER geforderten Format."""
    if locale == "en":
        return """[Role] Prompt engineer for chapter-generation in an LLM pipeline.
[Task] Based on the outline, generate prompt blocks for chapter drafting.
[Chapter prompt spec] Goal, scope, mandatory points, minimum and target word counts, tone, and formatting constraints; language = target book language from the brief.
[Constraints] No invented sources or footnotes; never return fewer prompt blocks than chapters.
[Output] Return text in the format requested by the USER section."""
    return """[Rola] Inżynier promptów dla etapu generacji rozdziałów (pipeline LLM).
[Zadanie] Na podstawie konspektu wygeneruj bloki promptów do pisania rozdziałów.
[Specyfikacja promptu rozdziału] Cel, zakres merytoryczny, punkty obowiązkowe, minimalna i docelowa liczba słów, ton, ograniczenia formatu; język = język docelowej książki z briefu.
[Ograniczenia] Bez zmyślonych źródeł i przypisów; nigdy mniej bloków promptów niż rozdziałów.
[Wyjście] Tekst zgodny z formatem żądanym w sekcji USER."""


def _sys_editor_full(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Chefredakteur und Korrektor.
[Aufgabe] Vollstaendige Redaktion des Manuskripts: Fluss verbessern, Wiederholungen entfernen, Terminologie vereinheitlichen; Sinn und Fakten muessen erhalten bleiben.
[Ausgabe] Nur der redigierte Endtext, ohne Redaktionskommentare und ohne Metanarration."""
    if locale == "en":
        return """[Role] Chief editor and copy editor.
[Task] Edit the full manuscript for flow, repetition, consistency, and terminology while preserving meaning and facts.
[Output] Return only the edited manuscript text, with no editorial commentary or meta narration."""
    return """[Rola] Redaktor naczelny + korektor (język, styl, spójność narracji).
[Zadanie] Redakcja pełnego manuskryptu: płynność, usuwanie powtórzeń, ujednolicenie terminologii; zachowanie sensu i faktów z draftu.
[Wyjście] Wyłącznie zredagowany tekst końcowy — bez komentarzy redakcyjnych i bez metanarracji."""


def _sys_editor_chunk(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Chefredakteur fuer einen Ausschnitt eines groesseren Manuskripts.
[Aufgabe] Redigiere den uebergebenen Abschnitt gemaess den Stilvorgaben, ohne den inhaltlichen Sinn zu veraendern.
[Ausgabe] Nur der redigierte Abschnitt."""
    if locale == "en":
        return """[Role] Chief editor working on a fragment of a larger manuscript.
[Task] Edit the supplied fragment to improve style and flow without changing the underlying meaning.
[Output] Return only the edited fragment."""
    return """[Rola] Redaktor naczelny (praca na fragmencie większej całości).
[Zadanie] Redakcja przekazanego fragmentu zgodnie z preferencjami stylu; bez zmiany sensu merytorycznego.
[Wyjście] Wyłącznie zredagowany fragment."""


def _sys_seo_specialist(market_label: str, locale: str) -> str:
    if locale == "de":
        return (
            f"[Rolle] Produkt-Copywriter und Listing-SEO-Spezialist fuer den Buchhandel ({market_label}).\n"
            "[Aufgabe] Verfasse den Buch-Listing-Text mit starkem Hook, Lesermehrwert, klarer Positionierung und Call-to-Action.\n"
            "[Grenzen] <= 2500 Zeichen inklusive Leerzeichen; der erste Satz muss sofort Aufmerksamkeit erzeugen; reiner Text ohne Markdown; Keywords natuerlich einbauen.\n"
            "[Ausgabe] Nur die Beschreibung."
        )
    if locale == "en":
        return (
            f"[Role] Product copywriter and bookstore SEO specialist for {market_label}.\n"
            "[Task] Write a book listing description with a strong hook, clear reader benefits, positioning, and call to action.\n"
            "[Constraints] <= 2500 characters including spaces; the first sentence must be a strong hook; plain text only, no Markdown; weave keywords in naturally.\n"
            "[Output] Return only the description."
        )
    return (
        f"[Rola] Specjalista copywritingu produktowego i pozycjonowania opisów w księgarni "
        f"(Amazon / meta dane dla rynku: {market_label}).\n"
        "[Zadanie] Opis listingu produktu (książka): hook, korzyści, przekaz wartości, wezwanie do działania.\n"
        "[Ograniczenia] ≤ 2500 znaków (łącznie ze spacjami); pierwsze zdanie = silny hook; czysty tekst, bez Markdown; "
        "słowa kluczowe osadzone naturalnie, bez keyword stuffing.\n"
        "[Wyjście] Wyłącznie treść opisu."
    )


def _sys_keywords_specialist(market_label: str, locale: str) -> str:
    if locale == "de":
        return (
            f"[Rolle] Amazon-Keyword-Analyst fuer den Markt {market_label}.\n"
            "[Aufgabe] Erzeuge genau 7 Keyword-Phrasen mit 2-5 Woertern, passend zur Suchintention der Kaeufer.\n"
            "[Ausgabe] Nummerierte Liste 1-7, eine Phrase pro Zeile; moeglichst ohne doppelte Titel-Tokens."
        )
    if locale == "en":
        return (
            f"[Role] Amazon keyword analyst for the {market_label} market.\n"
            "[Task] Generate exactly 7 keyword phrases with 2-5 words each that match buyer intent.\n"
            "[Output] Numbered list 1-7, one phrase per line; avoid duplicating title tokens when possible."
        )
    return (
        f"[Rola] Analityk słów kluczowych dla wyszukiwarki produktów Amazon (rynek: {market_label}).\n"
        "[Zadanie] Wygeneruj dokładnie 7 fraz kluczowych (2–5 słów), zgodnych z intencją wyszukiwania kupującego.\n"
        "[Wyjście] Lista numerowana 1–7, jedna fraza na linię; bez duplikacji tokenów z tytułu, jeśli to możliwe."
    )


def _sys_catalog_specialist(market_label: str, locale: str) -> str:
    if locale == "de":
        return (
            f"[Rolle] Buchkategorisierung / Browse-Tree-Spezialist fuer {market_label} (Kindle / Books).\n"
            "[Aufgabe] (1) Erstelle die am besten passenden hierarchischen Kategorien. (2) Gib drei empfohlene Vollpfade mit Wettbewerbsniveau und Begruendung an.\n"
            "[Ausgabe] Strukturierter Text gemaess der USER-Anweisung."
        )
    if locale == "en":
        return (
            f"[Role] Book categorization / browse-tree specialist for {market_label} (Kindle / Books).\n"
            "[Task] (1) Build the best-fit category tree. (2) Recommend three full category paths with competition level and reasoning.\n"
            "[Output] Structured text matching the USER formatting instructions."
        )
    return (
        f"[Rola] Kategoryzacja produktów książkowych / drzewo Browse dla {market_label} (Kindle / Books).\n"
        "[Zadanie] (1) Hierarchiczne drzewo kategorii najlepiej dopasowanych do tematu. "
        "(2) Trzy rekomendowane pełne ścieżki kategorii z oceną konkurencji i uzasadnieniem.\n"
        "[Wyjście] Strukturalny tekst zgodny z instrukcją formatu w sekcji USER."
    )


def _sys_cover_art_director(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Art Director / Cover-Brief fuer Print und digitales Thumbnail.
[Aufgabe] Erstelle einen Produktionsbrief mit visueller Idee, Typografie, HEX-Palette, Komposition und drei Bildgenerator-Prompts.
[Ausgabe] Nur der Brief, keine Rueckfragen."""
    if locale == "en":
        return """[Role] Art director / cover brief for print and digital thumbnail.
[Task] Produce a cover brief with visual concept, typography, HEX palette, composition, and three image-generator prompts.
[Output] Return only the brief, with no client-facing discussion."""
    return """[Rola] Art director / brief dla projektu okładki (print + digital thumbnail).
[Zadanie] Brief produkcyjny: koncepcja wizualna, typografia, paleta HEX, kompozycja, trzy prompty do generatora obrazu.
[Wyjście] Wyłącznie treść briefu; bez dyskusji z klientem."""


def _sys_publish_ops(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Spezialist fuer Amazon KDP / Self-Publishing Operations.
[Aufgabe] Erstelle eine umsetzbare Checkliste fuer Datei, Metadaten, Cover, Preis, Kategorien, Pre-Launch und Launch; jede Aufgabe mit kurzem Grund.
[Ausgabe] Nur die Checkliste, strukturiert als Abschnitte mit Punkten."""
    if locale == "en":
        return """[Role] Amazon KDP / self-publishing operations specialist.
[Task] Build an actionable checklist for file prep, metadata, cover, pricing, categories, pre-launch, and launch, with a short reason for each task.
[Output] Return only the checklist, structured as sections and bullet points."""
    return """[Rola] Specjalista operacyjny Amazon KDP / self-publishing.
[Zadanie] Checklista wdrożenia: plik, metadane, okładka, ceny, kategorie, pre-launch, launch — zadań punktowanych z krótką racją.
[Wyjście] Wyłącznie checklista w strukturze sekcji → punkty."""


def _sys_ideas_strategist(locale: str) -> str:
    if locale == "de":
        return """[Rolle] Strateg fuer Buchprodukte / kommerzielle Recherche.
[Aufgabe] Analysiere die Nische: moegliche Titel, Leser-Personas, zu loesende Probleme, Keywords und Differenzierung gegenueber Konkurrenz.
[Ausgabe] Text gemaess der USER-Nummerierung, ohne Rueckfragen."""
    if locale == "en":
        return """[Role] Book product strategist / commercial research analyst.
[Task] Analyze the niche: title concepts, reader personas, problems to solve, keywords, and differentiation versus competitors.
[Output] Return text following the numbered USER format, with no follow-up questions."""
    return """[Rola] Strateg produktu książkowego / research komercyjny.
[Zadanie] Analiza niszy: propozycje tytułów, persony czytelników, problemy do rozwiązania, słowa kluczowe, diferencjacja vs konkurencja.
[Wyjście] Tekst zgodny z numeracją sekcji w sekcji USER; bez pytań zwrotnych."""


def _sys_translation_seo(market_label: str, lang_name: str, locale: str) -> str:
    if locale == "de":
        return (
            f"[Rolle] Lokalisierung von Buchbeschreibungen fuer {market_label}; Ausgabesprache: {lang_name}.\n"
            "[Aufgabe] Schreibe eine originelle Verkaufsbeschreibung, kulturell passend fuer den Zielmarkt, nicht als Woerter-fuer-Woerter-Uebersetzung.\n"
            "[Grenzen] <= 2500 Zeichen; starke Hook-Zeile am Anfang; reiner Text.\n"
            "[Ausgabe] Nur die Beschreibung."
        )
    if locale == "en":
        return (
            f"[Role] Localization specialist for book product descriptions targeting {market_label}; output language: {lang_name}.\n"
            "[Task] Write an original sales description adapted to the target market rather than a literal 1:1 translation.\n"
            "[Constraints] <= 2500 characters; strong hook in the opening line; plain text only.\n"
            "[Output] Return only the description."
        )
    return (
        f"[Rola] Lokalizacja opisu produktu (książka) pod kątem {market_label} — język wyjściowy: {lang_name}.\n"
        "[Zadanie] Oryginalny opis sprzedażowy z uwzględnieniem norm kulturowych rynku (nie tłumaczenie dosłowne 1:1).\n"
        "[Ograniczenia] ≤ 2500 znaków; mocny hook w pierwszej linii; czysty tekst.\n"
        "[Wyjście] Wyłącznie opis."
    )


def _sys_translation_keywords(market_label: str, locale: str) -> str:
    if locale == "de":
        return (
            f"[Rolle] Amazon-Keyword-Spezialist fuer {market_label} in der lokalen Suchsprache.\n"
            "[Aufgabe] Erstelle 7 Keyword-Phrasen mit 2-5 Woertern im Format 1-7.\n"
            "[Ausgabe] Nur die Liste."
        )
    if locale == "en":
        return (
            f"[Role] Amazon keyword specialist for {market_label} in the local search language.\n"
            "[Task] Generate 7 keyword phrases with 2-5 words each in a numbered 1-7 list.\n"
            "[Output] Return only the list."
        )
    return (
        f"[Rola] Słowa kluczowe Amazon dla {market_label} (lokalny język wyszukiwania).\n"
        "[Zadanie] 7 fraz (2–5 słów); format lista 1–7.\n"
        "[Wyjście] Wyłącznie lista."
    )


def _sys_translation_catalog(market_label: str, lang_name: str, locale: str) -> str:
    if locale == "de":
        return (
            f"[Rolle] Kategorisierung und Browse-Pfade fuer {market_label}; Ausgabesprache: {lang_name}.\n"
            "[Aufgabe] Erstelle den Kategoriebaum plus 3 empfohlene Pfade mit Wettbewerbsniveau und Begruendung.\n"
            "[Ausgabe] Nur strukturierter Text gemaess USER."
        )
    if locale == "en":
        return (
            f"[Role] Categorization and browse-path specialist for {market_label}; output language: {lang_name}.\n"
            "[Task] Build the category tree plus 3 recommended paths with competition level and reasoning.\n"
            "[Output] Return only structured text matching the USER instructions."
        )
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

_TITLE_CASE_SMALL_WORDS = {
    "en": {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "via", "with"},
    "pl": {"a", "i", "lub", "na", "o", "od", "oraz", "po", "u", "w", "z", "ze"},
}


def _count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or "", flags=re.UNICODE))


def _target_chapters(project: BookProject) -> int:
    configured = int(getattr(project, "target_chapters", 0) or 0)
    if configured > 0:
        return max(3, configured)
    legacy_pages = int(getattr(project, "target_pages", 0) or 0)
    return max(5, legacy_pages // 4) if legacy_pages else 10


def _style_mix(project: BookProject, locale: str) -> str:
    selected = deserialize_writing_styles(getattr(project, "writing_styles", ""), getattr(project, "writing_style", ""))
    if not selected:
        return project.tone_preferences or ""
    style_map = {
        "conversational": {
            "pl": "konwersacyjny i przystępny ton",
            "en": "a conversational, approachable tone",
            "de": "ein zugaenglicher, konversationsnaher Ton",
        },
        "scientific": {
            "pl": "naukowa precyzja i logiczna struktura bez zmyślonych źródeł",
            "en": "scientific precision and logical structure without invented sources",
            "de": "wissenschaftliche Praezision und klare Logik ohne erfundene Quellen",
        },
        "motivational": {
            "pl": "motywacyjna energia i poczucie sprawczości",
            "en": "motivational energy and a sense of agency",
            "de": "motivierende Energie und ein Gefuehl von Wirksamkeit",
        },
        "storytelling": {
            "pl": "narracyjne przykłady i storytelling",
            "en": "story-driven examples and narrative flow",
            "de": "erzahlerische Beispiele und Storytelling",
        },
        "practical": {
            "pl": "praktyczne wskazówki i jasne zastosowanie",
            "en": "practical guidance and clear application",
            "de": "praktische Hinweise und klare Umsetzbarkeit",
        },
        "light": {
            "pl": "lekkość i subtelny humor",
            "en": "lightness and subtle humor",
            "de": "Leichtigkeit und feiner Humor",
        },
        "formal": {
            "pl": "formalny, uporządkowany rejestr",
            "en": "a formal, orderly register",
            "de": "ein formelles, geordnetes Register",
        },
    }
    tokens = [style_map[slug][locale] for slug in selected if slug in style_map]
    if project.tone_preferences:
        tokens.append(project.tone_preferences)
    return "; ".join(tokens)


def _chapter_prefix(locale: str) -> str:
    return {"de": "Kapitel", "en": "Chapter"}.get(locale, "Rozdział")


def _toc_label(locale: str) -> str:
    return {"de": "Inhaltsverzeichnis", "en": "Table of contents"}.get(locale, "Spis treści")


def _looks_like_title_case(text: str, locale: str) -> bool:
    if locale == "de":
        return False
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ][\w'-]*", text or "")]
    if len(words) < 2:
        return False
    small_words = _TITLE_CASE_SMALL_WORDS.get(locale, set())
    capped = 0
    meaningful = 0
    for word in words:
        if word.lower() in small_words:
            continue
        meaningful += 1
        if word[:1].isupper() and word[1:] != word[1:].lower():
            capped += 1
        elif word[:1].isupper():
            capped += 1
    return meaningful >= 2 and capped == meaningful


def _normalize_heading_title(text: str, locale: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip(" :-"))
    if not cleaned:
        return ""
    if locale == "de" or not _looks_like_title_case(cleaned, locale):
        return cleaned
    first, rest = cleaned[:1], cleaned[1:]
    return first.upper() + rest.lower()


def _strip_forbidden_references(text: str) -> str:
    cleaned = text or ""
    patterns = [
        r"\[(?:\d+|[A-Za-z][^\]]{0,40})\]",
        r"\([^)]*(?:19|20)\d{2}[^)]*\)",
        r"(?im)^(?:sources?|references?|bibliography|footnotes?|przypisy|bibliografia|źródła|literaturverzeichnis)\s*:.*$",
        r"(?im)^\s*\d+\s*(?:\.|\))\s*[A-ZĄĆĘŁŃÓŚŹŻ][^\n]{0,120}(?:19|20)\d{2}[^\n]*$",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _has_forbidden_references(text: str) -> bool:
    return _strip_forbidden_references(text) != (text or "").strip()


def _default_chapter_title(project: BookProject, locale: str, index: int) -> str:
    topic = (project.title or project.concept or "").strip()
    if locale == "de":
        return f"Kernaspekt {index}: {topic[:40] or 'Thema'}"
    if locale == "en":
        return f"Core angle {index}: {topic[:40] or 'Topic'}"
    return f"Kluczowy aspekt {index}: {topic[:40] or 'Temat'}"


def _fallback_subsections(project: BookProject, locale: str, index: int) -> list[str]:
    if locale == "de":
        return [
            f"Wichtigster Fokus von Kapitel {index}",
            "Praktische Anwendung",
            "Schluesselerkenntnisse",
        ]
    if locale == "en":
        return [
            f"Primary focus of chapter {index}",
            "Practical application",
            "Key takeaways",
        ]
    return [
        f"Główny fokus rozdziału {index}",
        "Praktyczne zastosowanie",
        "Kluczowe wnioski",
    ]


def _chapter_word_budgets(project: BookProject) -> list[int]:
    chapters = _target_chapters(project)
    total_words = max(int(project.target_words or 0), chapters * 900)
    base = total_words // chapters
    remainder = total_words % chapters
    return [base + (1 if idx < remainder else 0) for idx in range(chapters)]


def _chapter_block_goal(locale: str, chapter_title: str, block_idx: int) -> str:
    if locale == "de":
        return f"Baue Kapitel {chapter_title} in Block {block_idx} substanziell weiter aus"
    if locale == "en":
        return f"Substantially advance chapter {chapter_title} in block {block_idx}"
    return f"Wyraźnie rozwiń rozdział {chapter_title} w bloku {block_idx}"


def _chapter_block_forbidden(locale: str) -> str:
    if locale == "de":
        return "keine erfundenen Quellen, Fussnoten, Bibliografie, URL, Meta-Kommentare oder uebertriebenen Title Case"
    if locale == "en":
        return "no invented citations, footnotes, bibliography, URLs, meta commentary, or all-words title case"
    return "bez zmyślonych źródeł, przypisów, bibliografii, URL, metakomentarzy i title case dla wszystkich słów"


def _chapter_block_prompt(locale: str, chapter_title: str, focus: str, style: str) -> str:
    if locale == "de":
        return (
            f"Halte das Kapitel '{chapter_title}' kohärent, arbeite die Themen {focus} aus, "
            f"und halte den Stil konsistent mit: {style or 'natuerliche, klare Prosa'}."
        )
    if locale == "en":
        return (
            f"Keep chapter '{chapter_title}' cohesive, develop {focus}, "
            f"and stay consistent with this style mix: {style or 'clear, natural prose'}."
        )
    return (
        f"Utrzymaj spójność rozdziału '{chapter_title}', rozwiń wątki: {focus}, "
        f"i trzymaj się miksu stylów: {style or 'klarowna, naturalna proza'}."
    )


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
        locale = _prompt_locale(project.language)
        context = self._context(project)
        target_chapters = _target_chapters(project)
        if locale == "de":
            user_prompt = dedent(f"""
            Erstelle eine detaillierte Buchgliederung in der Sprache: {_language_name(project.language)}.
            Liefere exakt {target_chapters} nummerierte Kapitel, ohne zusaetzliche Kapitel ausserhalb dieser Zahl.
            Jedes Kapitel braucht einen Titel, 2-4 Unterkapitel und 2-3 Saetze zur geplanten inhaltlichen Abdeckung.
            Die Kapitelzahl und Tiefe muessen sauber zur Zielwortzahl passen: {project.target_words}.
            Verwende keine erfundenen Quellen, Fussnoten oder Bibliografie.

            {context}
            """)
        elif locale == "en":
            user_prompt = dedent(f"""
            Create a detailed book outline in this language: {_language_name(project.language)}.
            Return exactly {target_chapters} numbered chapters, with no extra chapters outside that count.
            Each chapter should include a title, 2-4 subsections, and 2-3 sentences describing the intended content.
            Match the structure to the target word count: {project.target_words}.
            Do not invent citations, references, footnotes, or bibliography entries.

            {context}
            """)
        else:
            user_prompt = dedent(f"""
            Stwórz szczegółowy konspekt książki w języku: {project.language}.
            Zwróć dokładnie {target_chapters} numerowanych rozdziałów i żadnych dodatkowych rozdziałów poza tą liczbą.
            Każdy rozdział ma mieć tytuł, 2-4 podrozdziały i 2-3 zdania opisu zawartości.
            Struktura ma pasować do docelowej liczby słów: {project.target_words}.
            Nie twórz zmyślonych przypisów, bibliografii ani źródeł.

            {context}
            """)
        outline, provider = self._generate(
            _sys_outline_architect(locale),
            user_prompt,
            cfg,
        )
        project.outline_text = self._normalize_outline(project, outline)
        project.llm_provider_used = provider
        project.status = "outline_ready"
        return project

    def generate_prompts(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        chapters = self._parse_outline_structure(project.outline_text, project)
        project.chapter_prompts = self._build_prompt_blocks(project, chapters)
        project.llm_provider_used = project.llm_provider_used or "deterministic_prompt_planner"
        project.status = "prompts_ready"
        return project

    def generate_draft(
        self,
        project: BookProject,
        cfg: LLMConfig | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> BookProject:
        """Generate draft block by block to enforce length and structure."""
        cfg = cfg or LLMConfig()
        locale = _prompt_locale(project.language)
        system_prompt = (project.custom_system_prompt or "").strip() or get_book_writer_default_prompt(project.language)
        blocks = self._parse_prompt_blocks(project.chapter_prompts)
        if not blocks:
            blocks = self._prompt_blocks_from_outline(project)

        parts: list[str] = []
        last_provider = "template_fallback"
        context_window = ""
        total_blocks = len(blocks)
        chapter_started: set[int] = set()

        for idx, block in enumerate(blocks, 1):
            chapter_title = block["chapter_title"]
            chapter_number = block["chapter_number"]
            if on_progress:
                on_progress(f"Piszę blok {idx}/{total_blocks}: {chapter_title[:60]}", idx, total_blocks)
            user_msg = self._draft_user_prompt(project, block, context_window)
            text, provider = self._generate(system_prompt, user_msg, cfg)
            text = self._finalize_block_text(project, block, text, provider)
            if _count_words(text) < block["min_words"]:
                text = self._expand_block_text(project, block, text, cfg, system_prompt)
            text = self._finalize_block_text(project, block, text, provider)
            if chapter_number not in chapter_started:
                parts.append(f"{_chapter_prefix(locale)} {chapter_number}: {chapter_title}")
                chapter_started.add(chapter_number)
            parts.append(text.strip())
            context_window = "\n\n".join(parts[-3:])[-1800:]
            last_provider = provider

        project.manuscript_text = "\n\n".join(part for part in parts if part.strip()).strip()
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
        locale = _prompt_locale(project.language)
        system_prompt = (project.custom_system_prompt or "").strip() or get_book_writer_default_prompt(project.language)
        draft = project.manuscript_text or ""
        chunk_size = 8000
        if len(draft) <= chunk_size:
            if on_progress:
                on_progress("Redaguję manuskrypt...", 1, 1)
            if locale == "de":
                user_prompt = dedent(f"""
                Redigiere den folgenden Entwurf: verbessere Fluss, Stil und narrative Kohärenz, entferne Wiederholungen.
                Behalte eine natuerliche menschliche Stimme. Stilpraeferenzen: {project.tone_preferences}

                ENTWURF:
                {draft}
                """)
            elif locale == "en":
                user_prompt = dedent(f"""
                Edit the draft below: improve flow, style, and narrative consistency, and remove repetition.
                Keep a natural human voice. Style preferences: {project.tone_preferences}

                DRAFT:
                {draft}
                """)
            else:
                user_prompt = dedent(f"""
                Zredaguj poniższy draft: popraw flow, styl, spójność narracyjną, usuń powtórzenia.
                Zachowaj naturalny ludzki głos. Preferencje stylu: {project.tone_preferences}

                DRAFT:
                {draft}
                """)
            edited, provider = self._generate(
                system_prompt + "\n\n" + _sys_editor_full(locale),
                user_prompt,
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
                if locale == "de":
                    user_prompt = dedent(f"""
                    Redigiere diesen Buchausschnitt: verbessere Fluss und Stil, entferne Wiederholungen.
                    Stilpraeferenzen: {project.tone_preferences}

                    AUSSCHNITT:
                    {chunk}
                    """)
                elif locale == "en":
                    user_prompt = dedent(f"""
                    Edit this book fragment: improve flow and style, and remove repetition.
                    Style preferences: {project.tone_preferences}

                    FRAGMENT:
                    {chunk}
                    """)
                else:
                    user_prompt = dedent(f"""
                    Zredaguj ten fragment książki: popraw flow, styl, usuń powtórzenia.
                    Preferencje stylu: {project.tone_preferences}

                    FRAGMENT:
                    {chunk}
                    """)
                edited_chunk, provider = self._generate(
                    system_prompt + "\n\n" + _sys_editor_chunk(locale),
                    user_prompt,
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
        locale = _prompt_locale(project.target_market or project.language)
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon")
        market_lang = MARKET_LANGUAGES.get(project.target_market or "en-US", project.language)

        audience_info = ""
        if project.target_audience:
            audience_info = f"\nODBIORCA: {project.target_audience}"
        if project.emotions_to_convey:
            audience_info += f"\nEMOCJE DO PRZEKAZANIA: {project.emotions_to_convey}"
        style_mix = _style_mix(project, locale)
        if style_mix:
            audience_info += f"\nSTYL PISANIA: {style_mix}"
        if project.author_bio:
            audience_info += f"\nAUTOR: {project.author_bio}"
        if locale == "de":
            user_prompt = dedent(f"""
            Schreibe eine ueberzeugende Verkaufsbeschreibung fuer {market_label}.
            Sprache der Beschreibung: {market_lang}.

            ANFORDERUNGEN:
            - Maximal 2500 Zeichen
            - Starte mit einem starken Hook im ersten Satz
            - Danach: Nutzen fuer den Leser, Kernthemen, Call-to-Action
            - Keywords organisch einbauen
            - Reiner Text, kein Markdown

            TITEL: {project.title}
            ZUSAMMENFASSUNG: {project.concept}
            {audience_info}
            BUCHAUSSCHNITT:
            {(project.edited_text or project.manuscript_text)[:4000]}
            """)
        elif locale == "en":
            user_prompt = dedent(f"""
            Write a compelling sales description for {market_label}.
            Description language: {market_lang}.

            REQUIREMENTS:
            - Maximum 2500 characters
            - Start with a strong hook in the first sentence
            - Then cover reader benefits, core topics, and a call to action
            - Use keywords organically
            - Plain text only, no Markdown

            TITLE: {project.title}
            SUMMARY: {project.concept}
            {audience_info}
            BOOK EXCERPT:
            {(project.edited_text or project.manuscript_text)[:4000]}
            """)
        else:
            user_prompt = dedent(f"""
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
            """)

        seo, provider = self._generate(
            _sys_seo_specialist(market_label, locale),
            user_prompt,
            cfg,
        )
        project.seo_description = seo
        project.llm_provider_used = provider
        project.status = "seo_ready"
        return project

    def generate_keywords(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        locale = _prompt_locale(project.target_market or project.language)
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon")
        market_lang = MARKET_LANGUAGES.get(project.target_market or "en-US", project.language)
        if locale == "de":
            user_prompt = dedent(f"""
            Erzeuge genau 7 Keyword-Phrasen fuer dieses Buch auf {market_label}.
            Sprache der Keywords: {market_lang}.

            REGELN:
            - Jede Phrase hat 2-5 Woerter
            - Es muessen echte Amazon-Suchbegriffe von Kaeufern sein
            - Wo moeglich keine Wiederholung von Woertern aus dem Titel
            - Beruecksichtige Problem, Loesung, Persona und Nachbarthemen
            - Format: nummerierte Liste 1-7

            TITEL: {project.title}
            THEMA: {project.concept}
            ZIELGRUPPE: {project.target_audience or 'allgemein'}
            SEO-TEXT:
            {project.seo_description[:1500]}
            """)
        elif locale == "en":
            user_prompt = dedent(f"""
            Generate exactly 7 keyword phrases for this book on {market_label}.
            Keyword language: {market_lang}.

            RULES:
            - Each keyword must be a 2-5 word phrase
            - Use phrases real Amazon buyers would actually search for
            - Avoid repeating title words when possible
            - Cover multiple angles: problem, solution, reader persona, adjacent topics
            - Output format: numbered list 1-7

            TITLE: {project.title}
            TOPIC: {project.concept}
            AUDIENCE: {project.target_audience or 'general'}
            SEO DESCRIPTION:
            {project.seo_description[:1500]}
            """)
        else:
            user_prompt = dedent(f"""
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
            """)

        keywords, provider = self._generate(
            _sys_keywords_specialist(market_label, locale),
            user_prompt,
            cfg,
        )
        project.amazon_keywords = keywords
        project.llm_provider_used = provider
        project.status = "keywords_ready"
        return project

    def generate_catalog(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        locale = _prompt_locale(project.target_market or project.language)
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon")
        market_lang = MARKET_LANGUAGES.get(project.target_market or "en-US", project.language)
        if locale == "de":
            user_prompt = dedent(f"""
            Erstelle den Kategoriebaum und die besten Pfade fuer dieses Buch auf {market_label}.
            Antwortsprache: {market_lang}.

            TEIL 1 — AMAZON-KATEGORIEBAUM:
            Gib den hierarchischen Browse-Tree aus.

            TEIL 2 — 3 IDEALE PFADE:
            Fuer jeden Pfad:
            - Vollstaendiger Kategoriepfad
            - Wettbewerbsniveau (niedrig/mittel/hoch)
            - Begruendung

            TITEL: {project.title}
            THEMA: {project.concept}
            ZIELGRUPPE: {project.target_audience or 'allgemein'}
            """)
        elif locale == "en":
            user_prompt = dedent(f"""
            Build the category tree and ideal category paths for this book on {market_label}.
            Response language: {market_lang}.

            PART 1 — AMAZON CATEGORY TREE:
            Provide the hierarchical browse tree.

            PART 2 — 3 IDEAL PATHS:
            For each path include:
            - Full category path
            - Competition level (low/medium/high)
            - Reasoning

            TITLE: {project.title}
            TOPIC: {project.concept}
            AUDIENCE: {project.target_audience or 'general'}
            """)
        else:
            user_prompt = dedent(f"""
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
            """)

        catalog, provider = self._generate(
            _sys_catalog_specialist(market_label, locale),
            user_prompt,
            cfg,
        )
        project.catalog_tree = catalog
        project.llm_provider_used = provider
        project.status = "catalog_ready"
        return project

    def generate_cover(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        locale = _prompt_locale(project.language)
        if locale == "de":
            user_prompt = dedent(f"""
            Erstelle ein vollstaendiges Cover-Briefing fuer dieses Buch. Beruecksichtige:
            1. Visuelles Konzept (Hauptmotiv, Stimmung, Symbolik)
            2. Typografie (Familie, Gewicht, Groesse von Titel und Autor)
            3. Farbpalette mit HEX-Codes
            4. Komposition (Vordergrund, Hintergrund, Layout)
            5. Drei Prompt-Varianten fuer einen Bildgenerator

            TITEL: {project.title}
            BESCHREIBUNG: {project.concept}
            STIL: {_style_mix(project, locale) or project.tone_preferences}
            ZIELGRUPPE: {project.target_audience or 'allgemein'}
            SEO: {project.seo_description[:800]}
            """)
        elif locale == "en":
            user_prompt = dedent(f"""
            Create a complete cover brief for this book. Include:
            1. Visual concept (main motif, mood, symbolism)
            2. Typography (family, weight, title size, author size)
            3. Color palette with hex codes
            4. Composition (foreground, background, layout)
            5. Three AI image-generator prompt variants

            TITLE: {project.title}
            DESCRIPTION: {project.concept}
            STYLE: {_style_mix(project, locale) or project.tone_preferences}
            AUDIENCE: {project.target_audience or 'general'}
            SEO: {project.seo_description[:800]}
            """)
        else:
            user_prompt = dedent(f"""
            Stwórz kompletny brief okładki dla tej książki. Uwzględnij:
            1. Koncepcja wizualna (główny motyw, nastrój, symbolika)
            2. Typografia (family, weight, rozmiar tytułu i autora)
            3. Paleta kolorów (z kodami hex)
            4. Kompozycja (co na pierwszym planie, tło, układ)
            5. Trzy warianty promptów do generatora AI (Midjourney/DALL-E style)

            TYTUŁ: {project.title}
            OPIS: {project.concept}
            STYL: {_style_mix(project, locale) or project.tone_preferences}
            ODBIORCA: {project.target_audience or 'ogólny'}
            SEO: {project.seo_description[:800]}
            """)
        cover, provider = self._generate(
            _sys_cover_art_director(locale),
            user_prompt,
            cfg,
        )
        project.cover_brief = cover
        project.llm_provider_used = provider
        project.status = "cover_ready"
        return project

    def generate_publish(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        locale = _prompt_locale(project.target_market or project.language)
        market_label = MARKET_LABELS.get(project.target_market or "en-US", "Amazon KDP")
        if locale == "de":
            user_prompt = dedent(f"""
            Erstelle eine vollstaendige Veroeffentlichungs-Checkliste fuer {market_label} fuer dieses Buch.
            Gliedere in: Dateivorbereitung, Metadaten, Cover, Pricing, Kategorien, Pre-Launch, Launch.
            Format: Abschnitt -> Aufgabenliste mit kurzem Grund.

            TITEL: {project.title}
            ZIELWORTZAHL: {project.target_words}
            MARKT: {market_label}
            SEO:
            {project.seo_description[:1500]}
            """)
        elif locale == "en":
            user_prompt = dedent(f"""
            Create a complete publication checklist for {market_label} for this book.
            Split it into: file prep, metadata, cover, pricing, categories, pre-launch, and launch.
            Format: section -> task list with a short explanation.

            TITLE: {project.title}
            TARGET WORD COUNT: {project.target_words}
            MARKET: {market_label}
            SEO:
            {project.seo_description[:1500]}
            """)
        else:
            user_prompt = dedent(f"""
            Stwórz kompletną checklistę publikacji na {market_label} dla tej książki.
            Podziel na sekcje: przygotowanie pliku, metadane, okładka, pricing, kategorie, pre-launch, launch.
            Format: sekcja → punktorowane zadania z krótkim wyjaśnieniem.

            TYTUŁ: {project.title}
            DOCELOWE SŁOWA: {project.target_words}
            RYNEK: {market_label}
            SEO:
            {project.seo_description[:1500]}
            """)
        checklist, provider = self._generate(
            _sys_publish_ops(locale) + f"\n[Market context] {market_label}",
            user_prompt,
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
        locale = _prompt_locale(target_lang)

        if locale == "de":
            seo_prompt = dedent(f"""
            Schreibe eine ueberzeugende Verkaufsbeschreibung fuer {market_label}.
            Sprache der Beschreibung: {lang_name}.

            ANFORDERUNGEN:
            - Maximal 2500 Zeichen
            - Beginne mit einem kulturell passenden starken Hook fuer {market_label}
            - Nenne Lesermehrwert, Schwerpunkte und Call-to-Action
            - Nicht woertlich 1:1 uebersetzen; fuer den lokalen Markt umschreiben

            TITEL: {project.title}
            ZUSAMMENFASSUNG: {project.concept}
            ZIELGRUPPE: {project.target_audience or 'allgemein'}
            ORIGINAL-SEO-TEXT:
            {project.seo_description[:2000]}
            """)
            keywords_prompt = dedent(f"""
            Erzeuge 7 Keyword-Phrasen fuer dieses Buch auf {market_label}.
            Sprache: {lang_name}.
            - 2-5 Woerter pro Phrase
            - Keine Wiederholung von Titelwoertern
            - Format: nummerierte Liste 1-7

            TITEL: {project.title}
            THEMA: {project.concept}
            ZIELGRUPPE: {project.target_audience or 'allgemein'}
            """)
            catalog_prompt = dedent(f"""
            Erstelle den Kategoriebaum und 3 ideale Pfade fuer dieses Buch auf {market_label}.
            Sprache: {lang_name}.

            TEIL 1 — KATEGORIEBAUM:
            Hierarchischer Baum fuer den Zielmarkt.

            TEIL 2 — 3 IDEALE PFADE:
            Fuer jeden Pfad: voller Pfad, Wettbewerbsniveau, Begruendung.

            TITEL: {project.title}
            THEMA: {project.concept}
            """)
        elif locale == "en":
            seo_prompt = dedent(f"""
            Write a compelling sales description for {market_label}.
            Description language: {lang_name}.

            REQUIREMENTS:
            - Maximum 2500 characters
            - Start with a culturally appropriate strong hook for {market_label}
            - Cover reader benefits, key topics, and a call to action
            - Do not translate literally 1:1; localize for the market

            TITLE: {project.title}
            SUMMARY: {project.concept}
            AUDIENCE: {project.target_audience or 'general'}
            ORIGINAL SEO DESCRIPTION:
            {project.seo_description[:2000]}
            """)
            keywords_prompt = dedent(f"""
            Generate 7 keyword phrases for this book on {market_label}.
            Language: {lang_name}.
            - 2-5 words per phrase
            - Avoid repeating title words
            - Format: numbered list 1-7

            TITLE: {project.title}
            TOPIC: {project.concept}
            AUDIENCE: {project.target_audience or 'general'}
            """)
            catalog_prompt = dedent(f"""
            Build the category tree and 3 ideal category paths for this book on {market_label}.
            Language: {lang_name}.

            PART 1 — CATEGORY TREE:
            Hierarchical tree for the target market.

            PART 2 — 3 IDEAL PATHS:
            For each path: full path, competition level, reasoning.

            TITLE: {project.title}
            TOPIC: {project.concept}
            """)
        else:
            seo_prompt = dedent(f"""
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
            """)
            keywords_prompt = dedent(f"""
            Wygeneruj 7 słów kluczowych (keyword phrases) dla tej książki na {market_label}.
            Język: {lang_name}.
            - Frazy 2-5 słów, które kupujący wpisują w Amazon {market_label.split()[-1]}
            - Nie powtarzaj słów z tytułu
            - Format: lista numerowana 1-7

            TYTUŁ: {project.title}
            TEMAT: {project.concept}
            ODBIORCA: {project.target_audience or 'ogólny'}
            """)
            catalog_prompt = dedent(f"""
            Przygotuj drzewo katalogu i 3 idealne ścieżki dla tej książki na {market_label}.
            Język: {lang_name}.

            CZĘŚĆ 1 — DRZEWO KATEGORII {market_label.upper()}:
            Hierarchiczne drzewo kategorii właściwych dla rynku {market_label}.

            CZĘŚĆ 2 — 3 IDEALNE ŚCIEŻKI:
            Dla każdej: pełna ścieżka, poziom konkurencji, uzasadnienie.

            TYTUŁ: {project.title}
            TEMAT: {project.concept}
            """)

        seo, _ = self._generate(
            _sys_translation_seo(market_label, lang_name, locale),
            seo_prompt,
            cfg,
        )

        keywords, _ = self._generate(
            _sys_translation_keywords(market_label, locale),
            keywords_prompt,
            cfg,
        )

        catalog, _ = self._generate(
            _sys_translation_catalog(market_label, lang_name, locale),
            catalog_prompt,
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
        locale = _prompt_locale(None)
        return self._generate(
            _sys_ideas_strategist(locale),
            dedent(f"""
            Generate book ideas for this niche, commercial hooks, reader angles, and research notes.
            Focus on commercially viable positioning.

            NICHE: {niche}
            NOTES: {notes or 'none'}

            Format:
            1. Top 5 title ideas with a one-sentence description
            2. Ideal readers (3 personas)
            3. Key problems the book solves
            4. Suggested Amazon keywords
            5. Competition (what to do differently)
            """),
            cfg,
        )

    # --------------------------------------------------------------- internals

    def _context(self, project: BookProject) -> str:
        locale = _prompt_locale(project.language)
        if locale == "de":
            labels = {
                "title": "TITEL",
                "concept": "KONZEPT",
                "chapters": "ZIELKAPITEL",
                "words": "ZIELWOERTER",
                "style": "STIL",
                "language": "SPRACHE",
                "market": "MARKT",
                "writing_style": "SCHREIBSTILE",
                "audience": "ZIELGRUPPE",
                "emotions": "GEWUENSCHTE EMOTIONEN",
                "knowledge": "EXPERTENWISSEN",
                "author": "AUTOR",
                "sources": "INSPIRATIONSQUELLEN",
            }
        elif locale == "en":
            labels = {
                "title": "TITLE",
                "concept": "CONCEPT",
                "chapters": "TARGET CHAPTERS",
                "words": "TARGET WORDS",
                "style": "STYLE",
                "language": "LANGUAGE",
                "market": "MARKET",
                "writing_style": "WRITING STYLES",
                "audience": "AUDIENCE",
                "emotions": "EMOTIONS TO CONVEY",
                "knowledge": "KNOWLEDGE/EXPERTISE",
                "author": "AUTHOR",
                "sources": "INSPIRATION SOURCES",
            }
        else:
            labels = {
                "title": "TYTUŁ",
                "concept": "POMYSŁ",
                "chapters": "DOCELOWE ROZDZIAŁY",
                "words": "DOCELOWE SŁOWA",
                "style": "STYL",
                "language": "JĘZYK",
                "market": "RYNEK",
                "writing_style": "STYLE PISANIA",
                "audience": "ODBIORCA",
                "emotions": "EMOCJE DO PRZEKAZANIA",
                "knowledge": "WIEDZA/EKSPERTYZA",
                "author": "AUTOR",
                "sources": "ŹRÓDŁA INSPIRACJI",
            }
        lines = [
            f"{labels['title']}: {project.title}",
            f"{labels['concept']}: {project.concept}",
            f"{labels['chapters']}: {_target_chapters(project)}",
            f"{labels['words']}: {project.target_words}",
            f"{labels['style']}: {_style_mix(project, locale) or project.tone_preferences}",
            f"{labels['language']}: {_language_name(project.language)}",
            f"{labels['market']}: {MARKET_LABELS.get(project.target_market or 'en-US', project.target_market)}",
        ]
        selected_styles = deserialize_writing_styles(project.writing_styles, project.writing_style)
        if selected_styles:
            lines.append(f"{labels['writing_style']}: {', '.join(selected_styles)}")
        if project.target_audience:
            lines.append(f"{labels['audience']}: {project.target_audience}")
        if project.emotions_to_convey:
            lines.append(f"{labels['emotions']}: {project.emotions_to_convey}")
        if project.knowledge_to_share:
            lines.append(f"{labels['knowledge']}: {project.knowledge_to_share}")
        if project.author_bio:
            lines.append(f"{labels['author']}: {project.author_bio}")
        if project.inspiration_sources:
            lines.append(f"{labels['sources']}: {project.inspiration_sources}")
        return "\n".join(lines)

    def _normalize_outline(self, project: BookProject, outline_text: str) -> str:
        locale = _prompt_locale(project.language)
        chapters = self._parse_outline_structure(outline_text, project)
        target = _target_chapters(project)
        normalized: list[dict] = []
        for idx in range(1, target + 1):
            source = chapters[idx - 1] if idx - 1 < len(chapters) else {}
            title = _normalize_heading_title(source.get("title", ""), locale) or _default_chapter_title(project, locale, idx)
            subsections = [_normalize_heading_title(item, locale) for item in source.get("subsections", []) if item.strip()]
            subsections = [item for item in subsections if item][:4]
            if len(subsections) < 2:
                subsections = _fallback_subsections(project, locale, idx)
            summary = (source.get("summary", "") or "").strip()
            if not summary:
                if locale == "de":
                    summary = f"Dieses Kapitel vertieft {title.lower()} und fuehrt den Leser mit klaren Beispielen weiter."
                elif locale == "en":
                    summary = f"This chapter deepens {title.lower()} and moves the reader forward with concrete examples."
                else:
                    summary = f"Ten rozdział rozwija temat: {title.lower()} i prowadzi czytelnika przez konkretne przykłady."
            normalized.append({"title": title, "subsections": subsections, "summary": summary})
        return self._render_outline(normalized, locale)

    def _render_outline(self, chapters: list[dict], locale: str) -> str:
        lines: list[str] = []
        for idx, chapter in enumerate(chapters, 1):
            lines.append(f"{_chapter_prefix(locale)} {idx}: {chapter['title']}")
            for subsection in chapter["subsections"]:
                lines.append(f"- {subsection}")
            lines.append(chapter["summary"])
            lines.append("")
        return "\n".join(lines).strip()

    def _parse_outline_structure(self, outline: str, project: BookProject) -> list[dict]:
        locale = _prompt_locale(project.language)
        chapters: list[dict] = []
        current: dict | None = None
        for raw_line in (outline or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            chapter_match = re.match(
                r"^(?:Rozdział|ROZDZIAŁ|Chapter|CHAPTER|Kapitel)\s+(\d+)[:\.]?\s*(.+)$",
                line,
            )
            if not chapter_match:
                chapter_match = re.match(r"^(\d+)\.\s+(.+)$", line)
            if not chapter_match:
                chapter_match = re.match(r"^#\s+(.+)$", line)
            if chapter_match:
                title = chapter_match.group(chapter_match.lastindex).strip()
                current = {"title": title, "subsections": [], "summary": ""}
                chapters.append(current)
                continue
            cleaned = re.sub(r"^(?:[-*•]+|\d+\.\d+)\s*", "", line).strip()
            if current is None:
                continue
            if line.startswith("##") or raw_line.lstrip().startswith(("-", "*", "•")) or re.match(r"^\d+\.\d+", line):
                current["subsections"].append(cleaned)
                continue
            if _count_words(cleaned) <= 10 and len(cleaned) < 90:
                current["subsections"].append(cleaned)
            elif not current["summary"]:
                current["summary"] = cleaned
        return chapters

    def _build_prompt_blocks(self, project: BookProject, chapters: list[dict]) -> str:
        locale = _prompt_locale(project.language)
        budgets = _chapter_word_budgets(project)
        blocks: list[str] = []
        for idx, chapter in enumerate(chapters, 1):
            chapter_title = chapter["title"]
            chapter_budget = budgets[idx - 1] if idx - 1 < len(budgets) else budgets[-1]
            subsections = chapter.get("subsections", []) or _fallback_subsections(project, locale, idx)
            block_count = 2 if chapter_budget < 2600 else 3 if chapter_budget < 4200 else 4
            block_count = max(2, min(4, block_count))
            block_count = min(block_count, max(2, len(subsections))) if len(subsections) > 2 else block_count
            grouped_subsections = self._group_subsections(subsections, block_count)
            target_per_block = max(450, chapter_budget // len(grouped_subsections))
            remainder = chapter_budget - target_per_block * len(grouped_subsections)
            blocks.append(f"CHAPTER {idx}: {chapter_title}")
            for block_idx, subsection_group in enumerate(grouped_subsections, 1):
                extra = 1 if block_idx <= remainder else 0
                target_words = target_per_block + extra
                min_words = max(350, int(target_words * 0.85))
                focus = "; ".join(subsection_group)
                blocks.extend(
                    [
                        f"BLOCK {block_idx}",
                        f"GOAL: {_chapter_block_goal(locale, chapter_title, block_idx)}",
                        f"SUBSECTIONS: {focus}",
                        f"MIN_WORDS: {min_words}",
                        f"TARGET_WORDS: {target_words}",
                        f"FORBIDDEN: {_chapter_block_forbidden(locale)}",
                        f"LANGUAGE: {_language_name(project.language)}",
                        f"PROMPT: {_chapter_block_prompt(locale, chapter_title, focus, _style_mix(project, locale))}",
                        "",
                    ]
                )
            blocks.append("")
        return "\n".join(blocks).strip()

    def _group_subsections(self, subsections: list[str], groups: int) -> list[list[str]]:
        clean = [item.strip() for item in subsections if item.strip()]
        if not clean:
            clean = ["Main development"]
        groups = max(1, min(groups, len(clean)))
        chunk_size = ceil(len(clean) / groups)
        return [clean[i:i + chunk_size] for i in range(0, len(clean), chunk_size)]

    def _parse_prompt_blocks(self, prompts_text: str) -> list[dict]:
        blocks: list[dict] = []
        current_chapter = 0
        chapter_title = ""
        current_block: dict | None = None
        for raw_line in (prompts_text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            chapter_match = re.match(r"^CHAPTER\s+(\d+):\s+(.+)$", line)
            if chapter_match:
                current_chapter = int(chapter_match.group(1))
                chapter_title = chapter_match.group(2).strip()
                current_block = None
                continue
            block_match = re.match(r"^BLOCK\s+(\d+)$", line)
            if block_match:
                current_block = {
                    "chapter_number": current_chapter,
                    "chapter_title": chapter_title,
                    "block_number": int(block_match.group(1)),
                    "goal": "",
                    "subsections": "",
                    "min_words": 450,
                    "target_words": 550,
                    "forbidden": "",
                    "language": "",
                    "prompt": "",
                }
                blocks.append(current_block)
                continue
            if current_block is None or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "goal":
                current_block["goal"] = value
            elif key == "subsections":
                current_block["subsections"] = value
            elif key == "min_words":
                current_block["min_words"] = int(value or 450)
            elif key == "target_words":
                current_block["target_words"] = int(value or 550)
            elif key == "forbidden":
                current_block["forbidden"] = value
            elif key == "language":
                current_block["language"] = value
            elif key == "prompt":
                current_block["prompt"] = value
        return blocks

    def _prompt_blocks_from_outline(self, project: BookProject) -> list[dict]:
        prompts = self._build_prompt_blocks(project, self._parse_outline_structure(project.outline_text, project))
        return self._parse_prompt_blocks(prompts)

    def _draft_user_prompt(self, project: BookProject, block: dict, context_window: str) -> str:
        locale = _prompt_locale(project.language)
        continuation = context_window[-1200:] if context_window else ""
        common = {
            "chapter": block["chapter_title"],
            "style": _style_mix(project, locale),
            "goal": block["goal"],
            "subsections": block["subsections"],
            "min_words": block["min_words"],
            "target_words": block["target_words"],
            "prompt": block["prompt"],
            "outline": project.outline_text[:2500],
            "continuation": continuation,
        }
        if locale == "de":
            return dedent(
                f"""
                Schreibe nur den naechsten Manuskriptblock fuer Kapitel "{common['chapter']}" auf {_language_name(project.language)}.
                Stil: {common['style']}
                Ziel des Blocks: {common['goal']}
                Fokus / Unterkapitel: {common['subsections']}
                Mindestlaenge: {common['min_words']} Woerter
                Zielumfang: {common['target_words']} Woerter
                Zusatzausfuehrung: {common['prompt']}

                Gesamtgliederung:
                {common['outline']}

                Vorheriger Kontext:
                {common['continuation'] or 'kein vorheriger Block'}

                Anforderungen:
                - Nur Fliesstext fuer diesen Block, ohne Kapitelwiederholung am Anfang.
                - Keine Quellen, Fussnoten, Bibliografie, Statistikreferenzen oder URL.
                - Untertitel nur bei Bedarf als "## Titel".
                """
            )
        if locale == "en":
            return dedent(
                f"""
                Write only the next manuscript block for chapter "{common['chapter']}" in {_language_name(project.language)}.
                Style: {common['style']}
                Block goal: {common['goal']}
                Focus / subsections: {common['subsections']}
                Minimum length: {common['min_words']} words
                Target length: {common['target_words']} words
                Additional direction: {common['prompt']}

                Full outline:
                {common['outline']}

                Previous context:
                {common['continuation'] or 'none'}

                Requirements:
                - Return only the prose for this block, without repeating the chapter heading at the start.
                - No citations, footnotes, bibliography, named source references, or URLs.
                - Use subheadings only when needed and only as "## Subtitle".
                """
            )
        return dedent(
            f"""
            Napisz tylko kolejny blok manuskryptu dla rozdziału "{common['chapter']}" w języku {_language_name(project.language)}.
            Styl: {common['style']}
            Cel bloku: {common['goal']}
            Fokus / podrozdziały: {common['subsections']}
            Minimalna długość: {common['min_words']} słów
            Docelowa długość: {common['target_words']} słów
            Dodatkowe wytyczne: {common['prompt']}

            Konspekt całości:
            {common['outline']}

            Poprzedni kontekst:
            {common['continuation'] or 'brak'}

            Wymagania:
            - Zwróć wyłącznie treść tego bloku, bez powtarzania nagłówka rozdziału na początku.
            - Bez przypisów, cytowań, bibliografii, nazw źródeł, statystyk ze źródłami i URL.
            - Śródtytuły tylko w razie potrzeby i tylko jako "## Tytuł".
            """
        )

    def _finalize_block_text(self, project: BookProject, block: dict, text: str, provider: str) -> str:
        locale = _prompt_locale(project.language)
        cleaned = self._strip_repeated_heading(text, block["chapter_title"])
        cleaned = _strip_forbidden_references(cleaned)
        cleaned = self._normalize_inline_headings(cleaned, locale)
        if provider == "template_fallback":
            cleaned = self._synthesize_block_text(project, block, cleaned)
        return cleaned.strip()

    def _expand_block_text(
        self,
        project: BookProject,
        block: dict,
        text: str,
        cfg: LLMConfig,
        system_prompt: str,
    ) -> str:
        locale = _prompt_locale(project.language)
        current = text.strip()
        attempts = 0
        while _count_words(current) < block["min_words"] and attempts < 2:
            missing = block["target_words"] - _count_words(current)
            if missing <= 0:
                break
            if locale == "de":
                top_up_prompt = dedent(
                    f"""
                    Fuehre denselben Block nahtlos fort und schreibe nur den fehlenden Text.
                    Kapitel: {block['chapter_title']}
                    Fehlende Zielwoerter: mindestens {max(150, missing)}
                    Fokus: {block['subsections']}
                    Bereits geschriebener Text:
                    {current[-1800:]}
                    Keine Quellen, Fussnoten oder Kapitelueberschrift wiederholen.
                    """
                )
            elif locale == "en":
                top_up_prompt = dedent(
                    f"""
                    Continue the same block seamlessly and write only the missing prose.
                    Chapter: {block['chapter_title']}
                    Remaining target words: at least {max(150, missing)}
                    Focus: {block['subsections']}
                    Existing text:
                    {current[-1800:]}
                    Do not add citations, footnotes, or repeat the chapter heading.
                    """
                )
            else:
                top_up_prompt = dedent(
                    f"""
                    Kontynuuj płynnie ten sam blok i dopisz tylko brakującą treść.
                    Rozdział: {block['chapter_title']}
                    Brakujący budżet słów: co najmniej {max(150, missing)}
                    Fokus: {block['subsections']}
                    Dotychczasowa treść:
                    {current[-1800:]}
                    Nie dodawaj przypisów, cytowań ani powtórki nagłówka rozdziału.
                    """
                )
            extra, provider = self._generate(system_prompt, top_up_prompt, cfg)
            current = f"{current}\n\n{self._finalize_block_text(project, block, extra, provider)}".strip()
            attempts += 1
        return current

    def _strip_repeated_heading(self, text: str, chapter_title: str) -> str:
        cleaned = (text or "").strip()
        patterns = [
            rf"^(?:Rozdział|ROZDZIAŁ|Chapter|CHAPTER|Kapitel)\s+\d+[:\.]?\s*{re.escape(chapter_title)}\s*",
            rf"^#\s*{re.escape(chapter_title)}\s*",
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _normalize_inline_headings(self, text: str, locale: str) -> str:
        lines = []
        for raw_line in (text or "").splitlines():
            line = raw_line.rstrip()
            if line.startswith("##"):
                title = line.lstrip("# ").strip()
                lines.append(f"## {_normalize_heading_title(title, locale)}")
            else:
                lines.append(line)
        return "\n".join(lines).strip()

    def _synthesize_block_text(self, project: BookProject, block: dict, base_text: str) -> str:
        locale = _prompt_locale(project.language)
        current = (base_text or "").strip()
        templates = {
            "de": "Dieser Abschnitt entwickelt {focus} mit konkreten Beispielen, klaren Schritten und einem natuerlichen Uebergang zum naechsten Gedanken.",
            "en": "This section develops {focus} with concrete examples, practical detail, and a natural transition into the next idea.",
            "pl": "Ta sekcja rozwija temat: {focus}, dodając konkretne przykłady, praktyczne niuanse i naturalne przejście do kolejnej myśli.",
        }
        sentence = templates.get(locale, templates["en"]).format(focus=block["subsections"] or block["chapter_title"])
        while _count_words(current) < block["min_words"]:
            paragraph = " ".join([sentence] * 4)
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
        return current

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

    def _get_chapter_prompt(self, prompts_text: str, chapter_title: str, index: int, language: str = "pl") -> str:
        """Find chapter-specific prompt from chapter_prompts text."""
        locale = _prompt_locale(language)
        if not prompts_text:
            if locale == "de":
                return f"Schreibe den Inhalt fuer dieses Kapitel: {chapter_title}"
            if locale == "en":
                return f"Write the content for this chapter: {chapter_title}"
            return f"Napisz treść rozdziału: {chapter_title}"
        lines = prompts_text.splitlines()
        for i, line in enumerate(lines):
            if (
                chapter_title.lower()[:20] in line.lower()
                or f"rozdział {index}" in line.lower()
                or f"chapter {index}" in line.lower()
                or f"kapitel {index}" in line.lower()
            ):
                prompt_lines = lines[i: i + 8]
                return "\n".join(prompt_lines).strip()
        chunk_size = max(1, len(prompts_text) // 10)
        start = (index - 1) * chunk_size
        fallback = prompts_text[start: start + chunk_size].strip()
        if fallback:
            return fallback
        if locale == "de":
            return f"Schreibe den Inhalt fuer dieses Kapitel: {chapter_title}"
        if locale == "en":
            return f"Write the content for this chapter: {chapter_title}"
        return f"Napisz treść rozdziału: {chapter_title}"

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
        [Fallback output — no LLM response available]
        System task: {system_prompt[:200]}

        This section was generated without a live LLM response. Configure LM Studio, Gemini, or OpenRouter in settings.

        Request summary:
        {user_prompt[:2000]}
        """).strip()


book_pipeline_service = BookPipelineService()
