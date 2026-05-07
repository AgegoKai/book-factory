"""
Full integration test suite for Book Factory.
Tests run with an isolated SQLite DB and no real LLM (all providers disabled).
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
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
    "target_chapters": 10,
    "target_words": 3000,
    "tone_preferences": "Natural prose",
    "language": "pl",
    "custom_system_prompt": "",
    "writing_styles": ["conversational", "practical"],
    "target_market": "en-US",
    "author_bio": "Test Author — QA specialist.",
    "emotions_to_convey": "ciekawość",
    "knowledge_to_share": "testowanie oprogramowania",
    "target_audience": "programiści i testerzy",
    "pdf_font_family": "Georgia",
    "pdf_trim_size": "6x9",
    "pdf_body_size": 11,
    "pdf_heading_size": 23,
    "pdf_book_title_size": 30,
    "pdf_chapter_title_size": 23,
    "pdf_subchapter_title_size": 17,
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
        target_chapters=8,
        target_words=10000,
        tone_preferences="formal",
        language="de",
        target_market="de-DE",
        writing_style="akademicki",
        writing_styles='["formal","scientific"]',
        target_audience="nauczyciele",
        emotions_to_convey="inspiracja",
        knowledge_to_share="pedagogika",
        author_bio="Dr. Jan",
    )
    ctx = svc._context(proj)
    assert "8" in ctx
    assert "formal" in ctx
    assert "scientific" in ctx
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


def test_pipeline_normalizes_outline_and_prompt_blocks(tmp_path):
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService

    svc = BookPipelineService()
    proj = BookProject(
        title="English test book",
        concept="A book about useful habits.",
        language="en",
        target_chapters=4,
        target_words=8000,
        writing_styles='["conversational","practical"]',
    )
    broken_outline = """
    Chapter 1: Big Ideas
    - Why It Matters
    Chapter 2: Daily Systems
    - Small Wins
    """
    normalized = svc._normalize_outline(proj, broken_outline)
    assert normalized.count("Chapter ") == 4

    proj.outline_text = normalized
    prompts_project = svc.generate_prompts(proj)
    blocks = svc._parse_prompt_blocks(prompts_project.chapter_prompts)
    assert len(blocks) >= 8
    assert all(block["target_words"] >= block["min_words"] for block in blocks)
    assert sum(block["target_words"] for block in blocks) >= 7600


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


def test_human_check_endpoint_stores_result(tmp_path):
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        create = client.post("/projects", data=_PROJECT_FORM, cookies=cookies, follow_redirects=False)
        project_url = create.headers["location"]

        client.post(
            f"{project_url}/save",
            data={
                "title": "Test Book",
                "concept": "Test concept",
                "language": "en",
                "target_market": "en-US",
                "writing_style": "",
                "writing_styles": [],
                "author_bio": "",
                "target_audience": "",
                "tone_preferences": "Natural prose",
                "emotions_to_convey": "",
                "knowledge_to_share": "",
                "target_chapters": 10,
                "target_words": 3000,
                "pdf_font_family": "Georgia",
                "pdf_trim_size": "6x9",
                "pdf_heading_size": 23,
                "pdf_body_size": 11,
                "pdf_book_title_size": 30,
                "pdf_chapter_title_size": 23,
                "pdf_subchapter_title_size": 17,
                "pdf_title_override": "",
                "pdf_subtitle": "",
                "pdf_author_name": "",
                "pdf_include_toc": "1",
                "pdf_show_page_numbers": "1",
                "outline_text": "",
                "chapter_prompts": "",
                "manuscript_text": "This is a long enough manuscript paragraph. " * 40,
                "edited_text": "This is a human sounding edited manuscript paragraph. " * 40,
                "seo_description": "",
                "amazon_keywords": "",
                "catalog_tree": "",
                "cover_brief": "",
                "publish_checklist": "",
                "custom_system_prompt": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )

        from app import main as app_main

        fake_result = {
            "provider": "copyleaks",
            "human_score": 0.73,
            "ai_score": 0.27,
            "total_words": 320,
            "checked_at": "2026-04-12T12:00:00Z",
            "model_version": "v5",
            "scan_id": "scan-123",
            "results": [{"classification": 1, "probability": 0.73}],
            "summary": {"human": 0.73, "ai": 0.27},
        }
        with mock.patch.object(app_main.human_check_service, "analyze_text", return_value=fake_result):
            resp = client.post(
                f"{project_url}/human-check",
                data={"source": "edited"},
                cookies=cookies,
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert "tab=humancheck" in resp.headers["location"]

        detail = client.get(project_url + "?tab=humancheck", cookies=cookies)
        assert detail.status_code == 200
        assert "Human / AI Verification" in detail.text
        assert "73.0%" in detail.text
        assert "scan-123" in detail.text


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


def test_exporter_pdf_invalid_size_settings_fallbacks(tmp_path):
    """Malformed PDF settings stored in SQLite should not break export."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService
    svc = ExportService()
    proj = BookProject(
        title="Broken PDF config",
        concept="Invalid persisted PDF settings should fall back to defaults.",
        manuscript_text="Rozdział 1: Test\n\nAkapit testowy z poprawnym tekstem.",
        edited_text="",
    )
    proj.pdf_font_family = "NotARealFont"
    proj.pdf_heading_size = "abc"
    proj.pdf_body_size = ""

    pdf_bytes = svc.build_pdf(proj)
    assert pdf_bytes[:4] == b"%PDF", "build_pdf did not recover from invalid PDF settings"
    assert len(pdf_bytes) > 1000


