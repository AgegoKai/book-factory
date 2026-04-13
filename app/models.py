import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

BOOK_WRITER_DEFAULT_PROMPTS = {
    "pl": """[Rola systemowa] Ghostwriter literacki / autor treści długiej formy. Output: wyłącznie ciągły tekst manuskryptu — bez metakomentarzy, bez zwrotów do czytelnika, bez podsumowań typu „oto rozdział”.

[Protokół wyjściowy]
- Pierwszy znak odpowiedzi = pierwszy znak treści narracji lub eksplikacji (zero wstępów).
- Zakaz: „Mam nadzieję”, „w tym rozdziale”, „poniżej znajdziesz”, placeholdery, listy zadań dla użytkownika.

[Parametry stylistyczne]
- Priorytet: precyzja, konkret, sensoryka i „show, don't tell”; unikaj pustych fraz i tanich klisz.
- Spójność: utrzymuj ciągłość czasu, miejsca, tonu i motywów; każdy blok logicznie kontynuuje poprzedni.
- Gęstość: jedna odpowiedź ≈ jedna jednostka redakcyjna (docelowo 500–700 słów), zachowując tempo i napięcie tam, gdzie temat tego wymaga.
- Zakaz zmyślonych przypisów, bibliografii, cytowań, nazw badań, statystyk i źródeł, jeśli nie zostały podane w briefie.

[Format — ŚCISŁY]
- ZAKAZ stosowania formatowania Markdown: żadnych **pogrubień**, *kursywy*, list - ani *, hasztagów #słowo.
- ZAKAZ wstawiania linków URL ani odnośników [text](url).
- Tytuły rozdziałów zaznaczaj wyłącznie jako: "Rozdział N: Tytuł" lub "# Tytuł" — tylko na granicy nowego rozdziału.
- Tytuły i śródtytuły zapisuj normalną kapitalizacją zdaniową, nie title case dla każdego wyrazu.
- Podrozdziały zaznaczaj wyłącznie jako: "## Tytuł podrozdziału" — bez innych ozdobników.
- Akapity oddzielaj pustą linią. Żadnych linii dekoracyjnych (---, ***).
- Zwracaj wyłącznie czysty tekst narracji, gotowy do druku.""",
    "en": """[System role] Literary ghostwriter / long-form author. Output only the continuous manuscript text — no meta commentary, no direct address to the reader, no filler such as “here is the chapter”.

[Output protocol]
- The first character of the reply must be the first character of the actual manuscript text.
- Forbidden: “I hope”, “in this chapter”, “below you will find”, placeholders, TODO lists, or instructions to the user.

[Style parameters]
- Priority: precision, specificity, sensory detail, and show-don't-tell; avoid empty phrasing and cheap cliches.
- Continuity: keep time, place, tone, and motifs coherent; each block should continue naturally from the previous one.
- Density: one response should equal one meaningful editorial unit (typically 500-700 words where appropriate) while preserving momentum.
- Never invent citations, footnotes, bibliographies, studies, named sources, or statistics unless they were provided in the brief.

[Format — STRICT]
- Do NOT use Markdown formatting: no **bold**, *italic*, bullet lists, hashtags, or decorative separators.
- Do NOT include URLs or links like [text](url).
- Mark chapter titles only as: "Chapter N: Title" or "# Title".
- Write chapter and subsection titles in sentence case, not title case for every word.
- Mark subheadings only as: "## Subtitle" — nothing else.
- Separate paragraphs with a blank line.
- Return only clean manuscript prose ready for print.""",
    "de": """[Systemrolle] Literarischer Ghostwriter / Autor fuer lange Formate. Gib ausschliesslich den fortlaufenden Manuskripttext aus — keine Metakommentare, keine direkte Ansprache an die Leser, keine Einleitungen wie „hier ist das Kapitel“.

[Ausgabeprotokoll]
- Das erste Zeichen der Antwort muss das erste Zeichen des eigentlichen Manuskripttexts sein.
- Verboten: „ich hoffe“, „in diesem Kapitel“, „unten findest du“, Platzhalter, TODO-Listen oder Anweisungen an den Nutzer.

[Stilparameter]
- Prioritaet: Praezision, Konkretheit, sensorische Details und show-don't-tell; vermeide leere Formulierungen und Klischees.
- Kontinuitaet: Halte Zeit, Ort, Ton und Motive konsistent; jeder Block soll logisch aus dem vorherigen folgen.
- Dichte: Eine Antwort entspricht einer sinnvollen redaktionellen Einheit (typisch 500-700 Woerter, wenn passend), ohne den Fluss zu verlieren.
- Erfinde keine Quellen, Fussnoten, Literaturangaben, Studiennamen oder Statistiken, sofern sie nicht im Briefing stehen.

[Format — STRIKT]
- Kein Markdown: kein **Fett**, keine *Kursivschrift*, keine Listen, keine Hashtags, keine dekorativen Trennlinien.
- Keine URLs oder Links wie [Text](url).
- Kapitelueberschriften nur als: "Kapitel N: Titel" oder "# Titel".
- Kapitel- und Untertitel in normaler Satzgrossschreibung schreiben, nicht als Title Case fuer jedes Wort.
- Unterueberschriften nur als: "## Untertitel" — nichts weiter.
- Absätze mit einer Leerzeile trennen.
- Gib nur sauberen Manuskripttext aus, druckfertig und ohne Zusatzkommentare.""",
}

