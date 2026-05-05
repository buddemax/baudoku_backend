import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from baudoku_api.ai import AiProviderError, AiProviderProtocol
from baudoku_api.dependencies import (
    get_ai_provider,
    get_ai_rate_limiter,
    get_current_user,
    get_project_repository,
)
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.rate_limit import RateLimitExceededError, RateLimiterProtocol
from baudoku_api.repositories import (
    ProjectNotFoundError,
    ProjectRepositoryError,
    ProjectRepositoryProtocol,
)
from baudoku_api.schemas import AiImageDescriptionRequest, AiJobRead, AiTranscriptionRequest
from baudoku_api.supabase_client import SupabaseConfigurationError

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger(__name__)
STALE_QUEUED_JOB_AFTER = timedelta(seconds=30)


@router.post("/transcriptions", response_model=AiJobRead, status_code=status.HTTP_202_ACCEPTED)
def start_transcription(
    payload: AiTranscriptionRequest,
    background_tasks: BackgroundTasks,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
    ai_provider: AiProviderProtocol = Depends(get_ai_provider),
    rate_limiter: RateLimiterProtocol = Depends(get_ai_rate_limiter),
) -> dict:
    try:
        rate_limiter.check(f"{current_user.id}:ai")
        job, created = repository.queue_ai_transcription(
            str(payload.voice_note_id), current_user, ai_provider
        )
        if created or _is_stale_queued_job(job):
            background_tasks.add_task(
                repository.process_ai_transcription_job,
                str(job["id"]),
                str(payload.voice_note_id),
                current_user,
                ai_provider,
            )
        return job
    except (
        ProjectNotFoundError,
        ProjectRepositoryError,
        RateLimitExceededError,
        SupabaseConfigurationError,
    ) as exc:
        raise _http_error(exc) from exc


@router.post("/image-descriptions", response_model=AiJobRead)
def start_image_description(
    payload: AiImageDescriptionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
    ai_provider: AiProviderProtocol = Depends(get_ai_provider),
    rate_limiter: RateLimiterProtocol = Depends(get_ai_rate_limiter),
) -> dict:
    try:
        rate_limiter.check(f"{current_user.id}:ai")
        return repository.start_ai_image_description(
            str(payload.media_asset_id), current_user, ai_provider
        )
    except (
        ProjectNotFoundError,
        ProjectRepositoryError,
        RateLimitExceededError,
        SupabaseConfigurationError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get("/jobs/{job_id}", response_model=AiJobRead)
def get_ai_job(
    job_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.get_ai_job(str(job_id), current_user.id)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail("NOT_FOUND", str(exc)),
        )
    if isinstance(exc, RateLimitExceededError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_error_detail(
                "AI_RATE_LIMITED",
                "KI-Rate-Limit erreicht. Bitte spaeter erneut versuchen.",
            ),
        )
    if isinstance(exc, AiProviderError):
        logger.warning(
            "AI provider error.",
            extra={
                "error_code": "AI_PROVIDER_UNAVAILABLE",
                "exception_type": exc.__class__.__name__,
            },
        )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                "AI_PROVIDER_UNAVAILABLE",
                "KI-Provider ist aktuell nicht erreichbar.",
            ),
        )
    if isinstance(exc, SupabaseConfigurationError):
        logger.warning(
            "AI Supabase configuration error.",
            extra={
                "error_code": "SUPABASE_NOT_CONFIGURED",
                "exception_type": exc.__class__.__name__,
            },
        )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail(
                "SUPABASE_NOT_CONFIGURED",
                "KI-Service ist nicht vollstaendig konfiguriert.",
            ),
        )
    logger.warning(
        "AI route repository error.",
        extra={
            "error_code": "AI_REQUEST_FAILED",
            "exception_type": exc.__class__.__name__,
        },
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error_detail(
            "AI_REQUEST_FAILED",
            "KI-Anfrage konnte nicht verarbeitet werden.",
        ),
    )


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _is_stale_queued_job(job: dict[str, Any]) -> bool:
    if job.get("status") != "queued":
        return False

    updated_at = _parse_job_timestamp(job.get("updated_at")) or _parse_job_timestamp(
        job.get("created_at")
    )
    if updated_at is None:
        return False
    return datetime.now(timezone.utc) - updated_at >= STALE_QUEUED_JOB_AFTER


def _parse_job_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
