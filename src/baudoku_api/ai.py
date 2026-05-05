from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, Protocol

from baudoku_api.config import Settings


class AiConfigurationError(RuntimeError):
    """Raised when the configured AI provider cannot be used."""


class AiProviderError(RuntimeError):
    """Raised when the provider call fails."""


class AiProviderProtocol(Protocol):
    provider_name: str

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
        file_name: str,
        project: dict[str, Any],
        target_type: str,
    ) -> str:
        """Transcribe and prepare an audio recording for the requested target."""

    def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        project: dict[str, Any],
    ) -> str:
        """Generate a short, factual image caption suggestion."""


class OpenAiAiProvider:
    provider_name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_enabled:
            raise AiConfigurationError("KI ist im Backend deaktiviert.")
        if settings.ai_provider != "openai":
            raise AiConfigurationError("Aktuell ist nur OpenAI als KI-Provider implementiert.")
        if not settings.openai_api_key:
            raise AiConfigurationError("OPENAI_API_KEY muss im Backend gesetzt sein.")

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - dependency/runtime surface
            raise AiConfigurationError("openai Python-Paket ist nicht installiert.") from exc

        self._settings = settings
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.ai_request_timeout_seconds,
        )

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime_type: str,
        file_name: str,
        project: dict[str, Any],
        target_type: str,
    ) -> str:
        if len(audio_bytes) <= 0:
            raise AiProviderError("Audio-Datei ist leer oder Upload unvollstaendig.")

        try:
            audio_file = (file_name, BytesIO(audio_bytes), mime_type)
            raw_transcript = self._client.audio.transcriptions.create(
                model=self._settings.openai_transcription_model,
                file=audio_file,
                prompt=_transcription_prompt(project, target_type),
                response_format="text",
            )
            return self._prepare_text(str(raw_transcript), project, target_type)
        except AiProviderError:
            raise
        except Exception as exc:  # pragma: no cover - provider/runtime surface
            raise AiProviderError("KI-Transkription fehlgeschlagen.") from exc

    def describe_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        project: dict[str, Any],
    ) -> str:
        try:
            data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
            response = self._client.responses.create(
                model=self._settings.openai_vision_model,
                input=[
                    {
                        "role": "system",
                        "content": _image_system_prompt(project),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Erstelle eine kurze Bildunterschrift fuer den Bericht.",
                            },
                            {"type": "input_image", "image_url": data_url},
                        ],
                    },
                ],
            )
            return _response_text(response)
        except Exception as exc:  # pragma: no cover - provider/runtime surface
            raise AiProviderError("KI-Bildbeschreibung fehlgeschlagen.") from exc

    def _prepare_text(self, transcript: str, project: dict[str, Any], target_type: str) -> str:
        try:
            response = self._client.responses.create(
                model=self._settings.openai_text_model,
                input=[
                    {
                        "role": "system",
                        "content": _text_system_prompt(project, target_type),
                    },
                    {"role": "user", "content": transcript},
                ],
            )
            return _response_text(response)
        except Exception as exc:  # pragma: no cover - provider/runtime surface
            raise AiProviderError("KI-Textaufbereitung fehlgeschlagen.") from exc


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    raise AiProviderError("KI-Antwort enthielt keinen Text.")


def _project_language(project: dict[str, Any]) -> str:
    return "Englisch" if project.get("language") == "en" else "Deutsch"


def _transcription_prompt(project: dict[str, Any], target_type: str) -> str:
    return (
        f"Sprache: {_project_language(project)}. Kontext: Baubegehung, "
        f"Gutachtentyp {project.get('appraisal_type')}. Zieltext: {target_type}. "
        "Fachbegriffe aus Bauwesen und Gutachten moeglichst exakt transkribieren."
    )


def _text_system_prompt(project: dict[str, Any], target_type: str) -> str:
    target_labels = {
        "general_finding": "eine kurze sachliche allgemeine Feststellung",
        "conclusion": "ein knappes, fachliches Fazit",
        "defect_description": "eine neutrale Mangelbeschreibung",
        "caption": "eine kurze Bildunterschrift",
    }
    target = target_labels.get(target_type, "einen fachlichen Berichtstext")
    return (
        f"Du formulierst fuer einen Baubegehungsbericht auf {_project_language(project)} "
        f"{target}. Schreibe sachlich, knapp und ohne Spekulationen. "
        "Erfinde keine Ursachen, Mengen, Orte oder Normen. Gib nur den finalen Text aus."
    )


def _image_system_prompt(project: dict[str, Any]) -> str:
    return (
        f"Du erstellst fuer einen Baubegehungsbericht auf {_project_language(project)} "
        "eine kurze, sachliche Bildunterschrift. Beschreibe nur Sichtbares. "
        "Erfinde keine Schadensursache, kein Gewerk und keine Bewertung. "
        "Gib nur die Bildunterschrift aus."
    )
