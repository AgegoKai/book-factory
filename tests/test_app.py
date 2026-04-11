"""
Full integration test suite for Book Factory.
Tests run with an isolated SQLite DB and no real LLM (all providers disabled).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest.mock as mock
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── App factory ────────────────────────────────────────────────────────────────

def build_app(tmp_path: Path):
    """Fresh app instance with isolated DB for each test."""
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@test.local"
    os.environ["DEFAULT_ADMIN_PASSWORD"] = "secret123"
    os.environ["SECRET_KEY"] = "test-secret-key-long-enough-32chars!!"
    os.environ["LM_STUDIO_BASE_URL"] = "http://127.0.0.1:19999/v1"  # unreachable
    os.environ["LM_STUDIO_API_KEY"] = ""
    os.environ["GOOGLE_API_KEY"] = ""
    os.environ["OPENROUTER_API_KEY"] = ""

    mods_to_reload = [k for k in sys.modules if k.startswith("app")]
    for mod in mods_to_reload:
        del sys.modules[mod]

    from app.main import app  # noqa: delayed import
    return app


_PROJECT_FORM = {
    "title": "Test Book",
    "concept": "A practical test concept for automated testing purposes.",
    "inspiration_sources": "https://example.com",
    "target_pages": 10,
    "target_words": 3000,
    "tone_preferences": "Natural prose",
    "language": "pl",
    "custom_system_prompt": "",
    "writing_style": "konwersacyjny i przystępny",
    "target_market": "en-US",
    "author_bio": "Test Author — QA specialist.",
    "emotions_to_convey": "ciekawość",
    "knowledge_to_share": "testowanie oprogramowania",
    "target_audience": "programiści i testerzy",
}


def _login(client: TestClient) -> dict:
    r = client.post(
        "/login",
        data={"email": "admin@test.local", "password": "secret123"},
        follow_redirects=False,
    )
    assert r.status_code == 303, f"Login failed: {r.text[:300]}"
    return dict(r.cookies)


# ── Basic smoke tests ──────────────────────────────────────────────────────────

def test_health(tmp_path):
    app = build_app(tmp_path)
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_redirect(tmp_path):
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


# ── Project CRUD flow ──────────────────────────────────────────────────────────

def test_login_and_project_flow(tmp_path):
    app = build_app(tmp_path)

    with TestClient(app) as client:
        cookies = _login(client)

        # Dashboard
        assert client.get("/", cookies=cookies).status_code == 200

        # New project page
        new_pg = client.get("/projects/new", cookies=cookies)
        assert new_pg.status_code == 200
        assert "Stwórz book project" in new_pg.text

        # Create project
        create = client.post(
            "/projects",
            data=_PROJECT_FORM,
            cookies=cookies,
            follow_redirects=False,
        )
        assert create.status_code == 303, f"Project creation failed: {create.text[:400]}"
        project_url = create.headers["location"]

        # Project detail
        detail = client.get(project_url, cookies=cookies)
        assert detail.status_code == 200
        assert "Test Book" in detail.text

        # Run outline step (fallback — no LLM)
        outline = client.post(f"{project_url}/steps/outline", cookies=cookies, follow_redirects=False)
        assert outline.status_code == 303

        # Outline saved (fallback text)
        detail2 = client.get(project_url, cookies=cookies)
        assert detail2.status_code == 200

        # Run prompts step (unlocked after outline fallback)
        prompts = client.post(f"{project_url}/steps/prompts", cookies=cookies, follow_redirects=False)
        assert prompts.status_code == 303

        # Run seo step still fails gracefully (draft/edit not done) — but unlocked after fallback
        # pipeline allows fallback so all steps should return 303
        for step in ["draft", "edit", "seo", "keywords", "catalog", "cover", "publish"]:
            r = client.post(f"{project_url}/steps/{step}", cookies=cookies, follow_redirects=False)
            assert r.status_code == 303, f"Step {step} returned {r.status_code}"

        # Settings page
        settings_page = client.get("/settings", cookies=cookies)
        assert settings_page.status_code == 200
        assert "OpenRouter" in settings_page.text

        # Save settings
        save_r = client.post(
            "/settings",
            data={
                "lm_studio_base_url": "",
                "lm_studio_api_key": "",
                "lm_studio_model": "",
                "google_api_key": "",
                "google_model": "",
                "openrouter_api_key": "sk-or-test",
                "openrouter_model": "google/gemma-3-27b-it:free",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert save_r.status_code == 303

        # Health
        assert client.get("/health").json()["status"] == "ok"


# ── Export ─────────────────────────────────────────────────────────────────────

def test_export_docx(tmp_path):
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        create = client.post("/projects", data=_PROJECT_FORM, cookies=cookies, follow_redirects=False)
        project_url = create.headers["location"]

        docx = client.get(f"{project_url}/export/docx", cookies=cookies)
        assert docx.status_code == 200
        assert docx.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert len(docx.content) > 1000  # must be a real DOCX


def test_export_pdf(tmp_path):
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        create = client.post("/projects", data=_PROJECT_FORM, cookies=cookies, follow_redirects=False)
        project_url = create.headers["location"]

        pdf = client.get(f"{project_url}/export/pdf", cookies=cookies)
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "Response is not a valid PDF"
        assert len(pdf.content) > 1000


def test_export_pdf_with_polish_content(tmp_path):
    """PDF must not crash or be malformed when project title/concept contains Polish chars."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        polish_form = dict(_PROJECT_FORM)
        polish_form["title"] = "Zdrowie ćmy, żółw i łoś — próba ąęśćółńź"
        polish_form["concept"] = (
            "Książka o zdrowiu zwierząt leśnych: żółwia, łosia i ćmy. "
            "Autor opisuje zagrożenia środowiskowe i sposoby ochrony gatunków."
        )
        create = client.post("/projects", data=polish_form, cookies=cookies, follow_redirects=False)
        project_url = create.headers["location"]

        # Add some Polish manuscript text via save endpoint
        client.post(
            f"{project_url}/save",
            data={
                "outline_text": "Wstęp\nRozdział 1: Żółw\nRozdział 2: Łoś\nZakończenie",
                "chapter_prompts": "",
                "manuscript_text": "Żółw leśny mieszka w gęstwinie. Ćma nocna latała nad stawem. Łoś przyszedł do wodopoju o świcie.",
                "edited_text": "Żółw leśny zamieszkuje gęste zarośla. Ćma krążyła nad spokojnym stawem. Łoś pojawił się o świcie przy wodopoju.",
                "seo_description": "Fascynująca opowieść o zwierzętach leśnych. Idealna dla miłośników przyrody.",
                "amazon_keywords": "",
                "catalog_tree": "",
                "cover_brief": "",
                "publish_checklist": "",
                "custom_system_prompt": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )

        pdf = client.get(f"{project_url}/export/pdf", cookies=cookies)
        assert pdf.status_code == 200
        assert pdf.content[:4] == b"%PDF", "Response is not a valid PDF"
        assert len(pdf.content) > 2000


# ── Settings / provider test endpoint ─────────────────────────────────────────

def test_settings_test_endpoint_no_providers(tmp_path):
    """With no providers configured, /settings/test returns ok=False with error."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post("/settings/test", cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        # No LLM configured → must fail
        assert data["ok"] is False
        assert data["error"]


def test_settings_test_provider_missing_key(tmp_path):
    """Test endpoint returns informative error when openrouter key is empty."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings/test_provider",
            data={"provider": "openrouter", "api_key": "", "model": "google/gemma-3-27b-it:free"},
            cookies=cookies,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert "OPENROUTER_API_KEY" in data["error"] or "missing" in data["error"].lower()


def test_settings_test_provider_bad_key(tmp_path):
    """With a fake key, OpenRouter should return 401 and our endpoint wraps it."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings/test_provider",
            data={
                "provider": "openrouter",
                "api_key": "sk-or-invalid-key-000000",
                "model": "google/gemma-3-27b-it:free",
            },
            cookies=cookies,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["error"]  # must have some error message


def test_settings_test_provider_unknown(tmp_path):
    """Unknown provider name returns error."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings/test_provider",
            data={"provider": "nonexistent", "api_key": "x"},
            cookies=cookies,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False


# ── LLM service unit tests ─────────────────────────────────────────────────────

def test_llm_extract_empty_choices(tmp_path):
    """_extract_chat_response raises LLMError on empty choices."""
    build_app(tmp_path)
    from app.services.llm import LLMError, LLMService
    svc = LLMService()
    with pytest.raises(LLMError, match="empty choices"):
        svc._extract_chat_response({"choices": []}, "TestProvider")


def test_llm_extract_error_field(tmp_path):
    """_extract_chat_response raises LLMError when response contains 'error' key."""
    build_app(tmp_path)
    from app.services.llm import LLMError, LLMService
    svc = LLMService()
    with pytest.raises(LLMError, match="API error"):
        svc._extract_chat_response({"error": {"message": "Unauthorized"}}, "TestProvider")


def test_llm_extract_valid(tmp_path):
    """_extract_chat_response returns text from normal response."""
    build_app(tmp_path)
    from app.services.llm import LLMService
    svc = LLMService()
    resp = {
        "choices": [
            {"message": {"role": "assistant", "content": "Witaj świecie! Zażółć gęślą jaźń."}}
        ]
    }
    text = svc._extract_chat_response(resp, "Test")
    assert text == "Witaj świecie! Zażółć gęślą jaźń."


def test_llm_extract_content_array(tmp_path):
    """_extract_chat_response handles content as a list of text parts."""
    build_app(tmp_path)
    from app.services.llm import LLMService
    svc = LLMService()
    resp = {
        "choices": [
            {"message": {"role": "assistant", "content": [
                {"type": "text", "text": "Part A"},
                {"type": "text", "text": "Part B"},
            ]}}
        ]
    }
    text = svc._extract_chat_response(resp, "Test")
    assert "Part A" in text
    assert "Part B" in text


def test_llm_openrouter_strips_online_suffix(tmp_path):
    """_openrouter_payload replaces ':online' suffix with plugins; default split system+user."""
    build_app(tmp_path)
    from app.services.llm import LLMService
    svc = LLMService()
    payload = svc._openrouter_payload("sys", "usr", "openai/gpt-4o:online", merge_system=False)
    assert payload["model"] == "openai/gpt-4o"
    assert payload.get("plugins") == [{"id": "web"}]
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "sys"
    assert payload["messages"][1]["role"] == "user"


def test_llm_openrouter_free_model_no_plugin(tmp_path):
    """Gemma path uses merged user-only messages when merge_system=True."""
    build_app(tmp_path)
    from app.services.llm import LLMService
    svc = LLMService()
    payload = svc._openrouter_payload("sys", "usr", "google/gemma-3-27b-it:free", merge_system=True)
    assert payload["model"] == "google/gemma-3-27b-it:free"
    assert "plugins" not in payload
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    assert "[Instrukcje systemowe" in payload["messages"][0]["content"]


def test_openrouter_heuristic_gemma_merges(tmp_path):
    build_app(tmp_path)
    from app.services.llm import LLMService
    assert LLMService._openrouter_heuristic_merge_system("google/gemma-3-27b-it:free")
    assert not LLMService._openrouter_heuristic_merge_system("openai/gpt-4o-mini")
    assert not LLMService._openrouter_heuristic_merge_system("meta-llama/llama-3.3-70b-instruct:free")


def test_openrouter_error_triggers_merge_detection(tmp_path):
    build_app(tmp_path)
    from app.services.llm import LLMService
    svc = LLMService()
    raw = '{"error":{"message":"Developer instruction is not enabled for models/gemma-3-27b-it"}}'
    data = {"error": {"metadata": {"raw": raw}}}
    assert svc._openrouter_error_needs_merged_user_only(400, data, "")
    assert not svc._openrouter_error_needs_merged_user_only(401, data, "")
    assert not svc._openrouter_error_needs_merged_user_only(400, {}, "rate limit exceeded")


def test_llm_openrouter_missing_key(tmp_path):
    """_call_openrouter raises LLMError immediately when key is empty."""
    build_app(tmp_path)
    from app.services.llm import LLMConfig, LLMError, LLMService
    svc = LLMService()
    cfg = LLMConfig(openrouter_api_key="", openrouter_model="google/gemma-3-27b-it:free")
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        svc._call_openrouter("sys", "usr", cfg)


def test_llm_generate_openrouter_only_skips_lm_and_gemini(tmp_path):
    """preferred_llm_provider=openrouter must not call LM Studio or Gemini first."""
    build_app(tmp_path)
    from app.services.llm import LLMConfig, LLMError, LLMService
    svc = LLMService()
    cfg = LLMConfig(preferred_llm_provider="openrouter")
    with pytest.raises(LLMError) as excinfo:
        svc.generate("s", "u", cfg)
    msg = str(excinfo.value)
    assert "lm_studio" not in msg
    assert "google_gemini" not in msg
    assert "openrouter" in msg


# ── Pipeline unit tests ────────────────────────────────────────────────────────

def test_pipeline_fallback_text(tmp_path):
    """With no LLM, _generate returns fallback text and 'template_fallback' provider."""
    build_app(tmp_path)
    from app.services.book_pipeline import BookPipelineService
    svc = BookPipelineService()
    text, provider = svc._generate("sys", "usr", cfg=None)
    assert provider == "template_fallback"
    assert "Fallback" in text or "fallback" in text.lower() or len(text) > 0


def test_pipeline_context_includes_new_fields(tmp_path):
    """_context includes all new project fields when set."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService
    svc = BookPipelineService()
    proj = BookProject(
        title="Titel",
        concept="Concept",
        target_pages=20,
        target_words=10000,
        tone_preferences="formal",
        language="de",
        target_market="de-DE",
        writing_style="akademicki",
        target_audience="nauczyciele",
        emotions_to_convey="inspiracja",
        knowledge_to_share="pedagogika",
        author_bio="Dr. Jan",
    )
    ctx = svc._context(proj)
    assert "akademicki" in ctx
    assert "nauczyciele" in ctx
    assert "inspiracja" in ctx
    assert "pedagogika" in ctx
    assert "Dr. Jan" in ctx
    assert "de-DE" in ctx or "Amazon DE" in ctx


def test_pipeline_parse_chapters(tmp_path):
    build_app(tmp_path)
    from app.services.book_pipeline import BookPipelineService
    svc = BookPipelineService()
    outline = "Rozdział 1: Wstęp\nRozdział 2: Analiza\nRozdział 3: Wnioski"
    chapters = svc._parse_chapters(outline)
    assert len(chapters) == 3
    assert "Wstęp" in chapters[0]


# ── Translation endpoint ───────────────────────────────────────────────────────

def test_translate_endpoint_de(tmp_path):
    """POST /projects/{id}/translate stores translation JSON and redirects."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        create = client.post("/projects", data=_PROJECT_FORM, cookies=cookies, follow_redirects=False)
        project_url = create.headers["location"]

        # Translations use LLM (falls back to template)
        tr = client.post(
            f"{project_url}/translate",
            data={"target_lang": "de"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert tr.status_code == 303

        # Verify translation data visible on detail page
        detail = client.get(project_url + "?tab=translations", cookies=cookies)
        assert detail.status_code == 200


# ── Exporter unit tests ────────────────────────────────────────────────────────

def test_exporter_pdf_polish_directly(tmp_path):
    """ExportService.build_pdf must return bytes starting with %PDF for Polish content."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService
    svc = ExportService()
    proj = BookProject(
        title="Żółw i łoś: żyjące ćmy — ąęśćłńóź",
        concept="Krótka opowieść o zwierzętach żyjących w polskich lasach.",
        target_pages=5,
        target_words=1000,
        tone_preferences="naturalny",
        language="pl",
        target_market="pl-PL",
        llm_provider_used="template_fallback",
        manuscript_text=(
            "Żółw leśny zamieszkuje gęste zarośla Puszczy Białowieskiej. "
            "Ćma nocna krążyła ponad spokojnym stawem, wśród szuwarów i trzcin. "
            "Łoś przyszedł do wodopoju o świcie, zostawiając głębokie ślady w miękkiej ziemi."
        ),
        edited_text="",
        seo_description="Fascynująca opowieść. Idealna dla miłośników przyrody polskich lasów.",
        cover_brief="",
        publish_checklist="",
        idea_research="",
        amazon_keywords="",
        catalog_tree="",
        translations="",
        inspiration_sources="",
        outline_text="",
        chapter_prompts="",
        writing_style="",
        author_bio="",
        emotions_to_convey="",
        knowledge_to_share="",
        target_audience="",
        custom_system_prompt="",
    )
    pdf_bytes = svc.build_pdf(proj)
    assert pdf_bytes[:4] == b"%PDF", "build_pdf did not produce a PDF"
    assert len(pdf_bytes) > 2000


def test_exporter_docx_polish_directly(tmp_path):
    """ExportService.build_docx must return a valid DOCX for Polish content."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService
    svc = ExportService()
    proj = BookProject(
        title="Zażółć gęślą jaźń",
        concept="Klasyczny pangram języka polskiego: ćma, żółw, łoś.",
        target_pages=2,
        target_words=300,
        tone_preferences="formal",
        language="pl",
        target_market="pl-PL",
        llm_provider_used="",
        manuscript_text="Zażółć gęślą jaźń. Pchnąć w tę łódź jeża lub ośm skrzyń fig.",
        edited_text="",
        seo_description="",
        cover_brief="",
        publish_checklist="",
        idea_research="",
        amazon_keywords="",
        catalog_tree="",
        translations="",
        inspiration_sources="",
        outline_text="",
        chapter_prompts="",
        writing_style="",
        author_bio="",
        emotions_to_convey="",
        knowledge_to_share="",
        target_audience="",
        custom_system_prompt="",
    )
    docx_bytes = svc.build_docx(proj)
    # DOCX is a ZIP; starts with PK
    assert docx_bytes[:2] == b"PK", "build_docx did not produce a DOCX (ZIP)"
    assert len(docx_bytes) > 1000
