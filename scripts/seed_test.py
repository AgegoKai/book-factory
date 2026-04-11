"""
Szybki seed projektu testowego do testów generacji książki.
Tworzy miniaturowy projekt (2 strony, 500 słów) i opcjonalnie
uruchamia jeden krok pipeline, żeby sprawdzić czy provider działa.

Użycie:
    python scripts/seed_test.py              # tylko tworzy projekt
    python scripts/seed_test.py --run outline  # tworzy + uruchamia outline
    python scripts/seed_test.py --run all      # tworzy + pełny pipeline
    python scripts/seed_test.py --provider openrouter  # wymusza provider

Zmienne środowiskowe (opcjonalne, nadpisują .env):
    OPENROUTER_API_KEY, OPENROUTER_MODEL, GOOGLE_API_KEY itd.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Seed a test book project")
    parser.add_argument("--run", default="", help="Step to run: outline|prompts|draft|edit|seo|all")
    parser.add_argument("--provider", default="", help="Force provider: lm_studio|google_gemini|openrouter")
    parser.add_argument("--clean", action="store_true", help="Delete old TEST projects first")
    args = parser.parse_args()

    # Bootstrap app (creates tables, migrates)
    from app.bootstrap import ensure_default_admin, init_db, migrate_db
    from app.config import settings
    from app.database import SessionLocal
    from app.models import BookProject, User, UserSettings

    print(f"DB: {settings.database_url}")
    init_db()
    migrate_db()

    db = SessionLocal()
    ensure_default_admin(db)

    # Get or create admin user
    admin = db.query(User).filter(User.email == settings.default_admin_email).first()
    if not admin:
        print("ERROR: admin user not found after ensure_default_admin")
        sys.exit(1)
    print(f"User: {admin.email}")

    # Clean old test projects
    if args.clean:
        old = db.query(BookProject).filter(
            BookProject.owner_id == admin.id,
            BookProject.title.like("[TEST]%"),
        ).all()
        for p in old:
            db.delete(p)
        db.commit()
        print(f"Deleted {len(old)} old TEST projects")

    # Create minimal test project
    project = BookProject(
        owner_id=admin.id,
        title="[TEST] Pszczoły Miodne — Szybki Test",
        concept=(
            "Krótki poradnik o hodowli pszczół dla początkujących. "
            "Opisuje podstawy: rodzaje ula, pory roku, zbiór miodu."
        ),
        target_pages=2,
        target_words=500,
        language="pl",
        target_market="pl-PL",
        tone_preferences="Prosty, przyjazny, krótkie zdania.",
        writing_style="poradnikowy",
        target_audience="Osoby zaczynające hodowlę pszczół",
        emotions_to_convey="ciekawość i zachęta",
        knowledge_to_share="podstawy pszczelarstwa",
        author_bio="Piotr Pasieka — pszczelarz z 10-letnim doświadczeniem.",
        inspiration_sources="",
        custom_system_prompt="",
        status="draft",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    print(f"\n✓ Projekt testowy utworzony: ID={project.id} — '{project.title}'")
    print(f"  URL: http://localhost:8008/projects/{project.id}")

    if not args.run:
        print("\nAby uruchomić krok, dodaj --run outline (lub --run all)")
        db.close()
        return

    # Build LLM config
    from app.services.book_pipeline import BookPipelineService, _build_cfg
    from app.services.llm import LLMConfig, LLMError

    us = db.query(UserSettings).filter(UserSettings.user_id == admin.id).first()
    cfg = _build_cfg(us)
    if args.provider:
        cfg.preferred_llm_provider = args.provider
        print(f"  Provider wymuszony: {args.provider}")
    else:
        print(f"  Provider: {cfg.resolve_preferred_provider()}")

    # Quick connection test first
    from app.services.llm import llm_service
    print("\n→ Test połączenia...")
    t0 = time.time()
    try:
        text, prov = llm_service.generate(
            "Odpowiedz jednym słowem: OK",
            "OK",
            cfg,
        )
        print(f"  ✓ Provider: {prov} ({time.time()-t0:.1f}s) — odpowiedź: '{text[:80]}'")
    except LLMError as e:
        print(f"  ✕ Błąd połączenia: {e}")
        print("  Nie kontynuuję bez działającego providera.")
        db.close()
        sys.exit(1)

    # Run requested step(s)
    svc = BookPipelineService()
    steps = (
        ["outline", "prompts", "draft", "edit", "seo", "keywords", "catalog", "cover", "publish"]
        if args.run == "all"
        else [args.run]
    )

    for step in steps:
        if step not in svc.step_order:
            print(f"  ! Nieznany krok: {step}. Dostępne: {svc.step_order}")
            continue
        print(f"\n→ Krok: {step}...")
        t0 = time.time()
        try:
            def on_progress(msg, ch=0, tot=0):
                frac = f" [{ch}/{tot}]" if tot > 1 else ""
                print(f"   {msg}{frac}", end="\r", flush=True)

            project = svc.run_step(project, step, us, on_progress=on_progress)
            db.add(project)
            db.commit()
            print(f"  ✓ {step} — {time.time()-t0:.1f}s (provider: {project.llm_provider_used})")
        except (LLMError, ValueError) as e:
            print(f"  ✕ {step} błąd: {e}")
            break

    print(f"\n✓ Gotowe. Projekt: http://localhost:8008/projects/{project.id}")
    db.close()


if __name__ == "__main__":
    main()
