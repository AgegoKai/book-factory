import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_app(tmp_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@test.local"
    os.environ["DEFAULT_ADMIN_PASSWORD"] = "secret123"
    os.environ["SECRET_KEY"] = "test-secret"

    from app.main import app

    return app


def test_login_and_project_flow(tmp_path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"email": "admin@test.local", "password": "secret123"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        cookies = login.cookies
        create = client.post(
            "/projects",
            data={
                "title": "Test Book",
                "concept": "A practical test concept",
                "inspiration_sources": "https://example.com",
                "target_pages": 20,
                "target_words": 5000,
                "tone_preferences": "Natural prose",
                "language": "pl",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert create.status_code == 303

        detail = client.get(create.headers["location"], cookies=cookies)
        assert detail.status_code == 200
        assert "Test Book" in detail.text

        outline = client.post(f"{create.headers['location']}/steps/outline", cookies=cookies, follow_redirects=False)
        assert outline.status_code == 303

        prompts = client.post(f"{create.headers['location']}/steps/prompts", cookies=cookies, follow_redirects=False)
        assert prompts.status_code == 303

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
