from __future__ import annotations

from textwrap import dedent

from ..models import BookProject
from .llm import LLMError, llm_service


class BookPipelineService:
    def run_full_pipeline(self, project: BookProject) -> BookProject:
        context = self._context(project)

        outline, provider = self._generate(
            "You are a senior nonfiction ghostwriter and book architect.",
            f"Create a detailed outline in Polish for this book. {context}",
        )
        project.outline_text = outline
        project.llm_provider_used = provider

        chapter_prompts, provider = self._generate(
            "You create practical chapter-writing prompts for long-form books.",
            f"Based on this outline, write chapter prompts for every chapter.\n\nOUTLINE:\n{project.outline_text}\n\n{context}",
        )
        project.chapter_prompts = chapter_prompts
        project.llm_provider_used = provider

        manuscript, provider = self._generate(
            "You are a book writer. Write rich, human, commercially useful prose.",
            f"Write the book draft in Polish using the outline and prompts below. Keep it coherent and useful.\n\nOUTLINE:\n{project.outline_text}\n\nPROMPTS:\n{project.chapter_prompts}\n\n{context}",
        )
        project.manuscript_text = manuscript
        project.llm_provider_used = provider

        edited, provider = self._generate(
            "You are a developmental editor and line editor.",
            f"Edit the following draft for clarity, stronger flow, better style, and consistency. Preserve a natural human voice.\n\nDRAFT:\n{project.manuscript_text}\n\nSTYLE PREFERENCE:\n{project.tone_preferences}",
        )
        project.edited_text = edited
        project.llm_provider_used = provider

        seo, provider = self._generate(
            "You write Amazon-ready SEO product descriptions for books.",
            f"Write a compelling Amazon SEO description in Polish for this book. Include hooks, benefits, and a strong selling angle.\n\nTITLE: {project.title}\n\nBOOK:\n{project.edited_text[:12000]}",
        )
        project.seo_description = seo
        project.llm_provider_used = provider

        cover, provider = self._generate(
            "You create high-converting cover briefs for book designers and image models.",
            f"Create a sellable, viral-leaning cover brief for this book. Include concept, typography, colors, visual symbols, and 3 prompt variants.\n\nTITLE: {project.title}\n\nDESCRIPTION:\n{project.concept}\n\nSEO:\n{project.seo_description}",
        )
        project.cover_brief = cover
        project.llm_provider_used = provider

        checklist, provider = self._generate(
            "You design practical publishing checklists.",
            f"Create a step-by-step Amazon KDP publication checklist for this book, including metadata, formatting, category selection, and final QA.\n\nTITLE: {project.title}\nSEO:\n{project.seo_description}\nCOVER:\n{project.cover_brief}",
        )
        project.publish_checklist = checklist
        project.status = "ready"
        project.llm_provider_used = provider
        return project

    def generate_ideas(self, niche: str, notes: str = "") -> tuple[str, str]:
        return self._generate(
            "You are a market-aware book ideation strategist.",
            dedent(
                f"""
                Generate book ideas, hooks, target reader angles, and inspiration research notes.
                Focus on commercially viable angles.

                NICHE: {niche}
                NOTES: {notes}
                """
            ),
        )

    def _context(self, project: BookProject) -> str:
        return dedent(
            f"""
            TITLE: {project.title}
            IDEA: {project.concept}
            TARGET PAGES: {project.target_pages}
            TARGET WORDS: {project.target_words}
            TONE: {project.tone_preferences}
            LANGUAGE: {project.language}
            INSPIRATION SOURCES: {project.inspiration_sources}
            """
        )

    def _generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        try:
            return llm_service.generate(system_prompt, user_prompt)
        except LLMError:
            fallback = self._fallback_text(system_prompt, user_prompt)
            return fallback, "template_fallback"

    def _fallback_text(self, system_prompt: str, user_prompt: str) -> str:
        return dedent(
            f"""
            [Fallback output]
            System goal: {system_prompt}

            This section was generated without a live LLM response. Replace it by connecting LM Studio or OpenRouter.

            Summary of requested task:
            {user_prompt[:4000]}
            """
        ).strip()


book_pipeline_service = BookPipelineService()
