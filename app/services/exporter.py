from __future__ import annotations

import os
import re
from io import BytesIO

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm, cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable

from ..models import BookProject

# ── Font registration ──────────────────────────────────────────────────────────

_FONTS_REGISTERED = False
_BODY_FONT = "Helvetica"
_BODY_FONT_BOLD = "Helvetica-Bold"
_BODY_FONT_ITALIC = "Helvetica-Oblique"

_STATIC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "static", "fonts"))


def _font_search_dirs() -> list[str]:
    """Return candidate directories for TrueType fonts, ordered by preference."""
    dirs = [
        _STATIC_DIR,                                           # bundled fonts (highest prio)
        r"C:\Windows\Fonts",                                   # Windows
        "/usr/share/fonts/truetype/dejavu",                    # Debian/Ubuntu (Docker)
        "/usr/share/fonts/dejavu",                             # some Debian variants
        "/usr/share/fonts/truetype/liberation",                # Liberation
        "/usr/share/fonts/liberation",
        "/usr/share/fonts/truetype/freefont",
        "/usr/share/fonts/truetype/noto",
        "/usr/share/fonts/truetype",                           # broad fallback
        "/usr/share/fonts",
        # macOS system fonts
        "/Library/Fonts",
        "/System/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
        # macOS Homebrew cask fonts
        "/usr/local/share/fonts",
        "/opt/homebrew/share/fonts",
    ]
    return [d for d in dirs if d]


_FONT_SETS = [
    # (alias, regular, bold, italic) — filenames to look for
    ("DejaVu",      "DejaVuSerif.ttf",             "DejaVuSerif-Bold.ttf",        "DejaVuSerif-Italic.ttf"),
    ("DejaVuSans",  "DejaVuSans.ttf",              "DejaVuSans-Bold.ttf",         "DejaVuSans-Oblique.ttf"),
    ("Liberation",  "LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf",    "LiberationSerif-Italic.ttf"),
    ("LiberSans",   "LiberationSans-Regular.ttf",  "LiberationSans-Bold.ttf",     "LiberationSans-Italic.ttf"),
    ("FreeSans",    "FreeSans.ttf",                "FreeSansBold.ttf",            "FreeSansOblique.ttf"),
    ("NotoSans",    "NotoSans-Regular.ttf",        "NotoSans-Bold.ttf",           "NotoSans-Italic.ttf"),
]


def _try_register_set(folder: str, fname: str, regular: str, bold: str, italic: str) -> bool:
    """Try to register one font family; return True on success."""
    global _BODY_FONT, _BODY_FONT_BOLD, _BODY_FONT_ITALIC
    rp = os.path.join(folder, regular)
    if not os.path.isfile(rp):
        return False
    try:
        pdfmetrics.registerFont(TTFont(fname, rp))
        bp = os.path.join(folder, bold)
        ip = os.path.join(folder, italic)
        bold_name = fname + "Bold"
        italic_name = fname + "Italic"
        if os.path.isfile(bp):
            pdfmetrics.registerFont(TTFont(bold_name, bp))
            _BODY_FONT_BOLD = bold_name
        else:
            _BODY_FONT_BOLD = fname   # fallback to regular
        if os.path.isfile(ip):
            pdfmetrics.registerFont(TTFont(italic_name, ip))
            _BODY_FONT_ITALIC = italic_name
        else:
            _BODY_FONT_ITALIC = fname
        _BODY_FONT = fname
        return True
    except Exception:
        return False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    _FONTS_REGISTERED = True   # always mark done; Helvetica is last-resort fallback

    for folder in _font_search_dirs():
        if not os.path.isdir(folder):
            continue
        for font_set in _FONT_SETS:
            if _try_register_set(folder, *font_set):
                return   # found a working font — done


# ── Color palette ──────────────────────────────────────────────────────────────

INK         = colors.HexColor("#1a1a2e")
INK_LIGHT   = colors.HexColor("#2d2d48")
ACCENT      = colors.HexColor("#6366f1")
ACCENT_SOFT = colors.HexColor("#a5b4fc")
GOLD        = colors.HexColor("#f59e0b")
CREAM       = colors.HexColor("#fafaf8")
RULE_COLOR  = colors.HexColor("#e2e0db")
CAPTION_COL = colors.HexColor("#6b7280")
WHITE       = colors.white