def test_exporter_pdf_uses_6x9_trim_and_localized_toc(tmp_path):
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService

    svc = ExportService()
    proj = BookProject(
        title="English PDF",
        concept="Testing trim size and TOC localization.",
        language="en",
        target_chapters=2,
        manuscript_text=(
            "Chapter 1: First chapter\n\n## Opening idea\n\n"
            + ("This is a test sentence for the English manuscript. " * 120)
            + "\n\nChapter 2: Second chapter\n\n## Closing angle\n\n"
            + ("This is another sentence that keeps the PDF long enough. " * 120)
        ),
        pdf_trim_size="6x9",
        pdf_include_toc=True,
    )

    pdf_bytes = svc.build_pdf(proj)
    assert b"/MediaBox [ 0 0 432 648 ]" in pdf_bytes or b"/MediaBox [0 0 432 648]" in pdf_bytes
    assert pdf_bytes[:4] == b"%PDF"


def test_exporter_pdf_long_unicode_header_footer(tmp_path):
    """Later-page header/footer rendering should tolerate long Unicode title and author."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService
    svc = ExportService()
    proj = BookProject(
        title="Zażółć gęślą jaźń — bardzo długi tytuł książki o żółwiu, łośiu i ćmie nocnej",
        concept="Long manuscript to force later pages.",
        author_bio="Łukasz Żółć — autor, badacz i opiekun żółwi błotnych",
        manuscript_text="Rozdział 1: Tytuł\n\n" + ("Zażółć gęślą jaźń. " * 1200),
        edited_text="",
    )

    pdf_bytes = svc.build_pdf(proj)
    assert pdf_bytes[:4] == b"%PDF", "build_pdf failed on later pages with Unicode header/footer"
    assert len(pdf_bytes) > 4000


def test_exporter_registers_dejavu_variant_aliases(tmp_path):
    """Selected PDF families must expose Bold/Italic aliases expected by ReportLab."""
    build_app(tmp_path)
    import app.services.exporter as exporter
    registered = []
    families = []

    with mock.patch("app.services.exporter.os.path.isfile", return_value=True), \
         mock.patch("app.services.exporter.TTFont", side_effect=lambda name, path: (name, path)), \
         mock.patch("app.services.exporter.pdfmetrics.registerFont", side_effect=lambda font: registered.append(font[0])), \
         mock.patch("app.services.exporter.pdfmetrics.registerFontFamily", side_effect=lambda *args, **kwargs: families.append((args, kwargs))):
        ok = exporter._try_register_set(
            "/tmp/fonts",
            "DejaVu",
            "DejaVuSerif.ttf",
            "DejaVuSerif-Bold.ttf",
            "DejaVuSerif-Italic.ttf",
        )

    assert ok is True
    assert "DejaVu" in registered
    assert "DejaVuBold" in registered
    assert "DejaVuItalic" in registered
    assert families
    _, kwargs = families[0]
    assert kwargs["normal"] == "DejaVu"
    assert kwargs["bold"] == "DejaVuBold"
    assert kwargs["italic"] == "DejaVuItalic"


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


def test_docker_entrypoint_creates_backup_snapshot(tmp_path):
    data_dir = tmp_path / "data"
    backups_dir = data_dir / "backups"
    data_dir.mkdir()
    db_file = data_dir / "book_factory.db"
    db_bytes = b"sqlite-test-bytes"
    db_file.write_bytes(db_bytes)

    env = os.environ.copy()
    env.update(
        {
            "BOOK_FACTORY_DB_PATH": str(db_file),
            "BOOK_FACTORY_BACKUP_DIR": str(backups_dir),
            "BOOK_FACTORY_BACKUP_KEEP": "5",
            "BOOK_FACTORY_BOOT_CMD": "true",
        }
    )

    result = subprocess.run(
        ["sh", str(PROJECT_ROOT / "scripts" / "docker-entrypoint.sh")],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    restore_file = data_dir / "book_factory.restore.sqlite"
    snapshots = list(backups_dir.glob("book_factory-*.sqlite"))
    assert restore_file.read_bytes() == db_bytes
    assert len(snapshots) == 1
    assert snapshots[0].read_bytes() == db_bytes
    assert "zapisano backup bazy" in result.stdout



# ── ULTRA UPGRADE: Quality, multi-language, watermark, top-up ─────────────────


def test_quality_check_pass(tmp_path):
    """Manuscript meeting all targets passes the QA pipeline."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.quality import run_quality_check

    body = "This is a chapter body that simulates a long stretch of natural prose. " * 60
    manuscript = "\n\n".join(
        f"Chapter {i}: Sample heading\n\n{body}" for i in range(1, 6)
    )
    proj = BookProject(
        title="Test", concept="C", language="en",
        target_chapters=5, target_words=2500,
        manuscript_text="", edited_text=manuscript,
    )
    report = run_quality_check(proj)
    assert report.passed is True, report.issues
    assert report.stats["actual_chapters"] == 5
    assert report.stats["uses_edited_manuscript"] is True


