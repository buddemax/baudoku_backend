from typing import Any, Optional, Protocol

from baudoku_api.domain import AuthenticatedUser
from baudoku_api.repositories.projects import ProjectRepositoryProtocol, SupabaseProjectRepository
from baudoku_api.supabase_client import get_supabase_client


class AuthenticationError(Exception):
    """Raised when a bearer token cannot be validated."""


class InactiveUserError(Exception):
    """Raised when a known Supabase user is disabled in the app profile."""


class AuthServiceProtocol(Protocol):
    def authenticate(self, access_token: str) -> AuthenticatedUser:
        """Validate an access token and return the app user."""


class SupabaseAuthService:
    def __init__(
        self,
        repository: Optional[ProjectRepositoryProtocol] = None,
    ) -> None:
        self._repository = repository or SupabaseProjectRepository()

    def authenticate(self, access_token: str) -> AuthenticatedUser:
        try:
            response = get_supabase_client().auth.get_user(access_token)
        except Exception as exc:  # pragma: no cover - library-specific exception surface
            raise AuthenticationError("Ungueltige oder abgelaufene Session.") from exc

        auth_user = _get_attr(response, "user")
        if auth_user is None:
            raise AuthenticationError("Ungueltige oder abgelaufene Session.")

        user_id = _get_attr(auth_user, "id")
        email = _get_attr(auth_user, "email") or ""
        if not user_id:
            raise AuthenticationError("Ungueltige oder abgelaufene Session.")

        display_name = _display_name_from_auth_user(auth_user, email)
        profile = self._repository.ensure_profile(
            AuthenticatedUser(id=str(user_id), email=str(email), display_name=display_name)
        )

        if not profile.is_active:
            raise InactiveUserError("Nutzer ist deaktiviert.")

        return profile


def _get_attr(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _display_name_from_auth_user(auth_user: Any, email: str) -> str:
    metadata = _get_attr(auth_user, "user_metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    for key in ("display_name", "full_name", "name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if email and "@" in email:
        return email.split("@", maxsplit=1)[0]

    return "BBA Nutzer"
