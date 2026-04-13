from __future__ import annotations

import json
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .bootstrap import ensure_default_admin, init_db, migrate_db
from .config import settings
from .database import SessionLocal, get_db
from .deps import _LoginRedirect, current_user
from .models import (
    BOOK_WRITER_DEFAULT_PROMPTS,
    BookProject,
    User,
    UserSettings,
    WRITING_STYLE_PRESETS,
    deserialize_writing_styles,
    get_book_writer_default_prompt,
    primary_writing_style,
    serialize_writing_styles,
    writing_style_labels,
)
from .schemas import ProjectCreate
from .security import verify_password
from .services.book_pipeline import book_pipeline_service
from .services.exporter import export_service
from .services.human_check import HumanCheckConfig, HumanCheckError, human_check_service
from .session import SESSION_COOKIE, sign_session

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    migrate_db()
    db = SessionLocal()
    try:
        ensure_default_admin(db)
        yield
    finally:
        db.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------- exception handlers

@app.exception_handler(_LoginRedirect)
async def login_redirect_handler(request: Request, exc: _LoginRedirect):
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------- auth routes

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Nieprawidłowy email lub hasło."}, status_code=400
        )
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(SESSION_COOKIE, sign_session(user.id), httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------- dashboard

@app.get("/", response_class=HTMLResponse)
def root(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    projects = (
        db.query(BookProject)
        .filter(BookProject.owner_id == user.id)
        .order_by(BookProject.updated_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request, "dashboard.html", {"user": user, "projects": projects}
    )


# ---------------------------------------------------------------- project CRUD

@app.get("/projects/new", response_class=HTMLResponse)
def new_project_page(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(
        request,
        "project_new.html",
        {
            "user": user,
            "default_system_prompt": get_book_writer_default_prompt("pl"),
            "default_system_prompts": BOOK_WRITER_DEFAULT_PROMPTS,
            "writing_style_options": WRITING_STYLE_PRESETS,
        },
    )


@app.post("/projects")
def create_project(
    request: Request,
    title: str = Form(...),
    concept: str = Form(...),
    inspiration_sources: str = Form(""),
    target_chapters: int = Form(10),
    target_words: int = Form(5000),
    tone_preferences: str = Form("Dłuższe, naturalne zdania, ludzki styl."),
    language: str = Form("pl"),
    custom_system_prompt: str = Form(""),
    writing_style: str = Form(""),
    writing_styles: list[str] = Form([]),
    target_market: str = Form("en-US"),
    author_bio: str = Form(""),
    emotions_to_convey: str = Form(""),
    knowledge_to_share: str = Form(""),
    target_audience: str = Form(""),
    pdf_font_family: str = Form("Georgia"),
    pdf_trim_size: str = Form("6x9"),
    pdf_heading_size: int = Form(22),
    pdf_body_size: int = Form(11),
    pdf_book_title_size: int = Form(30),
    pdf_chapter_title_size: int = Form(23),
    pdf_subchapter_title_size: int = Form(17),
    pdf_title_override: str = Form(""),
    pdf_subtitle: str = Form(""),
    pdf_author_name: str = Form(""),
    pdf_include_toc: str = Form("1"),
    pdf_show_page_numbers: str = Form("1"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    payload = ProjectCreate(
        title=title,
        concept=concept,
        inspiration_sources=inspiration_sources,
        target_chapters=target_chapters,
        target_words=target_words,
        tone_preferences=tone_preferences,
        language=language,
        custom_system_prompt=custom_system_prompt,
        writing_style=primary_writing_style("", writing_style),
        writing_styles=deserialize_writing_styles(serialize_writing_styles(writing_styles, writing_style)),
        target_market=target_market,
        author_bio=author_bio,
        emotions_to_convey=emotions_to_convey,
        knowledge_to_share=knowledge_to_share,
        target_audience=target_audience,
        pdf_font_family=pdf_font_family,
        pdf_trim_size=pdf_trim_size,
        pdf_heading_size=pdf_heading_size,
        pdf_body_size=pdf_body_size,
        pdf_book_title_size=pdf_book_title_size,
        pdf_chapter_title_size=pdf_chapter_title_size,
        pdf_subchapter_title_size=pdf_subchapter_title_size,
        pdf_title_override=pdf_title_override,
        pdf_subtitle=pdf_subtitle,
        pdf_author_name=pdf_author_name,
        pdf_include_toc=_as_bool(pdf_include_toc, default=True),
        pdf_show_page_numbers=_as_bool(pdf_show_page_numbers, default=True),
    )
    data = payload.model_dump()
    data["writing_styles"] = serialize_writing_styles(data["writing_styles"], data["writing_style"])
    data["writing_style"] = primary_writing_style(data["writing_styles"], data["writing_style"])
    project = BookProject(owner_id=user.id, **data)
    db.add(project)
    db.commit()
    db.refresh(project)
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(
    request: Request,
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    import json
    project = _project_or_404(project_id, user, db)
    metrics = {
        "draft_words": len((project.manuscript_text or "").split()),
        "edited_words": len((project.edited_text or "").split()),
        "outline_words": len((project.outline_text or "").split()),
    }
    steps = _step_status(project)
    providers = _build_providers_status(user, db)
    project_style_labels = writing_style_labels(project.writing_styles, project.writing_style)
    translations: dict = {}
    human_check: dict = {}
    if project.translations:
        try:
            translations = json.loads(project.translations)
        except Exception:
            translations = {}
    if project.human_check_result:
        try:
            human_check = json.loads(project.human_check_result)
        except Exception:
            human_check = {}
    active_tab = request.query_params.get("tab", "pipeline")
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "user": user,
            "project": project,
            "metrics": metrics,
            "steps": steps,
            "providers": providers,
            "translations": translations,
            "human_check": human_check,
            "active_tab": active_tab,
            "llm_routing_label": _llm_routing_label(_get_user_settings(user, db)),
            "default_system_prompt": get_book_writer_default_prompt(project.language),
            "human_check_error": request.query_params.get("human_check_error", ""),
            "human_check_notice": request.query_params.get("human_check_notice", ""),
            "writing_style_options": WRITING_STYLE_PRESETS,
            "project_writing_styles": deserialize_writing_styles(project.writing_styles, project.writing_style),
            "project_writing_style_labels": project_style_labels,
        },
    )


@app.post("/projects/{project_id}/save")
def save_project_sections(
    project_id: int,
    # Metadata fields
    title: str = Form(""),
    concept: str = Form(""),
    language: str = Form(""),
    target_market: str = Form(""),
    writing_style: str = Form(""),
    writing_styles: list[str] = Form([]),
    author_bio: str = Form(""),
    target_audience: str = Form(""),
    tone_preferences: str = Form(""),
    emotions_to_convey: str = Form(""),
    knowledge_to_share: str = Form(""),
    target_chapters: int = Form(0),
    target_words: int = Form(0),
    pdf_font_family: str = Form(""),
    pdf_trim_size: str = Form(""),
    pdf_heading_size: int = Form(0),
    pdf_body_size: int = Form(0),
    pdf_book_title_size: int = Form(0),
    pdf_chapter_title_size: int = Form(0),
    pdf_subchapter_title_size: int = Form(0),
    pdf_title_override: str = Form(""),
    pdf_subtitle: str = Form(""),
    pdf_author_name: str = Form(""),
    pdf_include_toc: str = Form(""),
    pdf_show_page_numbers: str = Form(""),
    # Content fields
    outline_text: str = Form(""),
    chapter_prompts: str = Form(""),
    manuscript_text: str = Form(""),
    edited_text: str = Form(""),
    seo_description: str = Form(""),
    amazon_keywords: str = Form(""),
    catalog_tree: str = Form(""),
    cover_brief: str = Form(""),
    publish_checklist: str = Form(""),
    custom_system_prompt: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    # Update metadata only if non-empty values were submitted
    if title.strip():
        project.title = title.strip()
    if concept.strip():
        project.concept = concept.strip()
    if language.strip():
        project.language = language.strip()
    if target_market.strip():
        project.target_market = target_market.strip()
    selected_styles = deserialize_writing_styles(serialize_writing_styles(writing_styles, writing_style))
    project.writing_styles = serialize_writing_styles(selected_styles)
    project.writing_style = primary_writing_style(project.writing_styles)
    if author_bio.strip():
        project.author_bio = author_bio.strip()
    if target_audience.strip():
        project.target_audience = target_audience.strip()
    if tone_preferences.strip():
        project.tone_preferences = tone_preferences.strip()
    if emotions_to_convey.strip():
        project.emotions_to_convey = emotions_to_convey.strip()
    if knowledge_to_share.strip():
        project.knowledge_to_share = knowledge_to_share.strip()
    if target_chapters > 0:
        project.target_chapters = target_chapters
    if target_words > 0:
        project.target_words = target_words
    if pdf_font_family.strip():
        project.pdf_font_family = pdf_font_family.strip()
    if pdf_trim_size.strip():
        project.pdf_trim_size = pdf_trim_size.strip()
    if pdf_heading_size > 0:
        project.pdf_heading_size = pdf_heading_size
    if pdf_body_size > 0:
        project.pdf_body_size = pdf_body_size
    if pdf_book_title_size > 0:
        project.pdf_book_title_size = pdf_book_title_size
    if pdf_chapter_title_size > 0:
        project.pdf_chapter_title_size = pdf_chapter_title_size
    if pdf_subchapter_title_size > 0:
        project.pdf_subchapter_title_size = pdf_subchapter_title_size
    project.pdf_title_override = pdf_title_override.strip()
    project.pdf_subtitle = pdf_subtitle.strip()
    project.pdf_author_name = pdf_author_name.strip()
    project.pdf_include_toc = _as_bool(pdf_include_toc, default=False)
    project.pdf_show_page_numbers = _as_bool(pdf_show_page_numbers, default=False)
    # Content fields (always overwrite — can be cleared by user)
    project.outline_text = outline_text
    project.chapter_prompts = chapter_prompts
    project.manuscript_text = manuscript_text
    project.edited_text = edited_text
    project.seo_description = seo_description
    project.amazon_keywords = amazon_keywords
    project.catalog_tree = catalog_tree
    project.cover_brief = cover_brief
    project.publish_checklist = publish_checklist
    project.custom_system_prompt = custom_system_prompt
    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}?saved=1&tab=editor", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/run")
def run_project(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from .services.book_pipeline import clear_progress, set_progress
    project = _project_or_404(project_id, user, db)
    user_settings = _get_user_settings(user, db)
    project.status = "running"
    db.commit()

    def _on_progress(msg: str, chapter: int = 0, total: int = 0):
        set_progress(project_id, step="run_all", msg=msg, chapter=chapter, total=total)

    try:
        project = book_pipeline_service.run_full_pipeline(project, user_settings, on_progress=_on_progress)
    finally:
        clear_progress(project_id)

    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/steps/{step_name}")
def run_project_step(
    step_name: str,
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from .services.book_pipeline import clear_progress, set_progress
    project = _project_or_404(project_id, user, db)
    steps = _step_status(project)
    target = next((step for step in steps if step["key"] == step_name), None)
    if not target:
        raise HTTPException(status_code=404, detail="Unknown step")
    if not target["unlocked"]:
        raise HTTPException(status_code=400, detail="Previous step is incomplete")
    user_settings = _get_user_settings(user, db)

    def _on_progress(msg: str, chapter: int = 0, total: int = 0):
        set_progress(project_id, step=step_name, msg=msg, chapter=chapter, total=total)

    _on_progress(f"Uruchamiam krok: {step_name}...")
    try:
        project = book_pipeline_service.run_step(project, step_name, user_settings, on_progress=_on_progress)
    finally:
        clear_progress(project_id)

    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/projects/{project_id}/progress")
def get_project_progress(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Polling endpoint — returns current generation progress for the project."""
    from .services.book_pipeline import get_progress
    _project_or_404(project_id, user, db)  # auth check only
    data = get_progress(project_id)
    if data is None:
        return {"active": False}
    return {"active": True, **data}


@app.post("/projects/{project_id}/ideas")
def generate_ideas(
    project_id: int,
    niche: str = Form(...),
    notes: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    user_settings = _get_user_settings(user, db)
    ideas, provider = book_pipeline_service.generate_ideas(niche, notes, user_settings)
    project.idea_research = ideas
    project.llm_provider_used = provider
    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}#research", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/translate")
def translate_project(
    project_id: int,
    target_lang: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Generate localized SEO pack (SEO description + keywords + catalog) for DE or ES."""
    import json
    project = _project_or_404(project_id, user, db)
    user_settings = _get_user_settings(user, db)
    result = book_pipeline_service.generate_translation(project, target_lang, user_settings)

    existing: dict = {}
    if project.translations:
        try:
            existing = json.loads(project.translations)
        except Exception:
            existing = {}
    existing[target_lang] = result
    project.translations = json.dumps(existing, ensure_ascii=False)
    project.llm_provider_used = result.get("lang", target_lang)
    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}?tab=translations&translated={target_lang}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/projects/{project_id}/human-check")
def run_human_check(
    project_id: int,
    source: str = Form("edited"),
    custom_text: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    user_settings = _get_user_settings(user, db)
    text = _human_check_text_for_source(project, source, custom_text)
    cfg = HumanCheckConfig(
        email=(user_settings.copyleaks_email if user_settings else "") or "",
        api_key=(user_settings.copyleaks_api_key if user_settings else "") or "",
    )
    try:
        result = human_check_service.analyze_text(text, language=project.language, cfg=cfg)
    except HumanCheckError as exc:
        return RedirectResponse(
            url=f"/projects/{project.id}?tab=humancheck&human_check_error={_url_query_escape(str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    result["source"] = source
    project.human_check_result = json.dumps(result, ensure_ascii=False)
    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}?tab=humancheck&human_check_notice=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------- export

@app.get("/projects/{project_id}/export/docx")
def export_docx(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    content = export_service.build_docx(project)
    safe_name = _safe_ascii_filename(project.title)
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}.docx"'}
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.get("/projects/{project_id}/export/pdf")
def export_pdf(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    content = export_service.build_pdf(project)
    safe_name = _safe_ascii_filename(project.title)
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'}
    return Response(content=content, media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------- settings

@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    user_settings = _get_user_settings(user, db)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "s": user_settings,
            "saved": request.query_params.get("saved"),
            "llm_routing_label": _llm_routing_label(user_settings),
        },
    )


_ALLOWED_PREFERRED_LLM = frozenset({"auto", "lm_studio", "google_gemini", "openrouter"})


@app.post("/settings")
def save_settings(
    request: Request,
    preferred_llm_provider: str = Form("auto"),
    lm_studio_base_url: str = Form(""),
    lm_studio_api_key: str = Form(""),
    lm_studio_model: str = Form(""),
    google_api_key: str = Form(""),
    google_model: str = Form(""),
    openrouter_api_key: str = Form(""),
    openrouter_model: str = Form(""),
    copyleaks_email: str = Form(""),
    copyleaks_api_key: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    user_settings = _get_user_settings(user, db)
    if user_settings is None:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)

    raw_pref = (preferred_llm_provider or "auto").strip().lower()
    user_settings.preferred_llm_provider = (
        raw_pref if raw_pref in _ALLOWED_PREFERRED_LLM else "auto"
    )
    user_settings.lm_studio_base_url = lm_studio_base_url.strip()
    user_settings.lm_studio_api_key = lm_studio_api_key.strip()
    user_settings.lm_studio_model = lm_studio_model.strip()
    user_settings.google_api_key = google_api_key.strip()
    user_settings.google_model = google_model.strip()
    user_settings.openrouter_api_key = openrouter_api_key.strip()
    user_settings.openrouter_model = openrouter_model.strip()
    user_settings.copyleaks_email = copyleaks_email.strip()
    user_settings.copyleaks_api_key = copyleaks_api_key.strip()
    db.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/settings/test")
async def test_connection(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """AJAX: tests all providers in priority order, returns JSON."""
    from .services.llm import LLMError, llm_service
    from .services.book_pipeline import _build_cfg
    user_settings = _get_user_settings(user, db)
    cfg = _build_cfg(user_settings)
    try:
        text, provider = llm_service.generate(
            "[Rola] Test integracji API.\n[Wyjście] Dokładnie jedno słowo: OK",
            "Wykonaj test. Odpowiedz dokładnie: OK",
            cfg,
        )
        return {"ok": True, "provider": provider, "response": text[:100]}
    except LLMError as e:
        return {"ok": False, "error": str(e)[:500]}


@app.post("/settings/test_provider")
async def test_single_provider(
    request: Request,
    provider: str = Form(...),
    api_key: str = Form(""),
    model: str = Form(""),
    base_url: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """AJAX: test a specific provider using supplied (unsaved) credentials. Returns JSON."""
    from .services.llm import LLMConfig, LLMError, llm_service

    SYS = "[Rola] Test integracji API.\n[Wyjście] Dokładnie jedno słowo: OK"
    USR = "Wykonaj test. Odpowiedz dokładnie: OK"

    key = api_key.strip()
    mdl = model.strip()
    url = base_url.strip()

    # Fall back to saved / env values when fields are blank
    user_settings = _get_user_settings(user, db)
    from .services.book_pipeline import _build_cfg
    saved_cfg = _build_cfg(user_settings)

    try:
        if provider == "lm_studio":
            cfg = LLMConfig(
                lm_studio_base_url=url or saved_cfg.resolve_lm_url(),
                lm_studio_api_key=key or saved_cfg.resolve_lm_key(),
                lm_studio_model=mdl or saved_cfg.resolve_lm_model(),
            )
            text = llm_service._call_lm_studio(SYS, USR, cfg)
            return {"ok": True, "provider": "lm_studio", "response": text[:100]}

        elif provider == "google":
            cfg = LLMConfig(
                google_api_key=key or saved_cfg.resolve_google_key(),
                google_model=mdl or saved_cfg.resolve_google_model(),
            )
            text = llm_service._call_google_gemini(SYS, USR, cfg)
            return {"ok": True, "provider": "google_gemini", "response": text[:100]}

        elif provider == "openrouter":
            cfg = LLMConfig(
                openrouter_api_key=key or saved_cfg.resolve_openrouter_key(),
                openrouter_model=mdl or saved_cfg.resolve_openrouter_model(),
            )
            text = llm_service._call_openrouter(SYS, USR, cfg)
            return {"ok": True, "provider": "openrouter", "response": text[:100]}

        elif provider == "copyleaks":
            hc_cfg = HumanCheckConfig(
                email=key or (user_settings.copyleaks_email if user_settings else "") or settings.copyleaks_email,
                api_key=mdl or (user_settings.copyleaks_api_key if user_settings else "") or settings.copyleaks_api_key,
            )
            result = human_check_service.analyze_text(
                "This is a short human-written sample paragraph designed to test the AI detector integration. "
                "It contains enough content to pass the minimum length requirements and should return a valid score.",
                language="en",
                cfg=hc_cfg,
            )
            return {
                "ok": True,
                "provider": "copyleaks",
                "response": f"human={result['human_score']:.0%}, ai={result['ai_score']:.0%}",
            }

        else:
            return {"ok": False, "error": f"Nieznany provider: {provider}"}

    except LLMError as e:
        return {"ok": False, "error": str(e)[:500]}
    except Exception as e:
        return {"ok": False, "error": f"Nieoczekiwany błąd: {str(e)[:400]}"}


# ---------------------------------------------------------------- health

@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


# ---------------------------------------------------------------- helpers

def _safe_ascii_filename(title: str, max_len: int = 60) -> str:
    """
    Return a filename-safe ASCII string from a title.
    Polish / accented chars are NFKD-decomposed then stripped to ASCII;
    spaces become underscores; the result is safe for HTTP headers (Latin-1).
    """
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in ascii_only)
    safe = safe.strip("_")
    if not safe:
        safe = "book"
    return safe[:max_len]


def _as_bool(value: str | None, *, default: bool) -> bool:
    raw = (value or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _url_query_escape(value: str) -> str:
    return quote_plus(value)


def _human_check_text_for_source(project: BookProject, source: str, custom_text: str) -> str:
    src = (source or "edited").strip().lower()
    if src == "custom":
        text = custom_text
    elif src == "seo":
        text = project.seo_description or ""
    elif src == "manuscript":
        text = project.manuscript_text or ""
    else:
        text = project.edited_text or project.manuscript_text or ""
    text = (text or "").strip()
    if not text:
        raise HumanCheckError("No text available for human check. Add manuscript text first.")
    return text


def _project_or_404(project_id: int, user: User, db: Session) -> BookProject:
    project = (
        db.query(BookProject)
        .filter(BookProject.id == project_id, BookProject.owner_id == user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_user_settings(user: User, db: Session) -> UserSettings | None:
    return db.query(UserSettings).filter(UserSettings.user_id == user.id).first()


def _llm_routing_label(user_settings: UserSettings | None) -> str:
    p = (
        (user_settings.preferred_llm_provider if user_settings else "")
        or settings.preferred_llm_provider
        or "auto"
    )
    p = (p or "auto").strip().lower()
    if p not in _ALLOWED_PREFERRED_LLM:
        p = "auto"
    return {
        "auto": "Automatycznie: LM Studio → Gemini → OpenRouter",
        "lm_studio": "Tylko LM Studio (bez przełączania na inne API)",
        "google_gemini": "Tylko Google Gemini",
        "openrouter": "Tylko OpenRouter",
    }[p]


def _build_providers_status(user: User, db: Session) -> list[dict]:
    us = _get_user_settings(user, db)
    lm_key = (us.lm_studio_api_key if us else "") or settings.lm_studio_api_key
    g_key = (us.google_api_key if us else "") or settings.google_api_key
    or_key = (us.openrouter_api_key if us else "") or settings.openrouter_api_key
    cp_email = (us.copyleaks_email if us else "") or settings.copyleaks_email
    cp_key = (us.copyleaks_api_key if us else "") or settings.copyleaks_api_key
    lm_url = (us.lm_studio_base_url if us else "") or settings.lm_studio_base_url

    return [
        {
            "name": "LM Studio",
            "icon": "cpu",
            "summary": "Lokalny model, najtańsza opcja. Działa z Twoją Gemmą 3 27B.",
            "status": "configured" if lm_url else "missing",
            "detail": lm_url or "brak URL",
        },
        {
            "name": "Google Gemini",
            "icon": "zap",
            "summary": "Oficjalne API Google. Główny zewnętrzny fallback.",
            "status": "configured" if g_key else "missing",
            "detail": "Klucz skonfigurowany" if g_key else "Brak klucza API",
        },
        {
            "name": "OpenRouter",
            "icon": "globe",
            "summary": "Router darmowych modeli. Ostatni fallback bez GPU.",
            "status": "configured" if or_key else "missing",
            "detail": "Klucz skonfigurowany" if or_key else "Brak klucza API",
        },
        {
            "name": "Human Check",
            "icon": "scan-search",
            "summary": "Detekcja AI/human dla gotowego tekstu książki.",
            "status": "configured" if (cp_email and cp_key) else "missing",
            "detail": "Copyleaks skonfigurowany" if (cp_email and cp_key) else "Brak email/API key Copyleaks",
        },
    ]


def _step_status(project: BookProject) -> list[dict]:
    # Safe strip — handles None from DB
    def has(val) -> bool:
        return bool((val or "").strip())

    completed = {
        "outline": has(project.outline_text),
        "prompts": has(project.chapter_prompts),
        "draft": has(project.manuscript_text),
        "edit": has(project.edited_text),
        "seo": has(project.seo_description),
        "keywords": has(project.amazon_keywords),
        "catalog": has(project.catalog_tree),
        "cover": has(project.cover_brief),
        "publish": has(project.publish_checklist),
    }
    labels = {
        "outline": "1. Konspekt",
        "prompts": "2. Prompty rozdziałów",
        "draft": "3. Draft książki",
        "edit": "4. Redakcja",
        "seo": "5. SEO Amazon (2500 zn.)",
        "keywords": "6. 7 Keywords Amazon",
        "catalog": "7. Drzewo katalogu + 3 ścieżki",
        "cover": "8. Brief okładki",
        "publish": "9. Checklista publikacji",
    }
    descriptions = {
        "outline": "System układa hierarchiczną strukturę książki z rozdziałami.",
        "prompts": "Na bazie konspektu tworzymy precyzyjne prompty do każdego rozdziału.",
        "draft": "Pełny draft książki, rozdział po rozdziale, dla zachowania ciągłości.",
        "edit": "Redakcja i korekta stylu — flow, spójność, usuwanie powtórzeń.",
        "seo": "Opis sprzedażowy max 2500 znaków z mocnym hookiem, dostosowany do rynku.",
        "keywords": "7 fraz kluczowych Amazon odpowiednich dla wybranego rynku (en/de/es).",
        "catalog": "Drzewo kategorii Amazon + 3 idealne ścieżki przeglądania dla rynku docelowego.",
        "cover": "Brief okładki z koncepcją, typografią, kolorami i promptami AI.",
        "publish": "Kompletna checklista publikacji krok po kroku na Amazon KDP.",
    }
    order = ["outline", "prompts", "draft", "edit", "seo", "keywords", "catalog", "cover", "publish"]
    steps = []
    previous_complete = True
    for key in order:
        unlocked = previous_complete
        steps.append(
            {
                "key": key,
                "label": labels[key],
                "description": descriptions[key],
                "completed": completed[key],
                "unlocked": unlocked,
            }
        )
        previous_complete = previous_complete and completed[key]
    return steps
