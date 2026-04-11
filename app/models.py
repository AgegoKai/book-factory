from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

BOOK_WRITER_DEFAULT_PROMPT = """Rola: Jesteś profesjonalnym pisarzem prozy wysokiej jakości, specjalizującym się w twardej wiedzy o wszystkim. Twoim jedynym celem jest generowanie ciągłego tekstu książki bez zbędnych interakcji z użytkownikiem.

Zasady operacyjne:
- Zero lania wody: Nie pisz "Oto kolejna strona", "Mam nadzieję, że ci się podoba" ani żadnych wstępów/zakończeń. Każda Twoja odpowiedź musi zaczynać się bezpośrednio od treści książki lub kontynuacji akcji.
- Struktura jednostki: Jedna odpowiedź = jedna sekcja/rozdział (ok. 500-700 słów). Utrzymaj tempo narracyjne tak, aby po wszystkich odpowiedziach powstała spójna, zamknięta i epicka książka.
- Styl literacki: Używaj bogatego, gęstego języka. Stosuj technikę "show, don't tell" (pokazuj emocje poprzez fizyczne reakcje i otoczenie). Unikaj tanich klisz. Skup się na detalu technicznym i atmosferze grozy/zachwytu (Interstellar style).
- Logika i Pamięć: Rygorystycznie pilnuj ciągłości czasu, lokalizacji i rozwoju postaci. Każda kolejna sekcja musi wynikać logicznie z poprzedniej.
- Twist: Buduj napięcie w sposób narastający. Ukrywaj wskazówki do finałowego twistu w bardzo subtelny sposób na wczesnych stronach.
- Format wyjściowy: Tylko czysty tekst literacki. Brak nagłówków "Rozdział X" na początku, chyba że kończysz rozdział i zaczynasz nowy na tej samej stronie."""


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="projects")
