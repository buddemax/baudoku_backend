from types import SimpleNamespace

import pytest

from baudoku_api.ai import AiProviderError, OpenAiAiProvider


class _TranscriptionClient:
    def create(self, **_kwargs: object) -> str:
        return "Rohtext"


class _FailingResponsesClient:
    def create(self, **_kwargs: object) -> object:
        raise RuntimeError("text model unavailable")


def _provider_with_clients() -> OpenAiAiProvider:
    provider = OpenAiAiProvider.__new__(OpenAiAiProvider)
    provider._settings = SimpleNamespace(
        openai_transcription_model="gpt-4o-mini-transcribe",
        openai_text_model="gpt-4o-mini",
    )
    provider._client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=_TranscriptionClient()),
        responses=_FailingResponsesClient(),
    )
    return provider


def test_transcribe_audio_rejects_empty_audio_before_provider_call() -> None:
    provider = _provider_with_clients()

    with pytest.raises(AiProviderError, match="Audio-Datei ist leer"):
        provider.transcribe_audio(b"", "audio/mp4", "audio.m4a", {}, "defect_description")


def test_transcribe_audio_preserves_text_preparation_error() -> None:
    provider = _provider_with_clients()

    with pytest.raises(AiProviderError, match="KI-Textaufbereitung fehlgeschlagen"):
        provider.transcribe_audio(b"audio", "audio/mp4", "audio.m4a", {}, "defect_description")
