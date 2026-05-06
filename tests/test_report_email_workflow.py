from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from baudoku_api.config import Settings
from baudoku_api.dependencies import get_auth_service, get_email_sender, get_project_repository
from baudoku_api.email_delivery import BrevoDeliveryError, EmailAddress, TransactionalEmail
from baudoku_api.main import create_app
from baudoku_api.repositories.report_generation import ProjectReportMixin

from workflow_fakes import FakeAuthService, PROJECT_ID, USER_ID, _headers

VERSION_ID = "55555555-5555-4555-8555-555555555555"
DOCX_MEDIA_ID = "66666666-6666-4666-8666-666666666666"
PDF_MEDIA_ID = "77777777-7777-4777-8777-777777777777"
NOW = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc).isoformat()


class FakeStorageBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def download(self, storage_path: str) -> bytes:
        return self.objects[storage_path]


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def from_(self, bucket: str) -> FakeStorageBucket:
        return FakeStorageBucket(self.objects)


class EmailReportRepository(ProjectReportMixin):
    def __init__(
        self,
        *,
        docx_bytes: bytes = b"docx",
        pdf_bytes: bytes = b"pdf",
        include_pdf: bool = True,
    ) -> None:
        self.project = {
            "id": PROJECT_ID,
            "project_number": "BBA-2026-001",
            "client_name": "Muster GmbH",
            "object_address": "Baustelle 1, Berlin",
            "site_visit_date": date(2026, 5, 4).isoformat(),
            "appraisal_type": "Abnahmebegehung",
            "lead_user_id": USER_ID,
            "status": "Bericht generiert",
            "language": "de",
            "created_by": USER_ID,
            "created_at": NOW,
            "updated_at": NOW,
            "revision": 1,
        }
        self.version = {
            "id": VERSION_ID,
            "project_id": PROJECT_ID,
            "version_number": 1,
            "media_asset_id": DOCX_MEDIA_ID,
            "pdf_media_asset_id": PDF_MEDIA_ID if include_pdf else None,
            "generated_by": USER_ID,
            "generated_at": NOW,
        }
        self.media = {
            DOCX_MEDIA_ID: {
                "id": DOCX_MEDIA_ID,
                "project_id": PROJECT_ID,
                "media_type": "report_docx",
                "storage_bucket": "project-files",
                "storage_path": f"projects/{PROJECT_ID}/reports/report_v1.docx",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "file_size": len(docx_bytes),
            },
        }
        self.objects = {
            f"projects/{PROJECT_ID}/reports/report_v1.docx": docx_bytes,
        }
        if include_pdf:
            self.media[PDF_MEDIA_ID] = {
                "id": PDF_MEDIA_ID,
                "project_id": PROJECT_ID,
                "media_type": "report_pdf",
                "storage_bucket": "project-files",
                "storage_path": f"projects/{PROJECT_ID}/reports/report_v1.pdf",
                "mime_type": "application/pdf",
                "file_size": len(pdf_bytes),
            }
            self.objects[f"projects/{PROJECT_ID}/reports/report_v1.pdf"] = pdf_bytes
        self.activities: list[dict[str, Any]] = []
        self.signed_url_requests: list[dict[str, Any]] = []

    @property
    def _client(self) -> Any:
        return SimpleNamespace(storage=FakeStorage(self.objects))

    def _select_one(self, table: str, column: str, value: str) -> Optional[dict[str, Any]]:
        if table == "report_versions" and column == "id" and value == VERSION_ID:
            return dict(self.version)
        return None

    def _get_project_for_user(self, project_id: str, user_id: str, derive_status: bool = False) -> dict[str, Any]:
        return dict(self.project)

    def _get_media_asset(self, media_asset_id: str) -> dict[str, Any]:
        return dict(self.media[media_asset_id])

    def _signed_download_url(
        self,
        storage_path: str,
        download_name: Optional[str] = None,
        expires_in_seconds: int = 600,
    ) -> str:
        self.signed_url_requests.append(
            {
                "storage_path": storage_path,
                "download_name": download_name,
                "expires_in_seconds": expires_in_seconds,
            }
        )
        return f"https://signed.example.test/{download_name}?expires={expires_in_seconds}"

    def _record_activity(
        self,
        project_id: Optional[str],
        user_id: str,
        event_type: str,
        entity_type: str,
        entity_id: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.activities.append(
            {
                "project_id": project_id,
                "user_id": user_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata or {},
            }
        )


class FakeEmailSender:
    configured_sender = EmailAddress(email="reports@example.test", name="Baudoku")

    def __init__(self, exc: Optional[Exception] = None) -> None:
        self.exc = exc
        self.messages: list[TransactionalEmail] = []

    def send_email(self, message: TransactionalEmail) -> str:
        if self.exc is not None:
            raise self.exc
        self.messages.append(message)
        return "provider-message-id"


def test_email_report_version_sends_inline_attachments(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "baudoku_api.repositories.report_generation.get_settings",
        lambda: Settings(_env_file=None, brevo_max_inline_attachment_raw_bytes=100),
    )
    repository = EmailReportRepository(docx_bytes=b"docx", pdf_bytes=b"pdf")
    sender = FakeEmailSender()
    client = _client(repository, sender)

    response = client.post(
        f"/v1/report-versions/{VERSION_ID}/email",
        headers=_headers(),
        json=_email_payload(client_send_id="mobile-send-1"),
    )

    assert response.status_code == 200
    assert response.json()["message_id"] == "provider-message-id"
    assert response.json()["delivery_mode"] == "attachments"
    assert response.json()["attachment_bytes"] == 7
    assert response.json()["recipient_count"] == 3
    message = sender.messages[0]
    assert message.reply_to == EmailAddress(email="gutachter@example.com", name="Gutachter")
    assert [attachment.name for attachment in message.attachments or []] == [
        "BBA-2026-001_v1.docx",
        "BBA-2026-001_v1.pdf",
    ]
    assert message.headers == {
        "X-Baudoku-Report-Version-Id": VERSION_ID,
        "X-Baudoku-Client-Send-Id": "mobile-send-1",
    }
    assert repository.activities[0]["event_type"] == "report.email_sent"
    assert "api_key" not in repository.activities[0]["metadata"]
    assert "message" not in repository.activities[0]["metadata"]


def test_email_report_version_uses_links_when_files_are_too_large(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "baudoku_api.repositories.report_generation.get_settings",
        lambda: Settings(
            _env_file=None,
            brevo_max_inline_attachment_raw_bytes=5,
            brevo_link_expiry_seconds=604800,
        ),
    )
    repository = EmailReportRepository(docx_bytes=b"docx", pdf_bytes=b"pdf")
    sender = FakeEmailSender()
    client = _client(repository, sender)

    response = client.post(
        f"/v1/report-versions/{VERSION_ID}/email",
        headers=_headers(),
        json=_email_payload(),
    )

    assert response.status_code == 200
    assert response.json()["delivery_mode"] == "links"
    assert response.json()["attachment_bytes"] == 0
    assert response.json()["link_expires_at"] is not None
    message = sender.messages[0]
    assert not message.attachments
    assert "DOCX: https://signed.example.test/BBA-2026-001_v1.docx" in str(message.text_content)
    assert "PDF: https://signed.example.test/BBA-2026-001_v1.pdf" in str(message.text_content)
    assert {request["expires_in_seconds"] for request in repository.signed_url_requests} == {604800}


def test_email_report_version_rejects_missing_pdf(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "baudoku_api.repositories.report_generation.get_settings",
        lambda: Settings(_env_file=None),
    )
    client = _client(EmailReportRepository(include_pdf=False), FakeEmailSender())

    response = client.post(
        f"/v1/report-versions/{VERSION_ID}/email",
        headers=_headers(),
        json=_email_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REPORT_VERSION_INCOMPLETE"
    assert "PDF" in response.json()["detail"]["message"]


def test_email_report_version_maps_provider_errors(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "baudoku_api.repositories.report_generation.get_settings",
        lambda: Settings(_env_file=None),
    )
    client = _client(
        EmailReportRepository(),
        FakeEmailSender(BrevoDeliveryError("Brevo nicht erreichbar.")),
    )

    response = client.post(
        f"/v1/report-versions/{VERSION_ID}/email",
        headers=_headers(),
        json=_email_payload(),
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "EMAIL_PROVIDER_ERROR"


def test_email_report_version_requires_email_configuration() -> None:
    def missing_sender() -> None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EMAIL_NOT_CONFIGURED", "message": "Brevo API-Key ist nicht konfiguriert."},
        )

    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    app.dependency_overrides[get_project_repository] = lambda: EmailReportRepository()
    app.dependency_overrides[get_email_sender] = missing_sender
    client = TestClient(app)

    response = client.post(
        f"/v1/report-versions/{VERSION_ID}/email",
        headers=_headers(),
        json=_email_payload(),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EMAIL_NOT_CONFIGURED"


def test_email_report_version_rejects_more_than_99_recipients() -> None:
    client = _client(EmailReportRepository(), FakeEmailSender())
    payload = _email_payload()
    payload["to"] = [{"email": f"kunde{index}@example.test"} for index in range(99)]
    payload["cc"] = [{"email": "cc@example.test"}]

    response = client.post(
        f"/v1/report-versions/{VERSION_ID}/email",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 422


def _client(repository: EmailReportRepository, sender: FakeEmailSender) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()
    app.dependency_overrides[get_project_repository] = lambda: repository
    app.dependency_overrides[get_email_sender] = lambda: sender
    return TestClient(app)


def _email_payload(client_send_id: Optional[str] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": [{"email": "kunde@example.test", "name": "Kunde"}],
        "cc": [{"email": "cc@example.test"}],
        "bcc": [{"email": "bcc@example.test"}],
        "subject": "Ihr Bericht",
        "message": "Anbei der Bericht.",
    }
    if client_send_id:
        payload["client_send_id"] = client_send_id
    return payload