BOOK_WRITER_DEFAULT_PROMPT = BOOK_WRITER_DEFAULT_PROMPTS["pl"]


def get_book_writer_default_prompt(language: str | None) -> str:
    raw = (language or "").strip().lower()
    if raw.startswith("pl"):
        return BOOK_WRITER_DEFAULT_PROMPTS["pl"]
    if raw.startswith("de"):
        return BOOK_WRITER_DEFAULT_PROMPTS["de"]
    return BOOK_WRITER_DEFAULT_PROMPTS["en"]


WRITING_STYLE_PRESETS = [
    {
        "slug": "conversational",
        "label": "Konwersacyjny i przystępny",
        "description": "Naturalny, bliski czytelnikowi głos bez akademickiego zadęcia.",
        "prompt": {
            "pl": "pisz konwersacyjnie, jasno i przystępnie, jak ekspert tłumaczący temat inteligentnemu czytelnikowi",
            "en": "write in a conversational, approachable voice that still sounds competent and precise",
            "de": "schreibe in einem zugaenglichen, konversationsnahen Ton, der trotzdem kompetent wirkt",
        },
    },
    {
        "slug": "scientific",
        "label": "Naukowy i precyzyjny",
        "description": "Wyższa ścisłość, definicje i logiczne prowadzenie wywodu bez zmyślonych źródeł.",
        "prompt": {
            "pl": "utrzymuj precyzję, logiczną strukturę i dyscyplinę pojęciową, ale bez wymyślania badań i przypisów",
            "en": "keep the prose precise, structured, and conceptually rigorous without inventing studies or references",
            "de": "halte den Text praezise, strukturiert und begrifflich sauber, ohne Studien oder Quellen zu erfinden",
        },
    },
    {
        "slug": "motivational",
        "label": "Motywacyjny i inspirujący",
        "description": "Energia, sprawczość i emocjonalny impakt bez przesadnego coachingu.",
        "prompt": {
            "pl": "wzmacniaj poczucie sprawczości i motywacji, ale bez pustych sloganów",
            "en": "add momentum, encouragement, and a sense of agency without sounding like empty hype",
            "de": "erzeuge Motivation und Handlungsenergie, aber ohne hohle Motivationsfloskeln",
        },
    },
    {
        "slug": "storytelling",
        "label": "Narracyjny storytelling",
        "description": "Opowieści, sceny i konkretne przykłady zamiast suchych tez.",
        "prompt": {
            "pl": "używaj scen, mini-opowieści i konkretnych przykładów, zamiast samych abstrakcyjnych tez",
            "en": "use narrative scenes, vivid examples, and story-driven transitions instead of abstract exposition alone",
            "de": "arbeite mit Szenen, Beispielen und erzahlerischen Uebergaengen statt nur mit abstrakter Erklaerung",
        },
    },
    {
        "slug": "practical",
        "label": "Praktyczny how-to",
        "description": "Krok po kroku, konkret, zastosowanie i jasne rezultaty dla czytelnika.",
        "prompt": {
            "pl": "stawiaj na konkret, zastosowanie, praktyczne kroki i użyteczne przykłady",
            "en": "prioritize practical application, concrete steps, and useful examples the reader can apply",
            "de": "priorisiere Anwendbarkeit, konkrete Schritte und nuetzliche Beispiele fuer die Praxis",
        },
    },
    {
        "slug": "light",
        "label": "Humorystyczny i lekki",
        "description": "Lekkość, dystans i odrobina humoru bez infantylizacji.",
        "prompt": {
            "pl": "dodawaj lekkość i subtelny humor, ale bez infantylnego tonu",
            "en": "add lightness and occasional humor without becoming flippant or childish",
            "de": "arbeite mit Leichtigkeit und feinem Humor, ohne albern oder flach zu wirken",
        },
    },
    {
        "slug": "formal",
        "label": "Akademicki i formalny",
        "description": "Wyższy rejestr języka i formalna organizacja materiału.",
        "prompt": {
            "pl": "utrzymuj formalny, uporządkowany rejestr i profesjonalne słownictwo",
            "en": "keep a formal register, orderly structure, and professional vocabulary",
            "de": "halte ein formelles Register, klare Ordnung und professionelles Vokabular",
        },
    },
]

