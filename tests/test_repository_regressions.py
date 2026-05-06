from __future__ import annotations

import ast
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    MediaUploadIntegrityError,
    ProjectRepositoryError,
    _extension_for,
    _plan_source_supports_image_render,
)
from baudoku_api.repositories.report_generation import _report_storage_path
from baudoku_api.repositories.projects import SupabaseProjectRepository
from baudoku_api.schemas import MediaCompleteUploadRequest, MediaInitUploadRequest


def test_defect_local_label_required_migration_backfills_and_constrains() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "20260505064300_require_defect_local_label.sql"
    )

    sql = migration_path.read_text(encoding="utf-8")

    assert "row_number() over" in sql
    assert "where local_label is null" in sql
    assert "alter column local_label set not null" in sql
    assert "defects_local_label_not_blank" in sql


def test_report_storage_path_uses_media_id_to_avoid_retry_collisions() -> None:
    project_id = str(uuid4())
    media_id = str(uuid4())

    assert _report_storage_path(project_id, media_id, "docx") == (
        f"projects/{project_id}/reports/{media_id}.docx"
    )


class _ChainQuery:
    def select(self, *_args: Any, **_kwargs: Any) -> "_ChainQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_ChainQuery":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_ChainQuery":
        return self


class _ProjectAccessClient:
    def table(self, _name: str) -> _ChainQuery:
        return _ChainQuery()


class _FakeStorageBucket:
    def __init__(self, info: dict[str, Any], content: bytes = b"file-bytes") -> None:
        self.info_payload = info
        self.content = content
        self.signed_upload_paths: list[str] = []

    def info(self, _path: str) -> dict[str, Any]:
        return self.info_payload

    def download(self, _path: str) -> bytes:
        return self.content

    def create_signed_upload_url(self, path: str) -> dict[str, str]:
        self.signed_upload_paths.append(path)
        return {
            "token": "fresh-upload-token",
            "signed_url": f"https://example.test/upload/{path}",
        }


class _FakeStorageClient:
    def __init__(self, bucket: _FakeStorageBucket) -> None:
        self.bucket = bucket

    def from_(self, _bucket_name: str) -> _FakeStorageBucket:
        return self.bucket


class _InsertQuery:
    def __init__(self, table_name: str, payload: dict[str, Any]) -> None:
        self.table_name = table_name
        self.payload = payload


class _InsertTable:
    def __init__(self, table_name: str) -> None:
        self.table_name = table_name

    def insert(self, payload: dict[str, Any]) -> _InsertQuery:
        return _InsertQuery(self.table_name, payload)


class _UploadIntegrityClient:
    def __init__(self, bucket: _FakeStorageBucket) -> None:
        self.storage = _FakeStorageClient(bucket)

    def table(self, table_name: str) -> _InsertTable:
        return _InsertTable(table_name)


