from baudoku_api.repositories.projects import _derive_project_status, _report_warnings


def test_project_status_stays_draft_without_capture_data() -> None:
    status = _derive_project_status([], [], [], None, [], [])

    assert status == "Entwurf"


def test_project_status_moves_to_capture_when_only_media_exists() -> None:
    status = _derive_project_status(
        [],
        [{"media_type": "photo"}],
        [],
        None,
        [],
        [],
    )

    assert status == "In Erfassung"


def test_project_status_is_ready_when_preview_content_has_no_required_gap() -> None:
    status = _derive_project_status(
        [{"description": "Riss im Putz", "media_links": []}],
        [],
        [],
        None,
        [{"transcript_status": "suggested"}],
        [],
    )

    assert status == "Bereit zur Pruefung"


def test_project_status_keeps_capture_when_defect_description_is_missing() -> None:
    status = _derive_project_status(
        [{"description": " "}],
        [],
        [],
        {"text": "Fazit liegt vor."},
        [],
        [],
    )

    assert status == "In Erfassung"


def test_project_status_report_generated_wins() -> None:
    status = _derive_project_status([], [], [], None, [], [{"version_number": 1}])

    assert status == "Bericht generiert"


def test_report_warnings_label_defect_voice_notes_by_entry() -> None:
    warnings = _report_warnings(
        [
            {
                "id": "defect-1",
                "local_label": "Eng 01",
                "kind": "defect",
                "description": "Riss",
                "media_links": [{"media_asset": {"media_type": "photo", "caption_status": "edited"}}],
            }
        ],
        [{"text": "Allgemeine Feststellung"}],
        {"text": "Fazit"},
        [
            {
                "id": "voice-1",
                "defect_id": "defect-1",
                "target_type": "defect_description",
                "transcript_status": "error",
            }
        ],
    )

    assert [warning.message for warning in warnings] == [
        "Sprachnotiz Eng 01: KI-Transkription ist fehlgeschlagen."
    ]
