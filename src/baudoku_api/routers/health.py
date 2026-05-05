from typing import Union

from fastapi import APIRouter

from baudoku_api.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, Union[str, bool]]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "supabase_configured": settings.is_supabase_configured,
        "ai_enabled": settings.ai_enabled,
        "ai_configured": settings.is_ai_configured,
    }
