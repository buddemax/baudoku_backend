from __future__ import annotations

from pathlib import Path

from docx import Document

from baudoku_api.reports.pdf_builder import ReportPdfBuilder


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da63fcff1f0003030200efbfa7db0000000049454e44ae426082"
)
PNG_BLUE_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c636060f80f00010301000889c2ec0000000049454e44ae426082"
)


def test_report_pdf_builds_valid_pdf_without_empty_conclusion_or_coordinates(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "template.docx"
    Document().save(template_path)
    builder = ReportPdfBuilder(template_path=template_path, image_loader=_image_loader_with_plan)

    pdf_bytes = builder.build(
        project=_project(),
        defects=_defects(),
        general_findings=_general_findings(),
        project_conclusion=None,
        plans=[
            {
                "name": "Grundriss EG",
                "media_asset": {
                    "media_type": "plan_render",
                    "storage_path": "projects/demo/plans/grundriss-render.png",
                },
                "markers": [
                    {
                        "defect_id": "defect-1",
                        "page_number": 1,
                        "x_norm": 0.5,
                        "y_norm": 0.25,
                    }
                ],
            }
        ],
    )

    assert pdf_bytes.startswith(b"%PDF")
    text = _pdf_text(pdf_bytes)
    assert "BBA Baubegehungsbericht" in text
    assert "Projektnummer" in text
    assert "BBA-2026-017" in text
    assert "Fazit" not in text
    assert "Grundriss EG" in text
    assert "Plan Grundriss EG: markierte Verortung" in text
    assert "Marker 1 - Mangel" not in text
    assert "Arbeitsnummer 1" not in text
    assert "Keine Marker" not in text
    assert "X 50%" not in text
    assert "Y 25%" not in text


def _image_loader_with_plan(storage_path: str) -> bytes:
    if storage_path == "projects/demo/plans/grundriss-render.png":
        return PNG_BLUE_1X1
    return PNG_1X1


def _project() -> dict[str, object]:
    return {
        "project_number": "BBA-2026-017",
        "client_name": "Muster GmbH",
        "object_address": "Musterstrasse 1, 15526 Bad Saarow",
        "site_visit_date": "2026-05-04",
        "appraisal_type": "Abnahmebegehung",
        "lead_user_display_name": "Max Mustermann",
    }


def _general_findings() -> list[dict[str, object]]:
    return [{"text": "Feuchtigkeit im Kellerbereich pruefen.", "sort_order": 1}]


def _defects() -> list[dict[str, object]]:
    return [
        {
            "id": "defect-1",
            "kind": "defect",
            "local_label": "Mangel 1",
            "report_number": 1,
            "trade_name_snapshot": "Putz",
            "category": "Innen",
            "description": "Riss im Putz am Treppenhaus.",
            "media_links": [
                {
                    "include_in_report": True,
                    "sort_order": 1,
                    "media_asset": {
                        "media_type": "photo",
                        "storage_path": "projects/demo/photos/riss.png",
                        "caption": "Detailfoto Rissbildung",
                    },
                }
            ],
        }
    ]


def _pdf_text(pdf_bytes: bytes) -> str:
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(page.get_text() for page in document)
