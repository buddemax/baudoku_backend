from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from baudoku_api.dependencies import (
    get_ai_provider,
    get_ai_rate_limiter,
    get_auth_service,
    get_project_repository,
)
from baudoku_api.main import create_app
from baudoku_api.repositories import ProjectRepositoryError
from baudoku_api.schemas import SyncOperation

from workflow_fakes import (
    DEFECT_ID,
    PLAN_ID,
    PROJECT_ID,
    FakeAiProvider,
    FakeAuthService,
    FakeRateLimiter,
    FakeWorkflowRepository,
    InMemorySyncRepository,
    _client,
    _headers,
    _user,
)


def _error_detail(response: object) -> dict[str, str]:
    detail = response.json()["detail"]
    if isinstance(detail, dict):
        return {
            "code": str(detail.get("code") or ""),
            "message": str(detail.get("message") or ""),
        }
    return {"code": "", "message": str(detail)}


def _create_voice_note_with_audio(client: TestClient) -> str:
    audio_id = str(uuid4())
    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss", "local_label": "Eng 01"},
    )
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": audio_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{audio_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )
    voice_note_response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": audio_id,
            "target_type": "defect_description",
            "defect_id": defect_response.json()["id"],
        },
    )
    return str(voice_note_response.json()["id"])


def test_defect_media_plan_report_and_sync_routes() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)

    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={
            "kind": "defect",
            "description": "Riss im Putz",
            "local_label": "1",
            "trade_name_snapshot": "Putz",
            "category": "Innen",
        },
    )
    defect_id = defect_response.json()["id"]
    notice_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={
            "kind": "notice",
            "description": "Fuge beobachten",
            "local_label": "2",
            "trade_name_snapshot": "Fassade",
            "category": "Aussen",
        },
    )
    notice_id = notice_response.json()["id"]

    filtered_defects_response = client.get(
        f"/v1/projects/{PROJECT_ID}/defects?kind=defect&category=Innen",
        headers=_headers(),
    )
    reorder_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects/reorder",
        headers=_headers(),
        json={"defect_ids": [notice_id, defect_id]},
    )

    upload_response = client.post(
        f"/v1/projects/{PROJECT_ID}/media/init-upload",
        headers=_headers(),
        json={"media_type": "photo", "mime_type": "image/jpeg", "file_name": "foto.jpg"},
    )
    media_id = upload_response.json()["media_id"]

    complete_response = client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "photo",
            "storage_bucket": "project-files",
            "storage_path": upload_response.json()["storage_path"],
            "mime_type": "image/jpeg",
            "file_size": 123,
            "width": 800,
            "height": 600,
        },
    )

    link_response = client.post(
        f"/v1/defects/{defect_id}/media-links",
        headers=_headers(),
        json={"media_asset_id": media_id},
    )
    media_list_response = client.get(
        f"/v1/projects/{PROJECT_ID}/media",
        headers=_headers(),
    )
    signed_url_response = client.get(
        f"/v1/media-assets/{media_id}/signed-url",
        headers=_headers(),
    )
    link_patch_response = client.patch(
        f"/v1/defect-media-links/{link_response.json()['id']}",
        headers=_headers(),
        json={"defect_id": notice_id, "include_in_report": False, "sort_order": 2},
    )

    plan_response = client.post(
        f"/v1/projects/{PROJECT_ID}/plans",
        headers=_headers(),
        json={"media_asset_id": media_id, "name": "Grundriss", "file_type": "jpg"},
    )

    marker_response = client.post(
        f"/v1/plans/{plan_response.json()['id']}/markers",
        headers=_headers(),
        json={"defect_id": defect_id, "x_norm": 0.4, "y_norm": 0.6, "page_number": 1},
    )
    plan_export_response = client.post(
        f"/v1/plans/{plan_response.json()['id']}/export",
        headers=_headers(),
        json={"format": "source"},
    )

    report_response = client.post(
        f"/v1/projects/{PROJECT_ID}/report/generate",
        headers=_headers(),
    )
    confirm_preview_response = client.post(
        f"/v1/projects/{PROJECT_ID}/report/preview/confirm",
        headers=_headers(),
    )
    sync_pull_response = client.get(
        "/v1/sync/pull?updated_since=2026-05-04T07:00:00Z",
        headers=_headers(),
    )
    link_delete_response = client.delete(
        f"/v1/defect-media-links/{link_response.json()['id']}",
        headers=_headers(),
    )

    sync_response = client.post(
        "/v1/sync/push",
        headers=_headers(),
        json={"operations": [{"client_operation_id": "op-1", "type": "defect.create", "payload": {}}]},
    )

    assert defect_response.status_code == 201
    assert notice_response.status_code == 201
    assert [item["id"] for item in filtered_defects_response.json()["items"]] == [defect_id]
    assert [item["report_number"] for item in reorder_response.json()["items"]] == [1, 2]
    assert complete_response.status_code == 200
    assert link_response.status_code == 201
    assert media_list_response.json()["items"][0]["id"] == media_id
    assert signed_url_response.json()["signed_url"] == "https://example.test/download"
    assert link_patch_response.json()["defect_id"] == notice_id
    assert link_patch_response.json()["include_in_report"] is False
    assert marker_response.status_code == 201
    assert plan_export_response.status_code == 200
    assert plan_export_response.json()["download_url"].endswith("_markiert.jpg")
    assert report_response.status_code == 200
    assert report_response.json()["version"]["download_url"].endswith("report.docx")
    assert report_response.json()["version"]["pdf_download_url"].endswith("report.pdf")
    assert confirm_preview_response.status_code == 200
    assert sync_pull_response.json()["tombstones"] == []
    assert link_delete_response.status_code == 204
    assert sync_response.json()["applied"] == [{"client_operation_id": "op-1"}]


