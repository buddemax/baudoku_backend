from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from baudoku_api.config import Settings

BREVO_SMTP_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"


class EmailDeliveryConfigurationError(Exception):
    """Raised when transactional email delivery is not configured."""


class EmailDeliveryTimeoutError(Exception):
    """Raised when the email provider request times out."""


class BrevoDeliveryError(Exception):
    """Raised when Brevo rejects a transactional email request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        provider_code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code


@dataclass(frozen=True)
class EmailAddress:
    email: str
    name: Optional[str] = None


@dataclass(frozen=True)
class EmailAttachment:
    name: str
    content: str


@dataclass(frozen=True)
class TransactionalEmail:
    sender: EmailAddress
    to: list[EmailAddress]
    subject: str
    text_content: Optional[str] = None
    html_content: Optional[str] = None
    reply_to: Optional[EmailAddress] = None
    cc: Optional[list[EmailAddress]] = None
    bcc: Optional[list[EmailAddress]] = None
    attachments: Optional[list[EmailAttachment]] = None
    tags: Optional[list[str]] = None
    headers: Optional[dict[str, str]] = None


class EmailSenderProtocol(Protocol):
    @property
    def configured_sender(self) -> EmailAddress:
        """Return the configured sender address."""

    def send_email(self, message: TransactionalEmail) -> str:
        """Send a transactional email and return the provider message id."""


class BrevoEmailSender:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: Optional[httpx.Client] = None,
        endpoint_url: str = BREVO_SMTP_EMAIL_URL,
    ) -> None:
        if not settings.brevo_api_key:
            raise EmailDeliveryConfigurationError("Brevo API-Key ist nicht konfiguriert.")
        if not settings.brevo_sender_email:
            raise EmailDeliveryConfigurationError("Brevo Absenderadresse ist nicht konfiguriert.")

        self._api_key = settings.brevo_api_key
        self._sender_email = settings.brevo_sender_email
        self._sender_name = settings.brevo_sender_name
        self._sandbox = settings.brevo_sandbox
        self._timeout_seconds = settings.brevo_timeout_seconds
        self._http_client = http_client
        self._endpoint_url = endpoint_url

    @property
    def configured_sender(self) -> EmailAddress:
        return EmailAddress(email=self._sender_email, name=self._sender_name)

    def send_email(self, message: TransactionalEmail) -> str:
        payload = self._payload(message)
        headers = {
            "accept": "application/json",
            "api-key": self._api_key,
            "content-type": "application/json",
        }
        if self._sandbox:
            headers["X-Sib-Sandbox"] = "drop"

        try:
            if self._http_client is not None:
                response = self._http_client.post(
                    self._endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                response = httpx.post(
                    self._endpoint_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
        except httpx.TimeoutException as exc:
            raise EmailDeliveryTimeoutError("Brevo-Anfrage hat das Zeitlimit ueberschritten.") from exc
        except httpx.HTTPError as exc:
            raise BrevoDeliveryError("Brevo-Anfrage konnte nicht gesendet werden.") from exc

        if response.status_code >= 400:
            message_text, provider_code = self._error_response(response)
            raise BrevoDeliveryError(
                message_text,
                status_code=response.status_code,
                provider_code=provider_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise BrevoDeliveryError("Brevo-Antwort war kein gueltiges JSON.") from exc

        message_id = data.get("messageId") or data.get("message_id")
        if not message_id:
            raise BrevoDeliveryError("Brevo-Antwort enthielt keine Message-ID.")
        return str(message_id)

    def _payload(self, message: TransactionalEmail) -> dict[str, object]:
        payload: dict[str, object] = {
            "sender": self._address(message.sender),
            "to": [self._address(recipient) for recipient in message.to],
            "subject": message.subject,
        }
        if message.reply_to is not None:
            payload["replyTo"] = self._address(message.reply_to)
        if message.cc:
            payload["cc"] = [self._address(recipient) for recipient in message.cc]
        if message.bcc:
            payload["bcc"] = [self._address(recipient) for recipient in message.bcc]
        if message.text_content is not None:
            payload["textContent"] = message.text_content
        if message.html_content is not None:
            payload["htmlContent"] = message.html_content
        if message.attachments:
            payload["attachment"] = [
                {"name": attachment.name, "content": attachment.content}
                for attachment in message.attachments
            ]
        if message.tags:
            payload["tags"] = message.tags
        if message.headers:
            payload["headers"] = message.headers
        return payload

    def _address(self, address: EmailAddress) -> dict[str, str]:
        payload = {"email": address.email}
        if address.name:
            payload["name"] = address.name
        return payload

    def _error_response(self, response: httpx.Response) -> tuple[str, Optional[str]]:
        try:
            data = response.json()
        except ValueError:
            return (
                f"Brevo lehnte die E-Mail ab (HTTP {response.status_code}).",
                None,
            )
        message = str(data.get("message") or "Brevo lehnte die E-Mail ab.")
        provider_code = data.get("code")
        return message, str(provider_code) if provider_code else None
