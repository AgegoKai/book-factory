from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine
from .models import User
from .security import hash_password


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


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
