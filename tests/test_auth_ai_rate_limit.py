from __future__ import annotations

from types import SimpleNamespace

import pytest

from baudoku_api.ai import (
    AiConfigurationError,
    AiProviderError,
    OpenAiAiProvider,
    _image_system_prompt,
    _response_text,
    _text_system_prompt,
    _transcription_prompt,
)
from baudoku_api.auth import (
    AuthenticationError,
    InactiveUserError,
    SupabaseAuthService,
    _display_name_from_auth_user,
    _get_attr,
)
from baudoku_api.config import Settings
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.rate_limit import InMemoryRateLimiter, RateLimitExceededError


class FakeProfileRepository:
    def __init__(self, active: bool = True) -> None:
        self.active = active
        self.seen_user: AuthenticatedUser | None = None

    def ensure_profile(self, auth_user: AuthenticatedUser) -> AuthenticatedUser:
        self.seen_user = auth_user
        return AuthenticatedUser(
            id=auth_user.id,
            email=auth_user.email,
            display_name=auth_user.display_name,
            is_active=self.active,
        )


class FakeSupabaseAuth:
    def __init__(self, user: object | None) -> None:
        self.user = user
        self.seen_token: str | None = None

    def get_user(self, access_token: str) -> SimpleNamespace:
        self.seen_token = access_token
        return SimpleNamespace(user=self.user)


def test_auth_service_uses_profile_and_blocks_inactive_user(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_user = {
        "id": "11111111-1111-4111-8111-111111111111",
        "email": "gutachter@example.com",
        "user_metadata": {"full_name": "Max Gutachter"},
    }
    fake_auth = FakeSupabaseAuth(auth_user)
    repository = FakeProfileRepository(active=False)
    monkeypatch.setattr(
        "baudoku_api.auth.get_supabase_client",
        lambda: SimpleNamespace(auth=fake_auth),
    )

    service = SupabaseAuthService(repository)

    with pytest.raises(InactiveUserError):
        service.authenticate("token")

    assert fake_auth.seen_token == "token"
    assert repository.seen_user is not None
    assert repository.seen_user.display_name == "Max Gutachter"


def test_auth_service_rejects_missing_supabase_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "baudoku_api.auth.get_supabase_client",
        lambda: SimpleNamespace(auth=FakeSupabaseAuth(None)),
    )

    with pytest.raises(AuthenticationError):
        SupabaseAuthService(FakeProfileRepository()).authenticate("token")


def test_auth_helpers_support_dicts_objects_and_email_fallbacks() -> None:
    assert _get_attr({"email": "user@example.com"}, "email") == "user@example.com"
    assert _get_attr(SimpleNamespace(email="object@example.com"), "email") == "object@example.com"
    assert (
        _display_name_from_auth_user(
            SimpleNamespace(user_metadata={"display_name": "  Bau Leitung  "}),
            "fallback@example.com",
        )
        == "Bau Leitung"
    )
    assert _display_name_from_auth_user(SimpleNamespace(user_metadata={}), "person@example.com") == "person"
    assert _display_name_from_auth_user(SimpleNamespace(user_metadata=None), "") == "BBA Nutzer"


def test_ai_provider_configuration_errors_are_explicit() -> None:
    with pytest.raises(AiConfigurationError, match="deaktiviert"):
        OpenAiAiProvider(Settings(_env_file=None, ai_enabled=False))

    with pytest.raises(AiConfigurationError, match="nur OpenAI"):
        OpenAiAiProvider(Settings(_env_file=None, ai_provider="gemini", gemini_api_key="gemini"))

    with pytest.raises(AiConfigurationError, match="OPENAI_API_KEY"):
        OpenAiAiProvider(Settings(_env_file=None, openai_api_key=None))


def test_ai_prompt_helpers_and_response_text() -> None:
    project = {"language": "en", "appraisal_type": "Schadensaufnahme"}

    assert "Englisch" in _transcription_prompt(project, "caption")
    assert "Bildunterschrift" in _text_system_prompt(project, "caption")
    assert "Beschreibe nur Sichtbares" in _image_system_prompt(project)
    assert _response_text(SimpleNamespace(output_text="  Fertiger Text  ")) == "Fertiger Text"

    with pytest.raises(AiProviderError):
        _response_text(SimpleNamespace(output_text=" "))


def test_in_memory_rate_limiter_blocks_within_window_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([10.0, 11.0, 25.0])
    monkeypatch.setattr("baudoku_api.rate_limit.time.monotonic", lambda: next(times))
    limiter = InMemoryRateLimiter(limit=1, window_seconds=10)

    limiter.check("user:ai")
    with pytest.raises(RateLimitExceededError):
        limiter.check("user:ai")
    limiter.check("user:ai")


def test_zero_rate_limit_disables_throttling() -> None:
    limiter = InMemoryRateLimiter(limit=0, window_seconds=60)

    limiter.check("user:ai")
    limiter.check("user:ai")
