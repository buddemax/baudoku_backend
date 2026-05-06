from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional


@dataclass(frozen=True)
class ProcessedReportImage:
    content: bytes
    width_px: int
    height_px: int
    display_width_inches: float
    display_height_inches: float
    mime_type: str = "image/jpeg"


def process_report_image(
    image_bytes: bytes,
    *,
    max_long_edge_px: int,
    max_width_inches: float,
    max_height_inches: float,
) -> ProcessedReportImage:
    """Normalize and bound a report image without cropping."""
    try:
        from PIL import Image, ImageOps
    except Exception as exc:  # pragma: no cover - optional dependency surface
        raise RuntimeError("Pillow ist nicht installiert.") from exc

    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    image.load()

    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, "white")
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        background.paste(image.convert("RGBA"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")

    image.thumbnail((max_long_edge_px, max_long_edge_px))
    width_px, height_px = image.size
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True, progressive=True)
    display_width, display_height = fit_dimensions(
        width_px,
        height_px,
        max_width_inches=max_width_inches,
        max_height_inches=max_height_inches,
    )
    return ProcessedReportImage(
        content=buffer.getvalue(),
        width_px=width_px,
        height_px=height_px,
        display_width_inches=display_width,
        display_height_inches=display_height,
    )


def fit_dimensions(
    width_px: Optional[int],
    height_px: Optional[int],
    *,
    max_width_inches: float,
    max_height_inches: float,
) -> tuple[float, float]:
    if not width_px or not height_px or width_px <= 0 or height_px <= 0:
        return max_width_inches, max_height_inches

    scale = min(max_width_inches / width_px, max_height_inches / height_px)
    return width_px * scale, height_px * scale
