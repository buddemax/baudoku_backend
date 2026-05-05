from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.schemas import (
    DefectCreate,
    DefectMediaLinkCreate,
    DefectMediaLinkUpdate,
    DefectUpdate,
    GeneralFindingCreate,
    GeneralFindingUpdate,
    MediaAssetUpdate,
    MediaCompleteUploadRequest,
    PlanCreate,
    PlanMarkerCreate,
    PlanMarkerUpdate,
    ProjectConclusionUpsert,
    ProjectUpdate,
    SyncOperation,
    VoiceNoteCreate,
    VoiceNoteUpdate,
)

from baudoku_api.repositories.project_helpers import (
    SYNC_ENTITY_TYPE_BY_OPERATION,
    SYNC_OPERATION_EVENT_TYPE,
    ProjectNotFoundError,
    ProjectRepositoryError,
    SyncConflictError,
    _response_data,
)


class ProjectSyncMixin:
    def sync_pull(
        self, user_id: str, updated_since: Optional[datetime] = None
    ) -> dict[str, list[dict[str, Any]]]:
        all_projects = self.list_projects(user_id, include_deleted=True)
        projects = self._filter_sync_rows(all_projects, updated_since)
        project_ids = [str(project["id"]) for project in all_projects]
        if not project_ids:
            return {
                "projects": [],
                "defects": [],
                "media_assets": [],
                "defect_media_links": [],
                "plan_files": [],
                "plan_markers": [],
                "voice_notes": [],
                "general_findings": [],
                "project_conclusions": [],
                "tombstones": [],
            }

        all_defects = self._select_project_rows("defects", project_ids)
        defects = self._filter_sync_rows(all_defects, updated_since)
        media_assets = self._filter_sync_rows(
            self._select_project_rows("media_assets", project_ids), updated_since
        )
        plan_files = self._filter_sync_rows(
            self._select_project_rows("plan_files", project_ids), updated_since
        )
        plan_markers = self._filter_sync_rows(
            self._select_project_rows("plan_markers", project_ids), updated_since
        )
        voice_notes = self._filter_sync_rows(
            self._select_project_rows("voice_notes", project_ids), updated_since
        )
        general_findings = self._filter_sync_rows(
            self._select_project_rows("general_findings", project_ids), updated_since
        )
        project_conclusions = self._filter_sync_rows(
            self._select_project_rows("project_conclusions", project_ids), updated_since
        )
        defect_ids = [str(defect["id"]) for defect in defects]
        if updated_since is not None:
            defect_ids = [str(defect["id"]) for defect in all_defects]
        defect_media_links = self._filter_sync_rows(
            self._select_rows_in("defect_media_links", "defect_id", defect_ids), updated_since
        )
        media_assets = [
            self._with_media_signed_url(row) if row.get("deleted_at") is None else row
            for row in media_assets
        ]
        return {
            "projects": projects,
            "defects": defects,
            "media_assets": media_assets,
            "defect_media_links": defect_media_links,
            "plan_files": plan_files,
            "plan_markers": plan_markers,
            "voice_notes": voice_notes,
            "general_findings": general_findings,
            "project_conclusions": project_conclusions,
            "tombstones": self._sync_tombstones(
                {
                    "project": projects,
                    "defect": defects,
                    "media_asset": media_assets,
                    "defect_media_link": defect_media_links,
                    "plan_file": plan_files,
                    "plan_marker": plan_markers,
                    "voice_note": voice_notes,
                    "general_finding": general_findings,
                    "project_conclusion": project_conclusions,
                }
            ),
        }

    def sync_push(
        self, operations: list[SyncOperation], user: AuthenticatedUser
    ) -> dict[str, list[dict[str, Any]]]:
        applied: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for operation in operations:
            try:
                existing_result = self._previous_sync_operation_result(operation, user)
                if existing_result is not None:
                    applied.append(
                        {
                            "client_operation_id": operation.client_operation_id,
                            "result": existing_result,
                        }
                    )
                    continue

                result = self._apply_sync_operation(operation, user)
                if result is None:
                    rejected.append(
                        {
                            "client_operation_id": operation.client_operation_id,
                            "detail": f"Operation {operation.type} wird noch nicht unterstuetzt.",
                        }
                    )
                    continue

                self._record_sync_operation_result(operation, user, result)
                applied.append(
                    {"client_operation_id": operation.client_operation_id, "result": result}
                )
            except SyncConflictError as exc:
                rejected.append(
                    {
                        "client_operation_id": operation.client_operation_id,
                        "code": "CONFLICT",
                        "message": str(exc),
                        "server_entity": exc.server_entity,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive per-operation isolation
                rejected.append(
                    {
                        "client_operation_id": operation.client_operation_id,
                        "detail": str(exc),
                    }
                )
        return {"applied": applied, "rejected": rejected}

    def _apply_sync_operation(
        self, operation: SyncOperation, user: AuthenticatedUser
    ) -> Optional[dict[str, Any]]:
        if operation.type == "project.update":
            project_id = str(operation.payload["id"])
            self._assert_sync_revision("projects", "id", project_id, operation.payload)
            return self.update_project(project_id, ProjectUpdate(**operation.payload), user)
        if operation.type == "project.delete":
            project_id = str(operation.payload["id"])
            project = self._assert_sync_revision("projects", "id", project_id, operation.payload)
            self.delete_project(project_id, user)
            return {**project, "deleted": True}
        if operation.type == "defect.create":
            project_id = str(operation.payload["project_id"])
            return self.create_defect(project_id, DefectCreate(**operation.payload), user)
        if operation.type == "defect.update":
            defect_id = str(operation.payload["id"])
            self._assert_sync_revision("defects", "id", defect_id, operation.payload)
            return self.update_defect(defect_id, DefectUpdate(**operation.payload), user)
        if operation.type == "defect.delete":
            defect_id = str(operation.payload["id"])
            self._assert_sync_revision("defects", "id", defect_id, operation.payload)
            deleted = self.delete_defect(defect_id, user)
            return {**deleted, "deleted": True}
        if operation.type in {"defect.reorder", "defects.reorder"}:
            project_id = str(operation.payload["project_id"])
            defect_ids = [str(defect_id) for defect_id in operation.payload["defect_ids"]]
            return {
                "id": project_id,
                "project_id": project_id,
                "items": self.reorder_defects(project_id, defect_ids, user),
            }
        if operation.type in {"media.create", "media.complete_upload"}:
            project_id = str(operation.payload["project_id"])
            return self.complete_media_upload(
                project_id, MediaCompleteUploadRequest(**operation.payload), user
            )
        if operation.type in {"media.update", "media_asset.update"}:
            media_asset_id = str(operation.payload["id"])
            self._assert_sync_revision("media_assets", "id", media_asset_id, operation.payload)
            return self.update_media_asset(media_asset_id, MediaAssetUpdate(**operation.payload), user)
        if operation.type in {"media.delete", "media_asset.delete"}:
            media_asset_id = str(operation.payload["id"])
            self._assert_sync_revision("media_assets", "id", media_asset_id, operation.payload)
            deleted = self.delete_media_asset(media_asset_id, user)
            return {**deleted, "deleted": True}
        if operation.type in {
            "defect_media_link.create",
            "media_link.create",
            "media.link.create",
        }:
            defect_id = str(operation.payload["defect_id"])
            return self.create_defect_media_link(
                defect_id, DefectMediaLinkCreate(**operation.payload), user
            )
        if operation.type in {
            "defect_media_link.update",
            "media_link.update",
            "media.link.update",
        }:
            link_id = str(operation.payload["id"])
            self._assert_sync_revision("defect_media_links", "id", link_id, operation.payload)
            return self.update_defect_media_link(
                link_id, DefectMediaLinkUpdate(**operation.payload), user
            )
        if operation.type in {
            "defect_media_link.delete",
            "media_link.delete",
            "media.link.delete",
        }:
            link_id = str(operation.payload["id"])
            self._assert_sync_revision("defect_media_links", "id", link_id, operation.payload)
            deleted = self.delete_defect_media_link(link_id, user)
            return {**deleted, "deleted": True}
        if operation.type == "plan.create":
            project_id = str(operation.payload["project_id"])
            return self.create_plan(project_id, PlanCreate(**operation.payload), user)
        if operation.type == "plan_marker.create":
            plan_id = str(operation.payload["plan_file_id"])
            return self.create_plan_marker(plan_id, PlanMarkerCreate(**operation.payload), user)
        if operation.type == "plan_marker.update":
            marker_id = str(operation.payload["id"])
            self._assert_sync_revision("plan_markers", "id", marker_id, operation.payload)
            return self.update_plan_marker(marker_id, PlanMarkerUpdate(**operation.payload), user)
        if operation.type == "plan_marker.delete":
            marker_id = str(operation.payload["id"])
            self._assert_sync_revision("plan_markers", "id", marker_id, operation.payload)
            marker = self._get_marker_for_user(marker_id, user.id)
            self.delete_plan_marker(marker_id, user)
            return {**marker, "deleted": True}
        if operation.type == "voice_note.create":
            project_id = str(operation.payload["project_id"])
            return self.create_voice_note(project_id, VoiceNoteCreate(**operation.payload), user)
        if operation.type == "voice_note.update":
            voice_note_id = str(operation.payload["id"])
            self._assert_sync_revision("voice_notes", "id", voice_note_id, operation.payload)
            return self.update_voice_note(voice_note_id, VoiceNoteUpdate(**operation.payload), user)
        if operation.type == "voice_note.delete":
            voice_note_id = str(operation.payload["id"])
            self._assert_sync_revision("voice_notes", "id", voice_note_id, operation.payload)
            deleted = self.delete_voice_note(voice_note_id, user)
            return {**deleted, "deleted": True}
        if operation.type == "general_finding.create":
            project_id = str(operation.payload["project_id"])
            return self.create_general_finding(
                project_id, GeneralFindingCreate(**operation.payload), user
            )
        if operation.type == "general_finding.update":
            finding_id = str(operation.payload["id"])
            self._assert_sync_revision("general_findings", "id", finding_id, operation.payload)
            return self.update_general_finding(
                finding_id, GeneralFindingUpdate(**operation.payload), user
            )
        if operation.type == "general_finding.delete":
            finding_id = str(operation.payload["id"])
            self._assert_sync_revision("general_findings", "id", finding_id, operation.payload)
            deleted = self.delete_general_finding(finding_id, user)
            return {**deleted, "deleted": True}
        if operation.type == "project_conclusion.upsert":
            project_id = str(operation.payload["project_id"])
            if "base_revision" in operation.payload:
                self._assert_sync_revision(
                    "project_conclusions", "project_id", project_id, operation.payload
                )
            return self.upsert_project_conclusion(
                project_id, ProjectConclusionUpsert(**operation.payload), user
            )
        if operation.type == "project_conclusion.delete":
            project_id = str(operation.payload["project_id"])
            self._assert_sync_revision(
                "project_conclusions", "project_id", project_id, operation.payload
            )
            deleted = self.delete_project_conclusion(project_id, user)
            return {**deleted, "deleted": True}
        return None

    def _assert_sync_revision(
        self,
        table: str,
        column: str,
        value: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = self._select_one(table, column, value)
        if row is None:
            raise ProjectNotFoundError("Sync-Ziel nicht gefunden.")

        base_revision = payload.get("base_revision")
        if base_revision is None:
            return row

        try:
            expected_revision = int(base_revision)
            current_revision = int(row.get("revision") or 0)
        except (TypeError, ValueError) as exc:
            raise ProjectRepositoryError("Sync-Revision ist ungueltig.") from exc

        if current_revision != expected_revision:
            raise SyncConflictError(
                "Lokaler Stand ist veraltet. Bitte Serverstand pruefen und erneut synchronisieren.",
                row,
            )
        return row

    def _previous_sync_operation_result(
        self, operation: SyncOperation, user: AuthenticatedUser
    ) -> Optional[dict[str, Any]]:
        event = self._get_sync_operation_event(operation, user)
        if event is None:
            return None

        entity_type = str(event.get("entity_type") or "")
        entity_id = event.get("entity_id")
        if entity_id:
            result = self._sync_entity_result(entity_type, str(entity_id))
            if result is not None:
                return result

        metadata = event.get("metadata") or {}
        result = metadata.get("result") if isinstance(metadata, dict) else None
        return result if isinstance(result, dict) else None

    def _get_sync_operation_event(
        self, operation: SyncOperation, user: AuthenticatedUser
    ) -> Optional[dict[str, Any]]:
        if not operation.client_operation_id:
            return None

        response = self._execute(
            self._client.table("activity_events")
            .select("*")
            .eq("actor_user_id", user.id)
            .eq("event_type", SYNC_OPERATION_EVENT_TYPE)
            .contains(
                "metadata",
                {
                    "client_operation_id": operation.client_operation_id,
                    "operation_type": operation.type,
                },
            )
            .limit(1)
        )
        rows = _response_data(response)
        return rows[0] if rows else None

    def _record_sync_operation_result(
        self, operation: SyncOperation, user: AuthenticatedUser, result: dict[str, Any]
    ) -> None:
        if not operation.client_operation_id:
            return

        entity_type = SYNC_ENTITY_TYPE_BY_OPERATION.get(operation.type)
        entity_id = result.get("id") or (
            result.get("project_id") if entity_type == "project_conclusion" else None
        )
        if not entity_type or not entity_id:
            return

        self._record_activity(
            self._sync_project_id(operation, result),
            user.id,
            SYNC_OPERATION_EVENT_TYPE,
            entity_type,
            str(entity_id),
            {
                "client_operation_id": operation.client_operation_id,
                "operation_type": operation.type,
                "result": result,
            },
        )

    def _sync_entity_result(self, entity_type: str, entity_id: str) -> Optional[dict[str, Any]]:
        table_by_entity_type = {
            "project": "projects",
            "defect": "defects",
            "media_asset": "media_assets",
            "defect_media_link": "defect_media_links",
            "plan_file": "plan_files",
            "plan_marker": "plan_markers",
            "voice_note": "voice_notes",
            "general_finding": "general_findings",
            "project_conclusion": "project_conclusions",
        }
        table = table_by_entity_type.get(entity_type)
        if table is None:
            return None

        select_column = "project_id" if entity_type == "project_conclusion" else "id"
        row = self._select_one(table, select_column, entity_id)
        if row is None:
            return None
        if entity_type == "defect":
            self._attach_defect_media([row])
        elif entity_type == "media_asset":
            row = self._with_media_signed_url(row)
        elif entity_type == "defect_media_link":
            media = self._get_media_asset(str(row["media_asset_id"]))
            row["media_asset"] = self._with_media_signed_url(media)
        elif entity_type == "plan_file":
            self._attach_plan_media_and_markers([row])
        elif entity_type == "voice_note":
            self._attach_voice_note_media([row])
        return row

    def _sync_project_id(self, operation: SyncOperation, result: dict[str, Any]) -> Optional[str]:
        if result.get("project_id"):
            return str(result["project_id"])
        if operation.payload.get("project_id"):
            return str(operation.payload["project_id"])

        defect_id = result.get("defect_id") or operation.payload.get("defect_id")
        if defect_id:
            defect = self._select_one("defects", "id", str(defect_id))
            if defect is not None and defect.get("project_id"):
                return str(defect["project_id"])
        return None

