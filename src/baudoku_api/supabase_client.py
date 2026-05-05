from functools import lru_cache

from supabase import Client, create_client

from baudoku_api.config import get_settings


class SupabaseConfigurationError(RuntimeError):
    """Raised when the backend is called without required Supabase settings."""


def create_supabase_service_client() -> Client:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SupabaseConfigurationError(
            "SUPABASE_URL und SUPABASE_SERVICE_ROLE_KEY muessen im Backend gesetzt sein."
        )

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


@lru_cache
def get_supabase_client() -> Client:
    return create_supabase_service_client()