# ── Custom flowables ───────────────────────────────────────────────────────────

class ColorRect(Flowable):
    """A filled color rectangle — used for decorative elements."""
    def __init__(self, width, height, fill_color, radius=0):
        super().__init__()
        self.width = width
        self.height = height
        self.fill_color = fill_color
        self.radius = radius

    def draw(self):
        self.canv.setFillColor(self.fill_color)
        if self.radius:
            self.canv.roundRect(0, 0, self.width, self.height, self.radius, fill=1, stroke=0)
        else:
            self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


class OrnamentalRule(Flowable):
    """Decorative chapter rule with central diamond."""
    def __init__(self, width, color=ACCENT):
        super().__init__()
        self.width = width
        self.color = color
        self.height = 12

    def draw(self):
        c = self.canv
        c.setStrokeColor(self.color)
        c.setFillColor(self.color)
        # Left line
        c.setLineWidth(0.8)
        c.line(0, 6, self.width * 0.42, 6)
        # Diamond
        cx, cy = self.width / 2, 6
        d = 4
        p = c.beginPath()
        p.moveTo(cx, cy + d)
        p.lineTo(cx + d, cy)
        p.lineTo(cx, cy - d)
        p.lineTo(cx - d, cy)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        # Right line
        c.line(self.width * 0.58, 6, self.width, 6)


# ── Style builder ──────────────────────────────────────────────────────────────

def _build_styles(body_font, bold_font, italic_font):
    s = {}

    common = dict(fontName=body_font, leading=20, textColor=INK, spaceAfter=8)

    s["body"] = ParagraphStyle(
        "body",
        fontName=body_font, fontSize=11, leading=19,
        textColor=INK, alignment=TA_JUSTIFY,
        spaceBefore=0, spaceAfter=10,
        firstLineIndent=18,
    )
    s["body_first"] = ParagraphStyle(
        "body_first",
        parent=s["body"],
        firstLineIndent=0,
        spaceAfter=10,
    )
    s["chapter_title"] = ParagraphStyle(
        "chapter_title",
        fontName=bold_font, fontSize=22, leading=28,
        textColor=INK, alignment=TA_LEFT,
        spaceBefore=4, spaceAfter=6,
    )
    s["chapter_num"] = ParagraphStyle(
        "chapter_num",
        fontName=body_font, fontSize=10, leading=14,
        textColor=ACCENT, alignment=TA_LEFT,
        spaceBefore=0, spaceAfter=4,
        letterSpacing=2,
    )
    s["section_head"] = ParagraphStyle(
        "section_head",
        fontName=bold_font, fontSize=14, leading=20,
        textColor=INK, alignment=TA_LEFT,
        spaceBefore=18, spaceAfter=6,
    )
    s["meta_label"] = ParagraphStyle(
        "meta_label",
        fontName=bold_font, fontSize=8, leading=12,
        textColor=ACCENT, alignment=TA_LEFT,
        spaceBefore=0, spaceAfter=2,
        letterSpacing=1.5,
    )
    s["caption"] = ParagraphStyle(
        "caption",
        fontName=italic_font, fontSize=9, leading=13,
        textColor=CAPTION_COL, alignment=TA_LEFT,
        spaceBefore=0, spaceAfter=8,
    )
    return s


# ── Page templates ─────────────────────────────────────────────────────────────

