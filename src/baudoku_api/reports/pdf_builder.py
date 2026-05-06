from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

from baudoku_api.reports.image_processing import process_report_image
from baudoku_api.reports.letterhead import BBA_BLUE, CONTACT_COLUMNS, logo_bytes_from_template
from baudoku_api.reports.report_content import (
    ReportContent,
    ReportImage,
    build_report_content,
)


ImageLoader = Callable[[str], bytes]


DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "templates" / "bba_briefbogen.docx"
PHOTO_MAX_LONG_EDGE_PX = 1800
PHOTO_MAX_WIDTH_INCHES = 4.5
PHOTO_MAX_HEIGHT_INCHES = 3.8
PLAN_MAX_LONG_EDGE_PX = 2400
PLAN_MAX_WIDTH_INCHES = 6.5
PLAN_MAX_HEIGHT_INCHES = 7.2


class ReportPdfBuilderError(Exception):
    """Raised when a PDF report cannot be built."""


class ReportPdfBuilder:
    def __init__(
        self,
        template_path: Optional[object] = None,
        image_loader: Optional[ImageLoader] = None,
    ) -> None:
        self.template_path = Path(str(template_path)).expanduser() if template_path else None
        self.image_loader = image_loader

    def build(
        self,
        project: dict[str, Any],
        defects: list[dict[str, Any]],
        general_findings: list[dict[str, Any]],
        project_conclusion: Optional[dict[str, Any]],
        plans: Optional[list[dict[str, Any]]] = None,
    ) -> bytes:
        content = build_report_content(project, defects, general_findings, project_conclusion, plans)
        return self._build_content(content)

    def _build_content(self, content: ReportContent) -> bytes:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                KeepTogether,
                ListFlowable,
                ListItem,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
            )
        except Exception as exc:  # pragma: no cover - optional dependency surface
            raise ReportPdfBuilderError("reportlab ist nicht installiert.") from exc

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=17.5 * mm,
            rightMargin=7.5 * mm,
            topMargin=42 * mm,
            bottomMargin=38 * mm,
            title=content.title,
        )
        styles = getSampleStyleSheet()
        styles["Normal"].fontName = "Helvetica"
        styles["Normal"].fontSize = 9.5
        styles["Normal"].leading = 13
        styles["Title"].fontName = "Helvetica-Bold"
        styles["Title"].fontSize = 19
        styles["Title"].leading = 23
        styles["Title"].textColor = colors.HexColor("#1F1A3D")
        styles["Heading1"].fontName = "Helvetica-Bold"
        styles["Heading1"].fontSize = 14
        styles["Heading1"].leading = 18
        styles["Heading1"].spaceBefore = 12
        styles["Heading1"].spaceAfter = 7
        styles["Heading1"].textColor = colors.HexColor("#1F1A3D")
        styles["Heading2"].fontName = "Helvetica-Bold"
        styles["Heading2"].fontSize = 11.5
        styles["Heading2"].leading = 15
        styles["Heading2"].spaceBefore = 9
        styles["Heading2"].spaceAfter = 4
        styles["Heading2"].textColor = colors.HexColor("#1F1A3D")
        caption_style = ParagraphStyle(
            "Caption",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#555555"),
            alignment=TA_CENTER,
            spaceAfter=6,
        )
        warning_style = ParagraphStyle(
            "Warning",
            parent=styles["Normal"],
            backColor=colors.HexColor("#FFF7E6"),
            borderColor=colors.HexColor("#E2A100"),
            borderWidth=0.5,
            borderPadding=5,
            spaceAfter=7,
        )

        story = [Paragraph(content.title, styles["Title"]), Spacer(1, 5 * mm)]
        story.append(self._metadata_table(content, styles))
        story.append(Spacer(1, 6 * mm))

        story.append(Paragraph("Allgemeine Feststellungen", styles["Heading1"]))
        if content.general_findings:
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(text, styles["Normal"])) for text in content.general_findings],
                    bulletType="bullet",
                    start="circle",
                    leftIndent=14,
                )
            )
        else:
            story.append(Paragraph("Es wurden noch keine allgemeinen Feststellungen erfasst.", styles["Normal"]))

        story.append(Paragraph("Mängel und Hinweise", styles["Heading1"]))
        if content.defects:
            for defect in content.defects:
                story.append(Paragraph(f"{defect.label} - {defect.kind}", styles["Heading2"]))
                details = []
                if defect.trade:
                    details.append(f"Gewerk: {defect.trade}")
                if defect.category:
                    details.append(f"Kategorie: {defect.category}")
                if details:
                    story.append(Paragraph(" | ".join(details), styles["Normal"]))
                story.append(Paragraph(defect.description or "Ohne Beschreibung", styles["Normal"]))
                for photo in defect.photos:
                    story.extend(self._image_flowables(photo, caption_style))
        else:
            story.append(Paragraph("Es wurden noch keine Mängel oder Hinweise erfasst.", styles["Normal"]))

        if content.plans:
            for plan_index, plan in enumerate(content.plans):
                plan_intro = []
                if plan_index == 0:
                    plan_intro.append(Paragraph("Planverortung", styles["Heading1"]))
                plan_intro.append(Paragraph(plan.name, styles["Heading2"]))
                if plan.storage_path:
                    plan_intro.extend(
                        self._image_flowables(
                            ReportImage(
                                storage_path=plan.storage_path,
                                caption=f"Plan {plan.name}: markierte Verortung",
                                label="",
                                kind="plan",
                            ),
                            caption_style,
                        )
                    )
                story.append(KeepTogether(plan_intro))
                if plan.render_error:
                    story.append(Paragraph(plan.render_error, warning_style))

        if content.conclusion:
            story.append(Paragraph("Fazit", styles["Heading1"]))
            story.append(Paragraph(content.conclusion, styles["Normal"]))

        doc.build(story, onFirstPage=self._draw_letterhead, onLaterPages=self._draw_letterhead)
        return buffer.getvalue()

    def _metadata_table(self, content: ReportContent, styles: Any) -> Any:
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, Table, TableStyle

        rows = [
            [Paragraph(f"<b>{label}</b>", styles["Normal"]), Paragraph(value or "Nicht angegeben", styles["Normal"])]
            for label, value in content.project_fields
        ]
        table = Table(rows, colWidths=[38 * mm, 147 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D6DCE2")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6DCE2")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F7FA")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    def _image_flowables(self, image: ReportImage, caption_style: Any) -> list[Any]:
        if not self.image_loader or not image.storage_path:
            return []
        try:
            from reportlab.lib.units import inch
            from reportlab.platypus import Image, KeepTogether, Paragraph, Spacer
        except Exception as exc:  # pragma: no cover - optional dependency surface
            raise ReportPdfBuilderError("reportlab ist nicht installiert.") from exc

        max_long_edge = PLAN_MAX_LONG_EDGE_PX if image.kind == "plan" else PHOTO_MAX_LONG_EDGE_PX
        max_width = PLAN_MAX_WIDTH_INCHES if image.kind == "plan" else PHOTO_MAX_WIDTH_INCHES
        max_height = PLAN_MAX_HEIGHT_INCHES if image.kind == "plan" else PHOTO_MAX_HEIGHT_INCHES
        try:
            processed = process_report_image(
                self.image_loader(image.storage_path),
                max_long_edge_px=max_long_edge,
                max_width_inches=max_width,
                max_height_inches=max_height,
            )
        except Exception:
            return [Paragraph(f"Bild konnte nicht eingebettet werden: {image.storage_path}", caption_style)]

        flowables = [
            Image(
                BytesIO(processed.content),
                width=processed.display_width_inches * inch,
                height=processed.display_height_inches * inch,
                hAlign="CENTER",
            ),
            Paragraph(f"{image.label + ': ' if image.label else ''}{image.caption}", caption_style),
            Spacer(1, 3),
        ]
        return [KeepTogether(flowables)]

    def _draw_letterhead(self, canvas: Any, doc: Any) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader

        width, height = A4
        left = 17.5 * mm
        right = width - 7.5 * mm
        logo = logo_bytes_from_template(self._resolved_template_path())
        if logo:
            canvas.drawImage(
                ImageReader(BytesIO(logo)),
                left,
                height - 24 * mm,
                width=52.6 * mm,
                height=16.8 * mm,
                preserveAspectRatio=True,
                mask="auto",
            )
        canvas.setStrokeColor(colors.HexColor(f"#{BBA_BLUE}"))
        canvas.setLineWidth(0.5)
        canvas.line(left, height - 32 * mm, right, height - 32 * mm)
        canvas.line(left, 31 * mm, right, 31 * mm)

        col_width = (right - left) / 4
        canvas.setFillColor(colors.black)
        for index, (heading, lines) in enumerate(CONTACT_COLUMNS):
            x = left + index * col_width
            y = 28 * mm
            canvas.setFont("Helvetica-Bold", 7)
            canvas.drawString(x, y, heading)
            canvas.setFont("Helvetica", 7)
            for line in lines:
                y -= 3.6 * mm
                canvas.drawString(x, y, line)

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawRightString(right, 8 * mm, f"Seite {canvas.getPageNumber()}")

    def _resolved_template_path(self) -> Path:
        if self.template_path is not None and self.template_path.exists():
            return self.template_path
        return DEFAULT_TEMPLATE_PATH
