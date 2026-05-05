from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

from baudoku_api.reports.plan_render import resolve_marker_label, resolve_marker_reference


ImageLoader = Callable[[str], bytes]

DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "templates" / "bba_briefbogen.docx"
PLAN_IMAGE_WIDTH_INCHES = 6.5


class ReportDocxBuilderError(Exception):
    """Raised when a DOCX report cannot be built."""


class ReportDocxBuilder:
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
        document = self._document_from_template()
        self._configure_styles(document)

        document.add_heading("BBA Baubegehungsbericht", 0)
        self._add_project_header(document, project)
        self._add_general_findings(document, general_findings)
        self._add_defects(document, defects)
        self._add_plans(document, plans or [], defects)
        self._add_conclusion(document, project_conclusion)

        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def _document_from_template(self) -> Any:
        try:
            from docx import Document
        except Exception as exc:  # pragma: no cover - optional dependency surface
            raise ReportDocxBuilderError("python-docx ist nicht installiert.") from exc

        template_path = self._resolved_template_path()
        try:
            return Document(str(template_path))
        except Exception as exc:
            raise ReportDocxBuilderError(
                f"Briefbogen-Template konnte nicht geladen werden: {template_path}"
            ) from exc

    def _resolved_template_path(self) -> Path:
        candidates = []
        if self.template_path is not None:
            candidates.append(self.template_path)
        candidates.append(DEFAULT_TEMPLATE_PATH)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        raise ReportDocxBuilderError(
            f"Briefbogen-Template fehlt. Erwarteter Fallback: {DEFAULT_TEMPLATE_PATH}"
        )

    def _configure_styles(self, document: Any) -> None:
        try:
            from docx.shared import Pt
        except Exception as exc:  # pragma: no cover - optional dependency surface
            raise ReportDocxBuilderError("python-docx ist nicht installiert.") from exc

        normal_style = document.styles["Normal"]
        normal_style.font.name = "Arial"
        normal_style.font.size = Pt(10)

    def _add_project_header(self, document: Any, project: dict[str, Any]) -> None:
        document.add_paragraph(f"Projektnummer: {_text(project.get('project_number'))}")
        document.add_paragraph(f"Auftraggeber: {_text(project.get('client_name'))}")
        document.add_paragraph(f"Objektadresse: {_text(project.get('object_address'))}")
        document.add_paragraph(f"Datum: {_format_date(project.get('site_visit_date'))}")
        document.add_paragraph(f"Bearbeiter: {_project_author(project)}")
        document.add_paragraph(f"Gutachtentyp: {_text(project.get('appraisal_type'))}")

    def _add_general_findings(
        self, document: Any, general_findings: list[dict[str, Any]]
    ) -> None:
        document.add_heading("Allgemeine Feststellungen", level=1)
        if not general_findings:
            document.add_paragraph("Es wurden noch keine allgemeinen Feststellungen erfasst.")
            return

        for finding in _sorted_items(general_findings, "sort_order"):
            finding_text = _text(finding.get("text"))
            if finding_text:
                document.add_paragraph(finding_text, style="List Bullet")

    def _add_defects(self, document: Any, defects: list[dict[str, Any]]) -> None:
        document.add_heading("M\u00e4ngel und Hinweise", level=1)
        if not defects:
            document.add_paragraph("Es wurden noch keine M\u00e4ngel oder Hinweise erfasst.")
            return

        for index, defect in enumerate(_sorted_items(defects, "report_sort_order"), start=1):
            kind = "Mangel" if defect.get("kind") == "defect" else "Hinweis"
            label = _defect_label(defect, index, kind)
            document.add_heading(f"{label} - {kind}", level=2)
            if defect.get("trade_name_snapshot"):
                document.add_paragraph(f"Gewerk: {_text(defect.get('trade_name_snapshot'))}")
            if defect.get("category"):
                document.add_paragraph(f"Kategorie: {_text(defect.get('category'))}")
            document.add_paragraph(_text(defect.get("description")))
            self._add_defect_photos(document, defect)

    def _add_defect_photos(self, document: Any, defect: dict[str, Any]) -> None:
        photos = [
            link
            for link in _sorted_items(defect.get("media_links") or [], "sort_order")
            if link.get("include_in_report") is not False
            and (link.get("media_asset") or {}).get("media_type") == "photo"
        ]
        if not photos:
            return

        document.add_heading("Fotos", level=3)
        for index, link in enumerate(photos, start=1):
            media = link.get("media_asset") or {}
            storage_path = _text(media.get("storage_path"))
            caption = _text(media.get("caption")) or "Ohne Bildunterschrift"
            self._try_add_picture(document, storage_path)
            document.add_paragraph(f"Foto {index}: {caption}")

    def _try_add_picture(self, document: Any, storage_path: str, width_inches: float = 4.5) -> None:
        if not self.image_loader or not storage_path:
            return

        try:
            from docx.shared import Inches
        except Exception as exc:  # pragma: no cover - optional dependency surface
            raise ReportDocxBuilderError("python-docx ist nicht installiert.") from exc

        try:
            document.add_picture(BytesIO(self.image_loader(storage_path)), width=Inches(width_inches))
        except Exception:
            document.add_paragraph(f"Bild konnte nicht eingebettet werden: {storage_path}")

    def _add_plans(
        self,
        document: Any,
        plans: list[dict[str, Any]],
        defects: list[dict[str, Any]],
    ) -> None:
        if not plans:
            return

        document.add_heading("Planverortung", level=1)
        for plan in plans:
            document.add_heading(_text(plan.get("name")) or "Plan", level=2)
            media = plan.get("media_asset") or {}
            if media.get("media_type") in {"photo", "plan_render"}:
                self._try_add_picture(
                    document,
                    _text(media.get("storage_path")),
                    width_inches=PLAN_IMAGE_WIDTH_INCHES,
                )
            render_error = _text(plan.get("render_error"))
            if render_error:
                document.add_paragraph(render_error)
            self._add_plan_markers(document, plan.get("markers") or [], defects)

    def _add_plan_markers(
        self,
        document: Any,
        markers: list[dict[str, Any]],
        defects: list[dict[str, Any]],
    ) -> None:
        if not markers:
            document.add_paragraph("Keine Marker fuer diesen Plan erfasst.")
            return

        defects_by_id = {str(defect.get("id")): defect for defect in defects}
        for index, marker in enumerate(markers, start=1):
            defect = defects_by_id.get(str(marker.get("defect_id")))
            marker_label = resolve_marker_label(marker, defect, str(index)) or str(index)
            marker_reference = resolve_marker_reference(marker, defect)
            kind = _defect_kind_label(defect)
            description = _text((defect or {}).get("description")) or "Ohne Beschreibung"
            details = _marker_details(marker, defect, marker_reference)
            document.add_paragraph(
                f"Marker {marker_label} - {kind}: {description}"
                + (f" ({'; '.join(details)})" if details else ""),
                style="List Bullet",
            )

    def _add_conclusion(
        self, document: Any, project_conclusion: Optional[dict[str, Any]]
    ) -> None:
        document.add_heading("Fazit", level=1)
        conclusion_text = _text((project_conclusion or {}).get("text"))
        if conclusion_text:
            document.add_paragraph(conclusion_text)
        else:
            document.add_paragraph("Es wurde noch kein Fazit erfasst.")


