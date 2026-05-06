from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.schemas import (
    DefectCreate,
    DefectMediaLinkCreate,
    DefectMediaLinkUpdate,
    DefectUpdate,
    MediaAssetUpdate,
    MediaCompleteUploadRequest,
    MediaInitUploadRequest,
)

from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    ProjectNotFoundError,
    ProjectRepositoryError,
    _extension_for,
    _now_iso,
    _response_data,
    _single_response_row,
)


class ProjectDefectMediaMixin:
    def list_defects(
        self,
        project_id: str,
        user_id: str,
        kind: Optional[str] = None,
        trade_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        query = self._client.table("defects").select("*").eq("project_id", project_id)
        if kind:
            query = query.eq("kind", kind)
        if trade_id:
            query = query.eq("trade_id", trade_id)
        if category:
            query = query.eq("category", category)
        response = self._execute(query.order("report_sort_order").order("created_at"))
        defects = [row for row in _response_data(response) if row.get("deleted_at") is None]
        self._attach_defect_media(defects)
        return defects

    def create_defect(
        self, project_id: str, payload: DefectCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        defect_payload = payload.model_dump(mode="json", exclude_none=True)
        defect_payload.update(
            {
                "project_id": project_id,
                "created_by": user.id,
                "report_sort_order": self._next_defect_sort_order(project_id),
            }
        )
        defect = _single_response_row(
            self._execute(self._client.table("defects").insert(defect_payload))
        )
        self._record_activity(project_id, user.id, "defect.created", "defect", str(defect["id"]))
        defect["media_links"] = []
        return defect

    def update_defect(
        self, defect_id: str, payload: DefectUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        defect = self._get_defect_for_user(defect_id, user.id)
        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if not update_payload:
            self._attach_defect_media([defect])
            return defect

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(defect.get("revision") or 1) + 1
        updated = _single_response_row(
            self._execute(self._client.table("defects").update(update_payload).eq("id", defect_id))
        )
        self._record_activity(
            str(updated["project_id"]), user.id, "defect.updated", "defect", str(updated["id"])
        )
        self._attach_defect_media([updated])
        return updated

    def delete_defect(self, defect_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        defect = self._get_defect_for_user(defect_id, user.id)
        deleted = _single_response_row(
            self._execute(
                self._client.table("defects")
                .update(
                    {
                        "deleted_at": _now_iso(),
                        "updated_at": _now_iso(),
                        "revision": int(defect.get("revision") or 1) + 1,
                    }
                )
                .eq("id", defect_id)
            )
        )
        self._record_activity(
            str(deleted["project_id"]), user.id, "defect.deleted", "defect", defect_id
        )
        self._attach_defect_media([deleted])
        return deleted

    def reorder_defects(
        self, project_id: str, defect_ids: list[str], user: AuthenticatedUser
    ) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user.id)
        if len(set(defect_ids)) != len(defect_ids):
            raise ProjectRepositoryError("Mangel-Reihenfolge enthaelt doppelte Eintraege.")

        existing_by_id = {
            str(defect["id"]): defect for defect in self.list_defects(project_id, user.id)
        }
        missing_ids = [defect_id for defect_id in defect_ids if defect_id not in existing_by_id]
        if missing_ids:
            raise ProjectNotFoundError("Mindestens ein Mangel gehoert nicht zu diesem Projekt.")

        now = _now_iso()
        for index, defect_id in enumerate(defect_ids, start=1):
            defect = existing_by_id[defect_id]
            self._execute(
                self._client.table("defects")
                .update(
                    {
                        "report_sort_order": float(index),
                        "report_number": index,
                        "updated_at": now,
                        "revision": int(defect.get("revision") or 1) + 1,
                    }
                )
                .eq("id", defect_id)
            )

        self._record_activity(project_id, user.id, "defects.reordered", "project", project_id)
        return self.list_defects(project_id, user.id)

    def init_media_upload(
        self, project_id: str, payload: MediaInitUploadRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        media_id = str(payload.media_id or uuid4())
        if payload.storage_path:
            storage_path = str(payload.storage_path)
            self._validate_media_upload_payload(
                project_id,
                MediaCompleteUploadRequest(
                    media_id=media_id,
                    media_type=payload.media_type,
                    storage_bucket=PROJECT_FILES_BUCKET,
                    storage_path=storage_path,
                    mime_type=payload.mime_type,
                    client_id=payload.client_id,
                ),
            )
        else:
            extension = _extension_for(payload.media_type, payload.mime_type, payload.file_name)
            folder = {
                "photo": "photos",
                "audio": "audio",
                "plan_source": "plans",
                "plan_render": "plans",
                "report_docx": "reports",
                "report_pdf": "reports",
            }[payload.media_type]
            storage_path = f"projects/{project_id}/{folder}/{media_id}.{extension}"

        try:
            signed = self._client.storage.from_(PROJECT_FILES_BUCKET).create_signed_upload_url(
                storage_path
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Upload-URL konnte nicht erzeugt werden.") from exc

        return {
            "media_id": media_id,
            "storage_bucket": PROJECT_FILES_BUCKET,
            "storage_path": storage_path,
            "upload_token": signed["token"],
            "signed_url": signed["signed_url"],
        }

    def complete_media_upload(
        self, project_id: str, payload: MediaCompleteUploadRequest, user: AuthenticatedUser
    ) -> dict[str, Any]:
        self._get_project_for_user(project_id, user.id)
        self._validate_media_upload_payload(project_id, payload)

        media_payload = payload.model_dump(mode="json", exclude_none=True)
        media_id = str(media_payload.pop("media_id"))
        existing_media = self._select_one("media_assets", "id", media_id)
        if existing_media is not None:
            self._validate_existing_media_upload(existing_media, project_id, payload)
            self._verify_completed_storage_upload(project_id, payload)
            return self._with_media_signed_url(existing_media)

        if payload.client_id is not None:
            existing_client_media = self._select_one("media_assets", "client_id", payload.client_id)
            if existing_client_media is not None:
                self._validate_existing_client_media_upload(
                    existing_client_media, project_id, payload
                )
                return self._with_media_signed_url(existing_client_media)

        existing_path_media = self._select_one("media_assets", "storage_path", payload.storage_path)
        if existing_path_media is not None:
            raise ProjectRepositoryError("Dateipfad ist bereits einer anderen Datei zugeordnet.")

        storage_size = self._verify_completed_storage_upload(project_id, payload)
        if str(media_payload.get("caption") or "").strip():
            media_payload["caption_status"] = "edited"
        media_payload["file_size"] = storage_size
        media_payload.update({"id": media_id, "project_id": project_id, "created_by": user.id})
        media = _single_response_row(
            self._execute(self._client.table("media_assets").insert(media_payload))
        )
        self._record_activity(project_id, user.id, "media.uploaded", "media_asset", media_id)
        return self._with_media_signed_url(media)

    def list_media_assets(
        self,
        project_id: str,
        user_id: str,
        media_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        query = self._client.table("media_assets").select("*").eq("project_id", project_id)
        if media_type:
            query = query.eq("media_type", media_type)
        rows = _response_data(self._execute(query.order("created_at")))
        if not include_deleted:
            rows = [row for row in rows if row.get("deleted_at") is None]
        return [self._with_media_signed_url(row) for row in rows]

    def get_media_asset_signed_url(
        self, media_asset_id: str, user: AuthenticatedUser
    ) -> dict[str, Any]:
        media = self._get_media_asset(media_asset_id)
        self._get_project_for_user(str(media["project_id"]), user.id)
        return {
            "media_asset_id": media_asset_id,
            "signed_url": self._signed_download_url(str(media["storage_path"])),
            "expires_in_seconds": 600,
        }

    def create_defect_media_link(
        self, defect_id: str, payload: DefectMediaLinkCreate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        defect = self._get_defect_for_user(defect_id, user.id)
        media = self._get_media_asset(str(payload.media_asset_id))
        if str(media.get("project_id")) != str(defect.get("project_id")):
            raise ProjectNotFoundError("Datei gehoert nicht zu diesem Projekt.")

        link_payload = payload.model_dump(mode="json")
        link_payload["defect_id"] = defect_id
        existing_link = self._existing_defect_media_link(
            defect_id, str(payload.media_asset_id), include_deleted=True
        )
        if existing_link is not None:
            update_payload = {
                "sort_order": payload.sort_order,
                "include_in_report": payload.include_in_report,
                "deleted_at": None,
                "updated_at": _now_iso(),
                "revision": int(existing_link.get("revision") or 1) + 1,
            }
            if payload.client_id is not None:
                update_payload["client_id"] = payload.client_id
            link = _single_response_row(
                self._execute(
                    self._client.table("defect_media_links")
                    .update(update_payload)
                    .eq("id", str(existing_link["id"]))
                )
            )
            link["media_asset"] = self._with_media_signed_url(media)
            return link

        link = _single_response_row(
            self._execute(self._client.table("defect_media_links").insert(link_payload))
        )
        link["media_asset"] = self._with_media_signed_url(media)
        self._record_activity(
            str(defect["project_id"]), user.id, "defect.media_linked", "defect", defect_id
        )
        return link

    def update_defect_media_link(
        self, link_id: str, payload: DefectMediaLinkUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        link = self._get_defect_media_link_for_user(link_id, user.id)
        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if payload.defect_id is not None:
            target_defect = self._get_defect_for_user(str(payload.defect_id), user.id)
            current_defect = self._select_one("defects", "id", str(link["defect_id"]))
            if str(target_defect.get("project_id")) != str((current_defect or {}).get("project_id")):
                raise ProjectRepositoryError("Foto-Zuordnung muss im selben Projekt bleiben.")
            update_payload["defect_id"] = str(payload.defect_id)
        if not update_payload:
            media = self._get_media_asset(str(link["media_asset_id"]))
            link["media_asset"] = self._with_media_signed_url(media)
            return link

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(link.get("revision") or 1) + 1
        updated = _single_response_row(
            self._execute(
                self._client.table("defect_media_links").update(update_payload).eq("id", link_id)
            )
        )
        media = self._get_media_asset(str(updated["media_asset_id"]))
        updated["media_asset"] = self._with_media_signed_url(media)
        defect = self._select_one("defects", "id", str(updated["defect_id"]))
        self._record_activity(
            str((defect or {}).get("project_id")),
            user.id,
            "defect.media_link_updated",
            "defect_media_link",
            link_id,
        )
        return updated

    def delete_defect_media_link(self, link_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        link = self._get_defect_media_link_for_user(link_id, user.id)
        deleted = _single_response_row(
            self._execute(
                self._client.table("defect_media_links")
                .update(
                    {
                        "deleted_at": _now_iso(),
                        "updated_at": _now_iso(),
                        "revision": int(link.get("revision") or 1) + 1,
                    }
                )
                .eq("id", link_id)
            )
        )
        defect = self._select_one("defects", "id", str(deleted["defect_id"]))
        self._record_activity(
            str((defect or {}).get("project_id")),
            user.id,
            "defect.media_link_deleted",
            "defect_media_link",
            link_id,
        )
        return deleted

    def update_media_asset(
        self, media_asset_id: str, payload: MediaAssetUpdate, user: AuthenticatedUser
    ) -> dict[str, Any]:
        media = self._get_media_asset(media_asset_id)
        self._get_project_for_user(str(media["project_id"]), user.id)
        update_payload = payload.model_dump(mode="json", exclude_unset=True, exclude_none=True)
        if not update_payload:
            return self._with_media_signed_url(media)

        update_payload["updated_at"] = _now_iso()
        update_payload["revision"] = int(media.get("revision") or 1) + 1
        updated = _single_response_row(
            self._execute(
                self._client.table("media_assets").update(update_payload).eq("id", media_asset_id)
            )
        )
        self._record_activity(
            str(updated["project_id"]),
            user.id,
            "media.updated",
            "media_asset",
            str(updated["id"]),
        )
        return self._with_media_signed_url(updated)

    def delete_media_asset(self, media_asset_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        media = self._get_media_asset(media_asset_id)
        self._get_project_for_user(str(media["project_id"]), user.id)
        deleted = _single_response_row(
            self._execute(
                self._client.table("media_assets")
                .update(
                    {
                        "deleted_at": _now_iso(),
                        "updated_at": _now_iso(),
                        "revision": int(media.get("revision") or 1) + 1,
                    }
                )
                .eq("id", media_asset_id)
            )
        )
        self._record_activity(
            str(deleted["project_id"]), user.id, "media.deleted", "media_asset", media_asset_id
        )
        return deleted