def test_quality_check_flags_short_book(tmp_path):
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.quality import run_quality_check

    proj = BookProject(
        title="Test", concept="C", language="en",
        target_chapters=10, target_words=20000,
        manuscript_text="Chapter 1: Tiny\n\nA very short body.", edited_text="",
    )
    report = run_quality_check(proj)
    assert report.passed is False
    assert any("Too few chapters" in issue for issue in report.issues)
    assert any("Manuscript too short" in issue for issue in report.issues)


def test_quality_check_flags_forbidden_sections(tmp_path):
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.quality import run_quality_check

    body = "Solid prose that goes on for a while. " * 60
    manuscript = "\n\n".join(
        f"Chapter {i}: Heading\n\n{body}" for i in range(1, 4)
    ) + "\n\n## References\n\nFake reference list goes here."
    proj = BookProject(
        title="Test", concept="C", language="en",
        target_chapters=3, target_words=1500,
        manuscript_text="", edited_text=manuscript,
    )
    report = run_quality_check(proj)
    assert report.passed is False
    joined = " ".join(report.issues)
    assert "references" in joined.lower() or "bibliography" in joined.lower()


def test_quality_check_flags_polish_labels_in_english_book(tmp_path):
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.quality import run_quality_check

    body = "Edited body of decent length. " * 60
    manuscript = (
        "Rozdział 1: Zły nagłówek\n\n" + body +
        "\n\nRozdział 2: Drugi rozdział\n\n" + body
    )
    proj = BookProject(
        title="Test", concept="C", language="en",
        target_chapters=2, target_words=1000,
        manuscript_text="", edited_text=manuscript,
    )
    report = run_quality_check(proj)
    assert report.passed is False
    assert any("Foreign-language" in issue for issue in report.issues)