def _text(value: object) -> str:
    return str(value or "").strip()


def _format_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _text(value)


def _project_author(project: dict[str, Any]) -> str:
    for key in (
        "lead_user_display_name",
        "lead_user_name",
        "created_by_display_name",
        "author_display_name",
        "bearbeiter",
    ):
        value = _text(project.get(key))
        if value:
            return value
    return "Nicht angegeben"


def _defect_label(defect: dict[str, Any], index: int, kind: str) -> str:
    for key in ("local_label", "label"):
        value = _text(defect.get(key))
        if value:
            return value
    report_number = _text(defect.get("report_number"))
    if report_number:
        return f"{kind} {report_number}"
    return f"Position {index}"


def _defect_kind_label(defect: Optional[dict[str, Any]]) -> str:
    if not defect:
        return "Unbekannter Eintrag"
    return "Mangel" if defect.get("kind") == "defect" else "Hinweis"


def _marker_details(
    marker: dict[str, Any],
    defect: Optional[dict[str, Any]],
    marker_reference: str,
) -> list[str]:
    defect = defect or {}
    details = []
    if marker_reference:
        details.append(f"Arbeitsnummer {marker_reference}")
    trade = _text(defect.get("trade_name_snapshot"))
    if trade:
        details.append(f"Gewerk {trade}")
    category = _text(defect.get("category"))
    if category:
        details.append(f"Kategorie {category}")
    details.append(f"Seite {_text(marker.get('page_number')) or '1'}")
    details.append(f"X {_percent(marker.get('x_norm'))}%")
    details.append(f"Y {_percent(marker.get('y_norm'))}%")
    return details


def _sorted_items(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: _sort_value(item.get(key)))


def _sort_value(value: object) -> tuple[int, float]:
    if value in (None, ""):
        return (1, 0)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, 0)


def _percent(value: object) -> int:
    try:
        return round(float(value or 0) * 100)
    except (TypeError, ValueError):
        return 0
