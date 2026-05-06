from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi.testclient import TestClient

from baudoku_api.dependencies import (
    get_ai_provider,
    get_auth_service,
    get_project_repository,
)
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.main import create_app
from baudoku_api.repositories.projects import ProjectRepositoryError, SupabaseProjectRepository
from baudoku_api.schemas import (
    DefectCreate,
    DefectMediaLinkCreate,
    DefectMediaLinkUpdate,
    GeneralFindingCreate,
    GeneralFindingUpdate,
    MediaAssetUpdate,
    MediaCompleteUploadRequest,
    MediaInitUploadRequest,
    PlanCreate,
    PlanMarkerCreate,
    ProjectConclusionUpsert,
    ReportWarning,
    SyncOperation,
    VoiceNoteCreate,
    VoiceNoteUpdate,
)

USER_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc).isoformat()
PLAN_ID = "33333333-3333-4333-8333-333333333333"
DEFECT_ID = "44444444-4444-4444-8444-444444444444"


class FakeAuthService:
    def authenticate(self, access_token: str) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=USER_ID,
            email="gutachter@example.com",
            display_name="Gutachter",
        )


class FakeAiProvider:
    provider_name = "openai"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
        file_name: str,
        project: dict[str, Any],
        target_type: str,
    ) -> str:
        if self.fail:
            raise RuntimeError("Provider nicht erreichbar.")
        return "KI-Vorschlag: Feuchtigkeit im Kellerbereich pruefen."

    def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        project: dict[str, Any],
    ) -> str:
        if self.fail:
            raise RuntimeError("Provider nicht erreichbar.")
        return "Foto zeigt einen Riss im Putz."


class FakeRateLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.counts: dict[str, int] = {}

    def check(self, key: str) -> None:
        next_count = self.counts.get(key, 0) + 1
        self.counts = {**self.counts, key: next_count}
        if next_count > self.limit:
            from baudoku_api.rate_limit import RateLimitExceededError

            raise RateLimitExceededError


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.defects: dict[str, dict[str, Any]] = {}
        self.media: dict[str, dict[str, Any]] = {}
        self.plans: dict[str, dict[str, Any]] = {}
        self.markers: dict[str, dict[str, Any]] = {}
        self.voice_notes: dict[str, dict[str, Any]] = {}
        self.general_findings: dict[str, dict[str, Any]] = {}
        self.project_conclusion: Optional[dict[str, Any]] = None
        self.ai_jobs: dict[str, dict[str, Any]] = {}
        self.preview_confirmation: Optional[dict[str, Any]] = None

    def ensure_profile(self, auth_user: AuthenticatedUser) -> AuthenticatedUser:
        return auth_user

    def get_project(self, project_id: str, user_id: str) -> dict[str, Any]:
        return _project(project_id)

    def list_projects(self, user_id: str) -> list[dict[str, Any]]:
        return [_project(PROJECT_ID)]

    def list_defects(
        self,
        project_id: str,
        user_id: str,
        kind: Optional[str] = None,
        trade_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        defects = list(self.defects.values())
        if kind:
            defects = [defect for defect in defects if defect["kind"] == kind]
        if trade_id:
            defects = [defect for defect in defects if str(defect.get("trade_id")) == trade_id]
        if category:
            defects = [defect for defect in defects if defect.get("category") == category]
        return defects

    def create_defect(
        self, project_id: str, payload: DefectCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        defect_id = str(uuid4())
        defect = {
            "id": defect_id,
            "project_id": project_id,
            "kind": payload.kind,
            "local_label": payload.local_label,
            "report_number": None,
            "report_sort_order": 1,
            "trade_id": None,
            "trade_name_snapshot": payload.trade_name_snapshot,
            "category": payload.category,
            "description": payload.description,
            "ai_status": "open",
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
            "revision": 1,
            "media_links": [],
        }
        self.defects[defect_id] = defect
        return defect

    def reorder_defects(
        self, project_id: str, defect_ids: list[str], user: AuthenticatedUser
    ) -> list[dict[str, Any]]:
        reordered: list[dict[str, Any]] = []
        for index, defect_id in enumerate(defect_ids, start=1):
            defect = self.defects[defect_id]
            defect["report_sort_order"] = float(index)
            defect["report_number"] = index
            defect["revision"] += 1
            reordered.append(defect)
        return reordered

    def init_media_upload(
        self, project_id: str, payload: MediaInitUploadRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        media_id = str(uuid4())
        return {
            "media_id": media_id,
            "storage_bucket": "project-files",
            "storage_path": f"projects/{project_id}/photos/{media_id}.jpg",
            "upload_token": "token",
            "signed_url": "https://example.test/upload",
        }

    def complete_media_upload(
        self, project_id: str, payload: MediaCompleteUploadRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        media = {
            "id": str(payload.media_id),
            "project_id": project_id,
            "media_type": payload.media_type,
            "storage_bucket": payload.storage_bucket,
            "storage_path": payload.storage_path,
            "mime_type": payload.mime_type,
            "file_size": payload.file_size,
            "width": payload.width,
            "height": payload.height,
            "duration_seconds": payload.duration_seconds,
            "caption": payload.caption,
            "caption_status": "edited" if str(payload.caption or "").strip() else "open",
            "created_by": user.id,
            "created_at": NOW,
            "signed_url": "https://example.test/download",
        }
        self.media[media["id"]] = media
        return media

    def create_defect_media_link(
        self, defect_id: str, payload: DefectMediaLinkCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        link = {
            "id": str(uuid4()),
            "defect_id": defect_id,
            "media_asset_id": str(payload.media_asset_id),
            "sort_order": payload.sort_order,
            "include_in_report": payload.include_in_report,
            "created_at": NOW,
            "media_asset": self.media[str(payload.media_asset_id)],
        }
        self.defects[defect_id]["media_links"] = [link]
        return link

    def list_media_assets(
        self,
        project_id: str,
        user_id: str,
        media_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        media_items = [
            item
            for item in self.media.values()
            if item["project_id"] == project_id
            and (include_deleted or item.get("deleted_at") is None)
        ]
        if media_type:
            media_items = [item for item in media_items if item["media_type"] == media_type]
        return media_items

    def get_media_asset_signed_url(
        self, media_asset_id: str, user: AuthenticatedUser
    ) -> dict[str, Any]:
        return {
            "media_asset_id": media_asset_id,
            "signed_url": self.media[media_asset_id]["signed_url"],
            "expires_in_seconds": 600,
        }

    def update_defect_media_link(
        self, link_id: str, payload: DefectMediaLinkUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        for defect in self.defects.values():
            for link in defect.get("media_links", []):
                if link["id"] == link_id:
                    updates = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
                    if "defect_id" in updates and updates["defect_id"] != link["defect_id"]:
                        defect["media_links"] = [
                            item for item in defect["media_links"] if item["id"] != link_id
                        ]
                        target_defect = self.defects[str(updates["defect_id"])]
                        link["defect_id"] = str(updates["defect_id"])
                        target_defect.setdefault("media_links", []).append(link)
                    link.update(updates)
                    link["updated_at"] = NOW
                    return link
        raise ProjectRepositoryError("Zuordnung nicht gefunden.")

    def delete_defect_media_link(self, link_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        for defect in self.defects.values():
            for link in list(defect.get("media_links", [])):
                if link["id"] == link_id:
                    defect["media_links"] = [
                        item for item in defect["media_links"] if item["id"] != link_id
                    ]
                    link["deleted_at"] = NOW
                    return link
        raise ProjectRepositoryError("Zuordnung nicht gefunden.")

    def update_media_asset(
        self, media_asset_id: str, payload: MediaAssetUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        media = self.media[media_asset_id]
        media.update(payload.model_dump(mode="json", exclude_unset=True, exclude_none=True))
        return media

    def delete_media_asset(self, media_asset_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        media = self.media[media_asset_id]
        media["deleted_at"] = NOW
        return media

    def list_plans(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        return list(self.plans.values())

    def create_plan(
        self, project_id: str, payload: PlanCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        preview_media = None
        if payload.file_type == "pdf":
            preview_media_id = str(uuid4())
            preview_media = {
                "id": preview_media_id,
                "project_id": project_id,
                "media_type": "plan_render",
                "storage_bucket": "project-files",
                "storage_path": f"projects/{project_id}/plans/{preview_media_id}.png",
                "mime_type": "image/png",
                "file_size": 1024,
                "width": 360,
                "height": 240,
                "caption": f"Planverortung: {payload.name}",
                "caption_status": "open",
                "created_by": user.id,
                "created_at": NOW,
                "signed_url": "https://example.test/pdf-preview",
            }
            self.media[preview_media_id] = preview_media
        plan = {
            "id": str(uuid4()),
            "project_id": project_id,
            "media_asset_id": str(payload.media_asset_id),
            "preview_media_asset_id": preview_media["id"] if preview_media else None,
            "name": payload.name,
            "file_type": payload.file_type,
            "page_count": payload.page_count,
            "selected_page": payload.selected_page,
            "created_by": user.id,
            "created_at": NOW,
            "media_asset": self.media[str(payload.media_asset_id)],
            "preview_media_asset": preview_media,
            "markers": [],
        }
        self.plans[plan["id"]] = plan
        return plan

    def create_plan_marker(
        self, plan_id: str, payload: PlanMarkerCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        marker = {
            "id": str(uuid4()),
            "project_id": PROJECT_ID,
            "plan_file_id": plan_id,
            "defect_id": str(payload.defect_id),
            "page_number": payload.page_number,
            "x_norm": payload.x_norm,
            "y_norm": payload.y_norm,
            "label_override": payload.label_override,
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
        }
        self.markers[marker["id"]] = marker
        self.plans[plan_id].setdefault("markers", []).append(marker)
        return marker

    def export_plan(self, plan_id: str, payload: Any, user: AuthenticatedUser) -> dict[str, Any]:
        extension = "png" if payload.format == "image" else self.plans[plan_id]["file_type"]
        mime_type = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
        }.get(extension, "image/jpeg")
        return {
            "download_url": f"https://example.test/{plan_id}_markiert.{extension}",
            "file_name": f"grundriss_markiert.{extension}",
            "mime_type": mime_type,
            "expires_in_seconds": 600,
        }

    def list_voice_notes(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        return list(self.voice_notes.values())

    def create_voice_note(
        self, project_id: str, payload: VoiceNoteCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        media = self.media[str(payload.media_asset_id)]
        if media["media_type"] != "audio":
            raise ProjectRepositoryError("Sprachnotiz benoetigt Audio.")
        if payload.target_type != "defect_description":
            raise ProjectRepositoryError("Sprachnotiz muss einem konkreten Eintrag zugeordnet sein.")
        if payload.defect_id is None:
            raise ProjectRepositoryError("Sprachnotiz fuer Mangel benoetigt einen Mangel.")
        defect = self.defects.get(str(payload.defect_id))
        if defect is None or str(defect["project_id"]) != project_id:
            raise ProjectRepositoryError(
                "Sprachnotiz und Mangel muessen im selben Projekt liegen."
            )
        voice_note = {
            "id": str(uuid4()),
            "project_id": project_id,
            "media_asset_id": str(payload.media_asset_id),
            "defect_id": str(payload.defect_id) if payload.defect_id else None,
            "target_type": payload.target_type,
            "transcript": payload.transcript,
            "transcript_status": payload.transcript_status,
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
            "media_asset": media,
        }
        self.voice_notes[voice_note["id"]] = voice_note
        return voice_note

    def update_voice_note(
        self, voice_note_id: str, payload: VoiceNoteUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        voice_note = self.voice_notes[voice_note_id]
        updates = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        voice_note.update(updates)
        voice_note["updated_at"] = NOW
        return voice_note

    def list_general_findings(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        return list(self.general_findings.values())

    def create_general_finding(
        self, project_id: str, payload: GeneralFindingCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        finding = {
            "id": str(uuid4()),
            "project_id": project_id,
            "text": payload.text,
            "source_voice_note_id": str(payload.source_voice_note_id)
            if payload.source_voice_note_id
            else None,
            "sort_order": payload.sort_order or float(len(self.general_findings) + 1),
            "status": payload.status,
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
        }
        self.general_findings[finding["id"]] = finding
        return finding

    def update_general_finding(
        self, finding_id: str, payload: GeneralFindingUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        finding = self.general_findings[finding_id]
        updates = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        finding.update(updates)
        finding["updated_at"] = NOW
        return finding

    def delete_general_finding(self, finding_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        return self.general_findings.pop(finding_id)

    def get_project_conclusion(
        self, project_id: str, user_id: str
    ) -> Optional[dict[str, Any]]:
        return self.project_conclusion

    def upsert_project_conclusion(
        self, project_id: str, payload: ProjectConclusionUpsert, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self.project_conclusion = {
            "project_id": project_id,
            "text": payload.text,
            "source_voice_note_id": str(payload.source_voice_note_id)
            if payload.source_voice_note_id
            else None,
            "status": payload.status,
            "updated_by": user.id,
            "updated_at": NOW,
        }
        return self.project_conclusion

    def start_ai_transcription(
        self, voice_note_id: str, user: AuthenticatedUser, ai_provider: Any
    ) -> dict[str, Any]:
        job, created = self.queue_ai_transcription(voice_note_id, user, ai_provider)
        if not created:
            return job
        return self.process_ai_transcription_job(str(job["id"]), voice_note_id, user, ai_provider)

    def queue_ai_transcription(
        self, voice_note_id: str, user: AuthenticatedUser, ai_provider: Any
    ) -> tuple[dict[str, Any], bool]:
        voice_note = self.voice_notes[voice_note_id]
        media = self.media[str(voice_note["media_asset_id"])]
        if media["media_type"] != "audio":
            raise ProjectRepositoryError("KI-Transkription benoetigt eine Audio-Datei.")
        for job in self.ai_jobs.values():
            if (
                str(job["project_id"]) == str(voice_note["project_id"])
                and str(job["media_asset_id"]) == str(media["id"])
                and job["job_type"] == "transcribe_audio"
                and job["status"] in {"queued", "processing"}
                and str(voice_note_id) in str(job["input_ref"])
            ):
                return job, False
        job = _ai_job(
            project_id=str(voice_note["project_id"]),
            media_asset_id=str(media["id"]),
            job_type="transcribe_audio",
            provider=ai_provider.provider_name,
            input_ref=f"voice_note:{voice_note_id}|{media['storage_path']}",
        )
        self.ai_jobs[job["id"]] = job
        return job, True

    def process_ai_transcription_job(
        self, job_id: str, voice_note_id: str, user: AuthenticatedUser, ai_provider: Any
    ) -> dict[str, Any]:
        voice_note = self.voice_notes[voice_note_id]
        media = self.media[str(voice_note["media_asset_id"])]
        if media["media_type"] != "audio":
            raise ProjectRepositoryError("KI-Transkription benoetigt eine Audio-Datei.")
        job = self.ai_jobs[job_id]
        if job["status"] != "queued":
            return job
        try:
            job["status"] = "processing"
            result = ai_provider.transcribe_audio(
                b"audio",
                str(media["mime_type"]),
                "audio.m4a",
                _project(str(voice_note["project_id"])),
                str(voice_note["target_type"]),
            )
            job.update({"status": "done", "result_text": result})
            voice_note.update({"transcript": result, "transcript_status": "suggested", "error_message": None})
        except Exception as exc:
            error_message = str(exc)
            job.update({"status": "failed", "error_message": error_message})
            voice_note.update({"transcript_status": "error", "error_message": error_message})
        return job

    def start_ai_image_description(
        self, media_asset_id: str, user: AuthenticatedUser, ai_provider: Any
    ) -> dict[str, Any]:
        media = self.media[media_asset_id]
        if media["media_type"] != "photo":
            raise ProjectRepositoryError("KI-Bildbeschreibung benoetigt ein Foto.")
        job = _ai_job(
            project_id=str(media["project_id"]),
            media_asset_id=media_asset_id,
            job_type="describe_image",
            provider=ai_provider.provider_name,
            input_ref=f"media_asset:{media_asset_id}|{media['storage_path']}",
        )
        try:
            result = ai_provider.describe_image(b"image", str(media["mime_type"]), _project(str(media["project_id"])))
            job.update({"status": "done", "result_text": result})
            media.update({"caption": result, "caption_status": "suggested"})
        except Exception as exc:
            job.update({"status": "failed", "error_message": str(exc)})
            media["caption_status"] = "error"
        self.ai_jobs[job["id"]] = job
        return job

    def get_ai_job(self, job_id: str, user_id: str) -> dict[str, Any]:
        return self.ai_jobs[job_id]

    def report_preview(self, project_id: str, user_id: str) -> dict[str, Any]:
        return {
            "project": _project(project_id),
            "defects": list(self.defects.values()),
            "general_findings": list(self.general_findings.values()),
            "project_conclusion": self.project_conclusion,
            "voice_notes": list(self.voice_notes.values()),
            "plans": list(self.plans.values()),
            "preview_confirmation": self.preview_confirmation,
            "warnings": [
                ReportWarning(
                    code="UNCONFIRMED_AI_TRANSCRIPT",
                    message="KI-Transkript ist noch nicht bestaetigt.",
                    severity="warning",
                )
                for voice_note in self.voice_notes.values()
                if voice_note.get("transcript_status") == "suggested"
            ],
        }

    def confirm_report_preview(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        self.preview_confirmation = {
            "id": str(uuid4()),
            "project_id": project_id,
            "confirmed_by": user.id,
            "confirmed_at": NOW,
            "project_revision": 1,
            "report_revision": 0,
        }
        return self.preview_confirmation

    def generate_report(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        return {
            "version": _report_version(project_id),
            "warnings": [ReportWarning(code="INFO", message="Warnungen blockieren nicht.", severity="info")],
        }

    def list_report_versions(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        return [_report_version(project_id)]

    def sync_pull(
        self, user_id: str, updated_since: Optional[datetime] = None
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "projects": [_project(PROJECT_ID)],
            "defects": list(self.defects.values()),
            "media_assets": list(self.media.values()),
            "defect_media_links": [],
            "plan_files": list(self.plans.values()),
            "plan_markers": list(self.markers.values()),
            "voice_notes": list(self.voice_notes.values()),
            "general_findings": list(self.general_findings.values()),
            "project_conclusions": [self.project_conclusion] if self.project_conclusion else [],
            "tombstones": [],
        }

    def sync_push(
        self, operations: list[SyncOperation], user: AuthenticatedUser
    ) -> dict[str, list[dict[str, Any]]]:
        return {"applied": [{"client_operation_id": operation.client_operation_id} for operation in operations], "rejected": []}


class InMemorySyncRepository(SupabaseProjectRepository):
    def __init__(self) -> None:
        self.defects: dict[str, dict[str, Any]] = {}
        self.markers: dict[str, dict[str, Any]] = {}
        self.sync_events: list[dict[str, Any]] = []
        self.defect_create_count = 0
        self.marker_create_count = 0

    def create_defect(
        self, project_id: str, payload: DefectCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self.defect_create_count += 1
        defect_id = str(uuid4())
        defect = {
            "id": defect_id,
            "project_id": project_id,
            "kind": payload.kind,
            "local_label": payload.local_label,
            "report_number": None,
            "report_sort_order": float(self.defect_create_count),
            "trade_id": None,
            "trade_name_snapshot": payload.trade_name_snapshot,
            "category": payload.category,
            "description": payload.description,
            "ai_status": "open",
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
            "revision": 1,
            "media_links": [],
        }
        self.defects[defect_id] = defect
        return defect

    def create_plan_marker(
        self, plan_id: str, payload: PlanMarkerCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self.marker_create_count += 1
        marker_id = str(uuid4())
        marker = {
            "id": marker_id,
            "project_id": PROJECT_ID,
            "plan_file_id": plan_id,
            "defect_id": str(payload.defect_id),
            "page_number": payload.page_number,
            "x_norm": payload.x_norm,
            "y_norm": payload.y_norm,
            "label_override": payload.label_override,
            "created_by": user.id,
            "created_at": NOW,
            "updated_at": NOW,
        }
        self.markers[marker_id] = marker
        return marker

    def _get_sync_operation_event(
        self, operation: SyncOperation, user: AuthenticatedUser
    ) -> Optional[dict[str, Any]]:
        for event in self.sync_events:
            metadata = event["metadata"]
            if (
                event["actor_user_id"] == user.id
                and metadata["client_operation_id"] == operation.client_operation_id
                and metadata["operation_type"] == operation.type
            ):
                return event
        return None

    def _record_activity(
        self,
        project_id: Optional[str],
        user_id: str,
        event_type: str,
        entity_type: str,
        entity_id: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.sync_events.append(
            {
                "id": str(uuid4()),
                "project_id": project_id,
                "actor_user_id": user_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata or {},
                "created_at": NOW,
            }
        )

    def _select_one(self, table: str, column: str, value: str) -> Optional[dict[str, Any]]:
        if column != "id":
            return None
        if table == "defects":
            return self.defects.get(value)
        if table == "plan_markers":
            return self.markers.get(value)
        return None

    def _select_rows_in(self, table: str, column: str, values: list[str]) -> list[dict[str, Any]]:
        return []


def _client(repository: FakeWorkflowRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    app.dependency_overrides[get_project_repository] = lambda: repository
    app.dependency_overrides[get_ai_provider] = lambda: FakeAiProvider()
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer fake-token"}


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=USER_ID,
        email="gutachter@example.com",
        display_name="Gutachter",
    )


def _project(project_id: str) -> dict[str, Any]:
    return {
        "id": project_id,
        "project_number": "BBA-2026-001",
        "client_name": "Muster GmbH",
        "object_address": "Baustelle 1, Berlin",
        "site_visit_date": date(2026, 5, 4).isoformat(),
        "appraisal_type": "Abnahmebegehung",
        "lead_user_id": USER_ID,
        "status": "Entwurf",
        "language": "de",
        "created_by": USER_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "revision": 1,
    }


def _report_version(project_id: str) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "project_id": project_id,
        "version_number": 1,
        "media_asset_id": str(uuid4()),
        "pdf_media_asset_id": str(uuid4()),
        "generated_by": USER_ID,
        "generated_at": NOW,
        "warning_count": 0,
        "warnings_snapshot": [],
        "template_version": "bba-report-v2",
        "download_url": "https://example.test/report.docx",
        "pdf_download_url": "https://example.test/report.pdf",
    }


def _ai_job(
    project_id: str,
    media_asset_id: str,
    job_type: str,
    provider: str,
    input_ref: str,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()),
        "project_id": project_id,
        "media_asset_id": media_asset_id,
        "job_type": job_type,
        "status": "queued",
        "provider": provider,
        "input_ref": input_ref,
        "result_text": None,
        "error_message": None,
        "created_at": created_at,
        "updated_at": created_at,
    }