def test_quality_check_flags_polish_labels_in_german_book(tmp_path):
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.quality import run_quality_check

    body = "Solide deutsche Prosa fuer Tests. " * 60
    manuscript = (
        "Rozdział 1: Verbotener Stempel\n\n" + body +
        "\n\nRozdział 2: Auch verboten\n\n" + body
    )
    proj = BookProject(
        title="Test", concept="C", language="de",
        target_chapters=2, target_words=1000,
        manuscript_text="", edited_text=manuscript,
    )
    report = run_quality_check(proj)
    assert report.passed is False
    flat = " ".join(report.issues)
    assert "rozdział" in flat.lower() or "rozdzial" in flat.lower()


def test_quality_check_endpoint_persists_report(tmp_path):
    """POST /projects/{id}/quality stores the JSON report and updates status."""
    import json as _json
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        create = client.post("/projects", data=_PROJECT_FORM, cookies=cookies, follow_redirects=False)
        project_url = create.headers["location"]

        res = client.post(f"{project_url}/quality", cookies=cookies, follow_redirects=False)
        assert res.status_code == 303

        # Project detail must render the panel and the badge.
        detail = client.get(project_url, cookies=cookies)
        assert detail.status_code == 200
        assert "Status jako" in detail.text  # Polish "Status jakości"


def test_pdf_no_book_factory_watermark(tmp_path):
    """The PDF binary must never contain the literal 'Book Factory' watermark."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService

    svc = ExportService()
    proj = BookProject(
        title="Watermark check",
        concept="Make sure the PDF does not leak the app name.",
        language="en",
        manuscript_text="Chapter 1: First\n\n" + ("Body of some prose. " * 80),
        edited_text="",
    )
    pdf_bytes = svc.build_pdf(proj)
    assert pdf_bytes[:4] == b"%PDF"
    lowered = pdf_bytes.lower()
    assert b"book factory" not in lowered, "Found 'Book Factory' watermark in PDF output"


def test_pdf_uses_6x9_default_for_new_project(tmp_path):
    """Default trim size is 6x9 (432 x 648 pt MediaBox)."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService
    svc = ExportService()
    proj = BookProject(
        title="Default trim",
        concept="Sanity check trim defaults.",
        language="en",
        manuscript_text="Chapter 1: First\n\n" + ("Body. " * 80),
        edited_text="",
    )
    pdf_bytes = svc.build_pdf(proj)
    assert b"/MediaBox [ 0 0 432 648 ]" in pdf_bytes or b"/MediaBox [0 0 432 648]" in pdf_bytes


def test_chapter_split_helper(tmp_path):
    build_app(tmp_path)
    from app.services.book_pipeline import _split_manuscript_into_chapters

    text = (
        "Chapter 1: Opening\n\nFirst paragraph.\n\n"
        "Chapter 2: Middle\n\nSecond paragraph.\n\n"
        "Kapitel 3: Schluss\n\nThird paragraph."
    )
    parts = _split_manuscript_into_chapters(text, "en")
    assert len(parts) == 3
    assert parts[0]["title"].lower().startswith("opening")
    assert "First paragraph" in parts[0]["body"]
    assert "Schluss" in parts[2]["heading"]


