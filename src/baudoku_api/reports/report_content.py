from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


@dataclass(frozen=True)
class ReportImage:
    storage_path: str
    caption: str
    label: str
    kind: str


@dataclass(frozen=True)
class ReportDefect:
    label: str
    kind: str
    trade: str
    category: str
    description: str
    photos: list[ReportImage] = field(default_factory=list)


@dataclass(frozen=True)
class ReportPlan:
    name: str
    storage_path: str
    render_error: str


@dataclass(frozen=True)
class ReportContent:
    title: str
    project_fields: list[tuple[str, str]]
    general_findings: list[str]
    defects: list[ReportDefect]
    plans: list[ReportPlan]
    conclusion: str


def build_report_content(
    project: dict[str, Any],
    defects: list[dict[str, Any]],
    general_findings: list[dict[str, Any]],
    project_conclusion: Optional[dict[str, Any]],
    plans: Optional[list[dict[str, Any]]] = None,
) -> ReportContent:
    return ReportContent(
        title="BBA Baubegehungsbericht",
        project_fields=[
            ("Projektnummer", _text(project.get("project_number"))),
            ("Auftraggeber", _text(project.get("client_name"))),
            ("Objektadresse", _text(project.get("object_address"))),
            ("Datum", _format_date(project.get("site_visit_date"))),
            ("Bearbeiter", _project_author(project)),
            ("Gutachtentyp", _text(project.get("appraisal_type"))),
        ],
        general_findings=[
            text
            for text in (
                _text(finding.get("text"))
                for finding in _sorted_items(general_findings, "sort_order")
            )
            if text
        ],
        defects=_build_defects(defects),
        plans=_build_plans(plans or [], defects),
        conclusion=_text((project_conclusion or {}).get("text")),
    )


def _build_defects(defects: list[dict[str, Any]]) -> list[ReportDefect]:
    report_defects = []
    for index, defect in enumerate(_sorted_items(defects, "report_sort_order"), start=1):
        kind = "Mangel" if defect.get("kind") == "defect" else "Hinweis"
        label = _defect_label(defect, index, kind)
        report_defects.append(
            ReportDefect(
                label=label,
                kind=kind,
                trade=_text(defect.get("trade_name_snapshot")),
                category=_text(defect.get("category")),
                description=_text(defect.get("description")),
                photos=_build_photos(defect, label),
            )
        )
    return report_defects


def _build_photos(defect: dict[str, Any], defect_label: str) -> list[ReportImage]:
    photos = [
        link
        for link in _sorted_items(defect.get("media_links") or [], "sort_order")
        if link.get("include_in_report") is not False
        and (link.get("media_asset") or {}).get("media_type") == "photo"
    ]
    report_images = []
    for index, link in enumerate(photos, start=1):
        media = link.get("media_asset") or {}
        caption = _text(media.get("caption")) or "Ohne Bildunterschrift"
        report_images.append(
            ReportImage(
                storage_path=_text(media.get("storage_path")),
                caption=caption,
                label=f"Foto {defect_label}.{index}",
                kind="photo",
            )
        )
    return report_images


def _build_plans(plans: list[dict[str, Any]], defects: list[dict[str, Any]]) -> list[ReportPlan]:
    report_plans = []
    for plan in plans:
        media = plan.get("media_asset") or {}
        storage_path = ""
        if media.get("media_type") in {"photo", "plan_render"}:
            storage_path = _text(media.get("storage_path"))
        report_plans.append(
            ReportPlan(
                name=_text(plan.get("name")) or "Plan",
                storage_path=storage_path,
                render_error=_text(plan.get("render_error")),
            )
        )
    return report_plans


def _sorted_items(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item.get(key) is None, item.get(key) or 0))


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

