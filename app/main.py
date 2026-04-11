from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .bootstrap import ensure_default_admin, init_db
from .config import settings
from .database import SessionLocal, get_db
from .deps import current_user
from .models import BookProject, User
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


@app.get("/", response_class=HTMLResponse)
def root(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    projects = db.query(BookProject).filter(BookProject.owner_id == user.id).order_by(BookProject.updated_at.desc()).all()
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "projects": projects})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid credentials."}, status_code=400)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(SESSION_COOKIE, sign_session(user.id), httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/projects/new", response_class=HTMLResponse)
def new_project_page(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(request, "project_new.html", {"user": user})


@app.post("/projects")
def create_project(
    request: Request,
    title: str = Form(...),
    concept: str = Form(...),
    inspiration_sources: str = Form(...),
    target_pages: int = Form(20),
    target_words: int = Form(5000),
    tone_preferences: str = Form("Longer, natural sentences with clean pacing."),
    language: str = Form("pl"),
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
    )
    project = BookProject(owner_id=user.id, **payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(project_id, user, db)
    metrics = {
        "draft_words": len((project.manuscript_text or "").split()),
        "edited_words": len((project.edited_text or "").split()),
        "outline_words": len((project.outline_text or "").split()),
    }
    steps = _step_status(project)
    providers = [
        {
            "name": "LM Studio",
            "summary": "Najtańsza opcja, bo lokalna. Działa z Twoją Gemmą 3 27B.",
            "status": "configured" if settings.lm_studio_base_url else "missing",
        },
        {
            "name": "Google Gemini API",
            "summary": "Oficjalne darmowe API testowe. Dobre jako awaryjny provider.",
            "status": "configured" if settings.google_api_key else "missing",
        },
        {
            "name": "OpenRouter free",
            "summary": "Router darmowych modeli, prosty fallback bez lokalnego GPU.",
            "status": "configured" if settings.openrouter_api_key else "missing",
        },
    ]
    return templates.TemplateResponse(request, "project_detail.html", {"user": user, "project": project, "metrics": metrics, "steps": steps, "providers": providers})


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
    db.add(project)
    db.commit()
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/run")
def run_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(project_id, user, db)
    project.status = "running"
    db.commit()
    project = book_pipeline_service.run_full_pipeline(project)
    db.add(project)
    db.commit()
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/steps/{step_name}")
def run_project_step(step_name: str, project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(project_id, user, db)
    steps = _step_status(project)
    target = next((step for step in steps if step["key"] == step_name), None)
    if not target:
        raise HTTPException(status_code=404, detail="Unknown step")
    if not target["unlocked"]:
        raise HTTPException(status_code=400, detail="Previous step is incomplete")
    project = book_pipeline_service.run_step(project, step_name)
    db.add(project)
    db.commit()
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/projects/{project_id}/ideas")
def generate_ideas(project_id: int, niche: str = Form(...), notes: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(project_id, user, db)
    ideas, provider = book_pipeline_service.generate_ideas(niche, notes)
    project.idea_research = ideas
    project.llm_provider_used = provider
    db.add(project)
    db.commit()
    return RedirectResponse(url=f"/projects/{project.id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/projects/{project_id}/export/docx")
def export_docx(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(project_id, user, db)
    content = export_service.build_docx(project)
    headers = {"Content-Disposition": f'attachment; filename="{project.title}.docx"'}
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers=headers)


@app.get("/projects/{project_id}/export/pdf")
def export_pdf(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(project_id, user, db)
    content = export_service.build_pdf(project)
    headers = {"Content-Disposition": f'attachment; filename="{project.title}.pdf"'}
    return Response(content=content, media_type="application/pdf", headers=headers)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


def _project_or_404(project_id: int, user: User, db: Session) -> BookProject:
    project = db.query(BookProject).filter(BookProject.id == project_id, BookProject.owner_id == user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _step_status(project: BookProject) -> list[dict]:
    completed = {
        "outline": bool(project.outline_text.strip()),
        "prompts": bool(project.chapter_prompts.strip()),
        "draft": bool(project.manuscript_text.strip()),
        "edit": bool(project.edited_text.strip()),
        "seo": bool(project.seo_description.strip()),
        "cover": bool(project.cover_brief.strip()),
        "publish": bool(project.publish_checklist.strip()),
    }
    labels = {
        "outline": "1. Konspekt",
        "prompts": "2. Prompty rozdziałów",
        "draft": "3. Draft książki",
        "edit": "4. Redakcja",
        "seo": "5. SEO Amazon",
        "cover": "6. Brief okładki",
        "publish": "7. Checklist publikacji",
    }
    descriptions = {
        "outline": "Najpierw system układa strukturę książki.",
        "prompts": "Dopiero z outline tworzymy prompty do rozdziałów.",
        "draft": "Teraz powstaje pełny draft książki.",
        "edit": "Po draftcie robimy redakcję i poprawiamy styl.",
        "seo": "Dopiero po redakcji piszemy opis sprzedażowy.",
        "cover": "Po SEO system przygotowuje brief na okładkę.",
        "publish": "Na końcu powstaje checklista publikacji na Amazon.",
    }
    order = ["outline", "prompts", "draft", "edit", "seo", "cover", "publish"]
    steps = []
    previous_complete = True
    for key in order:
        unlocked = previous_complete
        steps.append({
            "key": key,
            "label": labels[key],
            "description": descriptions[key],
            "completed": completed[key],
            "unlocked": unlocked,
        })
        previous_complete = previous_complete and completed[key]
    return steps
