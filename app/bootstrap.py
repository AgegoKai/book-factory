import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine
from .models import User
from .security import hash_password


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def migrate_db() -> None:
    """Add missing columns to existing SQLite database without dropping data."""
    new_book_columns = [
        ("writing_style", "TEXT DEFAULT ''"),
        ("writing_styles", "TEXT DEFAULT '[]'"),
        ("target_market", "VARCHAR(50) DEFAULT 'en-US'"),
        ("author_bio", "TEXT DEFAULT ''"),
        ("emotions_to_convey", "TEXT DEFAULT ''"),
        ("knowledge_to_share", "TEXT DEFAULT ''"),
        ("target_audience", "TEXT DEFAULT ''"),
        ("target_chapters", "INTEGER DEFAULT 10"),
        ("amazon_keywords", "TEXT DEFAULT ''"),
        ("catalog_tree", "TEXT DEFAULT ''"),
        ("translations", "TEXT DEFAULT ''"),
        ("pdf_font_family", "VARCHAR(50) DEFAULT 'Georgia'"),
        ("pdf_trim_size", "VARCHAR(20) DEFAULT '6x9'"),
        ("pdf_heading_size", "INTEGER DEFAULT 22"),
        ("pdf_body_size", "INTEGER DEFAULT 11"),
        ("pdf_book_title_size", "INTEGER DEFAULT 30"),
        ("pdf_chapter_title_size", "INTEGER DEFAULT 23"),
        ("pdf_subchapter_title_size", "INTEGER DEFAULT 17"),
        ("pdf_title_override", "VARCHAR(255) DEFAULT ''"),
        ("pdf_subtitle", "VARCHAR(255) DEFAULT ''"),
        ("pdf_author_name", "VARCHAR(255) DEFAULT ''"),
        ("pdf_include_toc", "BOOLEAN DEFAULT 1"),
        ("pdf_show_page_numbers", "BOOLEAN DEFAULT 1"),
        ("human_check_result", "TEXT DEFAULT ''"),
    ]
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(book_projects)"))
        existing = {row[1] for row in result}
        for col, definition in new_book_columns:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE book_projects ADD COLUMN {col} {definition}"))

        rows = conn.execute(
            text(
                """
                SELECT id, outline_text, target_pages, target_chapters, writing_style, writing_styles,
                       pdf_font_family, pdf_trim_size, pdf_book_title_size, pdf_chapter_title_size, pdf_subchapter_title_size
                FROM book_projects
                """
            )
        ).mappings()
        for row in rows:
            target_chapters = row["target_chapters"] or 0
            if target_chapters <= 0:
                target_chapters = _infer_target_chapters(row["outline_text"] or "", row["target_pages"] or 0)
            writing_styles = (row["writing_styles"] or "").strip()
            if not writing_styles:
                writing_styles = _legacy_writing_styles_json(row["writing_style"] or "")
            conn.execute(
                text(
                    """
                    UPDATE book_projects
                    SET target_chapters = :target_chapters,
                        writing_styles = :writing_styles,
                        pdf_font_family = CASE WHEN COALESCE(pdf_font_family, '') IN ('', 'auto') THEN 'Georgia' ELSE pdf_font_family END,
                        pdf_trim_size = CASE WHEN COALESCE(pdf_trim_size, '') = '' THEN '6x9' ELSE pdf_trim_size END,
                        pdf_book_title_size = CASE WHEN COALESCE(pdf_book_title_size, 0) <= 0 THEN 30 ELSE pdf_book_title_size END,
                        pdf_chapter_title_size = CASE WHEN COALESCE(pdf_chapter_title_size, 0) <= 0 THEN COALESCE(NULLIF(pdf_heading_size, 0), 23) ELSE pdf_chapter_title_size END,
                        pdf_subchapter_title_size = CASE WHEN COALESCE(pdf_subchapter_title_size, 0) <= 0 THEN 17 ELSE pdf_subchapter_title_size END
                    WHERE id = :project_id
                    """
                ),
                {
                    "project_id": row["id"],
                    "target_chapters": target_chapters,
                    "writing_styles": writing_styles,
                },
            )

        new_user_settings_columns = [
            ("preferred_llm_provider", "VARCHAR(30) DEFAULT 'auto'"),
            ("copyleaks_email", "VARCHAR(255) DEFAULT ''"),
            ("copyleaks_api_key", "VARCHAR(500) DEFAULT ''"),
        ]
        us_tables = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_settings' LIMIT 1")
        ).fetchone()
        if us_tables:
            result_us = conn.execute(text("PRAGMA table_info(user_settings)"))
            existing_us = {row[1] for row in result_us}
            for col, definition in new_user_settings_columns:
                if col not in existing_us:
                    conn.execute(text(f"ALTER TABLE user_settings ADD COLUMN {col} {definition}"))
        conn.commit()


def _legacy_writing_styles_json(value: str) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "konwersacyjny i przystępny": "conversational",
        "naukowy i precyzyjny": "scientific",
        "motywacyjny i inspirujący": "motivational",
        "narracyjny storytelling": "storytelling",
        "praktyczny how-to": "practical",
        "humorystyczny i lekki": "light",
        "akademicki": "formal",
        "akademicki i formalny": "formal",
    }
    slug = mapping.get(raw)
    return f'["{slug}"]' if slug else "[]"


def _infer_target_chapters(outline_text: str, target_pages: int) -> int:
    count = 0
    for line in (outline_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^(?:Rozdział|ROZDZIAŁ|Chapter|CHAPTER|Kapitel)\s+\d+[:\.]?", stripped):
            count += 1
            continue
        if re.match(r"^#{1}\s+\S", stripped):
            count += 1
            continue
        if re.match(r"^\d+\.\s+\S", stripped):
            count += 1
    if count > 0:
        return count
    pages = max(0, int(target_pages or 0))
    return max(5, pages // 4) if pages else 10


def ensure_default_admin(db: Session) -> None:
    existing = db.query(User).filter(User.email == settings.default_admin_email).first()
    if existing:
        return
    admin = User(
        email=settings.default_admin_email,
        password_hash=hash_password(settings.default_admin_password),
        is_admin=True,
    )
    db.add(admin)
    db.commit()
