from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from baudoku_api.schemas import ReportWarning

PROJECT_FILES_BUCKET = "project-files"
REPORT_TEMPLATE_VERSION = "simple-v1"
SYNC_OPERATION_EVENT_TYPE = "sync.operation_applied"

SYNC_ENTITY_TYPE_BY_OPERATION = {
    "project.update": "project",
    "project.delete": "project",
    "defect.create": "defect",
    "defect.update": "defect",
    "defect.delete": "defect",
    "defect.reorder": "defect",
    "defects.reorder": "defect",
    "media.create": "media_asset",
    "media.complete_upload": "media_asset",
    "media.update": "media_asset",
    "media.delete": "media_asset",
    "media_asset.update": "media_asset",
    "media_asset.delete": "media_asset",
    "defect_media_link.create": "defect_media_link",
    "defect_media_link.update": "defect_media_link",
    "defect_media_link.delete": "defect_media_link",
    "media_link.create": "defect_media_link",
    "media_link.update": "defect_media_link",
    "media_link.delete": "defect_media_link",
    "media.link.create": "defect_media_link",
    "media.link.update": "defect_media_link",
    "media.link.delete": "defect_media_link",
    "plan.create": "plan_file",
    "plan_marker.create": "plan_marker",
    "plan_marker.update": "plan_marker",
    "plan_marker.delete": "plan_marker",
    "voice_note.create": "voice_note",
    "voice_note.update": "voice_note",
    "voice_note.delete": "voice_note",
    "general_finding.create": "general_finding",
    "general_finding.update": "general_finding",
    "general_finding.delete": "general_finding",
    "project_conclusion.upsert": "project_conclusion",
    "project_conclusion.delete": "project_conclusion",
}


class ProjectRepositoryError(Exception):
    """Raised when Supabase project persistence fails."""


