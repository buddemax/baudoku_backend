from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal, Optional


PLAN_RENDER_MEDIA_TYPE = "plan_render"
PLAN_RENDER_MIME_TYPE = "image/png"
PLAN_RENDER_FILE_EXTENSION = "png"
MARKER_TARGET_DIAMETER_INCHES = 0.30
MARKER_TARGET_WORD_WIDTH_INCHES = 6.5


class PlanRenderError(Exception):
    """Raised when an annotated plan image cannot be rendered."""


class PlanRenderUnsupportedError(PlanRenderError):
    """Raised when a plan source format is not supported by the renderer."""


@dataclass(frozen=True)
class PlanRenderResult:
    content: bytes
    width: int
    height: int
    media_type: Literal["plan_render"] = PLAN_RENDER_MEDIA_TYPE
    mime_type: Literal["image/png"] = PLAN_RENDER_MIME_TYPE
    file_extension: Literal["png"] = PLAN_RENDER_FILE_EXTENSION


@dataclass(frozen=True)
class PlanImageRenderResult:
    content: bytes
    width: int
    height: int
    mime_type: str
    file_extension: str


def render_annotated_plan(
    plan: dict[str, Any],
    source_bytes: bytes,
    defects: Optional[list[dict[str, Any]]] = None,
) -> PlanRenderResult:
    """Render a plan source with normalized marker overlays to a PNG."""
    result = render_annotated_plan_image(plan, source_bytes, defects, output_format="png")
    return PlanRenderResult(content=result.content, width=result.width, height=result.height)


def render_annotated_plan_image(
    plan: dict[str, Any],
    source_bytes: bytes,
    defects: Optional[list[dict[str, Any]]] = None,
    output_format: str = "png",
) -> PlanImageRenderResult:
    """Render a plan source with normalized marker overlays to PNG or JPG."""
    if _is_pdf_plan(plan, source_bytes):
        image = _open_pdf_first_page(source_bytes, _optional_int(plan.get("selected_page")) or 1)
    else:
        image = _open_plan_image(source_bytes)
    width, height = image.size
    draw, font = _draw_context(image)
    defects_by_id = {str(defect.get("id")): defect for defect in defects or []}

    for index, marker in enumerate(_markers_for_selected_page(plan), start=1):
        x_norm = _normalized_coordinate(marker.get("x_norm"))
        y_norm = _normalized_coordinate(marker.get("y_norm"))
        x = int(round(x_norm * (width - 1)))
        y = int(round(y_norm * (height - 1)))
        label = _marker_label(marker, defects_by_id, str(index))
        _draw_marker(draw, font, image.size, x, y, label)

    buffer = BytesIO()
    file_extension = _normalized_image_extension(output_format)
    if file_extension == "jpg":
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
        return PlanImageRenderResult(
            content=buffer.getvalue(),
            width=width,
            height=height,
            mime_type="image/jpeg",
            file_extension="jpg",
        )
    image.convert("RGB").save(buffer, format="PNG")
    return PlanImageRenderResult(
        content=buffer.getvalue(),
        width=width,
        height=height,
        mime_type="image/png",
        file_extension="png",
    )


def _open_plan_image(source_bytes: bytes) -> Any:
    try:
        from PIL import Image, UnidentifiedImageError
    except Exception as exc:  # pragma: no cover - optional dependency surface
        raise PlanRenderError("Pillow ist nicht installiert.") from exc

    try:
        image = Image.open(BytesIO(source_bytes))
        image.load()
    except UnidentifiedImageError as exc:
        raise PlanRenderUnsupportedError(
            "Planquelle konnte nicht als JPG oder PNG geoeffnet werden."
        ) from exc
    except Exception as exc:
        raise PlanRenderError("Planbild konnte nicht geladen werden.") from exc

    if image.format not in {"JPEG", "PNG"}:
        raise PlanRenderUnsupportedError("Nur JPG- und PNG-Planbilder werden unterstuetzt.")
    return image.convert("RGBA")


def _open_pdf_first_page(source_bytes: bytes, selected_page: int) -> Any:
    try:
        import fitz
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional dependency surface
        raise PlanRenderError("PyMuPDF ist nicht installiert.") from exc

    try:
        document = fitz.open(stream=source_bytes, filetype="pdf")
    except Exception as exc:
        raise PlanRenderUnsupportedError("PDF-Plan konnte nicht geoeffnet werden.") from exc

    if document.page_count < 1:
        raise PlanRenderUnsupportedError("PDF-Plan enthaelt keine Seite.")

    page_index = max(0, min(document.page_count - 1, selected_page - 1))
    page = document.load_page(page_index)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png")))
    image.load()
    return image.convert("RGBA")


def _draw_context(image: Any) -> tuple[Any, Any]:
    from PIL import ImageDraw, ImageFont

    return ImageDraw.Draw(image), ImageFont


