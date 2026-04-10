from __future__ import annotations

from io import BytesIO

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from ..models import BookProject


class ExportService:
    def build_docx(self, project: BookProject) -> bytes:
        document = Document()
        document.add_heading(project.title, level=0)
        for section_title, content in self._sections(project):
            document.add_heading(section_title, level=1)
            for paragraph in (content or "").split("\n\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    document.add_paragraph(paragraph)
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def build_pdf(self, project: BookProject) -> bytes:
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margin = 40
        y = height - margin

        def draw_text(text: str, font_name: str = "Helvetica", font_size: int = 11):
            nonlocal y
            pdf.setFont(font_name, font_size)
            for raw_line in text.splitlines() or [""]:
                line = raw_line.strip() or " "
                words = line.split()
                current = ""
                for word in words or [""]:
                    test = f"{current} {word}".strip()
                    if stringWidth(test, font_name, font_size) <= width - 2 * margin:
                        current = test
                    else:
                        pdf.drawString(margin, y, current)
                        y -= 16
                        current = word
                        if y < margin:
                            pdf.showPage()
                            y = height - margin
                            pdf.setFont(font_name, font_size)
                pdf.drawString(margin, y, current)
                y -= 16
                if y < margin:
                    pdf.showPage()
                    y = height - margin
                    pdf.setFont(font_name, font_size)

        pdf.setTitle(project.title)
        draw_text(project.title, "Helvetica-Bold", 18)
        y -= 10
        for section_title, content in self._sections(project):
            draw_text(section_title, "Helvetica-Bold", 14)
            draw_text(content or "-")
            y -= 8
        pdf.save()
        return buffer.getvalue()

    def _sections(self, project: BookProject):
        return [
            ("Outline", project.outline_text),
            ("Chapter prompts", project.chapter_prompts),
            ("Draft", project.manuscript_text),
            ("Edited manuscript", project.edited_text),
            ("Amazon SEO", project.seo_description),
            ("Cover brief", project.cover_brief),
            ("Publish checklist", project.publish_checklist),
        ]


export_service = ExportService()
