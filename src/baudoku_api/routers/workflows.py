import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from baudoku_api.dependencies import get_current_user, get_project_repository
from baudoku_api.domain import AuthenticatedUser
from baudoku_api.repositories import (
    MediaUploadIntegrityError,
    ProjectNotFoundError,
    ProjectRepositoryError,
    ProjectRepositoryProtocol,
)
from baudoku_api.schemas import (
    DefectCreate,
    DefectListResponse,
    DefectMediaLinkCreate,
    DefectMediaLinkRead,
    DefectMediaLinkUpdate,
    DefectReorderRequest,
    DefectRead,
    DefectUpdate,
    MediaAssetListResponse,
    GeneralFindingCreate,
    GeneralFindingListResponse,
    GeneralFindingRead,
    GeneralFindingUpdate,
    MediaAssetRead,
    MediaSignedUrlResponse,
    MediaAssetUpdate,
    MediaCompleteUploadRequest,
    MediaInitUploadRequest,
    MediaInitUploadResponse,
    PlanCreate,
    PlanExportRequest,
    PlanExportResponse,
    PlanListResponse,
    PlanMarkerCreate,
    PlanMarkerRead,
    PlanMarkerUpdate,
    PlanRead,
    ProjectConclusionRead,
    ProjectConclusionUpsert,
    ReportGenerateResponse,
    ReportPreviewResponse,
    ReportPreviewConfirmationRead,
    ReportVersionListResponse,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    VoiceNoteCreate,
    VoiceNoteListResponse,
    VoiceNoteRead,
    VoiceNoteUpdate,
)
from baudoku_api.supabase_client import SupabaseConfigurationError

router = APIRouter(tags=["fieldwork"])
logger = logging.getLogger(__name__)