class MediaUploadIntegrityError(ProjectRepositoryError):
    """Raised when Storage does not contain the uploaded file claimed by the client."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ProjectNotFoundError(ProjectRepositoryError):
    """Raised when a project is missing or not visible to the current user."""


class SyncConflictError(ProjectRepositoryError):
    """Raised when a queued sync operation is based on a stale revision."""

    def __init__(self, message: str, server_entity: dict[str, Any]) -> None:
        super().__init__(message)
        self.server_entity = server_entity



def _response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def _single_response_row(response: Any) -> dict[str, Any]:
    data = _response_data(response)
    if not data:
        raise ProjectRepositoryError("Supabase-Antwort enthielt keinen Datensatz.")
    return data[0]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filter_projects(
    projects: list[dict[str, Any]],
    search: Optional[str],
    status: Optional[str],
    appraisal_type: Optional[str],
) -> list[dict[str, Any]]:
    normalized_search = (search or "").strip().casefold()
    normalized_status = (status or "").strip()
    normalized_appraisal_type = (appraisal_type or "").strip()

    filtered = projects
    if normalized_status:
        filtered = [
            project for project in filtered if str(project.get("status") or "") == normalized_status
        ]
    if normalized_appraisal_type:
        filtered = [
            project
            for project in filtered
            if str(project.get("appraisal_type") or "") == normalized_appraisal_type
        ]
    if normalized_search:
        search_fields = (
            "project_number",
            "client_name",
            "object_address",
            "site_visit_date",
            "appraisal_type",
            "status",
        )
        filtered = [
            project
            for project in filtered
            if any(
                normalized_search in str(project.get(field) or "").casefold()
                for field in search_fields
            )
        ]
    return filtered


def _extension_for(media_type: str, mime_type: str, file_name: Optional[str]) -> str:
    if file_name and "." in file_name:
        extension = file_name.rsplit(".", maxsplit=1)[-1].lower()
        if extension.isalnum() and len(extension) <= 8:
            return "jpg" if extension == "jpeg" else extension

    mime_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "application/pdf": "pdf",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    }
    if mime_type in mime_map:
        return mime_map[mime_type]
    return {"photo": "jpg", "audio": "m4a", "plan_source": "pdf", "plan_render": "png"}.get(
        media_type,
        "bin",
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def _plan_source_supports_image_render(plan: dict[str, Any], media: dict[str, Any]) -> bool:
    if _text(media.get("media_type")) == "plan_render":
        return True

    file_type = _text(plan.get("file_type")).casefold()
    mime_type = _text(media.get("mime_type")).casefold()
    if file_type == "pdf" or mime_type == "application/pdf":
        return False
    return file_type in {"jpg", "jpeg", "png"} or mime_type in {
        "image/jpeg",
        "image/jpg",
        "image/png",
    }


def _derive_project_status(
    defects: list[dict[str, Any]],
    media_assets: list[dict[str, Any]],
    general_findings: list[dict[str, Any]],
    project_conclusion: Optional[dict[str, Any]],
    voice_notes: list[dict[str, Any]],
    report_versions: list[dict[str, Any]],
) -> str:
    if any(version.get("deleted_at") is None for version in report_versions):
        return "Bericht generiert"

    conclusion_text = _text((project_conclusion or {}).get("text"))
    has_capture_data = (
        bool(defects)
        or any(
            media.get("media_type") in {"photo", "audio", "plan_source"}
            for media in media_assets
        )
        or bool(general_findings)
        or bool(conclusion_text)
        or bool(voice_notes)
    )
    if not has_capture_data:
        return "Entwurf"

    has_preview_content = bool(defects) or bool(general_findings) or bool(conclusion_text)
    has_required_gap = any(not _text(defect.get("description")) for defect in defects)
    if has_preview_content and not has_required_gap:
        return "Bereit zur Pruefung"

    return "In Erfassung"


def _report_warnings(
    defects: list[dict[str, Any]],
    general_findings: Optional[list[dict[str, Any]]] = None,
    project_conclusion: Optional[dict[str, Any]] = None,
    voice_notes: Optional[list[dict[str, Any]]] = None,
) -> list[ReportWarning]:
    warnings: list[ReportWarning] = []
    if not defects:
        warnings.append(
            ReportWarning(
                code="NO_DEFECTS",
                message="Es wurden noch keine Maengel oder Hinweise erfasst.",
                severity="warning",
            )
        )

    if not general_findings:
        warnings.append(
            ReportWarning(
                code="NO_GENERAL_FINDINGS",
                message="Es wurden noch keine allgemeinen Feststellungen erfasst.",
                severity="info",
            )
        )

    if not str((project_conclusion or {}).get("text") or "").strip():
        warnings.append(
            ReportWarning(
                code="NO_CONCLUSION",
                message="Es wurde noch kein Fazit erfasst.",
                severity="warning",
            )
        )

    defect_labels_by_id: dict[str, str] = {}
    for defect in defects:
        label = defect.get("local_label") or defect.get("id")
        if defect.get("id") is not None:
            defect_labels_by_id[str(defect["id"])] = str(label)
        if not str(defect.get("description") or "").strip():
            warnings.append(
                ReportWarning(
                    code="DEFECT_DESCRIPTION_EMPTY",
                    message=f"{label}: Beschreibung fehlt.",
                    severity="warning",
                )
            )
        if defect.get("kind") == "defect" and not defect.get("media_links"):
            warnings.append(
                ReportWarning(
                    code="DEFECT_WITHOUT_PHOTO",
                    message=f"{label}: Mangel hat noch kein Foto.",
                    severity="info",
                )
            )
        for link in defect.get("media_links") or []:
            media = link.get("media_asset") or {}
            if media.get("media_type") != "photo":
                continue
            caption_status = media.get("caption_status")
            if caption_status in {"open", None}:
                warnings.append(
                    ReportWarning(
                        code="PHOTO_WITHOUT_CAPTION",
                        message=f"{label}: Foto hat noch keine Bildunterschrift.",
                        severity="info",
                    )
                )
            elif caption_status == "suggested":
                warnings.append(
                    ReportWarning(
                        code="UNCONFIRMED_AI_CAPTION",
                        message=f"{label}: KI-Bildbeschreibung ist noch nicht bestaetigt.",
                        severity="warning",
                    )
                )
            elif caption_status == "error":
                warnings.append(
                    ReportWarning(
                        code="AI_CAPTION_FAILED",
                        message=f"{label}: KI-Bildbeschreibung ist fehlgeschlagen.",
                        severity="info",
                    )
                )

    for voice_note in voice_notes or []:
        defect_id = voice_note.get("defect_id")
        label = (
            defect_labels_by_id.get(str(defect_id))
            if defect_id is not None
            else None
        ) or voice_note.get("target_type") or voice_note.get("id")
        transcript_status = voice_note.get("transcript_status")
        if transcript_status == "open":
            warnings.append(
                ReportWarning(
                    code="VOICE_TRANSCRIPT_OPEN",
                    message=f"Sprachnotiz {label}: Transkription steht noch aus.",
                    severity="info",
                )
            )
        elif transcript_status == "suggested":
            warnings.append(
                ReportWarning(
                    code="UNCONFIRMED_AI_TRANSCRIPT",
                    message=f"Sprachnotiz {label}: KI-Transkript ist noch nicht bestaetigt.",
                    severity="warning",
                )
            )
        elif transcript_status == "error":
            warnings.append(
                ReportWarning(
                    code="AI_TRANSCRIPT_FAILED",
                    message=f"Sprachnotiz {label}: KI-Transkription ist fehlgeschlagen.",
                    severity="info",
                )
            )
    return warnings