def _draw_marker(
    draw: Any,
    font: Any,
    image_size: tuple[int, int],
    x: int,
    y: int,
    label: str,
) -> None:
    width, height = image_size
    target_radius = int(
        round(width * MARKER_TARGET_DIAMETER_INCHES / (2 * MARKER_TARGET_WORD_WIDTH_INCHES))
    )
    badge_radius = max(13, target_radius)
    badge_radius = min(badge_radius, max(13, int(round(min(width, height) * 0.10))))
    text = _text(label)
    max_badge_width = max(2, min(width - 2, max(badge_radius * 2, int(round(width * 0.42)))))
    font_size = max(13, int(round(badge_radius * 1.22)))
    badge_font = _badge_font(font, font_size)
    text_width, text_height = _text_size(draw, text, badge_font) if text else (0, 0)
    padding_x = max(5, badge_radius // 3)
    while text and text_width + padding_x * 2 > max_badge_width and font_size > 8:
        font_size -= 1
        badge_font = _badge_font(font, font_size)
        text_width, text_height = _text_size(draw, text, badge_font)
    badge_width = max(badge_radius * 2, text_width + padding_x * 2)
    badge_width = min(max_badge_width, badge_width)
    badge_height = badge_radius * 2

    half_width = badge_width // 2
    half_height = badge_height // 2
    x = max(half_width, min(width - half_width - 1, x))
    y = max(half_height, min(height - half_height - 1, y))
    outline_width = max(2, badge_radius // 6)

    badge_bounds = (
        x - half_width,
        y - half_height,
        x + half_width,
        y + half_height,
    )
    draw.rounded_rectangle(
        badge_bounds,
        radius=half_height,
        fill=(207, 38, 38, 230),
        outline=(255, 255, 255, 255),
        width=outline_width,
    )

    if text:
        text_x = x - text_width / 2
        text_y = y - text_height / 2 - max(1, badge_radius // 16)
        draw.text(
            (text_x, text_y),
            text,
            fill=(255, 255, 255, 255),
            font=badge_font,
        )


def _badge_font(image_font: Any, size: int) -> Any:
    for font_name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return image_font.truetype(font_name, size=size)
        except Exception:
            pass
    return image_font.load_default()


def _text_size(draw: Any, text: str, font: Any) -> tuple[int, int]:
    if hasattr(draw, "textbbox"):
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    return draw.textsize(text, font=font)


def _markers_for_selected_page(plan: dict[str, Any]) -> list[dict[str, Any]]:
    selected_page = _optional_int(plan.get("selected_page")) or 1
    return markers_for_page(plan, selected_page)


def markers_for_page(plan: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
    markers = plan.get("markers") or []
    return [
        marker
        for marker in markers
        if (_optional_int(marker.get("page_number")) or 1) == page_number
    ]


def resolve_marker_label(
    marker: dict[str, Any],
    defect: Optional[dict[str, Any]] = None,
    fallback: str = "",
) -> str:
    """Return the short marker badge label shown in the circle."""
    reference = resolve_marker_reference(marker, defect)
    if reference:
        return display_marker_label(reference)
    return display_marker_label(fallback)


def resolve_marker_reference(
    marker: dict[str, Any],
    defect: Optional[dict[str, Any]] = None,
) -> str:
    """Return the full user-facing work number/reference for marker legends."""
    defect = defect or {}
    for value in (
        marker.get("label_override"),
        defect.get("report_number"),
        defect.get("local_label"),
    ):
        text = _text(value)
        if text:
            return text
    return ""


def display_marker_label(value: object) -> str:
    return _text(value)


def _marker_label(
    marker: dict[str, Any],
    defects_by_id: dict[str, dict[str, Any]],
    fallback: str,
) -> str:
    return resolve_marker_label(marker, defects_by_id.get(str(marker.get("defect_id"))), fallback)


def _is_pdf_plan(plan: dict[str, Any], source_bytes: bytes) -> bool:
    media = plan.get("media_asset") or {}
    return (
        _text(plan.get("file_type")).casefold() == "pdf"
        or _text(media.get("mime_type")).casefold() == "application/pdf"
        or source_bytes.lstrip().startswith(b"%PDF")
    )


def is_pdf_plan(plan: dict[str, Any], source_bytes: bytes) -> bool:
    return _is_pdf_plan(plan, source_bytes)


def normalized_coordinate(value: object) -> float:
    return _normalized_coordinate(value)


def _normalized_coordinate(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _optional_int(value: object) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalized_image_extension(output_format: str) -> str:
    value = _text(output_format).casefold()
    if value in {"jpg", "jpeg"}:
        return "jpg"
    return "png"


def _text(value: object) -> str:
    return str(value or "").strip()