@router.get("/projects/{project_id}/defects", response_model=DefectListResponse)
def list_defects(
    project_id: UUID,
    kind: Optional[str] = Query(default=None),
    trade_id: Optional[UUID] = Query(default=None),
    category: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> DefectListResponse:
    try:
        return DefectListResponse(
            items=repository.list_defects(
                str(project_id),
                current_user.id,
                kind=kind,
                trade_id=str(trade_id) if trade_id else None,
                category=category,
            )
        )
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/projects/{project_id}/defects",
    response_model=DefectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_defect(
    project_id: UUID,
    defect: DefectCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_defect(str(project_id), defect, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/defects/{defect_id}", response_model=DefectRead)
def update_defect(
    defect_id: UUID,
    defect: DefectUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_defect(str(defect_id), defect, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post("/projects/{project_id}/defects/reorder", response_model=DefectListResponse)
def reorder_defects(
    project_id: UUID,
    reorder: DefectReorderRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> DefectListResponse:
    try:
        return DefectListResponse(
            items=repository.reorder_defects(
                str(project_id),
                [str(defect_id) for defect_id in reorder.defect_ids],
                current_user,
            )
        )
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post("/projects/{project_id}/media/init-upload", response_model=MediaInitUploadResponse)
def init_media_upload(
    project_id: UUID,
    upload: MediaInitUploadRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.init_media_upload(str(project_id), upload, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post("/projects/{project_id}/media/complete-upload", response_model=MediaAssetRead)
def complete_media_upload(
    project_id: UUID,
    upload: MediaCompleteUploadRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.complete_media_upload(str(project_id), upload, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/projects/{project_id}/media", response_model=MediaAssetListResponse)
def list_media_assets(
    project_id: UUID,
    media_type: Optional[str] = Query(default=None),
    include_deleted: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> MediaAssetListResponse:
    try:
        return MediaAssetListResponse(
            items=repository.list_media_assets(
                str(project_id),
                current_user.id,
                media_type=media_type,
                include_deleted=include_deleted,
            )
        )
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/defects/{defect_id}/media-links",
    response_model=DefectMediaLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def create_defect_media_link(
    defect_id: UUID,
    link: DefectMediaLinkCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_defect_media_link(str(defect_id), link, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/defect-media-links/{link_id}", response_model=DefectMediaLinkRead)
def update_defect_media_link(
    link_id: UUID,
    link: DefectMediaLinkUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_defect_media_link(str(link_id), link, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.delete("/defect-media-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_defect_media_link(
    link_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> None:
    try:
        repository.delete_defect_media_link(str(link_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/media-assets/{media_asset_id}", response_model=MediaAssetRead)
def update_media_asset(
    media_asset_id: UUID,
    media: MediaAssetUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_media_asset(str(media_asset_id), media, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/media-assets/{media_asset_id}/signed-url", response_model=MediaSignedUrlResponse)
def get_media_asset_signed_url(
    media_asset_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.get_media_asset_signed_url(str(media_asset_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.delete("/media-assets/{media_asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media_asset(
    media_asset_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> None:
    try:
        repository.delete_media_asset(str(media_asset_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/projects/{project_id}/plans", response_model=PlanListResponse)
def list_plans(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> PlanListResponse:
    try:
        return PlanListResponse(items=repository.list_plans(str(project_id), current_user.id))
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/projects/{project_id}/plans",
    response_model=PlanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_plan(
    project_id: UUID,
    plan: PlanCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_plan(str(project_id), plan, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post("/plans/{plan_id}/export", response_model=PlanExportResponse)
def export_plan(
    plan_id: UUID,
    export_request: Optional[PlanExportRequest] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.export_plan(str(plan_id), export_request or PlanExportRequest(), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/plans/{plan_id}/markers",
    response_model=PlanMarkerRead,
    status_code=status.HTTP_201_CREATED,
)
def create_plan_marker(
    plan_id: UUID,
    marker: PlanMarkerCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_plan_marker(str(plan_id), marker, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/plan-markers/{marker_id}", response_model=PlanMarkerRead)
def update_plan_marker(
    marker_id: UUID,
    marker: PlanMarkerUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_plan_marker(str(marker_id), marker, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.delete("/plan-markers/{marker_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan_marker(
    marker_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> None:
    try:
        repository.delete_plan_marker(str(marker_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/projects/{project_id}/voice-notes", response_model=VoiceNoteListResponse)
def list_voice_notes(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> VoiceNoteListResponse:
    try:
        return VoiceNoteListResponse(
            items=repository.list_voice_notes(str(project_id), current_user.id)
        )
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/projects/{project_id}/voice-notes",
    response_model=VoiceNoteRead,
    status_code=status.HTTP_201_CREATED,
)
def create_voice_note(
    project_id: UUID,
    voice_note: VoiceNoteCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_voice_note(str(project_id), voice_note, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/voice-notes/{voice_note_id}", response_model=VoiceNoteRead)
def update_voice_note(
    voice_note_id: UUID,
    voice_note: VoiceNoteUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_voice_note(str(voice_note_id), voice_note, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/projects/{project_id}/general-findings",
    response_model=GeneralFindingListResponse,
)
def list_general_findings(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> GeneralFindingListResponse:
    try:
        return GeneralFindingListResponse(
            items=repository.list_general_findings(str(project_id), current_user.id)
        )
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/projects/{project_id}/general-findings",
    response_model=GeneralFindingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_general_finding(
    project_id: UUID,
    finding: GeneralFindingCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.create_general_finding(str(project_id), finding, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.patch("/general-findings/{finding_id}", response_model=GeneralFindingRead)
def update_general_finding(
    finding_id: UUID,
    finding: GeneralFindingUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.update_general_finding(str(finding_id), finding, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.delete("/general-findings/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_general_finding(
    finding_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> None:
    try:
        repository.delete_general_finding(str(finding_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/projects/{project_id}/conclusion",
    response_model=Optional[ProjectConclusionRead],
)
def get_project_conclusion(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> Optional[dict]:
    try:
        return repository.get_project_conclusion(str(project_id), current_user.id)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.put("/projects/{project_id}/conclusion", response_model=ProjectConclusionRead)
def upsert_project_conclusion(
    project_id: UUID,
    conclusion: ProjectConclusionUpsert,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.upsert_project_conclusion(str(project_id), conclusion, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/projects/{project_id}/report/preview", response_model=ReportPreviewResponse)
def report_preview(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.report_preview(str(project_id), current_user.id)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/projects/{project_id}/report/warnings")
def report_warnings(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        preview = repository.report_preview(str(project_id), current_user.id)
        return {"items": preview["warnings"]}
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/projects/{project_id}/report/preview/confirm",
    response_model=ReportPreviewConfirmationRead,
)
def confirm_report_preview(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.confirm_report_preview(str(project_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post("/projects/{project_id}/report/generate", response_model=ReportGenerateResponse)
def generate_report(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.generate_report(str(project_id), current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/projects/{project_id}/report-versions", response_model=ReportVersionListResponse)
def list_report_versions(
    project_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> ReportVersionListResponse:
    try:
        return ReportVersionListResponse(
            items=repository.list_report_versions(str(project_id), current_user.id)
        )
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/report-versions/{version_id}/download")
def download_report_version(
    version_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> RedirectResponse:
    try:
        return RedirectResponse(repository.report_download_url(str(version_id), current_user))
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.get("/sync/pull", response_model=SyncPullResponse)
def sync_pull(
    updated_since: Optional[datetime] = Query(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.sync_pull(current_user.id, updated_since=updated_since)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


@router.post("/sync/push", response_model=SyncPushResponse)
def sync_push(
    payload: SyncPushRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ProjectRepositoryProtocol = Depends(get_project_repository),
) -> dict:
    try:
        return repository.sync_push(payload.operations, current_user)
    except (ProjectNotFoundError, ProjectRepositoryError, SupabaseConfigurationError) as exc:
        raise _http_error(exc) from exc


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail("NOT_FOUND", str(exc)),
        )
    if isinstance(exc, SupabaseConfigurationError):
        logger.warning(
            "Supabase configuration error in fieldwork route.",
            extra={
                "error_code": "SUPABASE_NOT_CONFIGURED",
                "exception_type": exc.__class__.__name__,
            },
        )
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_error_detail("SUPABASE_NOT_CONFIGURED", str(exc)),
        )
    if isinstance(exc, MediaUploadIntegrityError):
        logger.warning(
            "Media upload integrity error in fieldwork route.",
            extra={
                "error_code": exc.error_code,
                "exception_type": exc.__class__.__name__,
            },
        )
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error_detail(exc.error_code, str(exc)),
        )
    logger.warning(
        "Repository error in fieldwork route.",
        extra={
            "error_code": "REPOSITORY_UNAVAILABLE",
            "exception_type": exc.__class__.__name__,
        },
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_error_detail(
            "REPOSITORY_UNAVAILABLE",
            str(exc) or "Anfrage konnte nicht verarbeitet werden.",
        ),
    )


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