def test_per_chapter_edit_runs_per_chapter(tmp_path):
    """generate_edit must call the LLM once per detected chapter (not once for the whole doc)."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService

    svc = BookPipelineService()
    proj = BookProject(
        title="Edit test", concept="Editor must run per chapter.",
        language="en", target_chapters=3, target_words=900,
        manuscript_text=(
            "Chapter 1: First\n\nBody one. " * 1 +
            "\n\nChapter 2: Second\n\nBody two." +
            "\n\nChapter 3: Third\n\nBody three."
        ),
    )

    calls: list[tuple[str, str]] = []

    def fake_generate(system_prompt, user_prompt, cfg=None):
        calls.append((system_prompt[:40], user_prompt[:80]))
        return "Edited prose here.", "test_provider"

    with mock.patch.object(svc, "_generate", side_effect=fake_generate):
        svc.generate_edit(proj)

    assert len(calls) == 3, f"Expected 3 chapter edits, got {len(calls)}"
    assert "Chapter 1" in proj.edited_text
    assert "Chapter 2" in proj.edited_text
    assert "Chapter 3" in proj.edited_text


def test_draft_block_top_up_runs_when_too_short(tmp_path):
    """If LLM returns text below min_words, expand_block_text issues a top-up call."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService, _count_words

    svc = BookPipelineService()
    proj = BookProject(title="Short", concept="C", language="en",
                       target_chapters=2, target_words=2000,
                       outline_text="Chapter 1: A\n- one\n- two\nChapter 2: B\n- one\n- two")
    svc.generate_prompts(proj)

    # First call returns a very short block (forces top-up). Subsequent calls return
    # a longer block to satisfy min_words. Accept any number of additional calls.
    short = "Tiny block."
    long = ("This is a satisfyingly long paragraph of edited prose. " * 80).strip()
    responses = [(short, "test"), (long, "test"), (long, "test"), (long, "test"), (long, "test"), (long, "test"), (long, "test"), (long, "test"), (long, "test"), (long, "test")]

    call_log: list[int] = []

    def fake_generate(system_prompt, user_prompt, cfg=None):
        idx = len(call_log)
        call_log.append(idx)
        return responses[min(idx, len(responses) - 1)]

    with mock.patch.object(svc, "_generate", side_effect=fake_generate):
        svc.generate_draft(proj)

    # We submitted at least 4 prompt blocks (2 chapters x 2 blocks); top-up must add at
    # least one extra call for the first short block.
    blocks = svc._parse_prompt_blocks(proj.chapter_prompts)
    assert len(call_log) > len(blocks), (
        f"Top-up did not engage: {len(call_log)} calls vs {len(blocks)} blocks"
    )


def test_full_pipeline_writes_quality_report(tmp_path):
    """After run_full_pipeline the project always has a JSON quality_report."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService
    svc = BookPipelineService()
    proj = BookProject(
        title="Pipeline qa test", concept="Make sure QA writes a report.",
        language="en", target_chapters=4, target_words=4000,
    )
    svc.run_full_pipeline(proj)
    assert proj.status in ("ready", "qa_failed")
    assert proj.quality_report
    import json as _json
    payload = _json.loads(proj.quality_report)
    assert "passed" in payload
    assert "stats" in payload and "actual_words" in payload["stats"]


def test_pipeline_full_run_with_mocked_llm_passes_qa(tmp_path):
    """With an LLM that produces long, valid prose, the pipeline ends in 'ready' status."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService
    svc = BookPipelineService()
    proj = BookProject(
        title="Mocked LLM book", concept="A test book.",
        language="en", target_chapters=3, target_words=600,
    )

    def fake_generate(system_prompt, user_prompt, cfg=None):
        # Produce believable English prose long enough to pass length checks.
        body = "This is a satisfyingly long paragraph of edited natural prose. " * 80
        return body.strip(), "test_provider"

    with mock.patch.object(svc, "_generate", side_effect=fake_generate):
        svc.run_full_pipeline(proj)
    assert proj.status == "ready", f"Expected 'ready', got '{proj.status}': {proj.quality_report}"


