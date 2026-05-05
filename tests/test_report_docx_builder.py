from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document

from baudoku_api.reports.docx_builder import ReportDocxBuilder


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da63fcff1f0003030200efbfa7db0000000049454e44ae426082"
)
PNG_BLUE_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
    "0000000c49444154789c636060f80f00010301000889c2ec0000000049454e44ae426082"
)


def test_report_docx_is_valid_zip_and_contains_required_report_text(tmp_path: Path) -> None:
    template_path = tmp_path / "template.docx"
    _write_template(template_path)
    builder = ReportDocxBuilder(template_path=template_path, image_loader=_image_loader)

    docx_bytes = builder.build(
        project=_project(),
        defects=_defects(),
        general_findings=_general_findings(),
        project_conclusion=_project_conclusion(),
        plans=[],
    )

    names = _zip_names(docx_bytes)
    assert "[Content_Types].xml" in names
    assert "_rels/.rels" in names
    assert "word/document.xml" in names
    assert any(name.startswith("word/media/") for name in names)

    text = _document_text(docx_bytes)
    assert "BBA Briefbogen Dummy-Template" in text
    assert "BBA Baubegehungsbericht" in text
    assert "Projektnummer: BBA-2026-017" in text
    assert "Auftraggeber: Muster GmbH" in text
    assert "Objektadresse: Musterstrasse 1, 15526 Bad Saarow" in text
    assert "Datum: 2026-05-04" in text
    assert "Bearbeiter: Max Mustermann" in text
    assert "Gutachtentyp: Abnahmebegehung" in text
    assert "Allgemeine Feststellungen" in text
    assert "Feuchtigkeit im Kellerbereich pruefen." in text
    assert "M\u00e4ngel und Hinweise" in text
    assert "Mangel 1 - Mangel" in text
    assert "Riss im Putz am Treppenhaus." in text
    assert "Fotos" in text
    assert "Detailfoto Rissbildung" in text
    assert "Fazit" in text
    assert "Das Objekt ist mit Nacharbeiten abnahmefaehig." in text


def test_report_docx_omits_internal_status_fields_and_empty_plan_chapter(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "template.docx"
    _write_template(template_path)
    builder = ReportDocxBuilder(template_path=template_path, image_loader=_image_loader)

    docx_bytes = builder.build(
        project={
            **_project(),
            "status": "Bereit zur Pruefung",
            "sync_status": "synced",
            "qs_status": "unchecked",
        },
        defects=_defects(),
        general_findings=[
            {
                **_general_findings()[0],
                "status": "confirmed",
                "transcript_status": "suggested",
            }
        ],
        project_conclusion={**_project_conclusion(), "status": "confirmed"},
        plans=[],
    )

    text = _document_text(docx_bytes)
    text_lower = text.casefold()
    assert "ai_status" not in text_lower
    assert "caption_status" not in text_lower
    assert "transcript_status" not in text_lower
    assert "sync_status" not in text_lower
    assert "qs_status" not in text_lower
    assert "ki-status" not in text_lower
    assert "sync-status" not in text_lower
    assert "qs-status" not in text_lower
    assert "suggested" not in text_lower
    assert "confirmed" not in text_lower
    assert "Bereit zur Pruefung" not in text
    assert "Planverortung" not in text


def test_report_docx_embeds_plan_render_after_defect_list(tmp_path: Path) -> None:
    template_path = tmp_path / "template.docx"
    _write_template(template_path)
    builder = ReportDocxBuilder(
        template_path=template_path,
        image_loader=_image_loader_with_plan,
    )

    docx_bytes = builder.build(
        project=_project(),
        defects=_defects(),
        general_findings=[],
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

    assert sum(name.startswith("word/media/") for name in _zip_names(docx_bytes)) >= 2
    text = _document_text(docx_bytes)
    assert text.index("M\u00e4ngel und Hinweise") < text.index("Planverortung")
    assert "Grundriss EG" in text
    assert "Marker 1 - Mangel: Riss im Putz am Treppenhaus." in text
    assert "Arbeitsnummer 1" in text
    assert "Gewerk Putz" in text
    assert "Kategorie Innen" in text


def test_report_docx_preserves_duplicate_markers_and_label_precedence(tmp_path: Path) -> None:
    template_path = tmp_path / "template.docx"
    _write_template(template_path)
    builder = ReportDocxBuilder(
        template_path=template_path,
        image_loader=_image_loader_with_plan,
    )

    docx_bytes = builder.build(
        project=_project(),
        defects=[
            {
                "id": "defect-1",
                "kind": "defect",
                "local_label": "Mangel 1",
                "report_number": 1,
                "description": "Riss im Putz am Treppenhaus.",
                "media_links": [],
            },
            {
                "id": "defect-2",
                "kind": "defect",
                "local_label": "2",
                "report_number": None,
                "description": "Fehlstelle am Sockel.",
                "media_links": [],
            },
        ],
        general_findings=[],
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
                        "x_norm": 0.1,
                        "y_norm": 0.2,
                        "label_override": "A",
                    },
                    {
                        "defect_id": "defect-1",
                        "page_number": 1,
                        "x_norm": 0.3,
                        "y_norm": 0.4,
                    },
                    {
                        "defect_id": "defect-1",
                        "page_number": 1,
                        "x_norm": 0.5,
                        "y_norm": 0.6,
                    },
                    {
                        "defect_id": "defect-2",
                        "page_number": 1,
                        "x_norm": 0.7,
                        "y_norm": 0.8,
                    },
                ],
            }
        ],
    )

    text = _document_text(docx_bytes)
    assert "Marker A - Mangel: Riss im Putz am Treppenhaus." in text
    assert text.count("Marker 1 - Mangel: Riss im Putz am Treppenhaus.") == 2
    assert "Marker 2 - Mangel: Fehlstelle am Sockel." in text
    assert "Arbeitsnummer 2" in text


