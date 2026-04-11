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
        ("target_market", "VARCHAR(50) DEFAULT 'en-US'"),
        ("author_bio", "TEXT DEFAULT ''"),
        ("emotions_to_convey", "TEXT DEFAULT ''"),
        ("knowledge_to_share", "TEXT DEFAULT ''"),
        ("target_audience", "TEXT DEFAULT ''"),
        ("amazon_keywords", "TEXT DEFAULT ''"),
        ("catalog_tree", "TEXT DEFAULT ''"),
        ("translations", "TEXT DEFAULT ''"),
    ]
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(book_projects)"))
        existing = {row[1] for row in result}
        for col, definition in new_book_columns:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE book_projects ADD COLUMN {col} {definition}"))

        new_user_settings_columns = [
            ("preferred_llm_provider", "VARCHAR(30) DEFAULT 'auto'"),
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
