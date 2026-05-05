from __future__ import annotations

import logging
import re
from typing import Any, Optional

from baudoku_api.reports import (
    PlanRenderError,
    plan_export_fingerprint,
    render_annotated_plan,
    render_annotated_plan_source_export,
)
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.schemas import (
    GeneralFindingCreate,
    GeneralFindingUpdate,
    PlanCreate,
    PlanExportRequest,
    PlanMarkerCreate,
    PlanMarkerUpdate,
    ProjectConclusionUpsert,
    VoiceNoteCreate,
    VoiceNoteUpdate,
)

from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    ProjectNotFoundError,
    ProjectRepositoryError,
    _now_iso,
    _response_data,
    _single_response_row,
)

logger = logging.getLogger(__name__)
PLAN_EXPORT_SIGNED_URL_SECONDS = 600


class ProjectWorkflowMixin:
    def list_plans(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        plans = [
            row
            for row in _response_data(
                self._execute(
                    self._client.table("plan_files")
                    .select("*")
                    .eq("project_id", project_id)
                    .order("created_at")
                )
            )
            if row.get("deleted_at") is None
        ]
        self._attach_plan_media_and_markers(plans)
        self._ensure_pdf_plan_previews(project_id, plans, user_id)
        return plans

    def create_plan(
        self, project_id: str, payload: PlanCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        media = self._get_media_asset(str(payload.media_asset_id))
        if str(media.get("project_id")) != project_id or media.get("media_type") != "plan_source":
            raise ProjectNotFoundError("Plan-Datei nicht gefunden.")

        plan_payload = payload.model_dump(mode="json", exclude_none=True)
        plan_payload.update({"project_id": project_id, "created_by": user.id})
        plan = _single_response_row(
            self._execute(self._client.table("plan_files").insert(plan_payload))
        )
        plan["media_asset"] = self._with_media_signed_url(media)
        plan["preview_media_asset"] = self._create_plan_preview_media(
            project_id, plan, media, user
        )
        plan["markers"] = []
        self._record_activity(project_id, user.id, "plan.created", "plan_file", str(plan["id"]))
        return plan

    def _create_plan_preview_media(
        self,
        project_id: str,
        plan: dict[str, Any],
        media: dict[str, Any],
        user: AuthenticatedUser,
    ) -> Optional[dict[str, Any]]:
        if str(plan.get("file_type") or "").casefold() != "pdf":
            return None

        try:
            source_bytes = self._download_media_bytes(media)
            render_result = render_annotated_plan({**plan, "media_asset": media}, source_bytes, [])
            preview_media = self._store_plan_render(project_id, plan, render_result, user, 0)
        except (PlanRenderError, ProjectRepositoryError) as exc:
            raise ProjectRepositoryError("PDF-Vorschau konnte nicht gerendert werden.") from exc

        self._execute(
            self._client.table("plan_files")
            .update(
                {
                    "preview_media_asset_id": preview_media["id"],
                    "updated_at": _now_iso(),
                    "revision": int(plan.get("revision") or 1) + 1,
                }
            )
            .eq("id", str(plan["id"]))
        )
        plan["preview_media_asset_id"] = preview_media["id"]
        return self._with_media_signed_url(preview_media)

    def _ensure_pdf_plan_previews(
        self, project_id: str, plans: list[dict[str, Any]], user_id: str
    ) -> None:
        user = AuthenticatedUser(id=user_id, email="", display_name="")
        for plan in plans:
            media = plan.get("media_asset") or {}
            if (
                str(plan.get("file_type") or "").casefold() != "pdf"
                or plan.get("preview_media_asset_id")
                or str(media.get("mime_type") or "").casefold() != "application/pdf"
            ):
                continue
            try:
                plan["preview_media_asset"] = self._create_plan_preview_media(
                    project_id, plan, media, user
                )
            except ProjectRepositoryError:
                plan["preview_media_asset"] = None

    def create_plan_marker(
        self, plan_id: str, payload: PlanMarkerCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        plan = self._get_plan_for_user(plan_id, user.id)
        defect = self._get_defect_for_user(str(payload.defect_id), user.id)
        if str(defect.get("project_id")) != str(plan.get("project_id")):
            raise ProjectRepositoryError("Marker und Mangel muessen im selben Projekt liegen.")

        marker_payload = payload.model_dump(mode="json", exclude_none=True)
        marker_payload.update(
            {
                "project_id": str(plan["project_id"]),
                "plan_file_id": plan_id,
                "created_by": user.id,
            }
        )
        marker = _single_response_row(
            self._execute(self._client.table("plan_markers").insert(marker_payload))
        )
        self._record_activity(
            str(plan["project_id"]), user.id, "plan.marker_created", "plan_marker", str(marker["id"])
        )
        return marker

    def update_plan_marker(
        self, marker_id: str, payload: PlanMarkerUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        marker = self._get_marker_for_user(marker_id, user.id)
        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if payload.defect_id is not None:
            defect = self._get_defect_for_user(str(payload.defect_id), user.id)
            if str(defect.get("project_id")) != str(marker.get("project_id")):
                raise ProjectRepositoryError("Marker und Mangel muessen im selben Projekt liegen.")

        if not update_payload:
            return marker

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(marker.get("revision") or 1) + 1
        updated = _single_response_row(
            self._execute(
                self._client.table("plan_markers").update(update_payload).eq("id", marker_id)
            )
        )
        self._record_activity(
            str(updated["project_id"]),
            user.id,
            "plan.marker_updated",
            "plan_marker",
            str(updated["id"]),
        )
        return updated

    def delete_plan_marker(self, marker_id: str, user: AuthenticatedUser) -> None:
        marker = self._get_marker_for_user(marker_id, user.id)
        self._execute(
            self._client.table("plan_markers")
            .update(
                {
                    "deleted_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "revision": int(marker.get("revision") or 1) + 1,
                }
            )
            .eq("id", marker_id)
        )
        self._record_activity(
            str(marker["project_id"]), user.id, "plan.marker_deleted", "plan_marker", marker_id
        )

    def export_plan(
        self, plan_id: str, payload: PlanExportRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        plan = self._get_plan_for_user(plan_id, user.id)
        project_id = str(plan["project_id"])
        media = self._get_media_asset(str(plan["media_asset_id"]))
        if str(media.get("project_id")) != project_id or media.get("media_type") != "plan_source":
            raise ProjectNotFoundError("Plan-Datei nicht gefunden.")

        plan = dict(plan)
        plan["media_asset"] = media
        self._attach_plan_media_and_markers([plan])
        source_media = self._plan_export_source_media(project_id, plan, media, payload.format, user)
        defects = self.list_defects(project_id, user.id)

        try:
            source_bytes = self._download_media_bytes(source_media)
            output_extension = self._plan_export_extension(plan, source_media, payload.format)
            source_plan = (
                {**plan, "file_type": "png", "media_asset": source_media}
                if payload.format == "image" and source_media.get("media_type") == "plan_render"
                else {**plan, "media_asset": source_media}
            )
            render_result = render_annotated_plan_source_export(
                source_plan,
                source_bytes,
                defects,
                output_format=output_extension,
            )
        except (PlanRenderError, ProjectRepositoryError) as exc:
            logger.warning(
                "Plan export could not be rendered.",
                extra={
                    "error_code": "PLAN_EXPORT_FAILED",
                    "plan_file_id": plan_id,
                    "project_id": project_id,
                    "export_format": payload.format,
                    "marker_count": len(plan.get("markers") or []),
                    "exception_type": exc.__class__.__name__,
                },
            )
            raise ProjectRepositoryError("Markierter Plan konnte nicht exportiert werden.") from exc

        fingerprint = plan_export_fingerprint(
            plan,
            source_media,
            defects,
            payload.format,
            render_result.file_extension,
        )
        file_stem = self._plan_export_file_stem(plan)
        file_name = f"{file_stem}_markiert.{render_result.file_extension}"
        storage_path = (
            f"projects/{project_id}/plans/exports/{plan_id}_{payload.format}_"
            f"{fingerprint}.{render_result.file_extension}"
        )
        self._upload_plan_export(storage_path, render_result.content, render_result.mime_type)
        self._record_activity(
            project_id,
            user.id,
            "plan.exported",
            "plan_file",
            plan_id,
            {
                "format": payload.format,
                "storage_path": storage_path,
                "mime_type": render_result.mime_type,
                "marker_count": len(plan.get("markers") or []),
            },
        )
        return {
            "download_url": self._signed_download_url(storage_path, file_name),
            "file_name": file_name,
            "mime_type": render_result.mime_type,
            "expires_in_seconds": PLAN_EXPORT_SIGNED_URL_SECONDS,
        }

    def _plan_export_source_media(
        self,
        project_id: str,
        plan: dict[str, Any],
        media: dict[str, Any],
        export_format: str,
        user: AuthenticatedUser,
    ) -> dict[str, Any]:
        if export_format == "source":
            return media
        if str(plan.get("file_type") or "").casefold() == "pdf":
            source_media = self._report_plan_render_source_media(project_id, plan, user)
            plan["preview_media_asset"] = source_media
            plan["preview_media_asset_id"] = source_media.get("id")
            return source_media
        return media

    def _plan_export_extension(
        self,
        plan: dict[str, Any],
        source_media: dict[str, Any],
        export_format: str,
    ) -> str:
        if export_format == "image":
            return "png"
        mime_type = str(source_media.get("mime_type") or "").casefold()
        file_type = str(plan.get("file_type") or "").casefold()
        if file_type == "pdf" or mime_type == "application/pdf":
            return "pdf"
        if file_type in {"jpg", "jpeg"} or mime_type in {"image/jpeg", "image/jpg"}:
            return "jpg"
        return "png"

    def _upload_plan_export(self, storage_path: str, content: bytes, mime_type: str) -> None:
        try:
            self._client.storage.from_(PROJECT_FILES_BUCKET).upload(
                storage_path,
                content,
                {
                    "content-type": mime_type,
                    "upsert": "true",
                },
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Plan-Export konnte nicht gespeichert werden.") from exc

    def _plan_export_file_stem(self, plan: dict[str, Any]) -> str:
        name = str(plan.get("name") or "plan").strip().lower()
        normalized = re.sub(r"[^a-z0-9_-]+", "_", name)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "plan"

    def list_voice_notes(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        voice_notes = _response_data(
            self._execute(
                self._client.table("voice_notes")
                .select("*")
                .eq("project_id", project_id)
                .order("created_at")
            )
        )
        voice_notes = [row for row in voice_notes if row.get("deleted_at") is None]
        self._attach_voice_note_media(voice_notes)
        return voice_notes

    def create_voice_note(
        self, project_id: str, payload: VoiceNoteCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        media = self._get_media_asset(str(payload.media_asset_id))
        if str(media.get("project_id")) != project_id or media.get("media_type") != "audio":
            raise ProjectRepositoryError("Sprachnotiz benoetigt eine Audio-Datei im Projekt.")
        self._validate_voice_note_target(
            project_id,
            payload.target_type,
            str(payload.defect_id) if payload.defect_id is not None else None,
            user.id,
        )

        voice_note_payload = payload.model_dump(mode="json", exclude_none=True)
        voice_note_payload.update({"project_id": project_id, "created_by": user.id})
        voice_note = _single_response_row(
            self._execute(self._client.table("voice_notes").insert(voice_note_payload))
        )
        voice_note["media_asset"] = self._with_media_signed_url(media)
        self._record_activity(
            project_id, user.id, "voice_note.created", "voice_note", str(voice_note["id"])
        )
        return voice_note

    def update_voice_note(
        self, voice_note_id: str, payload: VoiceNoteUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        voice_note = self._get_voice_note_for_user(voice_note_id, user.id)
        next_target_type = (
            payload.target_type
            if "target_type" in payload.model_fields_set and payload.target_type is not None
            else str(voice_note.get("target_type") or "")
        )
        next_defect_id = (
            str(payload.defect_id)
            if "defect_id" in payload.model_fields_set and payload.defect_id is not None
            else str(voice_note.get("defect_id"))
            if voice_note.get("defect_id") is not None
            else None
        )
        self._validate_voice_note_target(
            str(voice_note["project_id"]), next_target_type, next_defect_id, user.id
        )

        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if not update_payload:
            self._attach_voice_note_media([voice_note])
            return voice_note

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(voice_note.get("revision") or 1) + 1
        updated = _single_response_row(
            self._execute(
                self._client.table("voice_notes").update(update_payload).eq("id", voice_note_id)
            )
        )
        self._attach_voice_note_media([updated])
        self._record_activity(
            str(updated["project_id"]), user.id, "voice_note.updated", "voice_note", str(updated["id"])
        )
        return updated

    def delete_voice_note(self, voice_note_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        voice_note = self._get_voice_note_for_user(voice_note_id, user.id)
        deleted = _single_response_row(
            self._execute(
                self._client.table("voice_notes")
                .update(
                    {
                        "deleted_at": _now_iso(),
                        "updated_at": _now_iso(),
                        "revision": int(voice_note.get("revision") or 1) + 1,
                    }
                )
                .eq("id", voice_note_id)
            )
        )
        self._record_activity(
            str(deleted["project_id"]), user.id, "voice_note.deleted", "voice_note", voice_note_id
        )
        self._attach_voice_note_media([deleted])
        return deleted

    def _validate_voice_note_target(
        self,
        project_id: str,
        target_type: str,
        defect_id: Optional[str],
        user_id: str,
    ) -> None:
        if target_type != "defect_description":
            raise ProjectRepositoryError(
                "Sprachnotiz muss einem konkreten Eintrag zugeordnet sein."
            )
        if defect_id is None:
            raise ProjectRepositoryError("Sprachnotiz fuer Mangel benoetigt einen Mangel.")
        defect = self._get_defect_for_user(defect_id, user_id)
        if str(defect.get("project_id")) != project_id:
            raise ProjectRepositoryError(
                "Sprachnotiz und Mangel muessen im selben Projekt liegen."
            )

    def list_general_findings(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        rows = _response_data(
            self._execute(
                self._client.table("general_findings")
                .select("*")
                .eq("project_id", project_id)
                .order("sort_order")
                .order("created_at")
            )
        )
        return [row for row in rows if row.get("deleted_at") is None]

    def create_general_finding(
        self, project_id: str, payload: GeneralFindingCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        self._validate_voice_note_project(payload.source_voice_note_id, project_id, user.id)
        finding_payload = payload.model_dump(mode="json", exclude_none=True)
        finding_payload.update(
            {
                "project_id": project_id,
                "created_by": user.id,
                "sort_order": payload.sort_order
                if payload.sort_order is not None
                else self._next_general_finding_sort_order(project_id),
            }
        )
        finding = _single_response_row(
            self._execute(self._client.table("general_findings").insert(finding_payload))
        )
        self._record_activity(
            project_id, user.id, "general_finding.created", "general_finding", str(finding["id"])
        )
        return finding

    def update_general_finding(
        self, finding_id: str, payload: GeneralFindingUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        finding = self._get_general_finding_for_user(finding_id, user.id)
        self._validate_voice_note_project(
            payload.source_voice_note_id, str(finding["project_id"]), user.id
        )
        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if not update_payload:
            return finding

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(finding.get("revision") or 1) + 1
        updated = _single_response_row(
            self._execute(
                self._client.table("general_findings").update(update_payload).eq("id", finding_id)
            )
        )
        self._record_activity(
            str(updated["project_id"]),
            user.id,
            "general_finding.updated",
            "general_finding",
            str(updated["id"]),
        )
        return updated

    def delete_general_finding(self, finding_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        finding = self._get_general_finding_for_user(finding_id, user.id)
        deleted = _single_response_row(
            self._execute(
                self._client.table("general_findings")
                .update(
                    {
                        "deleted_at": _now_iso(),
                        "updated_at": _now_iso(),
                        "revision": int(finding.get("revision") or 1) + 1,
                    }
                )
                .eq("id", finding_id)
            )
        )
        self._record_activity(
            str(finding["project_id"]),
            user.id,
            "general_finding.deleted",
            "general_finding",
            finding_id,
        )
        return deleted

    def get_project_conclusion(
        self, project_id: str, user_id: str
    ) -> Optional[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        conclusion = self._select_one("project_conclusions", "project_id", project_id)
        if conclusion is None or conclusion.get("deleted_at") is not None:
            return None
        return conclusion

    def upsert_project_conclusion(
        self, project_id: str, payload: ProjectConclusionUpsert, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        self._validate_voice_note_project(payload.source_voice_note_id, project_id, user.id)
        existing = self._select_one("project_conclusions", "project_id", project_id)
        conclusion_payload = payload.model_dump(mode="json", exclude_none=True)
        conclusion_payload.update(
            {
                "project_id": project_id,
                "updated_by": user.id,
                "updated_at": _now_iso(),
                "deleted_at": None,
                "revision": int((existing or {}).get("revision") or 0) + 1,
            }
        )
        conclusion = _single_response_row(
            self._execute(self._client.table("project_conclusions").upsert(conclusion_payload))
        )
        self._record_activity(
            project_id, user.id, "project_conclusion.upserted", "project_conclusion", project_id
        )
        return conclusion

    def delete_project_conclusion(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        conclusion = self._select_one("project_conclusions", "project_id", project_id)
        if conclusion is None or conclusion.get("deleted_at") is not None:
            raise ProjectNotFoundError("Fazit nicht gefunden.")
        deleted = _single_response_row(
            self._execute(
                self._client.table("project_conclusions")
                .update(
                    {
                        "deleted_at": _now_iso(),
                        "updated_at": _now_iso(),
                        "updated_by": user.id,
                        "revision": int(conclusion.get("revision") or 1) + 1,
                    }
                )
                .eq("project_id", project_id)
            )
        )
        self._record_activity(
            project_id, user.id, "project_conclusion.deleted", "project_conclusion", project_id
        )
        return deleted