class _UploadIntegrityRepository(SupabaseProjectRepository):
    def __init__(
        self,
        bucket: _FakeStorageBucket,
        existing_media: dict[str, Any] | None = None,
    ) -> None:
        self.inserted_media: dict[str, Any] | None = None
        self.existing_media = existing_media
        self.client = _UploadIntegrityClient(bucket)

    @property
    def _client(self) -> _UploadIntegrityClient:
        return self.client

    def _get_project_for_user(
        self,
        _project_id: str,
        _user_id: str,
        _derive_status: bool = True,
    ) -> dict[str, Any]:
        return {"id": _project_id}

    def _select_one(self, table: str, column: str, value: str) -> dict[str, Any] | None:
        if table != "media_assets" or self.existing_media is None:
            return None
        if column == "id" and str(self.existing_media.get("id")) == value:
            return self.existing_media
        if column == "storage_path" and str(self.existing_media.get("storage_path")) == value:
            return self.existing_media
        if column == "client_id" and str(self.existing_media.get("client_id")) == value:
            return self.existing_media
        return None

    def _execute(self, query: Any) -> SimpleNamespace:
        if getattr(query, "table_name", "") == "media_assets":
            self.inserted_media = dict(query.payload)
            return SimpleNamespace(data=[self.inserted_media])
        return SimpleNamespace(data=[query.payload])

    def _record_activity(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _with_media_signed_url(self, media: dict[str, Any]) -> dict[str, Any]:
        return {**media, "signed_url": "https://example.test/file"}


class _ProjectAccessRepository(SupabaseProjectRepository):
    def __init__(self) -> None:
        self.derived_calls = 0

    @property
    def _client(self) -> _ProjectAccessClient:
        return _ProjectAccessClient()

    def _execute(self, _query: Any) -> SimpleNamespace:
        return SimpleNamespace(
            data=[
                {
                    "projects": {
                        "id": "project-1",
                        "status": "Entwurf",
                        "deleted_at": None,
                    }
                }
            ]
        )

    def _with_derived_project_status(self, project: dict[str, Any]) -> dict[str, Any]:
        self.derived_calls += 1
        return {**project, "status": "Bericht generiert"}


class _ReportPlanRenderRepository(SupabaseProjectRepository):
    def __init__(self, storage: dict[str, bytes], preview_media: dict[str, Any] | None = None) -> None:
        self.storage = storage
        self.preview_media = preview_media
        self.preview_create_calls = 0
        self.downloaded_paths: list[str] = []
        self.stored_renders: list[dict[str, Any]] = []

    def _download_report_image(self, storage_path: str) -> bytes:
        self.downloaded_paths.append(storage_path)
        try:
            return self.storage[storage_path]
        except KeyError as exc:
            raise ProjectRepositoryError("Bild konnte nicht fuer Bericht geladen werden.") from exc

    def _create_plan_preview_media(
        self,
        _project_id: str,
        _plan: dict[str, Any],
        _media: dict[str, Any],
        _user: AuthenticatedUser,
    ) -> dict[str, Any] | None:
        self.preview_create_calls += 1
        return self.preview_media

    def _store_plan_render(
        self,
        project_id: str,
        plan: dict[str, Any],
        render_result: Any,
        _user: AuthenticatedUser,
        version_number: int,
    ) -> dict[str, Any]:
        storage_path = f"projects/{project_id}/plans/report-v{version_number}.png"
        media = {
            "id": f"report-render-{len(self.stored_renders) + 1}",
            "project_id": project_id,
            "media_type": render_result.media_type,
            "storage_bucket": PROJECT_FILES_BUCKET,
            "storage_path": storage_path,
            "mime_type": render_result.mime_type,
            "file_size": len(render_result.content),
            "width": render_result.width,
            "height": render_result.height,
            "caption": f"Planverortung: {plan.get('name') or 'Plan'}",
        }
        self.stored_renders.append(
            {
                "media": media,
                "content": render_result.content,
                "plan": dict(plan),
            }
        )
        return media


class _FlakyQuery:
    def __init__(self) -> None:
        self.attempts = 0
        self.response = SimpleNamespace(data=[{"ok": True}])

    def execute(self) -> SimpleNamespace:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("connection reset")
        return self.response


def test_supabase_repository_implements_private_mixin_helpers() -> None:
    repository = SupabaseProjectRepository()
    repository_root = Path(__file__).resolve().parents[1] / "src" / "baudoku_api" / "repositories"
    mixin_files = [
        repository_root / "ai_operations.py",
        repository_root / "defect_media_operations.py",
        repository_root / "media_integrity.py",
        repository_root / "project_core.py",
        repository_root / "report_generation.py",
        repository_root / "sync_operations.py",
        repository_root / "workflow_operations.py",
    ]

    called_helpers: set[str] = set()
    for mixin_file in mixin_files:
        tree = ast.parse(mixin_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr.startswith("_")
                and node.attr != "__class__"
            ):
                called_helpers.add(node.attr)

    missing_helpers = sorted(
        helper for helper in called_helpers if not hasattr(repository, helper)
    )

    assert missing_helpers == []


def test_filter_sync_rows_returns_all_rows_without_timestamp() -> None:
    repository = SupabaseProjectRepository()
    rows = [
        {"id": "old", "updated_at": "2026-05-04T08:00:00+00:00"},
        {"id": "new", "updated_at": "2026-05-04T09:00:00+00:00"},
    ]

    assert repository._filter_sync_rows(rows, None) == rows


def test_filter_sync_rows_uses_updated_created_and_deleted_timestamps() -> None:
    repository = SupabaseProjectRepository()
    updated_since = datetime(2026, 5, 4, 8, 30, tzinfo=timezone.utc)
    rows = [
        {"id": "old", "updated_at": "2026-05-04T08:00:00+00:00"},
        {"id": "new-update", "updated_at": "2026-05-04T09:00:00Z"},
        {"id": "new-create", "created_at": "2026-05-04T09:10:00+00:00"},
        {"id": "new-delete", "deleted_at": "2026-05-04T09:20:00+00:00"},
        {"id": "no-date"},
    ]

    filtered = repository._filter_sync_rows(rows, updated_since)

    assert [row["id"] for row in filtered] == ["new-update", "new-create", "new-delete"]


def test_validate_media_upload_payload_accepts_project_scoped_photo() -> None:
    repository = SupabaseProjectRepository()
    project_id = str(uuid4())
    media_id = uuid4()
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{media_id}.jpg",
        mime_type="image/jpeg",
        file_size=123,
        width=800,
        height=600,
    )

    repository._validate_media_upload_payload(project_id, payload)


