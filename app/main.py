from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .bootstrap import ensure_default_admin, init_db
from .config import settings
from .database import SessionLocal, get_db
from .deps import _LoginRedirect, current_user
from .models import BookProject, User, UserSettings
from .schemas import ProjectCreate
from .security import verify_password
from .services.book_pipeline import book_pipeline_service
from .services.exporter import export_service
from .session import SESSION_COOKIE, sign_session

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
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
    from .models import BOOK_WRITER_DEFAULT_PROMPT
    return templates.TemplateResponse(
        request,
        "project_new.html",
        {"user": user, "default_system_prompt": BOOK_WRITER_DEFAULT_PROMPT},
    )


@app.post("/projects")
def create_project(
    request: Request,
    title: str = Form(...),
    concept: str = Form(...),
    inspiration_sources: str = Form(""),
    target_pages: int = Form(20),
    target_words: int = Form(5000),
    tone_preferences: str = Form("Dłuższe, naturalne zdania, ludzki styl."),
    language: str = Form("pl"),
    custom_system_prompt: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    payload = ProjectCreate(
        title=title,
        concept=concept,
        inspiration_sources=inspiration_sources,
        target_pages=target_pages,
        target_words=target_words,
        tone_preferences=tone_preferences,
        language=language,
        custom_system_prompt=custom_system_prompt,
    )
    project = BookProject(owner_id=user.id, **payload.model_dump())
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
    project = _project_or_404(project_id, user, db)
    metrics = {
        "draft_words": len((project.manuscript_text or "").split()),
        "edited_words": len((project.edited_text or "").split()),
        "outline_words": len((project.outline_text or "").split()),
    }
    steps = _step_status(project)
    providers = _build_providers_status(user, db)
    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "user": user,
            "project": project,
            "metrics": metrics,
            "steps": steps,
            "providers": providers,
        },
    )


@app.post("/projects/{project_id}/save")
def save_project_sections(
    project_id: int,
    outline_text: str = Form(""),
    chapter_prompts: str = Form(""),
    manuscript_text: str = Form(""),
    edited_text: str = Form(""),
    seo_description: str = Form(""),
    cover_brief: str = Form(""),
    publish_checklist: str = Form(""),
    custom_system_prompt: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    project.outline_text = outline_text
    project.chapter_prompts = chapter_prompts
    project.manuscript_text = manuscript_text
    project.edited_text = edited_text
    project.seo_description = seo_description
    project.cover_brief = cover_brief
    project.publish_checklist = publish_checklist
    project.custom_system_prompt = custom_system_prompt
    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}?saved=1", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/projects/{project_id}/run")
def run_project(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    user_settings = _get_user_settings(user, db)
    project.status = "running"
    db.commit()
    project = book_pipeline_service.run_full_pipeline(project, user_settings)
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
    project = _project_or_404(project_id, user, db)
    steps = _step_status(project)
    target = next((step for step in steps if step["key"] == step_name), None)
    if not target:
        raise HTTPException(status_code=404, detail="Unknown step")
    if not target["unlocked"]:
        raise HTTPException(status_code=400, detail="Previous step is incomplete")
    user_settings = _get_user_settings(user, db)
    project = book_pipeline_service.run_step(project, step_name, user_settings)
    db.add(project)
    db.commit()
    return RedirectResponse(
        url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER
    )


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


# ---------------------------------------------------------------- export

@app.get("/projects/{project_id}/export/docx")
def export_docx(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = _project_or_404(project_id, user, db)
    content = export_service.build_docx(project)
    safe_name = "".join(c for c in project.title if c.isalnum() or c in " -_")[:60]
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
    safe_name = "".join(c for c in project.title if c.isalnum() or c in " -_")[:60]
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
        {"user": user, "s": user_settings, "saved": request.query_params.get("saved")},
    )


@app.post("/settings")
def save_settings(
    request: Request,
    lm_studio_base_url: str = Form(""),
    lm_studio_api_key: str = Form(""),
    lm_studio_model: str = Form(""),
    google_api_key: str = Form(""),
    google_model: str = Form(""),
    openrouter_api_key: str = Form(""),
    openrouter_model: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    user_settings = _get_user_settings(user, db)
    if user_settings is None:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)

    user_settings.lm_studio_base_url = lm_studio_base_url.strip()
    user_settings.lm_studio_api_key = lm_studio_api_key.strip()
    user_settings.lm_studio_model = lm_studio_model.strip()
    user_settings.google_api_key = google_api_key.strip()
    user_settings.google_model = google_model.strip()
    user_settings.openrouter_api_key = openrouter_api_key.strip()
    user_settings.openrouter_model = openrouter_model.strip()
    db.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/settings/test")
async def test_connection(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """AJAX endpoint — tests LM Studio connection, returns JSON."""
    from .services.llm import LLMConfig, LLMError, llm_service
    user_settings = _get_user_settings(user, db)
    from .services.book_pipeline import _build_cfg
    cfg = _build_cfg(user_settings)
    try:
        text, provider = llm_service.generate(
            "You are a test assistant.",
            "Reply with exactly: OK",
            cfg,
        )
        return {"ok": True, "provider": provider, "response": text[:100]}
    except LLMError as e:
        return {"ok": False, "error": str(e)[:300]}


# ---------------------------------------------------------------- health

@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


# ---------------------------------------------------------------- helpers

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


def _build_providers_status(user: User, db: Session) -> list[dict]:
    us = _get_user_settings(user, db)
    lm_key = (us.lm_studio_api_key if us else "") or settings.lm_studio_api_key
    g_key = (us.google_api_key if us else "") or settings.google_api_key
    or_key = (us.openrouter_api_key if us else "") or settings.openrouter_api_key
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
        "cover": has(project.cover_brief),
        "publish": has(project.publish_checklist),
    }
    labels = {
        "outline": "1. Konspekt",
        "prompts": "2. Prompty rozdziałów",
        "draft": "3. Draft książki",
        "edit": "4. Redakcja",
        "seo": "5. SEO Amazon",
        "cover": "6. Brief okładki",
        "publish": "7. Checklista publikacji",
    }
    descriptions = {
        "outline": "System układa hierarchiczną strukturę książki z rozdziałami.",
        "prompts": "Na bazie konspektu tworzymy precyzyjne prompty do każdego rozdziału.",
        "draft": "Pełny draft książki, rozdział po rozdziale, dla zachowania ciągłości.",
        "edit": "Redakcja i korekta stylu — flow, spójność, usuwanie powtórzeń.",
        "seo": "Przekonujący opis sprzedażowy i słowa kluczowe na Amazon.",
        "cover": "Brief okładki z koncepcją, typografią, kolorami i promptami AI.",
        "publish": "Kompletna checklista publikacji krok po kroku na Amazon KDP.",
    }
    order = ["outline", "prompts", "draft", "edit", "seo", "cover", "publish"]
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
