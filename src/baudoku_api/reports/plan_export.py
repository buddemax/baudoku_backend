from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from baudoku_api.reports.plan_render import (
    MARKER_TARGET_DIAMETER_INCHES,
    MARKER_TARGET_WORD_WIDTH_INCHES,
    PlanRenderError,
    PlanRenderUnsupportedError,
    is_pdf_plan,
    markers_for_page,
    normalized_coordinate,
    render_annotated_plan_image,
    resolve_marker_label,
)


@dataclass(frozen=True)
class PlanExportResult:
    content: bytes
    mime_type: str
    file_extension: str
    width: Optional[int] = None
    height: Optional[int] = None
    page_count: Optional[int] = None


def render_annotated_plan_source_export(
    plan: dict[str, Any],
    source_bytes: bytes,
    defects: Optional[list[dict[str, Any]]] = None,
    output_format: str = "png",
) -> PlanExportResult:
    if output_format == "pdf" or is_pdf_plan(plan, source_bytes):
        return render_annotated_plan_pdf(plan, source_bytes, defects)

    image_result = render_annotated_plan_image(plan, source_bytes, defects, output_format)
    return PlanExportResult(
        content=image_result.content,
        mime_type=image_result.mime_type,
        file_extension=image_result.file_extension,
        width=image_result.width,
        height=image_result.height,
    )


def render_annotated_plan_pdf(
    plan: dict[str, Any],
    source_bytes: bytes,
    defects: Optional[list[dict[str, Any]]] = None,
) -> PlanExportResult:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - optional dependency surface
        raise PlanRenderError("PyMuPDF ist nicht installiert.") from exc

    try:
        document = fitz.open(stream=source_bytes, filetype="pdf")
    except Exception as exc:
        raise PlanRenderUnsupportedError("PDF-Plan konnte nicht geoeffnet werden.") from exc

    if document.page_count < 1:
        raise PlanRenderUnsupportedError("PDF-Plan enthaelt keine Seite.")

    defects_by_id = {str(defect.get("id")): defect for defect in defects or []}
    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        page_number = page_index + 1
        for marker_index, marker in enumerate(markers_for_page(plan, page_number), start=1):
            label = resolve_marker_label(
                marker,
                defects_by_id.get(str(marker.get("defect_id"))),
                str(marker_index),
            )
            _draw_pdf_marker(page, marker, label)

    return PlanExportResult(
        content=document.tobytes(deflate=True, garbage=3),
        mime_type="application/pdf",
        file_extension="pdf",
        page_count=document.page_count,
    )


def plan_export_fingerprint(
    plan: dict[str, Any],
    source_media: dict[str, Any],
    defects: list[dict[str, Any]],
    export_format: str,
    file_extension: str,
) -> str:
    defects_by_id = {str(defect.get("id")): defect for defect in defects}
    markers = []
    for index, marker in enumerate(plan.get("markers") or [], start=1):
        defect = defects_by_id.get(str(marker.get("defect_id")))
        markers.append(
            {
                "id": _text(marker.get("id")),
                "defect_id": _text(marker.get("defect_id")),
                "page_number": marker.get("page_number") or 1,
                "x_norm": round(normalized_coordinate(marker.get("x_norm")), 8),
                "y_norm": round(normalized_coordinate(marker.get("y_norm")), 8),
                "label": resolve_marker_label(marker, defect, str(index)),
            }
        )

    payload = {
        "plan_id": _text(plan.get("id")),
        "plan_revision": plan.get("revision"),
        "source_media_id": _text(source_media.get("id")),
        "source_storage_path": _text(source_media.get("storage_path")),
        "source_updated_at": _text(source_media.get("updated_at")),
        "export_format": export_format,
        "file_extension": file_extension,
        "selected_page": plan.get("selected_page"),
        "markers": markers,
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:20]


def _draw_pdf_marker(page: Any, marker: dict[str, Any], label: str) -> None:
    import fitz

    rect = page.rect
    x = rect.x0 + normalized_coordinate(marker.get("x_norm")) * rect.width
    y = rect.y0 + normalized_coordinate(marker.get("y_norm")) * rect.height
    radius = max(
        6.0,
        rect.width * MARKER_TARGET_DIAMETER_INCHES / (2 * MARKER_TARGET_WORD_WIDTH_INCHES),
    )
    radius = min(radius, max(6.0, min(rect.width, rect.height) * 0.032), 20.0)
    text = _text(label)
    font_size = max(8.5, radius * 1.45)
    try:
        text_width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
    except Exception:
        text_width = len(text) * font_size * 0.6
    badge_width = radius * 2
    while text and text_width + radius * 0.35 > badge_width and font_size > 6.0:
        font_size -= 0.5
        try:
            text_width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
        except Exception:
            text_width = len(text) * font_size * 0.6
    badge_height = radius * 2
    half_width = badge_width / 2
    half_height = badge_height / 2
    x = max(rect.x0 + half_width, min(rect.x1 - half_width, x))
    y = max(rect.y0 + half_height, min(rect.y1 - half_height, y))
    badge_rect = fitz.Rect(
        x - half_width,
        y - half_height,
        x + half_width,
        y + half_height,
    )

    page.draw_rect(
        badge_rect,
        color=(1, 1, 1),
        fill=(0.81, 0.15, 0.15),
        width=max(1.5, radius / 8),
        overlay=True,
    )
    if text:
        page.insert_textbox(
            badge_rect,
            text,
            fontsize=font_size,
            fontname="helv",
            color=(1, 1, 1),
            align=fitz.TEXT_ALIGN_CENTER,
            overlay=True,
        )


def _text(value: object) -> str:
    return str(value or "").strip()
