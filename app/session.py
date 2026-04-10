from itsdangerous import URLSafeSerializer

from .config import settings

serializer = URLSafeSerializer(settings.secret_key, salt="book-factory-session")
SESSION_COOKIE = "book_factory_session"


def sign_session(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def read_session(token: str | None) -> int | None:
    if not token:
        return None
    try:
        data = serializer.loads(token)
        return int(data.get("user_id"))
    except Exception:
        return None
