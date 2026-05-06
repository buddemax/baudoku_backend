from __future__ import annotations

from typing import Any

import httpx
import pytest

from baudoku_api.config import Settings
from baudoku_api.email_delivery import (
    BrevoEmailSender,
    EmailAddress,
    EmailAttachment,
    EmailDeliveryConfigurationError,
    EmailDeliveryTimeoutError,
    TransactionalEmail,
)


class FakeResponse:
    def __init__(self, status_code: int, data: dict[str, Any]) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


class CapturingHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_brevo_sender_posts_expected_transactional_payload() -> None:
    http_client = CapturingHttpClient(FakeResponse(201, {"messageId": "brevo-message-id"}))
    sender = BrevoEmailSender(
        Settings(
            _env_file=None,
            brevo_api_key="secret-key",
            brevo_sender_email="reports@example.test",
            brevo_sender_name="Baudoku",
            brevo_sandbox=True,
        ),
        http_client=http_client,
    )

    message_id = sender.send_email(
        TransactionalEmail(
            sender=sender.configured_sender,
            reply_to=EmailAddress(email="gutachter@example.test", name="Gutachter"),
            to=[EmailAddress(email="kunde@example.test", name="Kunde")],
            cc=[EmailAddress(email="cc@example.test")],
            bcc=[EmailAddress(email="bcc@example.test")],
            subject="Bericht",
            text_content="Text",
            html_content="<p>Text</p>",
            attachments=[EmailAttachment(name="bericht.pdf", content="cGRm")],
            tags=["baudoku", "report-email"],
            headers={"X-Baudoku-Report-Version-Id": "version-id"},
        )
    )

    call = http_client.calls[0]
    assert message_id == "brevo-message-id"
    assert call["url"] == "https://api.brevo.com/v3/smtp/email"
    assert call["headers"]["api-key"] == "secret-key"
    assert call["headers"]["X-Sib-Sandbox"] == "drop"
    assert call["timeout"] == 20
    assert call["json"] == {
        "sender": {"email": "reports@example.test", "name": "Baudoku"},
        "replyTo": {"email": "gutachter@example.test", "name": "Gutachter"},
        "to": [{"email": "kunde@example.test", "name": "Kunde"}],
        "cc": [{"email": "cc@example.test"}],
        "bcc": [{"email": "bcc@example.test"}],
        "subject": "Bericht",
        "textContent": "Text",
        "htmlContent": "<p>Text</p>",
        "attachment": [{"name": "bericht.pdf", "content": "cGRm"}],
        "tags": ["baudoku", "report-email"],
        "headers": {"X-Baudoku-Report-Version-Id": "version-id"},
    }


def test_brevo_sender_requires_api_key_and_sender() -> None:
    with pytest.raises(EmailDeliveryConfigurationError):
        BrevoEmailSender(Settings(_env_file=None, brevo_sender_email="reports@example.test"))

    with pytest.raises(EmailDeliveryConfigurationError):
        BrevoEmailSender(Settings(_env_file=None, brevo_api_key="secret-key"))


def test_brevo_sender_maps_timeout() -> None:
    class TimeoutClient:
        def post(self, url: str, **kwargs: Any) -> FakeResponse:
            raise httpx.TimeoutException("timeout")

    sender = BrevoEmailSender(
        Settings(
            _env_file=None,
            brevo_api_key="secret-key",
            brevo_sender_email="reports@example.test",
        ),
        http_client=TimeoutClient(),
    )

    with pytest.raises(EmailDeliveryTimeoutError):
        sender.send_email(
            TransactionalEmail(
                sender=sender.configured_sender,
                to=[EmailAddress(email="kunde@example.test")],
                subject="Bericht",
                text_content="Text",
            )
        )