def test_defect_requires_non_empty_local_label() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)

    missing_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss im Putz"},
    )
    blank_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss im Putz", "local_label": " "},
    )
    created_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss im Putz", "local_label": "1"},
    )
    blank_update_response = client.patch(
        f"/v1/defects/{created_response.json()['id']}",
        headers=_headers(),
        json={"local_label": " "},
    )

    assert missing_response.status_code == 422
    assert blank_response.status_code == 422
    assert created_response.status_code == 201
    assert blank_update_response.status_code == 422


def test_pdf_plan_create_returns_preview_media_asset() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    media_id = str(uuid4())
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "plan_source",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/plans/{media_id}.pdf",
            "mime_type": "application/pdf",
            "file_size": 456,
        },
    )

    response = client.post(
        f"/v1/projects/{PROJECT_ID}/plans",
        headers=_headers(),
        json={
            "media_asset_id": media_id,
            "name": "PDF-Grundriss",
            "file_type": "pdf",
            "page_count": 1,
        },
    )

    assert response.status_code == 201
    assert response.json()["preview_media_asset_id"]
    assert response.json()["preview_media_asset"]["media_type"] == "plan_render"
    assert response.json()["preview_media_asset"]["mime_type"] == "image/png"


def test_voice_notes_findings_conclusion_and_preview_routes() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    finding_response = client.post(
        f"/v1/projects/{PROJECT_ID}/general-findings",
        headers=_headers(),
        json={
            "text": "Feuchtigkeit im Keller pruefen.",
            "status": "confirmed",
        },
    )
    finding_id = finding_response.json()["id"]
    conclusion_response = client.put(
        f"/v1/projects/{PROJECT_ID}/conclusion",
        headers=_headers(),
        json={
            "text": "Das Objekt ist mit Nacharbeiten abnahmefaehig.",
            "status": "confirmed",
        },
    )
    preview_response = client.get(
        f"/v1/projects/{PROJECT_ID}/report/preview",
        headers=_headers(),
    )
    update_finding_response = client.patch(
        f"/v1/general-findings/{finding_id}",
        headers=_headers(),
        json={"text": "Feuchtigkeit im Kellerbereich pruefen."},
    )
    delete_finding_response = client.delete(
        f"/v1/general-findings/{finding_id}",
        headers=_headers(),
    )

    assert finding_response.status_code == 201
    assert conclusion_response.status_code == 200
    assert preview_response.json()["general_findings"][0]["id"] == finding_id
    assert preview_response.json()["project_conclusion"]["text"].startswith("Das Objekt")
    assert update_finding_response.json()["text"] == "Feuchtigkeit im Kellerbereich pruefen."
    assert delete_finding_response.status_code == 204