class BookDocTemplate(BaseDocTemplate):
    def __init__(self, filename_or_buffer, title: str, author: str = "", **kwargs):
        self.book_title = title
        self.book_author = author
        self._page_num_map = {}
        super().__init__(filename_or_buffer, **kwargs)

    def handle_pageEnd(self):
        super().handle_pageEnd()

    def afterPage(self):
        pass

    def _header_footer(self, canvas, doc, show_header=True):
        canvas.saveState()
        w, h = A4
        margin_x = 22 * mm

        if show_header and doc.page > 1:
            # Header rule
            canvas.setStrokeColor(RULE_COLOR)
            canvas.setLineWidth(0.5)
            canvas.line(margin_x, h - 16 * mm, w - margin_x, h - 16 * mm)
            # Header text
            canvas.setFont(_BODY_FONT_ITALIC or "Helvetica-Oblique", 8)
            canvas.setFillColor(CAPTION_COL)
            if doc.page % 2 == 0:
                canvas.drawString(margin_x, h - 14 * mm, self.book_title)
            else:
                canvas.drawRightString(w - margin_x, h - 14 * mm, self.book_author or "Book Factory")

            # Footer
            canvas.setStrokeColor(RULE_COLOR)
            canvas.line(margin_x, 14 * mm, w - margin_x, 14 * mm)
            canvas.setFont(_BODY_FONT or "Helvetica", 9)
            canvas.setFillColor(CAPTION_COL)
            canvas.drawCentredString(w / 2, 10 * mm, str(doc.page - 1))  # -1 for cover

        canvas.restoreState()

    def build(self, flowables, **kwargs):
        self._calc = None
        super().build(flowables, **kwargs)


# ── Parse helpers ──────────────────────────────────────────────────────────────

def _is_chapter_line(line: str) -> tuple[bool, str, str]:
    """Returns (is_chapter, chapter_num_label, title)."""
    stripped = line.strip()
    patterns = [
        r"^={3,}\s*(.+?)\s*={0,}$",   # ===Title===
        r"^([A-ZĄĆĘŁŃÓŚŹŻ][^.!?\n]{3,60})\s*$",  # Standalone capitalized line (heuristic)
    ]
    # Numbered chapter: "Rozdział 1" or "1. Title" or "## Title"
    m = re.match(r"^(?:Rozdział|ROZDZIAŁ|Chapter|CHAPTER)\s+(\d+)[:\.]?\s*(.+)?$", stripped, re.I)
    if m:
        num = m.group(1)
        title = (m.group(2) or "").strip()
        return True, f"ROZDZIAŁ {num}", title

    m = re.match(r"^#\s+(.+)$", stripped)
    if m:
        return True, "", m.group(1).strip()

    m = re.match(r"^##\s+(.+)$", stripped)
    if m:
        return True, "", m.group(1).strip()

    m = re.match(r"^(\d+)\.\s+(.{5,60})$", stripped)
    if m:
        return True, f"ROZDZIAŁ {m.group(1)}", m.group(2).strip()

    # Pipeline separator pattern ===== Title =====
    m = re.match(r"^={20,}\s*$", stripped)
    if m:
        return False, "", ""
    m = re.match(r"^={3,}\s*(.+?)\s*=*$", stripped)
    if m:
        title = m.group(1).strip()
        if title:
            return True, "", title

    return False, "", ""


def _parse_manuscript(text: str) -> list[dict]:
    """Parse manuscript into chapters: list of {num, title, paragraphs}"""
    if not text:
        return []

    chapters = []
    current_num = ""
    current_title = ""
    current_paras: list[str] = []

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        is_ch, num, title = _is_chapter_line(stripped)

        if is_ch and title:
            # Save previous
            if current_paras or current_title:
                chapters.append({
                    "num": current_num,
                    "title": current_title,
                    "paragraphs": [p for p in current_paras if p.strip()],
                })
            current_num = num
            current_title = title
            current_paras = []
        elif stripped == "" and current_paras:
            # Blank line = paragraph break
            if current_paras and current_paras[-1] != "":
                current_paras.append("")
        elif stripped:
            current_paras.append(stripped)

        i += 1

    if current_paras or current_title:
        chapters.append({
            "num": current_num,
            "title": current_title or "Treść",
            "paragraphs": [p for p in current_paras if p.strip()],
        })

    return chapters


# ── Main exporter ──────────────────────────────────────────────────────────────

