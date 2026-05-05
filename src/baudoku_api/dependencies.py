from functools import lru_cache
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from baudoku_api.ai import AiConfigurationError, AiProviderProtocol, OpenAiAiProvider
from baudoku_api.auth import (
    AuthServiceProtocol,
    AuthenticationError,
    InactiveUserError,
    SupabaseAuthService,
)
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.rate_limit import InMemoryRateLimiter, RateLimiterProtocol
from baudoku_api.repositories import ProjectRepositoryProtocol, SupabaseProjectRepository
from baudoku_api.config import get_settings
from baudoku_api.supabase_client import SupabaseConfigurationError

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service() -> AuthServiceProtocol:
    return SupabaseAuthService()


def get_project_repository() -> ProjectRepositoryProtocol:
    return SupabaseProjectRepository()


def get_ai_provider() -> AiProviderProtocol:
    try:
        return OpenAiAiProvider(get_settings())
    except AiConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AI_NOT_CONFIGURED",
                "message": str(exc),
            },
        ) from exc


def get_ai_rate_limiter() -> RateLimiterProtocol:
    settings = get_settings()
    return _get_ai_rate_limiter(settings.ai_rate_limit_per_user_per_minute)


@lru_cache
def _get_ai_rate_limiter(limit: int) -> RateLimiterProtocol:
    return InMemoryRateLimiter(limit=limit, window_seconds=60)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    auth_service: AuthServiceProtocol = Depends(get_auth_service),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer Token fehlt.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return auth_service.authenticate(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
