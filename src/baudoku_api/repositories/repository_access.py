from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.reports import PlanRenderError, render_annotated_plan

from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    ProjectNotFoundError,
    ProjectRepositoryError,
    _derive_project_status,
    _now_iso,
    _plan_source_supports_image_render,
    _response_data,
    _single_response_row,
    _text,
)

logger = logging.getLogger(__name__)
PLAN_RENDER_WARNING = (
    "Planbild konnte nicht fuer den Bericht gerendert werden. "
    "Marker werden darunter nur als Liste ausgegeben."
)


class ProjectRepositoryAccessMixin:
    _MEDIA_UPLOAD_RULES = {
        "photo": {
            "folder": "photos",
            "mime_types": {"image/jpeg", "image/jpg", "image/png"},
        },
        "audio": {
            "folder": "audio",
            "mime_prefixes": ("audio/",),
        },
        "plan_source": {
            "folder": "plans",
            "mime_types": {"application/pdf", "image/jpeg", "image/jpg", "image/png"},
        },
        "plan_render": {
            "folder": "plans",
            "mime_types": {"image/png"},
        },
        "report_docx": {
            "folder": "reports",
            "mime_types": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            },
        },
    }

    def _create_memberships(self, project_id: str, current_user_id: str) -> None:
        active_profiles_response = self._execute(
            self._client.table("profiles").select("id").eq("is_active", True)
        )
        user_ids = {str(row["id"]) for row in _response_data(active_profiles_response)}
        user_ids.add(current_user_id)

        memberships = [
            {"project_id": project_id, "user_id": user_id}
            for user_id in sorted(user_ids)
        ]
        if memberships:
            self._execute(self._client.table("project_members").insert(memberships))

    def _record_activity(
        self,
        project_id: Optional[str],
        user_id: str,
        event_type: str,
        entity_type: str,
        entity_id: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self._execute(
            self._client.table("activity_events").insert(
                {
                    "project_id": project_id,
                    "actor_user_id": user_id,
                    "event_type": event_type,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "metadata": metadata or {},
                }
            )
        )

    def _next_defect_sort_order(self, project_id: str) -> float:
        rows = _response_data(
            self._execute(
                self._client.table("defects")
                .select("report_sort_order")
                .eq("project_id", project_id)
            )
        )
        if not rows:
            return 1
        return max(float(row.get("report_sort_order") or 0) for row in rows) + 1

    def _next_report_version(self, project_id: str) -> int:
        rows = _response_data(
            self._execute(
                self._client.table("report_versions")
                .select("version_number")
                .eq("project_id", project_id)
            )
        )
        if not rows:
            return 1
        return max(int(row.get("version_number") or 0) for row in rows) + 1

    def _next_general_finding_sort_order(self, project_id: str) -> float:
        rows = _response_data(
            self._execute(
                self._client.table("general_findings")
                .select("sort_order")
                .eq("project_id", project_id)
            )
        )
        if not rows:
            return 1
        return max(float(row.get("sort_order") or 0) for row in rows) + 1

    def _get_defect_for_user(self, defect_id: str, user_id: str) -> dict[str, Any]:
        defect = self._select_one("defects", "id", defect_id)
        if defect is None or defect.get("deleted_at") is not None:
            raise ProjectNotFoundError("Mangel nicht gefunden.")
        self._get_project_for_user(str(defect["project_id"]), user_id)
        return defect

    def _get_plan_for_user(self, plan_id: str, user_id: str) -> dict[str, Any]:
        plan = self._select_one("plan_files", "id", plan_id)
        if plan is None:
            raise ProjectNotFoundError("Plan nicht gefunden.")
        self._get_project_for_user(str(plan["project_id"]), user_id)
        return plan

    def _get_marker_for_user(self, marker_id: str, user_id: str) -> dict[str, Any]:
        marker = self._select_one("plan_markers", "id", marker_id)
        if marker is None or marker.get("deleted_at") is not None:
            raise ProjectNotFoundError("Marker nicht gefunden.")
        self._get_project_for_user(str(marker["project_id"]), user_id)
        return marker

    def _get_voice_note_for_user(self, voice_note_id: str, user_id: str) -> dict[str, Any]:
        voice_note = self._select_one("voice_notes", "id", voice_note_id)
        if voice_note is None:
            raise ProjectNotFoundError("Sprachnotiz nicht gefunden.")
        self._get_project_for_user(str(voice_note["project_id"]), user_id)
        return voice_note

    def _get_general_finding_for_user(self, finding_id: str, user_id: str) -> dict[str, Any]:
        finding = self._select_one("general_findings", "id", finding_id)
        if finding is None:
            raise ProjectNotFoundError("Allgemeine Feststellung nicht gefunden.")
        self._get_project_for_user(str(finding["project_id"]), user_id)
        return finding

    def _get_media_asset(self, media_asset_id: str) -> dict[str, Any]:
        media = self._select_one("media_assets", "id", media_asset_id)
        if media is None or media.get("deleted_at") is not None:
            raise ProjectNotFoundError("Datei nicht gefunden.")
        return media

    def _get_defect_media_link_for_user(
        self, link_id: str, user_id: str
    ) -> dict[str, Any]:
        link = self._select_one("defect_media_links", "id", link_id)
        if link is None or link.get("deleted_at") is not None:
            raise ProjectNotFoundError("Foto-Zuordnung nicht gefunden.")
        defect = self._get_defect_for_user(str(link["defect_id"]), user_id)
        if str(defect.get("project_id") or "") == "":
            raise ProjectRepositoryError("Foto-Zuordnung ist keinem Projekt zugeordnet.")
        return link

    def _existing_defect_media_link(
        self, defect_id: str, media_asset_id: str, include_deleted: bool = False
    ) -> Optional[dict[str, Any]]:
        rows = _response_data(
            self._execute(
                self._client.table("defect_media_links")
                .select("*")
                .eq("defect_id", defect_id)
                .eq("media_asset_id", media_asset_id)
                .limit(1)
            )
        )
        for row in rows:
            if include_deleted or row.get("deleted_at") is None:
                return row
        return None

    def _filter_sync_rows(
        self, rows: list[dict[str, Any]], updated_since: Optional[datetime]
    ) -> list[dict[str, Any]]:
        if updated_since is None:
            return rows

        normalized_since = self._normalize_sync_timestamp(updated_since)
        return [
            row
            for row in rows
            if any(
                row_timestamp is not None and row_timestamp > normalized_since
                for row_timestamp in [
                    self._parse_sync_timestamp(row.get(field))
                    for field in ("updated_at", "created_at", "deleted_at")
                ]
            )
        ]

    def _sync_tombstones(
        self, rows_by_entity_type: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        return [
            tombstone
            for entity_type, rows in rows_by_entity_type.items()
            for row in rows
            if (tombstone := self._sync_tombstone(entity_type, row)) is not None
        ]

    def _sync_tombstone(
        self, entity_type: str, row: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        deleted_at = self._parse_sync_timestamp(row.get("deleted_at"))
        entity_id = row.get("project_id") if entity_type == "project_conclusion" else row.get("id")
        if deleted_at is None or entity_id is None:
            return None

        project_id = row.get("project_id")
        updated_at = self._parse_sync_timestamp(row.get("updated_at"))
        return {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "deleted_at": deleted_at.isoformat(),
            **(
                {"project_id": str(project_id)}
                if project_id is not None
                else {"project_id": str(entity_id)}
                if entity_type == "project"
                else {}
            ),
            **({"updated_at": updated_at.isoformat()} if updated_at is not None else {}),
            **({"revision": row["revision"]} if row.get("revision") is not None else {}),
        }

    def _validate_media_upload_payload(self, project_id: str, payload: Any) -> None:
        media_type = str(payload.media_type)
        rules = self._MEDIA_UPLOAD_RULES.get(media_type)
        if rules is None:
            raise ProjectRepositoryError("Medientyp wird nicht unterstuetzt.")
        if payload.storage_bucket != PROJECT_FILES_BUCKET:
            raise ProjectRepositoryError("Upload-Bucket ist ungueltig.")

        storage_path = str(payload.storage_path)
        expected_prefix = f"projects/{project_id}/{rules['folder']}/"
        if not storage_path.startswith(expected_prefix):
            raise ProjectRepositoryError("Dateipfad gehoert nicht zu diesem Projekt.")
        if storage_path.startswith("/") or "/../" in storage_path or storage_path.endswith("/.."):
            raise ProjectRepositoryError("Dateipfad ist ungueltig.")

        mime_type = str(payload.mime_type).casefold()
        allowed_types = {str(item).casefold() for item in rules.get("mime_types", set())}
        allowed_prefixes = tuple(str(item).casefold() for item in rules.get("mime_prefixes", ()))
        if allowed_types and mime_type not in allowed_types:
            raise ProjectRepositoryError("Dateityp passt nicht zum Medientyp.")
        if allowed_prefixes and not mime_type.startswith(allowed_prefixes):
            raise ProjectRepositoryError("Dateityp passt nicht zum Medientyp.")

    def _validate_existing_media_upload(
        self, existing_media: dict[str, Any], project_id: str, payload: Any
    ) -> None:
        expected = {
            "id": str(payload.media_id),
            "project_id": project_id,
            "media_type": str(payload.media_type),
            "storage_bucket": payload.storage_bucket,
            "storage_path": payload.storage_path,
        }
        mismatched_fields = [
            field for field, value in expected.items() if str(existing_media.get(field)) != str(value)
        ]
        if mismatched_fields:
            raise ProjectRepositoryError("Upload ist bereits einer anderen Datei zugeordnet.")

    def _latest_report_preview_confirmation(
        self, project_id: str
    ) -> Optional[dict[str, Any]]:
        rows = _response_data(
            self._execute(
                self._client.table("report_preview_confirmations")
                .select("*")
                .eq("project_id", project_id)
                .order("confirmed_at", desc=True)
                .limit(1)
            )
        )
        return rows[0] if rows else None

    def _active_ai_job(
        self, project_id: str, media_asset_id: str, job_type: str, target_id: str
    ) -> Optional[dict[str, Any]]:
        rows = _response_data(
            self._execute(
                self._client.table("ai_jobs")
                .select("*")
                .eq("project_id", project_id)
                .eq("media_asset_id", media_asset_id)
                .eq("job_type", job_type)
                .in_("status", ["queued", "processing"])
                .order("updated_at", desc=True)
                .limit(10)
            )
        )
        for row in rows:
            if self._ai_input_ref_matches(row, target_id):
                return row
        return None

    def _create_ai_job(
        self,
        project_id: str,
        media_asset_id: str,
        job_type: str,
        provider: str,
        input_ref: str,
    ) -> dict[str, Any]:
        return _single_response_row(
            self._execute(
                self._client.table("ai_jobs").insert(
                    {
                        "project_id": project_id,
                        "media_asset_id": media_asset_id,
                        "job_type": job_type,
                        "status": "queued",
                        "provider": provider,
                        "input_ref": input_ref,
                    }
                )
            )
        )

    def _mark_ai_job_processing(self, job_id: str) -> dict[str, Any]:
        return _single_response_row(
            self._execute(
                self._client.table("ai_jobs")
                .update({"status": "processing", "updated_at": _now_iso()})
                .eq("id", job_id)
            )
        )

    def _claim_ai_job_processing(self, job_id: str) -> Optional[dict[str, Any]]:
        rows = _response_data(
            self._execute(
                self._client.table("ai_jobs")
                .update({"status": "processing", "updated_at": _now_iso()})
                .eq("id", job_id)
                .eq("status", "queued")
            )
        )
        return rows[0] if rows else None

    def _complete_ai_job(self, job_id: str, result_text: str) -> dict[str, Any]:
        return _single_response_row(
            self._execute(
                self._client.table("ai_jobs")
                .update(
                    {
                        "status": "done",
                        "result_text": result_text,
                        "error_message": None,
                        "updated_at": _now_iso(),
                    }
                )
                .eq("id", job_id)
            )
        )

    def _fail_ai_job(self, job_id: str, error_message: str) -> dict[str, Any]:
        return _single_response_row(
            self._execute(
                self._client.table("ai_jobs")
                .update(
                    {
                        "status": "failed",
                        "error_message": error_message,
                        "updated_at": _now_iso(),
                    }
                )
                .eq("id", job_id)
            )
        )

    def _render_report_plans(
        self,
        project_id: str,
        plans: list[dict[str, Any]],
        defects: list[dict[str, Any]],
        user: AuthenticatedUser,
        version_number: int,
    ) -> list[dict[str, Any]]:
        return [
            self._render_report_plan(project_id, plan, defects, user, version_number)
            for plan in plans
        ]

    def _render_report_plan(
        self,
        project_id: str,
        plan: dict[str, Any],
        defects: list[dict[str, Any]],
        user: AuthenticatedUser,
        version_number: int,
    ) -> dict[str, Any]:
        rendered_plan = dict(plan)
        try:
            source_media = self._report_plan_render_source_media(project_id, rendered_plan, user)
        except ProjectRepositoryError as exc:
            self._log_plan_render_failure(rendered_plan, exc)
            return self._with_plan_render_warning(rendered_plan)

        if not _plan_source_supports_image_render(rendered_plan, source_media):
            if rendered_plan.get("markers"):
                self._log_plan_render_failure(
                    rendered_plan,
                    ProjectRepositoryError("Planquelle wird fuer Bildrendering nicht unterstuetzt."),
                )
                return self._with_plan_render_warning(rendered_plan)
            return rendered_plan

        try:
            source_bytes = self._download_report_image(str(source_media["storage_path"]))
            source_plan = (
                {**rendered_plan, "file_type": "png", "media_asset": source_media}
                if source_media.get("media_type") == "plan_render"
                else rendered_plan
            )
            render_result = render_annotated_plan(source_plan, source_bytes, defects)
        except (KeyError, PlanRenderError, ProjectRepositoryError) as exc:
            self._log_plan_render_failure(rendered_plan, exc)
            return self._with_plan_render_warning(rendered_plan)

        rendered_plan["media_asset"] = self._store_plan_render(
            project_id,
            rendered_plan,
            render_result,
            user,
            version_number,
        )
        logger.info(
            "Plan rendered for report.",
            extra={
                "error_code": "PLAN_RENDERED_FOR_REPORT",
                "plan_file_id": str(rendered_plan.get("id") or ""),
                "source_media_type": str(source_media.get("media_type") or ""),
                "source_media_id": str(source_media.get("id") or ""),
                "report_version_number": version_number,
                "render_width": render_result.width,
                "render_height": render_result.height,
                "marker_count": len(rendered_plan.get("markers") or []),
            },
        )
        return rendered_plan

    def _report_plan_render_source_media(
        self,
        project_id: str,
        rendered_plan: dict[str, Any],
        user: AuthenticatedUser,
    ) -> dict[str, Any]:
        preview_media = rendered_plan.get("preview_media_asset")
        if preview_media:
            return preview_media

        source_media = rendered_plan.get("media_asset") or {}
        is_pdf_plan = (
            _text(rendered_plan.get("file_type")).casefold() == "pdf"
            or _text(source_media.get("mime_type")).casefold() == "application/pdf"
        )
        if not is_pdf_plan:
            return source_media

        preview_media = self._create_plan_preview_media(project_id, rendered_plan, source_media, user)
        if preview_media is None:
            raise ProjectRepositoryError("PDF-Vorschau konnte nicht erzeugt werden.")

        rendered_plan["preview_media_asset"] = preview_media
        rendered_plan["preview_media_asset_id"] = preview_media.get("id")
        return preview_media

    def _with_plan_render_warning(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {**plan, "render_error": PLAN_RENDER_WARNING}

    def _log_plan_render_failure(self, plan: dict[str, Any], exc: Exception) -> None:
        logger.warning(
            "Plan could not be rendered for report.",
            extra={
                "error_code": "PLAN_RENDER_FOR_REPORT_FAILED",
                "plan_file_id": str(plan.get("id") or ""),
                "media_asset_id": str(plan.get("media_asset_id") or ""),
                "preview_media_asset_id": str(plan.get("preview_media_asset_id") or ""),
                "exception_type": exc.__class__.__name__,
                "marker_count": len(plan.get("markers") or []),
            },
        )

    def _store_plan_render(
        self,
        project_id: str,
        plan: dict[str, Any],
        render_result: Any,
        user: AuthenticatedUser,
        version_number: int,
    ) -> dict[str, Any]:
        media_id = str(uuid4())
        storage_path = f"projects/{project_id}/plans/{media_id}.png"
        try:
            self._client.storage.from_(PROJECT_FILES_BUCKET).upload(
                storage_path,
                render_result.content,
                {
                    "content-type": render_result.mime_type,
                    "upsert": "false",
                },
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Plan-Render konnte nicht gespeichert werden.") from exc

        media = _single_response_row(
            self._execute(
                self._client.table("media_assets").insert(
                    {
                        "id": media_id,
                        "project_id": project_id,
                        "media_type": render_result.media_type,
                        "storage_bucket": PROJECT_FILES_BUCKET,
                        "storage_path": storage_path,
                        "mime_type": render_result.mime_type,
                        "file_size": len(render_result.content),
                        "width": render_result.width,
                        "height": render_result.height,
                        "caption": f"Planverortung: {_text(plan.get('name')) or 'Plan'}",
                        "created_by": user.id,
                    }
                )
            )
        )
        self._record_activity(
            project_id,
            user.id,
            "plan.rendered",
            "media_asset",
            media_id,
            {
                "plan_file_id": str(plan.get("id") or ""),
                "report_version_number": version_number,
            },
        )
        return media

    def _with_derived_project_status(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = str(project["id"])
        if project.get("deleted_at") is not None:
            return dict(project)

        defects = self._defects_for_status(project_id)
        media_assets = [
            media
            for media in self._select_project_rows("media_assets", [project_id])
            if media.get("deleted_at") is None
        ]
        general_findings = [
            finding
            for finding in self._select_project_rows("general_findings", [project_id])
            if finding.get("deleted_at") is None
        ]
        project_conclusion = self._select_one("project_conclusions", "project_id", project_id)
        voice_notes = [
            voice_note
            for voice_note in self._select_project_rows("voice_notes", [project_id])
            if voice_note.get("deleted_at") is None
        ]
        report_versions = self._select_project_rows("report_versions", [project_id])
        return {
            **project,
            "status": _derive_project_status(
                defects,
                media_assets,
                general_findings,
                project_conclusion,
                voice_notes,
                report_versions,
            ),
        }

    def _defects_for_status(self, project_id: str) -> list[dict[str, Any]]:
        defects = [
            defect
            for defect in self._select_project_rows("defects", [project_id])
            if defect.get("deleted_at") is None
        ]
        defect_ids = [str(defect["id"]) for defect in defects]
        links = [
            link
            for link in self._select_rows_in("defect_media_links", "defect_id", defect_ids)
            if link.get("deleted_at") is None
        ]
        media_ids = [str(link["media_asset_id"]) for link in links]
        media_by_id = {
            str(media["id"]): media
            for media in self._select_rows_in("media_assets", "id", media_ids)
            if media.get("deleted_at") is None
        }
        links_by_defect: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            enriched = {**link, "media_asset": media_by_id.get(str(link["media_asset_id"]))}
            links_by_defect = {
                **links_by_defect,
                str(link["defect_id"]): [
                    *links_by_defect.get(str(link["defect_id"]), []),
                    enriched,
                ],
            }
        return [
            {
                **defect,
                "media_links": sorted(
                    links_by_defect.get(str(defect["id"]), []),
                    key=lambda link: float(link.get("sort_order") or 0),
                ),
            }
            for defect in defects
        ]

    def _project_report_context(
        self, project: dict[str, Any], user: AuthenticatedUser
    ) -> dict[str, Any]:
        report_project = dict(project)
        if report_project.get("lead_user_display_name"):
            return report_project

        lead_user_id = str(report_project.get("lead_user_id") or "")
        if lead_user_id:
            profile = self._select_one("profiles", "id", lead_user_id)
            if profile is not None:
                report_project["lead_user_display_name"] = (
                    profile.get("display_name") or profile.get("email")
                )

        if not report_project.get("lead_user_display_name"):
            report_project["lead_user_display_name"] = user.display_name or user.email
        return report_project

    def _ai_input_ref(self, target_type: str, target_id: str, storage_path: str) -> str:
        return f"{target_type}:{target_id}|{storage_path}"

    def _ai_input_ref_matches(self, job: dict[str, Any], target_id: str) -> bool:
        input_ref = str(job.get("input_ref") or "")
        return target_id in input_ref

    def _validate_voice_note_project(
        self, voice_note_id: Optional[object], project_id: str, user_id: str
    ) -> None:
        if voice_note_id is None:
            return
        voice_note = self._get_voice_note_for_user(str(voice_note_id), user_id)
        if str(voice_note.get("project_id")) != project_id:
            raise ProjectRepositoryError(
                "Sprachnotiz und Text muessen im selben Projekt liegen."
            )

    def _attach_defect_media(self, defects: list[dict[str, Any]]) -> None:
        defect_ids = [str(defect["id"]) for defect in defects]
        links = [
            link
            for link in self._select_rows_in("defect_media_links", "defect_id", defect_ids)
            if link.get("deleted_at") is None
        ]
        media_ids = [str(link["media_asset_id"]) for link in links]
        media_by_id = {
            str(media["id"]): self._with_media_signed_url(media)
            for media in self._select_rows_in("media_assets", "id", media_ids)
            if media.get("deleted_at") is None
        }
        links_by_defect: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            defect_id = str(link["defect_id"])
            enriched = {**link, "media_asset": media_by_id.get(str(link["media_asset_id"]))}
            links_by_defect = {
                **links_by_defect,
                defect_id: [*links_by_defect.get(defect_id, []), enriched],
            }
        for defect in defects:
            defect["media_links"] = sorted(
                links_by_defect.get(str(defect["id"]), []),
                key=lambda link: float(link.get("sort_order") or 0),
            )

    def _attach_plan_media_and_markers(self, plans: list[dict[str, Any]]) -> None:
        media_ids = [
            str(media_id)
            for plan in plans
            for media_id in (plan.get("media_asset_id"), plan.get("preview_media_asset_id"))
            if media_id
        ]
        media_by_id = {
            str(media["id"]): self._with_media_signed_url(media)
            for media in self._select_rows_in("media_assets", "id", media_ids)
        }
        plan_ids = [str(plan["id"]) for plan in plans]
        markers = [
            marker
            for marker in self._select_rows_in("plan_markers", "plan_file_id", plan_ids)
            if marker.get("deleted_at") is None
        ]
        markers_by_plan: dict[str, list[dict[str, Any]]] = {}
        for marker in markers:
            plan_id = str(marker["plan_file_id"])
            markers_by_plan = {
                **markers_by_plan,
                plan_id: [*markers_by_plan.get(plan_id, []), marker],
            }
        for plan in plans:
            plan["media_asset"] = media_by_id.get(str(plan["media_asset_id"]))
            preview_media_asset_id = plan.get("preview_media_asset_id")
            plan["preview_media_asset"] = (
                media_by_id.get(str(preview_media_asset_id)) if preview_media_asset_id else None
            )
            plan["markers"] = sorted(
                markers_by_plan.get(str(plan["id"]), []),
                key=lambda marker: marker.get("created_at") or "",
            )

    def _attach_voice_note_media(self, voice_notes: list[dict[str, Any]]) -> None:
        media_ids = [str(voice_note["media_asset_id"]) for voice_note in voice_notes]
        media_by_id = {
            str(media["id"]): self._with_media_signed_url(media)
            for media in self._select_rows_in("media_assets", "id", media_ids)
        }
        for voice_note in voice_notes:
            voice_note["media_asset"] = media_by_id.get(str(voice_note["media_asset_id"]))

    def _with_media_signed_url(self, media: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(media)
        try:
            enriched["signed_url"] = self._signed_download_url(str(media["storage_path"]))
        except ProjectRepositoryError as exc:
            logger.warning(
                "Storage signed URL could not be created.",
                extra={
                    "error_code": "STORAGE_SIGNED_URL_UNAVAILABLE",
                    "media_id": str(media.get("id") or ""),
                    "storage_path": str(media.get("storage_path") or ""),
                    "exception_type": exc.__class__.__name__,
                },
            )
            enriched["signed_url"] = None
        return enriched

    def _signed_download_url(self, storage_path: str, download_name: Optional[str] = None) -> str:
        try:
            options: dict[str, Any] = {}
            if download_name:
                options["download"] = download_name
            response = self._client.storage.from_(PROJECT_FILES_BUCKET).create_signed_url(
                storage_path,
                600,
                options or None,
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Download-URL konnte nicht erzeugt werden.") from exc
        return str(response.get("signedUrl") or response.get("signedURL"))

    def _normalize_sync_timestamp(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _parse_sync_timestamp(self, value: object) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return self._normalize_sync_timestamp(value)
        if not isinstance(value, str):
            return None

        normalized_value = value.strip()
        if not normalized_value:
            return None
        if normalized_value.endswith("Z"):
            normalized_value = f"{normalized_value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized_value)
        except ValueError:
            return None
        return self._normalize_sync_timestamp(parsed)

    def _select_project_rows(self, table: str, project_ids: list[str]) -> list[dict[str, Any]]:
        return self._select_rows_in(table, "project_id", project_ids)

    def _select_rows_in(self, table: str, column: str, values: list[str]) -> list[dict[str, Any]]:
        if not values:
            return []
        response = self._execute(self._client.table(table).select("*").in_(column, values))
        return _response_data(response)

    def _select_one(self, table: str, column: str, value: str) -> Optional[dict[str, Any]]:
        response = self._execute(
            self._client.table(table).select("*").eq(column, value).limit(1)
        )
        data = _response_data(response)
        if not data:
            return None
        return data[0]

    def _execute(self, query: Any) -> Any:
        max_attempts = 3
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                return query.execute()
            except Exception as exc:  # pragma: no cover - library-specific exception surface
                last_exc = exc
                if attempt >= max_attempts:
                    break
                logger.warning(
                    "Supabase request failed, retrying.",
                    extra={
                        "error_code": "SUPABASE_TRANSIENT_RETRY",
                        "attempt": attempt,
                        "exception_type": exc.__class__.__name__,
                    },
                )
                time.sleep(0.05 * attempt)

        raise ProjectRepositoryError("Supabase-Anfrage fehlgeschlagen.") from last_exc
