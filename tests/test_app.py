import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_app(tmp_path: Path):
    """Build a fresh app instance with isolated DB for each test."""
    # Set env BEFORE any imports that trigger Settings()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@test.local"
    os.environ["DEFAULT_ADMIN_PASSWORD"] = "secret123"
    os.environ["SECRET_KEY"] = "test-secret-key-long-enough"
    os.environ["LM_STUDIO_API_KEY"] = ""
    os.environ["GOOGLE_API_KEY"] = ""
    os.environ["OPENROUTER_API_KEY"] = ""

    # Force reload of all app modules so new env is picked up
    mods_to_reload = [k for k in sys.modules if k.startswith("app")]
    for mod in mods_to_reload:
        del sys.modules[mod]

    from app.main import app  # noqa: delayed import
    return app


def test_health(tmp_path):
    app = build_app(tmp_path)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_redirect(tmp_path):
    """Unauthenticated request should redirect to /login."""
    app = build_app(tmp_path)
    with TestClient(app, follow_redirects=False) as client:
        r = client.get("/")
        assert r.status_code in (302, 303)
        assert "/login" in r.headers["location"]


def test_login_invalid(tmp_path):
    app = build_app(tmp_path)
    with TestClient(app) as client:
        r = client.post("/login", data={"email": "wrong@test.local", "password": "wrong"})
        assert r.status_code == 400


def test_login_and_project_flow(tmp_path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        # Login
        login = client.post(
            "/login",
            data={"email": "admin@test.local", "password": "secret123"},
            follow_redirects=False,
        )
        assert login.status_code == 303, f"Login failed: {login.text[:300]}"
        cookies = login.cookies

        # Dashboard
        dash = client.get("/", cookies=cookies)
        assert dash.status_code == 200

        # Create project
        create = client.post(
            "/projects",
            data={
                "title": "Test Book",
                "concept": "A practical test concept for automated testing.",
                "inspiration_sources": "https://example.com",
                "target_pages": 10,
                "target_words": 3000,
                "tone_preferences": "Natural prose",
                "language": "pl",
                "custom_system_prompt": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert create.status_code == 303, f"Project creation failed: {create.text[:300]}"

        project_url = create.headers["location"]

        # Project detail
        detail = client.get(project_url, cookies=cookies)
        assert detail.status_code == 200
        assert "Test Book" in detail.text

        # Run outline step (uses fallback since no LLM configured)
        outline = client.post(
            f"{project_url}/steps/outline",
            cookies=cookies,
            follow_redirects=False,
        )
        assert outline.status_code == 303

        # Verify outline was saved (fallback text)
        detail2 = client.get(project_url, cookies=cookies)
        assert detail2.status_code == 200

        # Run prompts step (outline done via fallback so unlocked)
        prompts = client.post(
            f"{project_url}/steps/prompts",
            cookies=cookies,
            follow_redirects=False,
        )
        assert prompts.status_code == 303

        # Settings page
        settings_page = client.get("/settings", cookies=cookies)
        assert settings_page.status_code == 200

        # Export DOCX (might be minimal content)
        docx = client.get(f"{project_url}/export/docx", cookies=cookies)
        assert docx.status_code == 200
        assert docx.headers["content-type"].startswith(
            "application/vnd.openxmlformats"
        )

        # Health check
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