def test_report_docx_includes_plan_render_warning(tmp_path: Path) -> None:
    template_path = tmp_path / "template.docx"
    _write_template(template_path)
    builder = ReportDocxBuilder(template_path=template_path, image_loader=_image_loader)

    docx_bytes = builder.build(
        project=_project(),
        defects=_defects(),
        general_findings=[],
        project_conclusion=None,
        plans=[
            {
                "name": "Grundriss EG",
                "render_error": (
                    "Planbild konnte nicht fuer den Bericht gerendert werden. "
                    "Marker werden darunter nur als Liste ausgegeben."
                ),
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

    text = _document_text(docx_bytes)
    assert "Planbild konnte nicht fuer den Bericht gerendert werden." in text
    assert "Marker 1 - Mangel: Riss im Putz am Treppenhaus." in text


def test_default_fallback_template_builds_a_valid_docx() -> None:
    builder = ReportDocxBuilder(image_loader=_image_loader)

    docx_bytes = builder.build(
        project=_project(),
        defects=[],
        general_findings=[],
        project_conclusion=None,
        plans=[],
    )

    assert "word/document.xml" in _zip_names(docx_bytes)
    text = _document_text(docx_bytes)
    assert "BBA Briefbogen Dummy-Template" in text
    assert "Projektnummer: BBA-2026-017" in text


def _write_template(path: Path) -> None:
    document = Document()
    document.add_paragraph("BBA Briefbogen Dummy-Template")
    document.save(path)


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
    return [
        {
            "text": "Feuchtigkeit im Kellerbereich pruefen.",
            "sort_order": 1,
            "status": "confirmed",
        }
    ]


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
            "ai_status": "suggested",
            "media_links": [
                {
                    "include_in_report": True,
                    "sort_order": 1,
                    "media_asset": {
                        "media_type": "photo",
                        "storage_path": "projects/demo/photos/riss.png",
                        "caption": "Detailfoto Rissbildung",
                        "caption_status": "suggested",
                    },
                }
            ],
        }
    ]


def _project_conclusion() -> dict[str, object]:
    return {"text": "Das Objekt ist mit Nacharbeiten abnahmefaehig.", "status": "confirmed"}


def _image_loader(storage_path: str) -> bytes:
    assert storage_path == "projects/demo/photos/riss.png"
    return PNG_1X1


def _image_loader_with_plan(storage_path: str) -> bytes:
    if storage_path == "projects/demo/plans/grundriss-render.png":
        return PNG_BLUE_1X1
    return PNG_1X1


def _zip_names(docx_bytes: bytes) -> set[str]:
    with ZipFile(BytesIO(docx_bytes)) as archive:
        assert archive.testzip() is None
        return set(archive.namelist())


def _document_text(docx_bytes: bytes) -> str:
    with ZipFile(BytesIO(docx_bytes)) as archive:
        document_xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return "\n".join(
        node.text or "" for node in root.findall(".//w:t", namespace) if node.text
    )