def test_validate_media_upload_payload_accepts_project_scoped_webp_photo() -> None:
    repository = SupabaseProjectRepository()
    project_id = str(uuid4())
    media_id = uuid4()
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{media_id}.webp",
        mime_type="image/webp",
        file_size=123,
        width=800,
        height=600,
    )

    repository._validate_media_upload_payload(project_id, payload)


def test_validate_media_upload_payload_accepts_project_scoped_webp_plan_source() -> None:
    repository = SupabaseProjectRepository()
    project_id = str(uuid4())
    media_id = uuid4()
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="plan_source",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/plans/{media_id}.webp",
        mime_type="image/webp",
        file_size=123,
        width=1200,
        height=900,
    )

    repository._validate_media_upload_payload(project_id, payload)


def test_webp_plan_sources_are_renderable_images() -> None:
    plan = {"file_type": "webp"}
    media = {"media_type": "plan_source", "mime_type": "image/webp"}

    assert _extension_for("plan_source", "image/webp", None) == "webp"
    assert _plan_source_supports_image_render(plan, media)


def test_report_plan_render_uses_pdf_preview_as_coordinate_basis() -> None:
    repository = _ReportPlanRenderRepository(
        {"projects/project-1/plans/preview.png": _image_bytes(size=(400, 200))}
    )
    plan = {
        "id": "plan-1",
        "name": "PDF-Grundriss",
        "file_type": "pdf",
        "media_asset_id": "source-media",
        "preview_media_asset_id": "preview-media",
        "media_asset": {
            "id": "source-media",
            "media_type": "plan_source",
            "storage_path": "projects/project-1/plans/source.pdf",
            "mime_type": "application/pdf",
        },
        "preview_media_asset": {
            "id": "preview-media",
            "media_type": "plan_render",
            "storage_path": "projects/project-1/plans/preview.png",
            "mime_type": "image/png",
            "width": 400,
            "height": 200,
        },
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.25,
                "y_norm": 0.5,
            }
        ],
    }

    result = repository._render_report_plan(
        "project-1",
        plan,
        [{"id": "defect-1", "report_number": 7}],
        _report_user(),
        3,
    )

    assert repository.preview_create_calls == 0
    assert repository.downloaded_paths == ["projects/project-1/plans/preview.png"]
    assert result["media_asset"]["width"] == 400
    assert result["media_asset"]["height"] == 200
    rendered = _rendered_image(repository.stored_renders[0]["content"])
    assert _crop_contains_red_pixels(rendered, center=(100, 100))


def test_report_plan_render_recreates_missing_pdf_preview_before_marking() -> None:
    preview_media = {
        "id": "preview-media",
        "media_type": "plan_render",
        "storage_path": "projects/project-1/plans/recreated-preview.png",
        "mime_type": "image/png",
        "width": 320,
        "height": 180,
    }
    repository = _ReportPlanRenderRepository(
        {"projects/project-1/plans/recreated-preview.png": _image_bytes(size=(320, 180))},
        preview_media=preview_media,
    )
    plan = {
        "id": "plan-1",
        "name": "PDF-Grundriss",
        "file_type": "pdf",
        "media_asset_id": "source-media",
        "media_asset": {
            "id": "source-media",
            "media_type": "plan_source",
            "storage_path": "projects/project-1/plans/source.pdf",
            "mime_type": "application/pdf",
        },
        "preview_media_asset": None,
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }

    result = repository._render_report_plan(
        "project-1",
        plan,
        [{"id": "defect-1", "report_number": 2}],
        _report_user(),
        4,
    )

    assert repository.preview_create_calls == 1
    assert repository.downloaded_paths == ["projects/project-1/plans/recreated-preview.png"]
    assert repository.stored_renders[0]["plan"]["preview_media_asset_id"] == "preview-media"
    assert result["media_asset"]["width"] == 320
    assert result["media_asset"]["height"] == 180