def test_voice_note_rejects_non_audio_media() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    media_id = str(uuid4())
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "photo",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/photos/{media_id}.jpg",
            "mime_type": "image/jpeg",
        },
    )

    response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={"media_asset_id": media_id, "target_type": "defect_description"},
    )

    assert response.status_code == 503
    assert "Sprachnotiz benoetigt Audio" in _error_detail(response)["message"]


def test_voice_note_can_be_attached_directly_to_defect() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={
            "kind": "defect",
            "description": "Riss neben Fenster",
            "local_label": "1",
            "trade_name_snapshot": "Putz",
        },
    )
    defect_id = defect_response.json()["id"]
    media_id = str(uuid4())
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{media_id}.m4a",
            "mime_type": "audio/mp4",
            "file_size": 456,
            "duration_seconds": 8.0,
        },
    )

    response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": media_id,
            "target_type": "defect_description",
            "defect_id": defect_id,
            "transcript": "Riss am Fenster dokumentieren.",
            "transcript_status": "edited",
        },
    )

    assert response.status_code == 201
    assert response.json()["target_type"] == "defect_description"
    assert response.json()["defect_id"] == defect_id
    assert response.json()["media_asset"]["media_type"] == "audio"


def test_defect_voice_note_requires_defect_id() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    media_id = str(uuid4())
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{media_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )

    response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={"media_asset_id": media_id, "target_type": "defect_description"},
    )

    assert response.status_code == 503
    assert _error_detail(response)["code"] == "REPOSITORY_UNAVAILABLE"
    assert "Mangel" in _error_detail(response)["message"]


def test_voice_note_rejects_free_target_type() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    media_id = str(uuid4())
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{media_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )

    response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": media_id,
            "target_type": "general_finding",
        },
    )

    assert response.status_code == 503
    assert _error_detail(response)["code"] == "REPOSITORY_UNAVAILABLE"
    assert "Eintrag" in _error_detail(response)["message"]


def test_media_complete_upload_with_caption_marks_caption_edited() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    media_id = str(uuid4())

    response = client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": media_id,
            "media_type": "photo",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/photos/{media_id}.jpg",
            "mime_type": "image/jpeg",
            "file_size": 123,
            "caption": "Riss am Fenstersturz.",
        },
    )

    assert response.status_code == 200
    assert response.json()["caption"] == "Riss am Fenstersturz."
    assert response.json()["caption_status"] == "edited"


def test_workflow_repository_errors_include_stable_code() -> None:
    class FailingRepository(FakeWorkflowRepository):
        def list_defects(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ProjectRepositoryError("Supabase-Anfrage fehlgeschlagen.")

    client = _client(FailingRepository())

    response = client.get(f"/v1/projects/{PROJECT_ID}/defects", headers=_headers())

    assert response.status_code == 503
    assert _error_detail(response) == {
        "code": "REPOSITORY_UNAVAILABLE",
        "message": "Supabase-Anfrage fehlgeschlagen.",
    }


def test_ai_transcription_image_description_and_job_routes() -> None:
    repository = FakeWorkflowRepository()
    client = _client(repository)
    audio_id = str(uuid4())
    photo_id = str(uuid4())
    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss", "local_label": "Eng 01"},
    )

    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": audio_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{audio_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )
    voice_note_response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": audio_id,
            "target_type": "defect_description",
            "defect_id": defect_response.json()["id"],
            "transcript_status": "open",
        },
    )
    voice_note_id = voice_note_response.json()["id"]
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": photo_id,
            "media_type": "photo",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/photos/{photo_id}.jpg",
            "mime_type": "image/jpeg",
        },
    )

    transcription_response = client.post(
        "/v1/ai/transcriptions",
        headers=_headers(),
        json={"voice_note_id": voice_note_id},
    )
    image_response = client.post(
        "/v1/ai/image-descriptions",
        headers=_headers(),
        json={"media_asset_id": photo_id},
    )
    wrong_media_response = client.post(
        "/v1/ai/image-descriptions",
        headers=_headers(),
        json={"media_asset_id": audio_id},
    )
    caption_response = client.patch(
        f"/v1/media-assets/{photo_id}",
        headers=_headers(),
        json={"caption": "Bestaetigte Bildunterschrift.", "caption_status": "confirmed"},
    )
    job_response = client.get(
        f"/v1/ai/jobs/{transcription_response.json()['id']}",
        headers=_headers(),
    )

    assert transcription_response.status_code == 202
    assert transcription_response.json()["status"] == "queued"
    assert repository.voice_notes[voice_note_id]["transcript_status"] == "suggested"
    assert image_response.status_code == 200
    assert image_response.json()["status"] == "done"
    assert wrong_media_response.status_code == 503
    assert caption_response.status_code == 200
    assert repository.media[photo_id]["caption"] == "Bestaetigte Bildunterschrift."
    assert repository.media[photo_id]["caption_status"] == "confirmed"
    assert job_response.json()["id"] == transcription_response.json()["id"]
    assert job_response.json()["status"] == "done"


