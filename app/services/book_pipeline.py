from __future__ import annotations

import re
from textwrap import dedent

from ..models import BookProject, UserSettings
from ..models import BOOK_WRITER_DEFAULT_PROMPT
from .llm import LLMConfig, LLMError, llm_service


def _build_cfg(user_settings: UserSettings | None) -> LLMConfig:
    if not user_settings:
        return LLMConfig()
    return LLMConfig(
        lm_studio_base_url=user_settings.lm_studio_base_url or "",
        lm_studio_api_key=user_settings.lm_studio_api_key or "",
        lm_studio_model=user_settings.lm_studio_model or "",
        google_api_key=user_settings.google_api_key or "",
        google_model=user_settings.google_model or "",
        openrouter_api_key=user_settings.openrouter_api_key or "",
        openrouter_model=user_settings.openrouter_model or "",
    )


class BookPipelineService:
    step_order = ["outline", "prompts", "draft", "edit", "seo", "cover", "publish"]

    def run_full_pipeline(
        self, project: BookProject, user_settings: UserSettings | None = None
    ) -> BookProject:
        cfg = _build_cfg(user_settings)
        self.generate_outline(project, cfg)
        self.generate_prompts(project, cfg)
        self.generate_draft(project, cfg)
        self.generate_edit(project, cfg)
        self.generate_seo(project, cfg)
        self.generate_cover(project, cfg)
        self.generate_publish(project, cfg)
        project.status = "ready"
        return project

    def run_step(
        self,
        project: BookProject,
        step: str,
        user_settings: UserSettings | None = None,
    ) -> BookProject:
        cfg = _build_cfg(user_settings)
        handlers = {
            "outline": self.generate_outline,
            "prompts": self.generate_prompts,
            "draft": self.generate_draft,
            "edit": self.generate_edit,
            "seo": self.generate_seo,
            "cover": self.generate_cover,
            "publish": self.generate_publish,
        }
        if step not in handlers:
            raise ValueError(f"Unknown step: {step}")
        return handlers[step](project, cfg)

    # ------------------------------------------------------------------ steps

    def generate_outline(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        context = self._context(project)
        outline, provider = self._generate(
            "Jesteś doświadczonym ghostwriterem i architektem książek non-fiction. Tworzysz precyzyjne, hierarchiczne konspekty.",
            dedent(f"""
            Stwórz szczegółowy konspekt książki w języku: {project.language}.
            Konspekt musi zawierać: wstęp, {max(5, project.target_pages // 4)} rozdziałów z podrozdziałami, zakończenie.
            Każdy rozdział powinien mieć tytuł i 2-3 zdania opisu zawartości.
            Liczba rozdziałów powinna odpowiadać docelowej liczbie słów: {project.target_words}.

            {context}
            """),
            cfg,
        )
        project.outline_text = outline
        project.llm_provider_used = provider
        project.status = "outline_ready"
        return project

    def generate_prompts(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        context = self._context(project)
        chapter_prompts, provider = self._generate(
            "Tworzysz precyzyjne prompty do pisania rozdziałów długich książek. Każdy prompt musi być konkretny i gotowy do użycia.",
            dedent(f"""
            Na podstawie poniższego konspektu, napisz osobny prompt do napisania każdego rozdziału.
            Format: "ROZDZIAŁ X: [Tytuł]\nPrompt: [treść prompta]"
            Każdy prompt powinien zawierać: główny temat, kluczowe punkty do omówienia, styl narracji.

            KONSPEKT:
            {project.outline_text}

            {context}
            """),
            cfg,
        )
        project.chapter_prompts = chapter_prompts
        project.llm_provider_used = provider
        project.status = "prompts_ready"
        return project

    def generate_draft(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        """Generate draft chapter by chapter to avoid timeout and improve coherence."""
        cfg = cfg or LLMConfig()
        system_prompt = (project.custom_system_prompt or "").strip() or BOOK_WRITER_DEFAULT_PROMPT

        chapters = self._parse_chapters(project.outline_text)
        if not chapters:
            # Fallback: generate as single block if outline not parseable
            manuscript, provider = self._generate(
                system_prompt,
                dedent(f"""
                Napisz pełny draft książki w języku: {project.language}.
                Stosuj styl: {project.tone_preferences}
                Docelowa objętość: {project.target_words} słów.

                KONSPEKT:
                {project.outline_text}

                PROMPTY ROZDZIAŁÓW:
                {project.chapter_prompts}
                """),
                cfg,
            )
            project.manuscript_text = manuscript
            project.llm_provider_used = provider
        else:
            # Chapter-by-chapter generation for coherence and to avoid timeouts
            parts: list[str] = []
            last_provider = "template_fallback"
            context_window = ""  # last ~600 chars of previous chapter for continuity

            for i, chapter_title in enumerate(chapters, 1):
                chapter_prompt = self._get_chapter_prompt(project.chapter_prompts, chapter_title, i)
                continuation = (
                    f"\n\nKontynuacja od: ...{context_window[-600:]}" if context_window else ""
                )
                user_msg = dedent(f"""
                Napisz rozdział dla: "{chapter_title}"
                Język: {project.language}
                Styl: {project.tone_preferences}
                To jest rozdział {i} z {len(chapters)}.{continuation}

                Instrukcje dla tego rozdziału:
                {chapter_prompt}

                Konspekt całości (dla zachowania ciągłości):
                {project.outline_text[:2000]}
                """)

                text, provider = self._generate(system_prompt, user_msg, cfg)
                parts.append(f"\n\n{'=' * 40}\n{chapter_title}\n{'=' * 40}\n\n{text}")
                context_window = text
                last_provider = provider

            project.manuscript_text = "\n".join(parts).strip()
            project.llm_provider_used = last_provider

        project.status = "draft_ready"
        return project

    def generate_edit(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        system_prompt = (project.custom_system_prompt or "").strip() or BOOK_WRITER_DEFAULT_PROMPT
        # Edit in chunks to avoid token limits
        draft = project.manuscript_text or ""
        chunk_size = 8000
        if len(draft) <= chunk_size:
            edited, provider = self._generate(
                system_prompt + "\n\nDodatkowa rola: jesteś teraz redaktorem i korektorem tej książki.",
                dedent(f"""
                Zredaguj poniższy draft: popraw flow, styl, spójność narracyjną, usuń powtórzenia.
                Zachowaj naturalny ludzki głos. Preferencje stylu: {project.tone_preferences}

                DRAFT:
                {draft}
                """),
                cfg,
            )
            project.edited_text = edited
            project.llm_provider_used = provider
        else:
            # Split into chunks and edit each
            chunks = [draft[i:i + chunk_size] for i in range(0, len(draft), chunk_size)]
            edited_parts = []
            last_provider = "template_fallback"
            for chunk in chunks:
                edited_chunk, provider = self._generate(
                    system_prompt + "\n\nDodatkowa rola: jesteś teraz redaktorem i korektorem.",
                    dedent(f"""
                    Zredaguj ten fragment książki: popraw flow, styl, usuń powtórzenia.
                    Preferencje stylu: {project.tone_preferences}

                    FRAGMENT:
                    {chunk}
                    """),
                    cfg,
                )
                edited_parts.append(edited_chunk)
                last_provider = provider
            project.edited_text = "\n\n".join(edited_parts)
            project.llm_provider_used = last_provider

        project.status = "edit_ready"
        return project

    def generate_seo(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        seo, provider = self._generate(
            "Jesteś ekspertem od marketingu książkowego i SEO na Amazon KDP. Piszesz opisy produktów, które sprzedają.",
            dedent(f"""
            Napisz przekonujący opis sprzedażowy na Amazon w języku: {project.language}.
            Zawrzyj: chwytliwy hook (pierwsze zdanie), korzyści dla czytelnika, kluczowe tematy, call-to-action.
            Użyj słów kluczowych. Długość: 400-600 słów.

            TYTUŁ: {project.title}
            STRESZCZENIE: {project.concept}
            FRAGMENT KSIĄŻKI:
            {(project.edited_text or project.manuscript_text)[:6000]}
            """),
            cfg,
        )
        project.seo_description = seo
        project.llm_provider_used = provider
        project.status = "seo_ready"
        return project

    def generate_cover(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        cover, provider = self._generate(
            "Jesteś art directorem specjalizującym się w okładkach książkowych i briefach dla grafików/AI image models.",
            dedent(f"""
            Stwórz kompletny brief okładki dla tej książki. Uwzględnij:
            1. Koncepcja wizualna (główny motyw, nastrój, symbolika)
            2. Typografia (family, weight, rozmiar tytułu i autora)
            3. Paleta kolorów (z kodami hex)
            4. Kompozycja (co na pierwszym planie, tło, układ)
            5. Trzy warianty promptów do generatora AI (Midjourney/DALL-E style)

            TYTUŁ: {project.title}
            OPIS: {project.concept}
            SEO: {project.seo_description[:1000]}
            """),
            cfg,
        )
        project.cover_brief = cover
        project.llm_provider_used = provider
        project.status = "cover_ready"
        return project

    def generate_publish(self, project: BookProject, cfg: LLMConfig | None = None) -> BookProject:
        cfg = cfg or LLMConfig()
        checklist, provider = self._generate(
            "Tworzysz praktyczne checklisty wydawnicze dla Amazon KDP. Znasz cały proces od A do Z.",
            dedent(f"""
            Stwórz kompletną checklistę publikacji na Amazon KDP dla tej książki.
            Podziel na sekcje: przygotowanie pliku, metadane, okładka, pricing, kategorie, pre-launch, launch.
            Format: sekcja → punktorowane zadania z krótkim wyjaśnieniem.

            TYTUŁ: {project.title}
            DOCELOWE SŁOWA: {project.target_words}
            SEO:
            {project.seo_description[:1500]}
            """),
            cfg,
        )
        project.publish_checklist = checklist
        project.llm_provider_used = provider
        project.status = "ready"
        return project

    def generate_ideas(
        self,
        niche: str,
        notes: str = "",
        user_settings: UserSettings | None = None,
    ) -> tuple[str, str]:
        cfg = _build_cfg(user_settings)
        return self._generate(
            "Jesteś strategiem książkowym zorientowanym na rynek. Generujesz idee, które sprzedają.",
            dedent(f"""
            Wygeneruj pomysły na książki w tej niszy, hooks sprzedażowe, kąty dla czytelnika i notatki research.
            Skup się na komercyjnie opłacalnych kątach.

            NISZA: {niche}
            NOTATKI: {notes or 'brak'}

            Format:
            1. Top 5 pomysłów na tytuły z jednozdaniowym opisem
            2. Idealni czytelnicy (3 persony)
            3. Kluczowe problemy, które książka rozwiązuje
            4. Sugerowane słowa kluczowe Amazon
            5. Konkurencja (co robić inaczej)
            """),
            cfg,
        )

    # --------------------------------------------------------------- internals

    def _context(self, project: BookProject) -> str:
        return dedent(f"""
        TYTUŁ: {project.title}
        POMYSŁ: {project.concept}
        DOCELOWE STRONY: {project.target_pages}
        DOCELOWE SŁOWA: {project.target_words}
        STYL: {project.tone_preferences}
        JĘZYK: {project.language}
        ŹRÓDŁA INSPIRACJI: {project.inspiration_sources or 'brak'}
        """)

    def _parse_chapters(self, outline: str) -> list[str]:
        """Extract chapter titles from outline text."""
        if not outline:
            return []
        chapters = []
        # Match patterns like "Rozdział 1:", "1.", "Chapter 1:", numbered headings
        patterns = [
            r"(?:Rozdział|Chapter|ROZDZIAŁ|CHAPTER)\s+\d+[:\.]?\s*(.+)",
            r"^\s*(\d+)\.\s+(.+)",
            r"^#{1,3}\s+(.+)",
        ]
        for line in outline.splitlines():
            line = line.strip()
            if not line:
                continue
            for pattern in patterns:
                m = re.match(pattern, line, re.IGNORECASE)
                if m:
                    title = m.group(len(m.groups()))
                    title = title.strip().rstrip(":")
                    if len(title) > 3:
                        chapters.append(title)
                    break
        return chapters[:30]  # cap at 30 chapters

    def _get_chapter_prompt(self, prompts_text: str, chapter_title: str, index: int) -> str:
        """Find chapter-specific prompt from chapter_prompts text."""
        if not prompts_text:
            return f"Napisz treść rozdziału: {chapter_title}"
        lines = prompts_text.splitlines()
        # Try to find prompt near this chapter title or index
        for i, line in enumerate(lines):
            if chapter_title.lower()[:20] in line.lower() or f"rozdział {index}" in line.lower():
                # Return next few lines as the prompt
                prompt_lines = lines[i: i + 8]
                return "\n".join(prompt_lines).strip()
        # Fallback: return chunk by index
        chunk_size = max(1, len(prompts_text) // 10)
        start = (index - 1) * chunk_size
        return prompts_text[start: start + chunk_size].strip() or f"Napisz treść rozdziału: {chapter_title}"

    def _generate(
        self,
        system_prompt: str,
        user_prompt: str,
        cfg: LLMConfig | None = None,
    ) -> tuple[str, str]:
        try:
            return llm_service.generate(system_prompt, user_prompt, cfg)
        except LLMError:
            fallback = self._fallback_text(system_prompt, user_prompt)
            return fallback, "template_fallback"

    def _fallback_text(self, system_prompt: str, user_prompt: str) -> str:
        return dedent(f"""
        [Fallback output — brak połączenia z LLM]
        Zadanie systemu: {system_prompt[:200]}

        Ta sekcja została wygenerowana bez odpowiedzi LLM. Podłącz LM Studio, Gemini lub OpenRouter w ustawieniach.

        Podsumowanie żądania:
        {user_prompt[:2000]}
        """).strip()


book_pipeline_service = BookPipelineService()
