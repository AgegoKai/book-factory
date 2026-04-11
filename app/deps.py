from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .session import read_session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = read_session(request.cookies.get("book_factory_session"))
    if not user_id:
        # Raise as exception-compatible redirect so FastAPI routes can depend on it
        raise _LoginRedirect()
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise _LoginRedirect()
    return user


class _LoginRedirect(Exception):
    """Sentinel used to redirect unauthenticated users to /login."""
    pass
