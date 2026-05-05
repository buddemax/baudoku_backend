from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from baudoku_api.auth import AuthenticationError, InactiveUserError
from baudoku_api.config import Settings
from baudoku_api.dependencies import get_current_user
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.supabase_client import SupabaseConfigurationError, get_supabase_client


class AuthServiceReturnsUser:
    def authenticate(self, access_token: str) -> AuthenticatedUser:
        return AuthenticatedUser(
            id="11111111-1111-4111-8111-111111111111",
            email="gutachter@example.com",
            display_name="Gutachter",
        )


class AuthServiceRaises:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def authenticate(self, access_token: str) -> AuthenticatedUser:
        raise self.exc


def test_get_current_user_requires_bearer_credentials() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(credentials=None, auth_service=AuthServiceReturnsUser())

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


def test_get_current_user_maps_authentication_errors() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            credentials=credentials,
            auth_service=AuthServiceRaises(AuthenticationError("Session abgelaufen.")),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Session abgelaufen."


def test_get_current_user_maps_inactive_users() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            credentials=credentials,
            auth_service=AuthServiceRaises(InactiveUserError("Nutzer ist deaktiviert.")),
        )

    assert exc_info.value.status_code == 403


def test_get_current_user_returns_authenticated_profile() -> None:
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")

    user = get_current_user(credentials=credentials, auth_service=AuthServiceReturnsUser())

    assert user.email == "gutachter@example.com"


def test_supabase_client_requires_backend_service_key(monkeypatch: pytest.MonkeyPatch) -> None:
    get_supabase_client.cache_clear()
    monkeypatch.setattr(
        "baudoku_api.supabase_client.get_settings",
        lambda: Settings(_env_file=None, supabase_url="https://example.supabase.co"),
    )

    with pytest.raises(SupabaseConfigurationError):
        get_supabase_client()

    get_supabase_client.cache_clear()


def test_supabase_client_uses_configured_service_role(monkeypatch: pytest.MonkeyPatch) -> None:
    get_supabase_client.cache_clear()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "baudoku_api.supabase_client.get_settings",
        lambda: Settings(
            _env_file=None,
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-key",
        ),
    )
    monkeypatch.setattr(
        "baudoku_api.supabase_client.create_client",
        lambda url, key: calls.append((url, key)) or SimpleNamespace(url=url, key=key),
    )

    client = get_supabase_client()

    assert client.key == "service-key"
    assert calls == [("https://example.supabase.co", "service-key")]
    get_supabase_client.cache_clear()