def test_ai_transcription_failure_sets_error_status() -> None:
    repository = FakeWorkflowRepository()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    app.dependency_overrides[get_project_repository] = lambda: repository
    app.dependency_overrides[get_ai_provider] = lambda: FakeAiProvider(fail=True)
    client = TestClient(app)
    audio_id = str(uuid4())
    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss", "local_label": "Eng 01"},
    )

    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": audio_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{audio_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )
    voice_note_response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": audio_id,
            "target_type": "defect_description",
            "defect_id": defect_response.json()["id"],
        },
    )

    response = client.post(
        "/v1/ai/transcriptions",
        headers=_headers(),
        json={"voice_note_id": voice_note_response.json()["id"]},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert repository.voice_notes[voice_note_response.json()["id"]]["transcript_status"] == "error"
    assert repository.voice_notes[voice_note_response.json()["id"]]["error_message"]


def test_ai_transcription_reuses_duplicate_active_job(monkeypatch) -> None:
    repository = FakeWorkflowRepository()
    scheduled_tasks: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def capture_task(self, func, *args, **kwargs) -> None:
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", capture_task)
    client = _client(repository)
    audio_id = str(uuid4())
    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss", "local_label": "Eng 01"},
    )
    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": audio_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{audio_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )
    voice_note_response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": audio_id,
            "target_type": "defect_description",
            "defect_id": defect_response.json()["id"],
        },
    )
    payload = {"voice_note_id": voice_note_response.json()["id"]}

    first_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)
    second_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_response.json()["id"] == second_response.json()["id"]
    assert first_response.json()["status"] == "queued"
    assert second_response.json()["status"] == "queued"
    assert len(repository.ai_jobs) == 1
    assert len(scheduled_tasks) == 1


def test_ai_transcription_reschedules_stale_queued_job(monkeypatch) -> None:
    repository = FakeWorkflowRepository()
    scheduled_tasks: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def capture_task(self, func, *args, **kwargs) -> None:
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", capture_task)
    client = _client(repository)
    voice_note_id = _create_voice_note_with_audio(client)
    payload = {"voice_note_id": voice_note_id}

    first_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)
    job_id = first_response.json()["id"]
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=31)).isoformat()
    repository.ai_jobs[job_id]["created_at"] = stale_timestamp
    repository.ai_jobs[job_id]["updated_at"] = stale_timestamp
    second_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert second_response.json()["id"] == job_id
    assert len(repository.ai_jobs) == 1
    assert len(scheduled_tasks) == 2


def test_ai_transcription_does_not_reschedule_processing_job(monkeypatch) -> None:
    repository = FakeWorkflowRepository()
    scheduled_tasks: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def capture_task(self, func, *args, **kwargs) -> None:
        scheduled_tasks.append((func, args, kwargs))

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", capture_task)
    client = _client(repository)
    voice_note_id = _create_voice_note_with_audio(client)
    payload = {"voice_note_id": voice_note_id}

    first_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)
    job_id = first_response.json()["id"]
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    repository.ai_jobs[job_id]["status"] = "processing"
    repository.ai_jobs[job_id]["updated_at"] = stale_timestamp
    second_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert second_response.json()["id"] == job_id
    assert second_response.json()["status"] == "processing"
    assert len(repository.ai_jobs) == 1
    assert len(scheduled_tasks) == 1


