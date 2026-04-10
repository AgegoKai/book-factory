from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    projects = relationship("BookProject", back_populates="owner")


class BookProject(Base):
    __tablename__ = "book_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    concept: Mapped[str] = mapped_column(Text)
    inspiration_sources: Mapped[str] = mapped_column(Text, default="")
    target_pages: Mapped[int] = mapped_column(Integer, default=20)
    target_words: Mapped[int] = mapped_column(Integer, default=5000)
    tone_preferences: Mapped[str] = mapped_column(Text, default="Longer, natural sentences with clean pacing.")
    language: Mapped[str] = mapped_column(String(50), default="pl")
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
