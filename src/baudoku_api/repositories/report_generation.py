from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from baudoku_api.config import get_settings
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.email_delivery import (
    EmailAddress,
    EmailAttachment,
    EmailSenderProtocol,
    TransactionalEmail,
)
from baudoku_api.reports import (
    ReportDocxBuilder,
    ReportDocxBuilderError,
    ReportPdfBuilder,
    ReportPdfBuilderError,
)
from baudoku_api.schemas import EmailRecipient, ReportEmailRequest

from baudoku_api.repositories.project_helpers import (
    PROJECT_FILES_BUCKET,
    REPORT_TEMPLATE_VERSION,
    ProjectNotFoundError,
    ProjectRepositoryError,
    ReportVersionIncompleteError,
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
        pdf_media_id = str(uuid4())
        storage_path = _report_storage_path(project_id, media_id, "docx")
        pdf_storage_path = _report_storage_path(project_id, pdf_media_id, "pdf")
        plans = self._render_report_plans(project_id, plans, defects, user, version_number)
        builder = ReportDocxBuilder(
            template_path=get_settings().bba_template_path,
            image_loader=self._download_report_image,
        )
        pdf_builder = ReportPdfBuilder(
            template_path=get_settings().bba_template_path,
            image_loader=self._download_report_image,
        )
        project_context = self._project_report_context(project, user)
        try:
            document_bytes = builder.build(
                project_context,
                defects,
                general_findings,
                project_conclusion,
                plans,
            )
            pdf_bytes = pdf_builder.build(
                project_context,
                defects,
                general_findings,
                project_conclusion,
                plans,
            )
        except (ReportDocxBuilderError, ReportPdfBuilderError) as exc:
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
            self._client.storage.from_(PROJECT_FILES_BUCKET).upload(
                pdf_storage_path,
                pdf_bytes,
                {
                    "content-type": "application/pdf",
                    "upsert": "false",
                },
            )
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Berichtsdateien konnten nicht gespeichert werden.") from exc

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
        pdf_media = _single_response_row(
            self._execute(
                self._client.table("media_assets").insert(
                    {
                        "id": pdf_media_id,
                        "project_id": project_id,
                        "media_type": "report_pdf",
                        "storage_bucket": PROJECT_FILES_BUCKET,
                        "storage_path": pdf_storage_path,
                        "mime_type": "application/pdf",
                        "file_size": len(pdf_bytes),
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
                        "pdf_media_asset_id": pdf_media["id"],
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
        version["pdf_download_url"] = self._signed_download_url(
            pdf_storage_path, f"{project.get('project_number')}_v{version_number}.pdf"
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
            pdf_media_id = row.get("pdf_media_asset_id")
            if pdf_media_id:
                try:
                    pdf_media = self._get_media_asset(str(pdf_media_id))
                    row["pdf_download_url"] = self._signed_download_url(
                        str(pdf_media["storage_path"]), f"report_v{row['version_number']}.pdf"
                    )
                except ProjectRepositoryError:
                    row["pdf_download_url"] = None
            else:
                row["pdf_download_url"] = None
        return rows

    def report_download_url(
        self, version_id: str, user: AuthenticatedUser, file_format: str = "docx"
    ) -> str:
        version = self._select_one("report_versions", "id", version_id)
        if version is None:
            raise ProjectNotFoundError("Berichtsversion nicht gefunden.")
        self._get_project_for_user(str(version["project_id"]), user.id)
        if file_format == "pdf":
            pdf_media_id = version.get("pdf_media_asset_id")
            if not pdf_media_id:
                raise ProjectNotFoundError("PDF-Berichtsversion nicht gefunden.")
            media = self._get_media_asset(str(pdf_media_id))
            return self._signed_download_url(
                str(media["storage_path"]), f"report_v{version['version_number']}.pdf"
            )

        media = self._get_media_asset(str(version["media_asset_id"]))
        return self._signed_download_url(
            str(media["storage_path"]), f"report_v{version['version_number']}.docx"
        )

    def email_report_version(
        self,
        version_id: str,
        payload: ReportEmailRequest,
        user: AuthenticatedUser,
        email_sender: EmailSenderProtocol,
    ) -> dict[str, Any]:
        settings = get_settings()
        version = self._select_one("report_versions", "id", version_id)
        if version is None:
            raise ProjectNotFoundError("Berichtsversion nicht gefunden.")

        project = self._get_project_for_user(str(version["project_id"]), user.id)
        files = self._report_version_delivery_files(version, project)
        total_raw_bytes = sum(int(file["raw_size"]) for file in files)
        max_inline_bytes = max(0, int(settings.brevo_max_inline_attachment_raw_bytes))
        recipient_count = self._recipient_count(payload)

        attachments: list[EmailAttachment] = []
        link_expires_at = None
        message_text = payload.message
        delivery_mode = "attachments"
        attachment_bytes = total_raw_bytes

        if total_raw_bytes <= max_inline_bytes:
            attachments = [
                EmailAttachment(
                    name=str(file["file_name"]),
                    content=base64.b64encode(file["content"]).decode("ascii"),
                )
                for file in files
            ]
        else:
            delivery_mode = "links"
            attachment_bytes = 0
            expires_in_seconds = max(60, int(settings.brevo_link_expiry_seconds))
            link_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
            links = [
                {
                    "label": str(file["label"]),
                    "url": self._signed_download_url(
                        str(file["media"]["storage_path"]),
                        str(file["file_name"]),
                        expires_in_seconds,
                    ),
                }
                for file in files
            ]
            message_text = self._append_report_download_links(
                message_text,
                links,
                link_expires_at,
            )

        message_id = email_sender.send_email(
            TransactionalEmail(
                sender=email_sender.configured_sender,
                reply_to=EmailAddress(email=user.email, name=user.display_name),
                to=[self._email_recipient(recipient) for recipient in payload.to],
                cc=[self._email_recipient(recipient) for recipient in payload.cc],
                bcc=[self._email_recipient(recipient) for recipient in payload.bcc],
                subject=payload.subject,
                text_content=message_text,
                attachments=attachments,
                tags=["baudoku", "report-email"],
                headers=self._report_email_headers(version_id, payload.client_send_id),
            )
        )

        sent_at = datetime.now(timezone.utc)
        self._record_activity(
            str(version["project_id"]),
            user.id,
            "report.email_sent",
            "report_version",
            version_id,
            {
                "message_id": message_id,
                "version_id": version_id,
                "recipient_count": recipient_count,
                "delivery_mode": delivery_mode,
                "attachment_bytes": attachment_bytes,
                "report_file_bytes": total_raw_bytes,
                "docx_media_asset_id": str(files[0]["media"]["id"]),
                "pdf_media_asset_id": str(files[1]["media"]["id"]),
                **({"client_send_id": payload.client_send_id} if payload.client_send_id else {}),
                **(
                    {"link_expires_at": link_expires_at.isoformat()}
                    if link_expires_at is not None
                    else {}
                ),
            },
        )

        return {
            "message_id": message_id,
            "version_id": version_id,
            "sent_at": sent_at,
            "recipient_count": recipient_count,
            "delivery_mode": delivery_mode,
            "attachment_bytes": attachment_bytes,
            "link_expires_at": link_expires_at,
        }

    def _report_version_delivery_files(
        self, version: dict[str, Any], project: dict[str, Any]
    ) -> list[dict[str, Any]]:
        docx_media = self._get_media_asset(str(version["media_asset_id"]))
        pdf_media_id = version.get("pdf_media_asset_id")
        if not pdf_media_id:
            raise ReportVersionIncompleteError(
                "Berichtsversion enthaelt keine PDF-Datei."
            )
        try:
            pdf_media = self._get_media_asset(str(pdf_media_id))
        except ProjectNotFoundError as exc:
            raise ProjectNotFoundError("PDF-Berichtsversion nicht gefunden.") from exc

        return [
            self._report_delivery_file(
                media=docx_media,
                expected_media_type="report_docx",
                file_name=self._report_file_name(project, version, "docx"),
                label="DOCX",
            ),
            self._report_delivery_file(
                media=pdf_media,
                expected_media_type="report_pdf",
                file_name=self._report_file_name(project, version, "pdf"),
                label="PDF",
            ),
        ]

    def _report_delivery_file(
        self,
        *,
        media: dict[str, Any],
        expected_media_type: str,
        file_name: str,
        label: str,
    ) -> dict[str, Any]:
        if str(media.get("media_type") or "") != expected_media_type:
            raise ReportVersionIncompleteError(
                f"{label}-Datei der Berichtsversion ist ungueltig."
            )
        content = self._download_report_file_bytes(media)
        raw_size = len(content)
        if raw_size <= 0:
            raise ReportVersionIncompleteError(
                f"{label}-Datei der Berichtsversion ist leer."
            )
        declared_size = self._optional_int(media.get("file_size"))
        if declared_size is not None and declared_size != raw_size:
            raise ReportVersionIncompleteError(
                f"{label}-Dateigroesse der Berichtsversion stimmt nicht mit Storage ueberein."
            )
        return {
            "media": media,
            "file_name": file_name,
            "label": label,
            "content": content,
            "raw_size": raw_size,
        }

    def _download_report_file_bytes(self, media: dict[str, Any]) -> bytes:
        bucket = str(media.get("storage_bucket") or PROJECT_FILES_BUCKET)
        storage_path = str(media["storage_path"])
        try:
            return self._client.storage.from_(bucket).download(storage_path)
        except Exception as exc:  # pragma: no cover - storage exception surface
            raise ProjectRepositoryError("Berichtsdatei konnte nicht geladen werden.") from exc

    def _append_report_download_links(
        self,
        message: str,
        links: list[dict[str, str]],
        link_expires_at: datetime,
    ) -> str:
        expiry = link_expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        link_lines = "\n".join(f"{link['label']}: {link['url']}" for link in links)
        return (
            f"{message}\n\n"
            "Die Berichtsdateien sind wegen ihrer Groesse als Download-Links angehaengt.\n\n"
            f"{link_lines}\n\n"
            f"Links gueltig bis: {expiry}"
        )

    def _report_file_name(
        self, project: dict[str, Any], version: dict[str, Any], extension: str
    ) -> str:
        project_number = self._safe_file_component(str(project.get("project_number") or "report"))
        version_number = int(version.get("version_number") or 1)
        return f"{project_number}_v{version_number}.{extension}"

    def _safe_file_component(self, value: str) -> str:
        cleaned = "".join(
            character
            if character.isalnum() or character in {"-", "_", "."}
            else "_"
            for character in value.strip()
        ).strip("._")
        return cleaned or "report"

    def _email_recipient(self, recipient: EmailRecipient) -> EmailAddress:
        return EmailAddress(email=recipient.email, name=recipient.name)

    def _recipient_count(self, payload: ReportEmailRequest) -> int:
        return len(payload.to) + len(payload.cc) + len(payload.bcc)

    def _report_email_headers(
        self, version_id: str, client_send_id: Optional[str]
    ) -> dict[str, str]:
        headers = {"X-Baudoku-Report-Version-Id": version_id}
        if client_send_id:
            headers["X-Baudoku-Client-Send-Id"] = client_send_id
        return headers

    def _optional_int(self, value: Any) -> Optional[int]:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None


def _report_storage_path(project_id: str, media_id: str, extension: str) -> str:
    return f"projects/{project_id}/reports/{media_id}.{extension}"