WRITING_STYLE_LABELS = {preset["slug"]: preset["label"] for preset in WRITING_STYLE_PRESETS}
_WRITING_STYLE_VALUE_MAP = {
    "conversational": "conversational",
    "konwersacyjny i przystępny": "conversational",
    "scientific": "scientific",
    "naukowy i precyzyjny": "scientific",
    "akademicki": "formal",
    "formal": "formal",
    "akademicki i formalny": "formal",
    "motivational": "motivational",
    "motywacyjny i inspirujący": "motivational",
    "storytelling": "storytelling",
    "narracyjny storytelling": "storytelling",
    "practical": "practical",
    "praktyczny how-to": "practical",
    "how-to": "practical",
    "light": "light",
    "humorystyczny i lekki": "light",
}


def normalize_writing_styles(values: list[str] | tuple[str, ...] | None, legacy: str = "") -> list[str]:
    normalized: list[str] = []
    source = list(values or [])
    if legacy:
        source.append(legacy)
    for value in source:
        slug = _WRITING_STYLE_VALUE_MAP.get((value or "").strip().lower())
        if slug and slug not in normalized:
            normalized.append(slug)
    return normalized


def serialize_writing_styles(values: list[str] | tuple[str, ...] | None, legacy: str = "") -> str:
    normalized = normalize_writing_styles(values, legacy)
    return json.dumps(normalized, ensure_ascii=False)


def deserialize_writing_styles(raw: str | None, legacy: str = "") -> list[str]:
    values: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                values = [str(item) for item in parsed]
        except Exception:
            values = []
    return normalize_writing_styles(values, legacy)


def writing_style_labels(raw: str | None, legacy: str = "") -> list[str]:
    return [WRITING_STYLE_LABELS.get(slug, slug) for slug in deserialize_writing_styles(raw, legacy)]


def primary_writing_style(raw: str | None, legacy: str = "") -> str:
    labels = writing_style_labels(raw, legacy)
    return labels[0] if labels else ""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    projects = relationship("BookProject", back_populates="owner")
    settings = relationship("UserSettings", back_populates="user", uselist=False)


