import logging
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from baudoku_api.dependencies import get_current_user, get_project_repository
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.repositories import (
    ProjectNotFoundError,
    ProjectRepositoryError,
    ProjectRepositoryProtocol,
)
from baudoku_api.schemas import (
    ProfileListResponse,
    ProjectCreate,
    ProjectListResponse,
    ProjectRead,
    ProjectUpdate,
    TradeListResponse,
)
from baudoku_api.supabase_client import SupabaseConfigurationError

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    search: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    appraisal_type: Optional[str] = Query(default=None),
    include_deleted: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> ProjectListResponse:
    try:
        return ProjectListResponse(
            items=repository.list_projects(
                current_user.id,
                search=search,
                status=status_filter,
                appraisal_type=appraisal_type,
                include_deleted=include_deleted,
            )
        )
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


profiles_router = APIRouter(prefix="/profiles", tags=["profiles"])


@profiles_router.get("", response_model=ProfileListResponse)
def list_profiles(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> ProfileListResponse:
    try:
        return ProfileListResponse(items=repository.list_profiles(current_user.id))
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


trades_router = APIRouter(prefix="/trades", tags=["trades"])


@trades_router.get("", response_model=TradeListResponse)
def list_trades(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> TradeListResponse:
    try:
        return TradeListResponse(items=repository.list_trades(current_user.id))
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    project: ProjectCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_project(project, current_user)
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.get_project(str(project_id), current_user.id)
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: UUID,
    project: ProjectUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_project(str(project_id), project, current_user)
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> Response:
    try:
        repository.delete_project(str(project_id), current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except SupabaseConfigurationError as exc:
        raise _supabase_unavailable(exc) from exc
    except ProjectRepositoryError as exc:
        raise _service_unavailable(exc) from exc


def _service_unavailable(exc: Exception) -> HTTPException:
    if isinstance(exc.__cause__, SupabaseConfigurationError):
        return _supabase_unavailable(exc.__cause__)

    logger.warning(
        "Project repository error.",
        extra={
            "error_code": "REPOSITORY_UNAVAILABLE",
            "exception_type": exc.__class__.__name__,
        },
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error_detail(
            "REPOSITORY_UNAVAILABLE",
            "Projekt-Daten konnten nicht verarbeitet werden.",
        ),
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_error_detail("NOT_FOUND", str(exc)),
    )


def _supabase_unavailable(exc: Exception) -> HTTPException:
    logger.warning(
        "Supabase configuration error in project route.",
        extra={
            "error_code": "SUPABASE_NOT_CONFIGURED",
            "exception_type": exc.__class__.__name__,
        },
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error_detail("SUPABASE_NOT_CONFIGURED", str(exc)),
    )


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
