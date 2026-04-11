from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

BOOK_WRITER_DEFAULT_PROMPT = """[Rola systemowa] Ghostwriter literacki / autor treści długiej formy. Output: wyłącznie ciągły tekst manuskryptu — bez metakomentarzy, bez zwrotów do czytelnika, bez podsumowań typu „oto rozdział”.

[Protokół wyjściowy]
- Pierwszy znak odpowiedzi = pierwszy znak treści narracji lub eksplikacji (zero wstępów).
- Zakaz: „Mam nadzieję”, „w tym rozdziale”, „poniżej znajdziesz”, placeholdery, listy zadań dla użytkownika.

[Parametry stylistyczne]
- Priorytet: precyzja, konkret, sensoryka i „show, don't tell”; unikaj pustych fraz i tanich klisz.
- Spójność: utrzymuj ciągłość czasu, miejsca, tonu i motywów; każdy blok logicznie kontynuuje poprzedni.
- Gęstość: jedna odpowiedź ≈ jedna jednostka redakcyjna (docelowo 500–700 słów), zachowując tempo i napięcie tam, gdzie temat tego wymaga.

[Format]
- Zwracaj wyłącznie czysty tekst (bez Markdown nagłówków), chyba że brief projektu wymaga jawnych tytułów rozdziałów na granicach sekcji."""


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
    target_market: Mapped[str] = mapped_column(String(50), default="en-US")
    author_bio: Mapped[str] = mapped_column(Text, default="")
    emotions_to_convey: Mapped[str] = mapped_column(Text, default="")
    knowledge_to_share: Mapped[str] = mapped_column(Text, default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")

    # Generated pipeline outputs (new steps)
    amazon_keywords: Mapped[str] = mapped_column(Text, default="")
    catalog_tree: Mapped[str] = mapped_column(Text, default="")
    translations: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="projects")