class ExportService:

    # ── DOCX ──────────────────────────────────────────────────────────────────

    def build_docx(self, project: BookProject) -> bytes:
        doc = Document()

        # Styles
        style = doc.styles["Normal"]
        style.font.name = "Georgia"
        style.font.size = Pt(11)

        # Title page
        t = doc.add_paragraph()
        t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = t.add_run(project.title)
        run.bold = True
        run.font.size = Pt(28)
        run.font.color.rgb = RGBColor(0x1a, 0x1a, 0x2e)

        doc.add_paragraph()
        meta = doc.add_paragraph(f"{project.language.upper()} · {project.target_words:,} słów · {project.target_pages} stron")
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta.runs[0].font.size = Pt(10)
        meta.runs[0].font.color.rgb = RGBColor(0x63, 0x66, 0xf1)

        doc.add_page_break()

        sections_map = [
            ("Konspekt", project.outline_text),
            ("Prompty rozdziałów", project.chapter_prompts),
            ("Draft", project.manuscript_text),
            ("Zredagowany manuskrypt", project.edited_text),
            ("Opis Amazon SEO", project.seo_description),
            ("Brief okładki", project.cover_brief),
            ("Checklista publikacji", project.publish_checklist),
        ]

        # For final export, prefer edited > draft
        content = project.edited_text or project.manuscript_text or ""
        if content.strip():
            sections_map = [
                ("Manuskrypt", content),
                ("Opis Amazon SEO", project.seo_description),
                ("Brief okładki", project.cover_brief),
                ("Checklista publikacji", project.publish_checklist),
            ]

        for sec_title, sec_content in sections_map:
            if not (sec_content or "").strip():
                continue
            h = doc.add_heading(sec_title, level=1)
            h.runs[0].font.color.rgb = RGBColor(0x1a, 0x1a, 0x2e)

            for para_text in (sec_content or "").split("\n\n"):
                para_text = para_text.strip()
                if not para_text:
                    continue
                p = doc.add_paragraph(para_text)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                if p.runs:
                    p.runs[0].font.size = Pt(11)
            doc.add_page_break()

        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    # ── PDF ───────────────────────────────────────────────────────────────────

    def build_pdf(self, project: BookProject) -> bytes:
        _register_fonts()
        styles = _build_styles(_BODY_FONT, _BODY_FONT_BOLD, _BODY_FONT_ITALIC)
        buf = BytesIO()

        page_w, page_h = A4
        margin_top    = 22 * mm
        margin_bottom = 22 * mm
        margin_inner  = 25 * mm   # gutter
        margin_outer  = 20 * mm

        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=margin_inner,
            rightMargin=margin_outer,
            topMargin=margin_top + 8 * mm,   # extra for header
            bottomMargin=margin_bottom + 6 * mm,
            title=project.title,
            author="Book Factory",
        )

        story = []

        # ── Cover page ──────────────────────────────────────────────
        story.extend(self._build_cover(project, styles, page_w, page_h))
        story.append(PageBreak())

        # ── Content: prefer edited > draft ─────────────────────────
        manuscript = (project.edited_text or project.manuscript_text or "").strip()
        chapters = _parse_manuscript(manuscript) if manuscript else []

        if chapters:
            story.extend(self._build_chapters(chapters, styles, page_w))
        elif manuscript:
            # Raw text fallback
            story.append(Paragraph("Manuskrypt", styles["section_head"]))
            story.append(OrnamentalRule(page_w - margin_inner - margin_outer))
            story.append(Spacer(1, 6 * mm))
            for block in manuscript.split("\n\n"):
                block = block.strip()
                if block:
                    story.append(Paragraph(self._escape(block), styles["body"]))

        # ── Back matter ────────────────────────────────────────────
        if (project.seo_description or "").strip():
            story.append(PageBreak())
            story.extend(self._build_back_section(
                "Opis Amazon SEO", project.seo_description, styles, page_w,
                margin_inner, margin_outer,
            ))
        if (project.cover_brief or "").strip():
            story.append(PageBreak())
            story.extend(self._build_back_section(
                "Brief okładki", project.cover_brief, styles, page_w,
                margin_inner, margin_outer,
            ))
        if (project.publish_checklist or "").strip():
            story.append(PageBreak())
            story.extend(self._build_back_section(
                "Checklista publikacji Amazon KDP", project.publish_checklist, styles,
                page_w, margin_inner, margin_outer,
            ))

        # ── Build with running header/footer ───────────────────────
        def _on_page(canvas, doc):
            canvas.saveState()
            _page_header_footer(canvas, doc, project.title)
            canvas.restoreState()

        doc.build(story, onFirstPage=_cover_page_bg, onLaterPages=_on_page)
        return buf.getvalue()

    # ── Cover builder ──────────────────────────────────────────────────────────

    def _build_cover(self, project: BookProject, styles, pw, ph) -> list:
        """Returns flowables that make a stunning cover page."""
        elements = []

        # Push content down ~1/3 of page
        elements.append(Spacer(1, ph * 0.18))

        # Accent bar top
        elements.append(ColorRect(pw - 45 * mm, 4, ACCENT, radius=2))
        elements.append(Spacer(1, 8 * mm))

        # Title
        title_style = ParagraphStyle(
            "ct",
            fontName=_BODY_FONT_BOLD,
            fontSize=36,
            leading=42,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=0,
        )
        elements.append(Paragraph(self._escape(project.title), title_style))
        elements.append(Spacer(1, 4 * mm))

        # Thin rule
        elements.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4 * mm))

        # Concept / subtitle
        sub_style = ParagraphStyle(
            "sub",
            fontName=_BODY_FONT,
            fontSize=13,
            leading=20,
            textColor=colors.HexColor("#4b5563"),
            alignment=TA_LEFT,
            spaceAfter=0,
        )
        concept_short = (project.concept or "")[:220].strip()
        if len(project.concept or "") > 220:
            concept_short += "…"
        elements.append(Paragraph(self._escape(concept_short), sub_style))
        elements.append(Spacer(1, ph * 0.14))

        # Metadata table
        meta_rows = [
            ["JĘZYK", project.language.upper()],
            ["CEL SŁÓW", f"{project.target_words:,}"],
            ["CEL STRON", str(project.target_pages)],
        ]
        if project.llm_provider_used:
            meta_rows.append(["MODEL", project.llm_provider_used])

        label_s = ParagraphStyle("ml", fontName=_BODY_FONT_BOLD, fontSize=7,
                                 textColor=ACCENT, leading=10, letterSpacing=1.5)
        val_s   = ParagraphStyle("mv", fontName=_BODY_FONT, fontSize=10,
                                 textColor=INK, leading=14)

        table_data = [[
            Paragraph(row[0], label_s),
            Paragraph(row[1], val_s),
        ] for row in meta_rows]

        t = Table(table_data, colWidths=[35 * mm, 80 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f5f5f8"), WHITE]),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("ROUNDEDCORNERS", [4]),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 8 * mm))

        # Bottom tag
        tag_s = ParagraphStyle("tag", fontName=_BODY_FONT_BOLD, fontSize=8,
                               textColor=CAPTION_COL, leading=12, letterSpacing=1)
        elements.append(Paragraph("Wygenerowano przez Book Factory · AI Writing Pipeline", tag_s))

        return elements

    # ── Chapter builder ────────────────────────────────────────────────────────

    def _build_chapters(self, chapters: list[dict], styles, pw) -> list:
        elements = []
        for idx, ch in enumerate(chapters):
            if idx > 0:
                elements.append(PageBreak())

            # Chapter number label
            if ch["num"]:
                elements.append(Paragraph(ch["num"], styles["chapter_num"]))
                elements.append(Spacer(1, 2 * mm))

            # Chapter title
            if ch["title"]:
                elements.append(Paragraph(self._escape(ch["title"]), styles["chapter_title"]))
                elements.append(Spacer(1, 3 * mm))

            # Ornamental rule
            elements.append(OrnamentalRule(pw - 45 * mm))
            elements.append(Spacer(1, 6 * mm))

            # Body paragraphs
            first = True
            for para in ch["paragraphs"]:
                if not para.strip():
                    elements.append(Spacer(1, 4 * mm))
                    first = True
                    continue
                s = styles["body_first"] if first else styles["body"]
                elements.append(Paragraph(self._escape(para), s))
                first = False

        return elements

    # ── Back section ──────────────────────────────────────────────────────────

    def _build_back_section(self, title, content, styles, pw, ml, mr) -> list:
        elements = []
        # Section header with colored bar
        elements.append(ColorRect(pw - ml - mr, 32, INK, radius=4))
        elements.append(Spacer(1, -8 * mm))   # overlap text on bar

        label_over = ParagraphStyle(
            "lbl_over", fontName=_BODY_FONT_BOLD, fontSize=13,
            textColor=WHITE, leading=18, leftIndent=8,
        )
        elements.append(Paragraph(self._escape(title), label_over))
        elements.append(Spacer(1, 8 * mm))

        for block in (content or "").split("\n\n"):
            block = block.strip()
            if not block:
                continue
            # Detect bullet/ checklist lines
            if block.startswith(("- ", "• ", "* ", "[ ]", "[x]", "☐", "✓", "✔")):
                for line in block.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    line = line.lstrip("-•*☐✓✔").lstrip("[ ]").lstrip("[x]").strip()
                    bp = ParagraphStyle("bp", fontName=_BODY_FONT, fontSize=10, leading=15,
                                        textColor=INK, leftIndent=12, spaceAfter=4,
                                        bulletIndent=0, bulletText="▪")
                    elements.append(Paragraph(self._escape(line), bp))
            else:
                elements.append(Paragraph(self._escape(block), styles["body_first"]))

        return elements

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _escape(text: str) -> str:
        """Escape XML special chars for ReportLab Paragraph."""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _sections(self, project: BookProject):
        all_sections = [
            ("Konspekt", project.outline_text),
            ("Prompty rozdziałów", project.chapter_prompts),
            ("Draft książki", project.manuscript_text),
            ("Zredagowany manuskrypt", project.edited_text),
            ("Opis Amazon SEO", project.seo_description),
            ("Brief okładki", project.cover_brief),
            ("Checklista publikacji", project.publish_checklist),
        ]
        return [(t, c) for t, c in all_sections if (c or "").strip()]


# ── Page decorators ────────────────────────────────────────────────────────────

def _cover_page_bg(canvas, doc):
    """Cover page: clean white with subtle accent elements."""
    canvas.saveState()
    w, h = A4
    # Subtle gradient-like top band
    canvas.setFillColor(colors.HexColor("#f0f0f8"))
    canvas.rect(0, h - 50 * mm, w, 50 * mm, fill=1, stroke=0)
    # Accent left edge
    canvas.setFillColor(colors.HexColor("#6366f1"))
    canvas.rect(0, 0, 4, h, fill=1, stroke=0)
    # Bottom right decorative block
    canvas.setFillColor(colors.HexColor("#f0f0f8"))
    canvas.rect(w - 30 * mm, 0, 30 * mm, 30 * mm, fill=1, stroke=0)
    canvas.restoreState()


def _page_header_footer(canvas, doc, title: str):
    """Running header and footer for content pages."""
    if doc.page <= 1:
        return
    w, h = A4
    ml, mr = 25 * mm, 20 * mm

    canvas.setStrokeColor(colors.HexColor("#e2e0db"))
    canvas.setLineWidth(0.4)

    # Header
    canvas.line(ml, h - 18 * mm, w - mr, h - 18 * mm)
    canvas.setFont(_BODY_FONT_ITALIC or "Helvetica-Oblique", 8)
    canvas.setFillColor(colors.HexColor("#9ca3af"))
    if doc.page % 2 == 0:
        canvas.drawString(ml, h - 15 * mm, title[:60])
    else:
        canvas.drawRightString(w - mr, h - 15 * mm, "Book Factory")

    # Accent left bar on content pages
    canvas.setFillColor(colors.HexColor("#6366f1"))
    canvas.setStrokeColor(colors.HexColor("#6366f1"))
    canvas.setLineWidth(2)
    canvas.line(0, 0, 0, h)

    # Footer
    canvas.setLineWidth(0.4)
    canvas.setStrokeColor(colors.HexColor("#e2e0db"))
    canvas.line(ml, 16 * mm, w - mr, 16 * mm)
    canvas.setFont(_BODY_FONT or "Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#9ca3af"))
    page_num = doc.page - 1
    canvas.drawCentredString(w / 2, 12 * mm, str(page_num))


export_service = ExportService()