def test_report_plan_render_returns_report_warning_when_image_render_fails() -> None:
    repository = _ReportPlanRenderRepository({})
    plan = {
        "id": "plan-1",
        "name": "Grundriss",
        "file_type": "png",
        "media_asset_id": "source-media",
        "media_asset": {
            "id": "source-media",
            "media_type": "plan_source",
            "storage_path": "projects/project-1/plans/missing.png",
            "mime_type": "image/png",
        },
        "markers": [
            {
                "defect_id": "defect-1",
                "page_number": 1,
                "x_norm": 0.5,
                "y_norm": 0.5,
            }
        ],
    }

    result = repository._render_report_plan(
        "project-1",
        plan,
        [{"id": "defect-1", "report_number": 1}],
        _report_user(),
        1,
    )

    assert "Planbild konnte nicht fuer den Bericht gerendert werden" in result["render_error"]
    assert repository.stored_renders == []


@pytest.mark.parametrize(
    ("storage_bucket", "storage_path", "mime_type"),
    [
        ("public", "projects/{project_id}/photos/{media_id}.jpg", "image/jpeg"),
        (PROJECT_FILES_BUCKET, "projects/other-project/photos/{media_id}.jpg", "image/jpeg"),
        (PROJECT_FILES_BUCKET, "projects/{project_id}/reports/{media_id}.jpg", "image/jpeg"),
        (PROJECT_FILES_BUCKET, "projects/{project_id}/photos/{media_id}.jpg", "application/pdf"),
    ],
)
def test_validate_media_upload_payload_rejects_invalid_photo_payload(
    storage_bucket: str,
    storage_path: str,
    mime_type: str,
) -> None:
    repository = SupabaseProjectRepository()
    project_id = str(uuid4())
    media_id = uuid4()
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=storage_bucket,
        storage_path=storage_path.format(project_id=project_id, media_id=media_id),
        mime_type=mime_type,
        file_size=123,
    )

    with pytest.raises(ProjectRepositoryError):
        repository._validate_media_upload_payload(project_id, payload)


def test_validate_existing_media_upload_is_idempotent_for_same_upload() -> None:
    repository = SupabaseProjectRepository()
    project_id = str(uuid4())
    media_id = uuid4()
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{media_id}.jpg",
        mime_type="image/jpeg",
        file_size=123,
    )
    existing_media = {
        "id": str(media_id),
        "project_id": project_id,
        "media_type": "photo",
        "storage_bucket": PROJECT_FILES_BUCKET,
        "storage_path": payload.storage_path,
    }

    repository._validate_existing_media_upload(existing_media, project_id, payload)


def test_init_media_upload_reuses_reserved_upload_path_for_retry() -> None:
    project_id = str(uuid4())
    media_id = uuid4()
    storage_path = f"projects/{project_id}/photos/{media_id}.webp"
    bucket = _FakeStorageBucket({"metadata": {"size": 123}})
    repository = _UploadIntegrityRepository(bucket)

    result = repository.init_media_upload(
        project_id,
        MediaInitUploadRequest(
            media_type="photo",
            mime_type="image/webp",
            file_name="capture.webp",
            client_id="pending-photo-1",
            media_id=media_id,
            storage_path=storage_path,
        ),
        SimpleNamespace(id="user-1"),
    )

    assert result["media_id"] == str(media_id)
    assert result["storage_path"] == storage_path
    assert result["upload_token"] == "fresh-upload-token"
    assert bucket.signed_upload_paths == [storage_path]


def test_complete_media_upload_is_idempotent_by_client_id() -> None:
    project_id = str(uuid4())
    existing_media_id = uuid4()
    retry_media_id = uuid4()
    existing_media = {
        "id": str(existing_media_id),
        "project_id": project_id,
        "media_type": "photo",
        "storage_bucket": PROJECT_FILES_BUCKET,
        "storage_path": f"projects/{project_id}/photos/{existing_media_id}.webp",
        "mime_type": "image/webp",
        "client_id": "pending-photo-1",
    }
    repository = _UploadIntegrityRepository(
        _FakeStorageBucket({"metadata": {"size": 321}}),
        existing_media=existing_media,
    )
    payload = MediaCompleteUploadRequest(
        media_id=retry_media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{retry_media_id}.webp",
        mime_type="image/webp",
        file_size=321,
        client_id="pending-photo-1",
    )

    media = repository.complete_media_upload(project_id, payload, SimpleNamespace(id="user-1"))

    assert media["id"] == str(existing_media_id)
    assert media["signed_url"] == "https://example.test/file"
    assert repository.inserted_media is None


def test_validate_existing_media_upload_rejects_cross_project_reuse() -> None:
    repository = SupabaseProjectRepository()
    project_id = str(uuid4())
    media_id = uuid4()
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{media_id}.jpg",
        mime_type="image/jpeg",
        file_size=123,
    )
    existing_media = {
        "id": str(media_id),
        "project_id": str(uuid4()),
        "media_type": "photo",
        "storage_bucket": PROJECT_FILES_BUCKET,
        "storage_path": payload.storage_path,
    }

    with pytest.raises(ProjectRepositoryError):
        repository._validate_existing_media_upload(existing_media, project_id, payload)


