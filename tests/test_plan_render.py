from __future__ import annotations

from io import BytesIO

from baudoku_api.reports.plan_render import (
    render_annotated_plan_image,
    render_annotated_plan,
    resolve_marker_label,
)
from baudoku_api.reports.plan_export import (
    plan_export_fingerprint,
    render_annotated_plan_pdf,
)
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.schemas import PlanMarkerCreate
from workflow_fakes import DEFECT_ID, PLAN_ID, FakeWorkflowRepository


def test_render_image_plan_with_markers_returns_valid_png() -> None:
    from PIL import Image

    source_bytes = _image_bytes("PNG", size=(240, 120), color=(245, 245, 240))
    plan = {
        "file_type": "png",
        "selected_page": 1,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }
    defects = [{"id": "defect-1", "report_number": 7, "local_label": "Mangel 7"}]

    result = render_annotated_plan(plan, source_bytes, defects)

    assert result.media_type == "plan_render"
    assert result.mime_type == "image/png"
    assert result.file_extension == "png"
    assert result.width == 240
    assert result.height == 120
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")

    rendered = Image.open(BytesIO(result.content)).convert("RGBA")
    assert rendered.size == (240, 120)
    assert _crop_contains_changed_pixels(rendered, center=(120, 60), base_color=(245, 245, 240))


def test_render_pdf_plan_first_page_with_markers_returns_valid_png() -> None:
    from PIL import Image

    source_bytes = _pdf_bytes(width=180, height=120)
    plan = {
        "file_type": "pdf",
        "selected_page": 1,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }
    defects = [{"id": "defect-1", "report_number": 4, "local_label": "Mangel 4"}]

    result = render_annotated_plan(plan, source_bytes, defects)

    assert result.media_type == "plan_render"
    assert result.mime_type == "image/png"
    assert result.file_extension == "png"
    assert result.width >= 180
    assert result.height >= 120
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")

    rendered = Image.open(BytesIO(result.content)).convert("RGBA")
    assert _crop_contains_changed_pixels(
        rendered,
        center=(rendered.width // 2, rendered.height // 2),
        base_color=(255, 255, 255),
    )


def test_render_preserves_duplicate_markers_for_same_defect() -> None:
    from PIL import Image

    source_bytes = _image_bytes("PNG", size=(260, 140), color=(245, 245, 240))
    plan = {
        "file_type": "png",
        "selected_page": 1,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.25,
                "y_norm": 0.5,
            },
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.75,
                "y_norm": 0.5,
            },
        ],
    }
    defects = [{"id": "defect-1", "report_number": 7, "local_label": "Mangel 7"}]

    result = render_annotated_plan(plan, source_bytes, defects)
    rendered = Image.open(BytesIO(result.content)).convert("RGBA")

    assert _crop_contains_changed_pixels(rendered, center=(65, 70), base_color=(245, 245, 240))
    assert _crop_contains_changed_pixels(rendered, center=(194, 70), base_color=(245, 245, 240))


def test_render_large_plan_uses_smaller_readable_marker_badge() -> None:
    from PIL import Image

    source_bytes = _image_bytes("PNG", size=(1600, 1000), color=(245, 245, 240))
    plan = {
        "file_type": "png",
        "selected_page": 1,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }
    defects = [{"id": "defect-1", "report_number": 42, "local_label": "Mangel 42"}]

    result = render_annotated_plan(plan, source_bytes, defects)
    rendered = Image.open(BytesIO(result.content)).convert("RGBA")

    red_pixels = _count_red_pixels(rendered, center=(800, 500), radius=90)
    assert red_pixels > 2000
    assert red_pixels < 3600


def test_render_high_resolution_plan_scales_badge_for_word_output() -> None:
    from PIL import Image

    source_bytes = _image_bytes("PNG", size=(3000, 1800), color=(245, 245, 240))
    plan = {
        "file_type": "png",
        "selected_page": 1,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }
    defects = [{"id": "defect-1", "local_label": "Ticketnummer 001"}]

    result = render_annotated_plan(plan, source_bytes, defects)
    rendered = Image.open(BytesIO(result.content)).convert("RGBA")

    red_pixels = _count_red_pixels(rendered, center=(1500, 900), radius=150)
    assert red_pixels > 24000
    assert red_pixels < 32000


def test_marker_label_uses_exact_work_number_before_report_number() -> None:
    defect = {"report_number": 12, "local_label": "OG1"}

    assert resolve_marker_label({"label_override": "A1"}, defect) == "A1"
    assert resolve_marker_label({"label_override": " "}, defect) == "12"
    assert (
        resolve_marker_label({"label_override": "", "defect_id": "defect-1"}, {"local_label": "EG-02"})
        == "EG-02"
    )
    assert resolve_marker_label({}, {"local_label": "Ticketnummer 001"}) == "Ticketnummer 001"
    assert resolve_marker_label({}, {"local_label": "001"}) == "001"
    assert resolve_marker_label({}, {"local_label": "1"}) == "1"
    assert resolve_marker_label({}, {}, "5") == "5"
    assert resolve_marker_label({"label_override": ""}, {}) == ""