def test_migration_preserves_legacy_projects(tmp_path):
    """Bootstrap migration must not break a legacy SQLite DB without quality_report."""
    import sqlite3
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Minimal legacy book_projects table from a much older version.
    cur.execute("""
        CREATE TABLE book_projects (
            id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            title TEXT,
            concept TEXT,
            inspiration_sources TEXT DEFAULT '',
            target_pages INTEGER DEFAULT 20,
            target_chapters INTEGER DEFAULT 0,
            target_words INTEGER DEFAULT 5000,
            tone_preferences TEXT DEFAULT '',
            language TEXT DEFAULT 'pl',
            custom_system_prompt TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            outline_text TEXT DEFAULT '',
            chapter_prompts TEXT DEFAULT '',
            manuscript_text TEXT DEFAULT '',
            edited_text TEXT DEFAULT '',
            seo_description TEXT DEFAULT '',
            cover_brief TEXT DEFAULT '',
            publish_checklist TEXT DEFAULT '',
            idea_research TEXT DEFAULT '',
            llm_provider_used TEXT DEFAULT '',
            writing_style TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute(
        "INSERT INTO book_projects (id, owner_id, title, concept, language, manuscript_text, target_pages) "
        "VALUES (1, 1, 'Legacy book', 'Old concept', 'pl', 'Rozdział 1: Test\n\nTreść', 24)"
    )
    conn.commit()
    conn.close()

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@test.local"
    os.environ["DEFAULT_ADMIN_PASSWORD"] = "secret123"
    os.environ["SECRET_KEY"] = "test-secret-key-long-enough-32chars!!"

    mods_to_reload = [k for k in sys.modules if k.startswith("app")]
    for mod in mods_to_reload:
        del sys.modules[mod]

    from app.bootstrap import init_db, migrate_db  # noqa: E402
    init_db()
    migrate_db()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(book_projects)")
    cols = {row[1] for row in cur.fetchall()}
    assert "quality_report" in cols
    cur.execute("SELECT title, target_chapters, quality_report FROM book_projects WHERE id=1")
    row = cur.fetchone()
    assert row[0] == "Legacy book"
    assert row[1] >= 1, "target_chapters should be inferred"
    assert row[2] == ""
    conn.close()


def test_exporter_localized_manuscript_label(tmp_path):
    """The localized manuscript heading helper returns the correct label per language."""
    build_app(tmp_path)
    from app.services.exporter import _manuscript_heading, _docx_section_labels

    assert _manuscript_heading("en") == "Manuscript"
    assert _manuscript_heading("de") == "Manuskript"
    assert _manuscript_heading("pl") == "Manuskrypt"

    assert _docx_section_labels("en")["manuscript"] == "Manuscript"
    assert _docx_section_labels("de")["manuscript"] == "Manuskript"
    assert _docx_section_labels("pl")["manuscript"] == "Manuskrypt"


def test_exporter_pdf_chapter_label_is_english_for_english_book(tmp_path):
    """English book PDF chapter label uses 'Chapter', not 'Rozdział'."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.exporter import ExportService
    import re, zlib, base64
    svc = ExportService()
    proj = BookProject(
        title="English book",
        concept="Test",
        language="en",
        manuscript_text="Chapter 1: First chapter\n\n" + ("Body. " * 80),
    )
    pdf = svc.build_pdf(proj)
    # Decode flate streams and look for the chapter prefix.
    found_chapter = False
    found_polish = False
    streams = re.findall(rb"stream\n(.+?)endstream", pdf, flags=re.DOTALL)
    for raw in streams:
        raw = raw.strip()
        try:
            ascii85 = base64.a85decode(raw, adobe=True)
        except Exception:
            ascii85 = raw
        try:
            decoded = zlib.decompress(ascii85)
        except Exception:
            continue
        if b"Chapter" in decoded:
            found_chapter = True
        if b"Rozdzia" in decoded:
            found_polish = True
    assert found_chapter, "English PDF should contain 'Chapter' label"
    assert not found_polish, "English PDF must not contain Polish 'Rozdział'"


def test_pipeline_chapter_prefix_localization(tmp_path):
    """generate_draft prefixes chapter headings in the book language (no ROZDZIAŁ in EN/DE)."""
    build_app(tmp_path)
    from app.models import BookProject
    from app.services.book_pipeline import BookPipelineService
    svc = BookPipelineService()

    for lang, banned, expected in [
        ("en", "Rozdział", "Chapter "),
        ("de", "Rozdział", "Kapitel "),
    ]:
        proj = BookProject(
            title=f"{lang} book", concept="C",
            language=lang, target_chapters=2, target_words=1200,
            outline_text=f"{expected}1: First\n- a\n- b\n{expected}2: Second\n- a\n- b",
        )
        svc.generate_prompts(proj)
        svc.generate_draft(proj)
        assert banned not in proj.manuscript_text, (
            f"{lang} book leaked Polish chapter label: {proj.manuscript_text[:200]}"
        )
        assert proj.manuscript_text.count(expected) >= 2


# ── OpenAI provider unit tests ─────────────────────────────────────────────────

def test_openai_config_resolves_from_settings(tmp_path):
    """LLMConfig.resolve_openai_key / model / base_url read from config fallback."""
    build_app(tmp_path)
    from app.services.llm import LLMConfig
    from app.config import settings as cfg
    lc = LLMConfig()
    assert lc.resolve_openai_key() == cfg.openai_api_key
    assert lc.resolve_openai_model() == cfg.openai_model
    assert lc.resolve_openai_base_url() == cfg.openai_base_url.rstrip("/")


def test_openai_call_raises_without_key(tmp_path):
    """_call_openai raises LLMError when no API key is set."""
    build_app(tmp_path)
    from app.services.llm import LLMConfig, LLMError, LLMService
    svc = LLMService()
    cfg_no_key = LLMConfig(openai_api_key="", openai_model="gpt-4o-mini")
    import unittest.mock as mock
    # Patch settings.openai_api_key to empty too
    with mock.patch("app.services.llm.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_model = ""
        mock_settings.llm_max_output_tokens = 8192
        try:
            svc._call_openai("sys", "user", cfg_no_key)
            assert False, "Expected LLMError"
        except LLMError as e:
            assert "OPENAI_API_KEY missing" in str(e)


def test_settings_openai_provider_saved(tmp_path):
    """Saving settings with openai provider persists the preference."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings",
            data={
                "preferred_llm_provider": "openai",
                "openai_api_key": "sk-test-key-abc",
                "openai_model": "gpt-4o-mini",
                "openai_base_url": "",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)
        # Follow the redirect and verify settings page loads
        r2 = client.get("/settings", cookies=cookies)
        assert r2.status_code == 200


def test_settings_test_provider_openai_missing_key(tmp_path):
    """test_provider for openai returns ok=False when key is absent."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings/test_provider",
            data={"provider": "openai", "api_key": "", "model": "gpt-4o-mini", "base_url": ""},
            cookies=cookies,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert "OPENAI_API_KEY" in data.get("error", "") or "missing" in data.get("error", "").lower()


def test_build_cfg_passes_openai_fields(tmp_path):
    """_build_cfg correctly maps UserSettings.openai_* to LLMConfig."""
    build_app(tmp_path)
    from app.models import UserSettings
    from app.services.book_pipeline import _build_cfg
    us = UserSettings(
        openai_api_key="sk-abc",
        openai_base_url="https://custom.api/v1",
        openai_model="gpt-4o",
    )
    cfg = _build_cfg(us)
    assert cfg.resolve_openai_key() == "sk-abc"
    assert cfg.resolve_openai_base_url() == "https://custom.api/v1"
    assert cfg.resolve_openai_model() == "gpt-4o"


# ── Project clone tests ─────────────────────────────────────────────────────────

def test_project_clone_creates_copy(tmp_path):
    """POST /projects/{id}/clone creates a new project with same settings but empty pipeline."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        # Create original project
        r = client.post(
            "/projects",
            data={
                "title": "Original Book",
                "concept": "A concept",
                "language": "en",
                "target_chapters": "5",
                "target_words": "10000",
                "writing_style": "journalistic",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)
        orig_url = r.headers.get("location", "")
        orig_id = int(orig_url.split("/")[-1])

        # Clone it
        r2 = client.post(
            f"/projects/{orig_id}/clone",
            cookies=cookies,
            follow_redirects=False,
        )
        assert r2.status_code in (302, 303)
        clone_url = r2.headers.get("location", "")
        clone_id = int(clone_url.split("/")[-1])
        assert clone_id != orig_id

        # Verify clone has the right title suffix
        r3 = client.get(f"/projects/{clone_id}", cookies=cookies)
        assert r3.status_code == 200
        assert "kopia" in r3.text.lower() or "Original Book" in r3.text


# ── OpenClaw provider tests ────────────────────────────────────────────────────

def test_openclaw_raises_without_token(tmp_path):
    """_call_openclaw raises LLMError when no OAuth token is set."""
    build_app(tmp_path)
    from app.services.llm import LLMConfig, LLMError, LLMService
    import unittest.mock as mock
    svc = LLMService()
    cfg_no_token = LLMConfig(openclaw_oauth_token="", openclaw_model="openai-codex/gpt-5.4")
    with mock.patch("app.services.llm.settings") as ms:
        ms.openclaw_oauth_token = ""
        ms.openclaw_base_url = "http://127.0.0.1:8765/v1"
        ms.openclaw_model = ""
        ms.llm_max_output_tokens = 8192
        try:
            svc._call_openclaw("sys", "user", cfg_no_token)
            assert False, "Expected LLMError"
        except LLMError as e:
            assert "OPENCLAW_OAUTH_TOKEN missing" in str(e)


def test_openclaw_resolve_methods(tmp_path):
    """LLMConfig resolve methods for openclaw read from config fallback."""
    build_app(tmp_path)
    from app.services.llm import LLMConfig
    from app.config import settings as cfg
    lc = LLMConfig()
    assert lc.resolve_openclaw_token() == cfg.openclaw_oauth_token
    assert lc.resolve_openclaw_model() == cfg.openclaw_model
    assert "8765" in lc.resolve_openclaw_base_url() or lc.resolve_openclaw_base_url() == cfg.openclaw_base_url.rstrip("/")


def test_openclaw_provider_saves_in_settings(tmp_path):
    """Saving openclaw as preferred_llm_provider persists correctly."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings",
            data={
                "preferred_llm_provider": "openclaw",
                "openclaw_oauth_token": "eyJtest.token.here",
                "openclaw_model": "openai-codex/gpt-5.4",
                "openclaw_base_url": "http://127.0.0.1:8765/v1",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)
        r2 = client.get("/settings", cookies=cookies)
        assert r2.status_code == 200


def test_openclaw_test_provider_missing_token(tmp_path):
    """test_provider for openclaw returns ok=False with no token."""
    app = build_app(tmp_path)
    with TestClient(app) as client:
        cookies = _login(client)
        r = client.post(
            "/settings/test_provider",
            data={"provider": "openclaw", "api_key": "", "model": "openai-codex/gpt-5.4", "base_url": ""},
            cookies=cookies,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert "OPENCLAW_OAUTH_TOKEN" in data.get("error", "")


def test_build_cfg_passes_openclaw_fields(tmp_path):
    """_build_cfg passes openclaw fields through to LLMConfig."""
    build_app(tmp_path)
    from app.models import UserSettings
    from app.services.book_pipeline import _build_cfg
    us = UserSettings(
        openclaw_oauth_token="sess_abc123",
        openclaw_base_url="http://127.0.0.1:9000/v1",
        openclaw_model="openai-codex/gpt-5.5",
    )
    cfg = _build_cfg(us)
    assert cfg.resolve_openclaw_token() == "sess_abc123"
    assert cfg.resolve_openclaw_base_url() == "http://127.0.0.1:9000/v1"
    assert cfg.resolve_openclaw_model() == "openai-codex/gpt-5.5"
