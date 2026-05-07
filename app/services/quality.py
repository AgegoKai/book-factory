"""Quality assurance pass for generated books.

Runs deterministic checks against the final manuscript before flipping the
project status to "ready". The report is JSON-serialisable and stored on
``BookProject.quality_report`` so the UI and downstream tools can surface it.

Checks performed:
- target chapter count vs manuscript chapter count
- total word count vs target_words (>= 85% threshold)
- absence of fabricated bibliography / references / footnotes blocks
- absence of cross-language chapter labels (no ``ROZDZIAŁ`` in EN/DE books)
- absence of leftover Markdown artefacts (``**``, ``__``, ``---`` separators)
- absence of inline citation patterns like ``[1]`` or ``(Smith, 2020)``
- absence of any "Book Factory" watermark string in the manuscript

The module is intentionally side-effect free. Callers persist the report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..models import BookProject

# Forbidden phrases that flag fabricated reference sections.
_FORBIDDEN_HEADINGS = (
    "bibliography",
    "references",
    "sources cited",
    "works cited",
    "literaturverzeichnis",
    "quellenverzeichnis",
    "literatur",
    "quellen",
    "fussnoten",
    "fußnoten",
    "footnotes",
    "przypisy",
    "źródła",
    "zrodla",
    "bibliografia",
)

_FOREIGN_CHAPTER_LABELS = {
    # Map locale to a list of chapter labels that must NOT appear.
    "en": ("rozdział", "rozdzial", "kapitel"),
    "de": ("rozdział", "rozdzial", "chapter"),
    "pl": ("kapitel",),  # in Polish books, German "Kapitel" is foreign
    "es": ("rozdział", "rozdzial", "kapitel", "chapter"),
    "fr": ("rozdział", "rozdzial", "kapitel", "chapter"),
}

_MARKDOWN_ARTEFACTS = (
    re.compile(r"\*\*[^*\n]+\*\*"),  # **bold**
    re.compile(r"(?<![A-Za-z0-9_])__[^_\n]+__(?![A-Za-z0-9_])"),  # __bold__
    re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE),  # horizontal rules
)

_CITATION_PATTERNS = (
    re.compile(r"\[\d{1,3}\]"),  # [1], [12]
    re.compile(r"\([A-Z][A-Za-zÀ-ÿ]+(?:\s+(?:and|&|i|und)\s+[A-Z][A-Za-zÀ-ÿ]+)?,\s*(?:19|20)\d{2}\)"),
)

_WATERMARK_PATTERNS = (
    re.compile(r"book\s*factory", re.IGNORECASE),
)


@dataclass
class QualityReport:
    passed: bool
    issues: list[str]
    warnings: list[str]
    stats: dict

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "issues": self.issues,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def _normalize_locale(language: str | None) -> str:
    raw = (language or "").strip().lower()
    if raw.startswith("pl"):
        return "pl"
    if raw.startswith("de"):
        return "de"
    if raw.startswith("en"):
        return "en"
    if raw.startswith("es"):
        return "es"
    if raw.startswith("fr"):
        return "fr"
    return "en"


def _count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or "", flags=re.UNICODE))


def _count_chapters(text: str) -> int:
    if not text:
        return 0
    matches = re.findall(
        r"(?im)^(?:Rozdział|Rozdzial|ROZDZIAŁ|Chapter|CHAPTER|Kapitel|KAPITEL|Capítulo|Capitulo|Chapitre)\s+\d+\b",
        text,
    )
    return len(matches)


def _find_forbidden_sections(text: str) -> list[str]:
    """Return any forbidden reference-section headings found in the manuscript."""
    haystack = (text or "").lower()
    found: list[str] = []
    for label in _FORBIDDEN_HEADINGS:
        # Look for the label as a heading (line-start) or as a clear section break.
        pattern = rf"(?im)^\s*(?:#{{1,3}}\s*)?{re.escape(label)}\s*[:\-]?\s*$"
        if re.search(pattern, haystack):
            found.append(label)
    return found


def _find_foreign_chapter_labels(text: str, locale: str) -> list[str]:
    forbidden = _FOREIGN_CHAPTER_LABELS.get(locale, ())
    if not forbidden:
        return []
    haystack = (text or "").lower()
    found: list[str] = []
    for label in forbidden:
        pattern = rf"(?im)^\s*{re.escape(label)}\s+\d+\b"
        if re.search(pattern, haystack):
            found.append(label)
    return found


def _find_markdown_artefacts(text: str) -> list[str]:
    artefacts: list[str] = []
    for pattern in _MARKDOWN_ARTEFACTS:
        match = pattern.search(text or "")
        if match:
            artefacts.append(match.group(0)[:60])
    return artefacts


def _find_citation_patterns(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _CITATION_PATTERNS:
        for match in pattern.finditer(text or ""):
            found.append(match.group(0))
            if len(found) >= 5:
                return found
    return found


def _find_watermarks(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _WATERMARK_PATTERNS:
        match = pattern.search(text or "")
        if match:
            found.append(match.group(0))
    return found


def _label_for(locale: str, key: str) -> str:
    catalog = {
        "pl": {
            "chapters_short": "Za mało rozdziałów: {actual}/{target}",
            "chapters_extra": "Za dużo rozdziałów: {actual}/{target}",
            "words_short": "Za krótka książka: {actual} słów to {ratio:.0%} celu ({target}).",
            "forbidden": "Wykryto zakazaną sekcję: {labels}",
            "foreign_labels": "Etykiety rozdziałów w obcym języku: {labels}",
            "markdown": "Artefakty Markdown w manuskrypcie: {samples}",
            "citations": "Wykryto zmyślone cytowania: {samples}",
            "watermark": "Wykryto watermark: {samples}",
            "no_manuscript": "Brak edytowanego manuskryptu — uruchom Draft i Redakcję.",
        },
        "en": {
            "chapters_short": "Too few chapters: {actual}/{target}",
            "chapters_extra": "Too many chapters: {actual}/{target}",
            "words_short": "Manuscript too short: {actual} words = {ratio:.0%} of target ({target}).",
            "forbidden": "Detected forbidden section heading: {labels}",
            "foreign_labels": "Foreign-language chapter labels: {labels}",
            "markdown": "Markdown artefacts left in manuscript: {samples}",
            "citations": "Detected fabricated citations: {samples}",
            "watermark": "Detected watermark: {samples}",
            "no_manuscript": "No edited manuscript yet — run Draft and Edit.",
        },
        "de": {
            "chapters_short": "Zu wenige Kapitel: {actual}/{target}",
            "chapters_extra": "Zu viele Kapitel: {actual}/{target}",
            "words_short": "Manuskript zu kurz: {actual} Woerter = {ratio:.0%} vom Ziel ({target}).",
            "forbidden": "Verbotene Abschnittsueberschrift erkannt: {labels}",
            "foreign_labels": "Fremdsprachige Kapitellabels: {labels}",
            "markdown": "Markdown-Artefakte im Manuskript: {samples}",
            "citations": "Erfundene Zitationen erkannt: {samples}",
            "watermark": "Wasserzeichen erkannt: {samples}",
            "no_manuscript": "Noch kein redigiertes Manuskript — Draft und Redaktion ausfuehren.",
        },
    }
    return catalog.get(locale, catalog["en"])[key]


def run_quality_check(project: BookProject, *, target_word_ratio: float = 0.85) -> QualityReport:
    """Run a synchronous, deterministic quality check on ``project``.

    ``target_word_ratio`` is the minimum fraction of ``project.target_words``
    that the edited manuscript must reach. Defaults to 0.85.
    """
    locale = _normalize_locale(getattr(project, "language", ""))
    edited = (getattr(project, "edited_text", "") or "").strip()
    draft = (getattr(project, "manuscript_text", "") or "").strip()
    manuscript = edited or draft
    target_chapters = int(getattr(project, "target_chapters", 0) or 0)
    target_words = int(getattr(project, "target_words", 0) or 0)

    issues: list[str] = []
    warnings: list[str] = []
    actual_chapters = _count_chapters(manuscript)
    actual_words = _count_words(manuscript)

    if not manuscript:
        issues.append(_label_for(locale, "no_manuscript"))
        return QualityReport(
            passed=False,
            issues=issues,
            warnings=warnings,
            stats={
                "locale": locale,
                "actual_chapters": 0,
                "target_chapters": target_chapters,
                "actual_words": 0,
                "target_words": target_words,
                "word_ratio": 0.0,
                "min_word_ratio": target_word_ratio,
                "uses_edited_manuscript": False,
            },
        )

    if target_chapters > 0:
        if actual_chapters < target_chapters:
            issues.append(
                _label_for(locale, "chapters_short").format(
                    actual=actual_chapters, target=target_chapters
                )
            )
        elif actual_chapters > target_chapters + 1:
            warnings.append(
                _label_for(locale, "chapters_extra").format(
                    actual=actual_chapters, target=target_chapters
                )
            )

    word_ratio = (actual_words / target_words) if target_words > 0 else 1.0
    if target_words > 0 and word_ratio < target_word_ratio:
        issues.append(
            _label_for(locale, "words_short").format(
                actual=actual_words,
                target=target_words,
                ratio=word_ratio,
            )
        )

    forbidden = _find_forbidden_sections(manuscript)
    if forbidden:
        issues.append(_label_for(locale, "forbidden").format(labels=", ".join(forbidden)))

    foreign = _find_foreign_chapter_labels(manuscript, locale)
    if foreign:
        issues.append(_label_for(locale, "foreign_labels").format(labels=", ".join(foreign)))

    markdown = _find_markdown_artefacts(manuscript)
    if markdown:
        warnings.append(_label_for(locale, "markdown").format(samples=", ".join(markdown[:3])))

    citations = _find_citation_patterns(manuscript)
    if citations:
        issues.append(_label_for(locale, "citations").format(samples=", ".join(citations[:3])))

    watermarks = _find_watermarks(manuscript)
    if watermarks:
        issues.append(_label_for(locale, "watermark").format(samples=", ".join(watermarks)))

    stats = {
        "locale": locale,
        "actual_chapters": actual_chapters,
        "target_chapters": target_chapters,
        "actual_words": actual_words,
        "target_words": target_words,
        "word_ratio": round(word_ratio, 4),
        "min_word_ratio": target_word_ratio,
        "uses_edited_manuscript": bool(edited),
    }
    return QualityReport(passed=not issues, issues=issues, warnings=warnings, stats=stats)


def report_to_json_dict(report: QualityReport) -> dict:
    """Convenience wrapper used by callers persisting the report."""
    return report.to_dict()


__all__ = ["QualityReport", "run_quality_check", "report_to_json_dict"]