class UserSettings(Base):
    """Per-user API configuration — overrides .env values in UI."""
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    lm_studio_base_url: Mapped[str] = mapped_column(String(500), default="")
    lm_studio_api_key: Mapped[str] = mapped_column(String(500), default="")
    lm_studio_model: Mapped[str] = mapped_column(String(200), default="")
    google_api_key: Mapped[str] = mapped_column(String(500), default="")
    google_model: Mapped[str] = mapped_column(String(200), default="")
    openrouter_api_key: Mapped[str] = mapped_column(String(500), default="")
    openrouter_model: Mapped[str] = mapped_column(String(200), default="")
    copyleaks_email: Mapped[str] = mapped_column(String(255), default="")
    copyleaks_api_key: Mapped[str] = mapped_column(String(500), default="")
    # auto | lm_studio | google_gemini | openrouter — który LLM generuje treść w tej sesji
    preferred_llm_provider: Mapped[str] = mapped_column(String(30), default="auto")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="settings")


class BookProject(Base):
    __tablename__ = "book_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    concept: Mapped[str] = mapped_column(Text)
    inspiration_sources: Mapped[str] = mapped_column(Text, default="")
    target_pages: Mapped[int] = mapped_column(Integer, default=20)
    target_chapters: Mapped[int] = mapped_column(Integer, default=10)
    target_words: Mapped[int] = mapped_column(Integer, default=5000)
    tone_preferences: Mapped[str] = mapped_column(Text, default="Dłuższe, naturalne zdania, ludzki styl.")
    language: Mapped[str] = mapped_column(String(50), default="pl")
    custom_system_prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="draft")
    outline_text: Mapped[str] = mapped_column(Text, default="")
    chapter_prompts: Mapped[str] = mapped_column(Text, default="")
    manuscript_text: Mapped[str] = mapped_column(Text, default="")
    edited_text: Mapped[str] = mapped_column(Text, default="")
    seo_description: Mapped[str] = mapped_column(Text, default="")
    cover_brief: Mapped[str] = mapped_column(Text, default="")
    publish_checklist: Mapped[str] = mapped_column(Text, default="")
    idea_research: Mapped[str] = mapped_column(Text, default="")
    llm_provider_used: Mapped[str] = mapped_column(String(100), default="")

    # Book positioning fields (set at project creation)
    writing_style: Mapped[str] = mapped_column(Text, default="")
    writing_styles: Mapped[str] = mapped_column(Text, default="[]")
    target_market: Mapped[str] = mapped_column(String(50), default="en-US")
    author_bio: Mapped[str] = mapped_column(Text, default="")
    emotions_to_convey: Mapped[str] = mapped_column(Text, default="")
    knowledge_to_share: Mapped[str] = mapped_column(Text, default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")

    # Generated pipeline outputs (new steps)
    amazon_keywords: Mapped[str] = mapped_column(Text, default="")
    catalog_tree: Mapped[str] = mapped_column(Text, default="")
    translations: Mapped[str] = mapped_column(Text, default="")

    # PDF export settings
    pdf_font_family: Mapped[str] = mapped_column(String(50), default="Georgia")
    pdf_trim_size: Mapped[str] = mapped_column(String(20), default="6x9")
    pdf_heading_size: Mapped[int] = mapped_column(Integer, default=22)
    pdf_body_size: Mapped[int] = mapped_column(Integer, default=11)
    pdf_book_title_size: Mapped[int] = mapped_column(Integer, default=30)
    pdf_chapter_title_size: Mapped[int] = mapped_column(Integer, default=23)
    pdf_subchapter_title_size: Mapped[int] = mapped_column(Integer, default=17)
    pdf_title_override: Mapped[str] = mapped_column(String(255), default="")
    pdf_subtitle: Mapped[str] = mapped_column(String(255), default="")
    pdf_author_name: Mapped[str] = mapped_column(String(255), default="")
    pdf_include_toc: Mapped[bool] = mapped_column(Boolean, default=True)
    pdf_show_page_numbers: Mapped[bool] = mapped_column(Boolean, default=True)
    human_check_result: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="projects")