def test_render_jpg_plan_export_preserves_jpg_format_with_marker() -> None:
    from PIL import Image

    source_bytes = _image_bytes("JPEG", size=(240, 120), color=(245, 245, 240))
    plan = {
        "file_type": "jpg",
        "selected_page": 1,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }

    result = render_annotated_plan_image(
        plan,
        source_bytes,
        [{"id": "defect-1", "report_number": 8, "local_label": "Alt"}],
        output_format="jpg",
    )

    assert result.mime_type == "image/jpeg"
    assert result.file_extension == "jpg"
    assert result.content.startswith(b"\xff\xd8")
    rendered = Image.open(BytesIO(result.content)).convert("RGBA")
    assert _crop_contains_changed_pixels(rendered, center=(120, 60), base_color=(245, 245, 240))


def test_render_pdf_export_keeps_all_pages_and_places_page_markers() -> None:
    import fitz

    source_bytes = _pdf_bytes(width=220, height=140, pages=2)
    plan = {
        "file_type": "pdf",
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            },
            {
                "defect_id": "defect-2",
                "page_number": 2,
                "x_norm": 0.25,
                "y_norm": 0.75,
            },
        ],
    }

    result = render_annotated_plan_pdf(
        plan,
        source_bytes,
        [
            {"id": "defect-1", "report_number": 1},
            {"id": "defect-2", "report_number": 2},
        ],
    )

    assert result.mime_type == "application/pdf"
    assert result.file_extension == "pdf"
    exported = fitz.open(stream=result.content, filetype="pdf")
    assert exported.page_count == 2
    first = _render_pdf_page(exported, 0)
    second = _render_pdf_page(exported, 1)
    first_red_pixels = _count_red_pixels(first, center=(220, 140), radius=60)
    second_red_pixels = _count_red_pixels(second, center=(110, 210), radius=60)
    assert first_red_pixels > 550
    assert first_red_pixels < 1100
    assert second_red_pixels > 550
    assert second_red_pixels < 1100


def test_plan_export_fingerprint_changes_with_marker_or_label() -> None:
    plan = {
        "id": "plan-1",
        "revision": 1,
        "selected_page": 1,
        "markers": [
            {
                "id": "marker-1",
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }
    media = {"id": "media-1", "storage_path": "projects/project-1/plans/source.pdf"}
    defects = [{"id": "defect-1", "report_number": 1}]

    base = plan_export_fingerprint(plan, media, defects, "source", "pdf")
    moved = plan_export_fingerprint(
        {**plan, "markers": [{**plan["markers"][0], "x_norm": 0.75}]},
        media,
        defects,
        "source",
        "pdf",
    )
    renumbered = plan_export_fingerprint(
        plan,
        media,
        [{"id": "defect-1", "report_number": 2}],
        "source",
        "pdf",
    )

    assert moved != base
    assert renumbered != base


def test_fake_workflow_repository_preserves_duplicate_plan_markers() -> None:
    repository = FakeWorkflowRepository()
    repository.plans[PLAN_ID] = {"id": PLAN_ID, "markers": []}
    user = AuthenticatedUser(
        id="11111111-1111-4111-8111-111111111111",
        email="gutachter@example.com",
        display_name="Gutachter",
    )
    payload = PlanMarkerCreate(
        defect_id=DEFECT_ID,
        x_norm=0.4,
        y_norm=0.6,
        page_number=1,
    )

    first = repository.create_plan_marker(PLAN_ID, payload, user)
    second = repository.create_plan_marker(PLAN_ID, payload, user)

    assert first["id"] != second["id"]
    assert repository.plans[PLAN_ID]["markers"] == [first, second]
    assert len(repository.markers) == 2


def _image_bytes(format_name: str, size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format=format_name)
    return buffer.getvalue()


def _pdf_bytes(width: int, height: int, pages: int = 1) -> bytes:
    import fitz

    document = fitz.open()
    for index in range(pages):
        page = document.new_page(width=width, height=height)
        page.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))
        page.insert_text((24, 48), f"PDF Plan {index + 1}", fontsize=14, color=(0.1, 0.1, 0.1))
    return document.tobytes()


def _render_pdf_page(document: object, page_index: int) -> object:
    from PIL import Image
    import fitz

    pixmap = document.load_page(page_index).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
    image = Image.open(BytesIO(pixmap.tobytes("png")))
    image.load()
    return image.convert("RGBA")


def _crop_contains_changed_pixels(
    image: object,
    center: tuple[int, int],
    base_color: tuple[int, int, int],
) -> bool:
    x_center, y_center = center
    for x in range(x_center - 12, x_center + 13):
        for y in range(y_center - 12, y_center + 13):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha and (red, green, blue) != base_color:
                return True
    return False


def _count_red_pixels(image: object, center: tuple[int, int], radius: int) -> int:
    x_center, y_center = center
    count = 0
    for x in range(x_center - radius, x_center + radius + 1):
        for y in range(y_center - radius, y_center + radius + 1):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha and red > 160 and green < 100 and blue < 100:
                count += 1
    return count