def test_complete_media_upload_rejects_empty_storage_object() -> None:
    project_id = str(uuid4())
    media_id = uuid4()
    repository = _UploadIntegrityRepository(_FakeStorageBucket({"metadata": {"size": 0}}))
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="audio",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/audio/{media_id}.m4a",
        mime_type="audio/mp4",
        file_size=0,
    )

    with pytest.raises(MediaUploadIntegrityError) as exc_info:
        repository.complete_media_upload(project_id, payload, SimpleNamespace(id="user-1"))

    assert exc_info.value.error_code == "UPLOAD_EMPTY_OR_INCOMPLETE"
    assert repository.inserted_media is None


def test_complete_media_upload_rejects_storage_size_mismatch() -> None:
    project_id = str(uuid4())
    media_id = uuid4()
    repository = _UploadIntegrityRepository(_FakeStorageBucket({"metadata": {"size": 321}}))
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{media_id}.jpg",
        mime_type="image/jpeg",
        file_size=123,
    )

    with pytest.raises(MediaUploadIntegrityError) as exc_info:
        repository.complete_media_upload(project_id, payload, SimpleNamespace(id="user-1"))

    assert exc_info.value.error_code == "UPLOAD_SIZE_MISMATCH"
    assert repository.inserted_media is None


def test_complete_media_upload_persists_verified_storage_size() -> None:
    project_id = str(uuid4())
    media_id = uuid4()
    repository = _UploadIntegrityRepository(_FakeStorageBucket({"metadata": {"size": 321}}))
    payload = MediaCompleteUploadRequest(
        media_id=media_id,
        media_type="photo",
        storage_bucket=PROJECT_FILES_BUCKET,
        storage_path=f"projects/{project_id}/photos/{media_id}.jpg",
        mime_type="image/jpeg",
        file_size=321,
        caption="Riss im Putz",
    )

    media = repository.complete_media_upload(project_id, payload, SimpleNamespace(id="user-1"))

    assert media["file_size"] == 321
    assert media["caption_status"] == "edited"
    assert media["signed_url"] == "https://example.test/file"


def test_download_media_bytes_rejects_empty_storage_file() -> None:
    repository = _UploadIntegrityRepository(_FakeStorageBucket({"metadata": {"size": 0}}, b""))

    with pytest.raises(ProjectRepositoryError, match="Upload unvollstaendig"):
        repository._download_media_bytes({"storage_path": "projects/project-1/audio/audio.m4a"})


def test_raw_project_access_does_not_run_status_derivation() -> None:
    repository = _ProjectAccessRepository()

    project = repository._get_project_for_user(
        "project-1", "user-1", derive_status=False
    )

    assert project["status"] == "Entwurf"
    assert repository.derived_calls == 0


def test_get_project_still_runs_status_derivation() -> None:
    repository = _ProjectAccessRepository()

    project = repository.get_project("project-1", "user-1")

    assert project["status"] == "Bericht generiert"
    assert repository.derived_calls == 1


def test_execute_retries_transient_supabase_read_once() -> None:
    repository = SupabaseProjectRepository()
    query = _FlakyQuery()

    response = repository._execute(query)

    assert response is query.response
    assert query.attempts == 2


def test_with_media_signed_url_returns_null_when_storage_signing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SupabaseProjectRepository()

    def raise_storage_error(_storage_path: str) -> str:
        raise ProjectRepositoryError("Storage-Signed-URL nicht verfuegbar.")

    monkeypatch.setattr(repository, "_signed_download_url", raise_storage_error)

    media = repository._with_media_signed_url(
        {
            "id": str(uuid4()),
            "storage_path": "projects/project-1/photos/photo.jpg",
        }
    )

    assert media["signed_url"] is None


def _report_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id="11111111-1111-4111-8111-111111111111",
        email="gutachter@example.com",
        display_name="Gutachter",
    )


def _image_bytes(size: tuple[int, int], color: tuple[int, int, int] = (245, 245, 240)) -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _rendered_image(content: bytes) -> Any:
    from PIL import Image

    return Image.open(BytesIO(content)).convert("RGBA")


def _crop_contains_red_pixels(image: Any, center: tuple[int, int]) -> bool:
    x_center, y_center = center
    for x in range(x_center - 16, x_center + 17):
        for y in range(y_center - 16, y_center + 17):
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha and red > 160 and green < 90 and blue < 90:
                return True
    return False