def test_process_ai_transcription_job_skips_non_queued_job() -> None:
    class CountingAiProvider(FakeAiProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def transcribe_audio(self, *args, **kwargs):
            self.calls += 1
            return super().transcribe_audio(*args, **kwargs)

    for status in ("processing", "done", "failed"):
        repository = FakeWorkflowRepository()
        client = _client(repository)
        voice_note_id = _create_voice_note_with_audio(client)
        provider = CountingAiProvider()
        job, _created = repository.queue_ai_transcription(voice_note_id, _user(), provider)
        job["status"] = status

        result = repository.process_ai_transcription_job(
            str(job["id"]), voice_note_id, _user(), provider
        )

        assert result["status"] == status
        assert repository.ai_jobs[str(job["id"])]["status"] == status
        assert provider.calls == 0


def test_ai_routes_are_rate_limited_per_user() -> None:
    repository = FakeWorkflowRepository()
    rate_limiter = FakeRateLimiter(limit=1)
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    app.dependency_overrides[get_project_repository] = lambda: repository
    app.dependency_overrides[get_ai_provider] = lambda: FakeAiProvider()
    app.dependency_overrides[get_ai_rate_limiter] = lambda: rate_limiter
    client = TestClient(app)
    audio_id = str(uuid4())
    defect_response = client.post(
        f"/v1/projects/{PROJECT_ID}/defects",
        headers=_headers(),
        json={"kind": "defect", "description": "Riss", "local_label": "Eng 01"},
    )

    client.post(
        f"/v1/projects/{PROJECT_ID}/media/complete-upload",
        headers=_headers(),
        json={
            "media_id": audio_id,
            "media_type": "audio",
            "storage_bucket": "project-files",
            "storage_path": f"projects/{PROJECT_ID}/audio/{audio_id}.m4a",
            "mime_type": "audio/mp4",
        },
    )
    voice_note_response = client.post(
        f"/v1/projects/{PROJECT_ID}/voice-notes",
        headers=_headers(),
        json={
            "media_asset_id": audio_id,
            "target_type": "defect_description",
            "defect_id": defect_response.json()["id"],
        },
    )
    payload = {"voice_note_id": voice_note_response.json()["id"]}

    first_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)
    second_response = client.post("/v1/ai/transcriptions", headers=_headers(), json=payload)

    assert first_response.status_code == 202
    assert second_response.status_code == 429
    assert _error_detail(second_response) == {
        "code": "AI_RATE_LIMITED",
        "message": "KI-Rate-Limit erreicht. Bitte spaeter erneut versuchen.",
    }


def test_sync_push_reuses_duplicate_defect_create_operation() -> None:
    repository = InMemorySyncRepository()
    user = _user()
    operation = SyncOperation(
        client_operation_id="op-defect-create-1",
        type="defect.create",
        payload={
            "project_id": PROJECT_ID,
            "kind": "defect",
            "description": "Riss im Putz",
            "local_label": "1",
        },
    )

    first_response = repository.sync_push([operation], user)
    second_response = repository.sync_push([operation], user)

    assert first_response["rejected"] == []
    assert second_response["rejected"] == []
    first_result = first_response["applied"][0]["result"]
    second_result = second_response["applied"][0]["result"]
    assert first_result["id"] == second_result["id"]
    assert repository.defect_create_count == 1
    assert len(repository.defects) == 1


def test_sync_push_reuses_duplicate_plan_marker_create_operation() -> None:
    repository = InMemorySyncRepository()
    user = _user()
    operation = SyncOperation(
        client_operation_id="op-marker-create-1",
        type="plan_marker.create",
        payload={
            "plan_file_id": PLAN_ID,
            "defect_id": DEFECT_ID,
            "x_norm": 0.4,
            "y_norm": 0.6,
            "page_number": 1,
        },
    )

    first_response = repository.sync_push([operation, operation], user)

    assert first_response["rejected"] == []
    assert len(first_response["applied"]) == 2
    assert (
        first_response["applied"][0]["result"]["id"]
        == first_response["applied"][1]["result"]["id"]
    )
    assert repository.marker_create_count == 1
    assert len(repository.markers) == 1
