from __future__ import annotations

from typing import Any
from uuid import uuid4

from baudoku_api.config import get_settings
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.reports import ReportDocxBuilder, ReportDocxBuilderError

from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    REPORT_TEMPLATE_VERSION,
    ProjectNotFoundError,
    ProjectRepositoryError,
    _now_iso,
    _report_warnings,
    _response_data,
    _single_response_row,
)


class ProjectReportMixin:
    def report_preview(self, project_id: str, user_id: str) -> dict[str, Any]:
        project = self.get_project(project_id, user_id)
        defects = self.list_defects(project_id, user_id)
        general_findings = self.list_general_findings(project_id, user_id)
        project_conclusion = self.get_project_conclusion(project_id, user_id)
        voice_notes = self.list_voice_notes(project_id, user_id)
        plans = self.list_plans(project_id, user_id)
        return {
            "project": project,
            "defects": defects,
            "general_findings": general_findings,
            "project_conclusion": project_conclusion,
            "voice_notes": voice_notes,
            "plans": plans,
            "preview_confirmation": self._latest_report_preview_confirmation(project_id),
            "warnings": _report_warnings(
                defects, general_findings, project_conclusion, voice_notes
            ),
        }

    def confirm_report_preview(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        project = self.get_project(project_id, user.id)
        confirmation = _single_response_row(
            self._execute(
                self._client.table("report_preview_confirmations").insert(
                    {
                        "project_id": project_id,
                        "confirmed_by": user.id,
                        "project_revision": int(project.get("revision") or 1),
                        "report_revision": int(project.get("report_revision") or 0),
                    }
                )
            )
        )
        self._record_activity(
            project_id,
            user.id,
            "report.preview_confirmed",
            "report_preview_confirmation",
            str(confirmation["id"]),
        )
        return confirmation

    def generate_report(self, project_id: str, user: AuthenticatedUser) -> dict[str, Any]:
        project = self.get_project(project_id, user.id)
        defects = self.list_defects(project_id, user.id)
        general_findings = self.list_general_findings(project_id, user.id)
        project_conclusion = self.get_project_conclusion(project_id, user.id)
        voice_notes = self.list_voice_notes(project_id, user.id)
        plans = self.list_plans(project_id, user.id)
        warnings = _report_warnings(defects, general_findings, project_conclusion, voice_notes)
        version_number = self._next_report_version(project_id)
        report_revision = int(project.get("report_revision") or 0) + 1
        media_id = str(uuid4())
        storage_path = f"projects/{project_id}/reports/report_v{version_number}.docx"
        plans = self._render_report_plans(project_id, plans, defects, user, version_number)
        builder = ReportDocxBuilder(
            template_path=get_settings().bba_template_path,
            image_loader=self._download_report_image,
        )
        try:
            document_bytes = builder.build(
                self._project_report_context(project, user),
                defects,
                general_findings,
                project_conclusion,
                plans,
            )
        except ReportDocxBuilderError as exc:
            raise ProjectRepositoryError(str(exc)) from exc

        try:
            self._client.storage.from_(PROJECT_FILES_BUCKET).upload(
                storage_path,
                document_bytes,
                {
                    "content-type": (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    "upsert": "false",
                },
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Word-Datei konnte nicht gespeichert werden.") from exc

        media = _single_response_row(
            self._execute(
                self._client.table("media_assets").insert(
                    {
                        "id": media_id,
                        "project_id": project_id,
                        "media_type": "report_docx",
                        "storage_bucket": PROJECT_FILES_BUCKET,
                        "storage_path": storage_path,
                        "mime_type": (
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        ),
                        "file_size": len(document_bytes),
                        "created_by": user.id,
                    }
                )
            )
        )
        version = _single_response_row(
            self._execute(
                self._client.table("report_versions").insert(
                    {
                        "project_id": project_id,
                        "version_number": version_number,
                        "media_asset_id": media["id"],
                        "generated_by": user.id,
                        "warning_count": len(warnings),
                        "warnings_snapshot": [warning.model_dump() for warning in warnings],
                        "template_version": REPORT_TEMPLATE_VERSION,
                        "report_revision": report_revision,
                    }
                )
            )
        )
        version["download_url"] = self._signed_download_url(
            storage_path, f"{project.get('project_number')}_v{version_number}.docx"
        )
        self._execute(
            self._client.table("projects")
            .update(
                {
                    "status": "Bericht generiert",
                    "updated_at": _now_iso(),
                    "revision": int(project.get("revision") or 1) + 1,
                    "report_revision": report_revision,
                }
            )
            .eq("id", project_id)
        )
        self._record_activity(project_id, user.id, "report.generated", "report_version", str(version["id"]))
        return {"version": version, "warnings": warnings}

    def list_report_versions(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        self._get_project_for_user(project_id, user_id)
        rows = _response_data(
            self._execute(
                self._client.table("report_versions")
                .select("*")
                .eq("project_id", project_id)
                .order("version_number", desc=True)
            )
        )
        for row in rows:
            media = self._get_media_asset(str(row["media_asset_id"]))
            try:
                row["download_url"] = self._signed_download_url(
                    str(media["storage_path"]), f"report_v{row['version_number']}.docx"
                )
            except ProjectRepositoryError:
                row["download_url"] = None
        return rows

    def report_download_url(self, version_id: str, user: AuthenticatedUser) -> str:
        version = self._select_one("report_versions", "id", version_id)
        if version is None:
            raise ProjectNotFoundError("Berichtsversion nicht gefunden.")
        self._get_project_for_user(str(version["project_id"]), user.id)
        media = self._get_media_asset(str(version["media_asset_id"]))
        return self._signed_download_url(
            str(media["storage_path"]), f"report_v{version['version_number']}.docx"
        )
